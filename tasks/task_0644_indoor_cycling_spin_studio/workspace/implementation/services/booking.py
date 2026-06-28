"""Booking, charge resolution, cancellation, promotion, and completion cascades.

Traces: PRD §3.4 (booking & charge resolution & attendance), §3.5 (early/late
cancel), §3.6 (waitlist & promotion), scaffold booking_charge_resolution and the
ClassSession / Reservation / WaitlistEntry state machines.
"""
from clock import clock
from db import db, stamp_new, touch
from constants import SHOE_RENTAL_FEE_CENTS
from services import packs as pack_svc
from services import members as member_svc


# ----------------------------------------------------------------------------
# First-ride eligibility (PRD §3.3, scaffold step 1 of booking_charge_resolution)
# ----------------------------------------------------------------------------
def first_ride_eligible(member):
    """True when:
      - member.completed_ride_count == 0, AND
      - member has no prior reservation in any attendance state other than
        EARLY_CANCELLED (a genuine first ride), AND
      - the first-ride comp has not already been consumed.
    Since the comp marks a reservation with first_ride_discount_applied=true and
    that reservation begins BOOKED (not EARLY_CANCELLED), the "no prior
    non-EARLY_CANCELLED reservation" test inherently covers the
    "not already consumed" condition.
    """
    member_id = member["id"]
    completed = sum(
        1 for r in db.reservations.values()
        if r["member_id"] == member_id and r["attendance_status"] == "ATTENDED"
    )
    if completed != 0:
        return False
    for r in db.reservations.values():
        if r["member_id"] != member_id:
            continue
        if r["attendance_status"] != "EARLY_CANCELLED":
            return False
        # An EARLY_CANCELLED reservation that consumed the comp still blocks
        # re-use of the comp (the coupon was already spent).
        if r.get("first_ride_discount_applied"):
            return False
    return True


# ----------------------------------------------------------------------------
# Pack candidate selection (PRD §3.4 charge resolution step 2)
# ----------------------------------------------------------------------------
def _scope_covers(pack, session):
    if pack["scope"] == "HOME_ONLY":
        member = db.members.get(pack["member_id"])
        return member is not None and session["studio_id"] == member["home_studio_id"]
    # MULTI_STUDIO
    return session["studio_id"] in pack["grant_studio_ids"]


def select_chargeable_pack(member, session):
    """Return the single pack chosen to cover a booking, or None if no candidate.

    Candidate set: member's packs that are ACTIVE, unexpired, scope-cover the
    session's studio, and able to pay (MEMBERSHIP, or CLASS_PACK with >= 1
    remaining credit).
    Ranking: (r1) CLASS_PACK before MEMBERSHIP; (r2) earliest expires_at ASC;
    (r3) earliest created_at ASC (then internal seq).
    """
    candidates = []
    for pack in db.credit_packs.values():
        if pack["member_id"] != member["id"]:
            continue
        if not pack_svc.is_chargeable(pack):
            continue
        if not _scope_covers(pack, session):
            continue
        candidates.append(pack)
    if not candidates:
        return None

    def rank(p):
        kind_rank = 0 if p["kind"] == "CLASS_PACK" else 1
        return (kind_rank, p["expires_at"], p["created_at"], p["_seq"])

    candidates.sort(key=rank)
    return candidates[0]


def booked_count(session_id):
    return sum(
        1 for r in db.reservations.values()
        if r["session_id"] == session_id and r["attendance_status"] == "BOOKED"
    )


def waiting_count(session_id):
    return sum(
        1 for w in db.waitlist_entries.values()
        if w["session_id"] == session_id and w["status"] == "WAITING"
    )


def member_has_booked(session_id, member_id):
    return any(
        r["session_id"] == session_id
        and r["member_id"] == member_id
        and r["attendance_status"] == "BOOKED"
        for r in db.reservations.values()
    )


def bike_held(session_id, bike_id):
    return any(
        r["session_id"] == session_id
        and r["bike_id"] == bike_id
        and r["attendance_status"] == "BOOKED"
        for r in db.reservations.values()
    )


def _create_reservation(session, member, bike_id, shoe_size, credit_pack_id, first_ride):
    """Materialize a reservation row with charge already resolved by caller."""
    now = clock.now()
    rec = {
        "session_id": session["id"],
        "member_id": member["id"],
        "bike_id": bike_id,
        "credit_pack_id": credit_pack_id,
        "attendance_status": "BOOKED",
        "billing_status": "CREDIT_HELD",
        "first_ride_discount_applied": bool(first_ride),
        "shoe_size": shoe_size,
        "shoe_fee_cents": 0,
        "shoe_status": "NONE",
        "booked_at": now,
    }
    if shoe_size is not None:
        rec["shoe_status"] = "RESERVED"
        rec["shoe_fee_cents"] = SHOE_RENTAL_FEE_CENTS
    stamp_new(rec)
    db.reservations[rec["id"]] = rec
    return rec


# ----------------------------------------------------------------------------
# Promotion off the waitlist (PRD §3.6)
# ----------------------------------------------------------------------------
def _free_bike_for_session(session):
    """Auto-assign a free ACTIVE bike in the session's room: lowest
    position_row, then position_col, then created_at (then internal seq)."""
    room_id = session["room_id"]
    held = {
        r["bike_id"]
        for r in db.reservations.values()
        if r["session_id"] == session["id"] and r["attendance_status"] == "BOOKED"
    }
    bikes = [
        b for b in db.bikes.values()
        if b["room_id"] == room_id and b["status"] == "ACTIVE" and b["id"] not in held
    ]
    if not bikes:
        return None
    bikes.sort(key=lambda b: (b["position_row"], b["position_col"], b["created_at"], b["_seq"]))
    return bikes[0]


def promote_next(session):
    """Attempt to promote the earliest WAITING entry after a seat frees up.

    Promotion proceeds only if the session now has free capacity, the entry's
    pre-authorized pack is chargeable (or member first-ride eligible), a free
    bike exists, and the duplicate-reservation guard still holds.
    PRD §3.6.
    """
    if booked_count(session["id"]) >= session["capacity"]:
        return None

    waiting = [
        w for w in db.waitlist_entries.values()
        if w["session_id"] == session["id"] and w["status"] == "WAITING"
    ]
    if not waiting:
        return None
    waiting.sort(key=lambda w: (w["enqueued_at"], w["created_at"], w["_seq"]))
    entry = waiting[0]

    member = db.members.get(entry["member_id"])
    if member is None:
        return None

    # Duplicate-reservation guard holds during promotion.
    if member_has_booked(session["id"], member["id"]):
        return None

    # Determine charge: first-ride comp, else the pre-authorized pack.
    first_ride = first_ride_eligible(member)
    chosen_pack = None
    if not first_ride:
        pack = db.credit_packs.get(entry["credit_pack_id"])
        if pack is None or pack["member_id"] != member["id"]:
            return None
        if not pack_svc.is_chargeable(pack):
            return None
        if not _scope_covers(pack, session):
            return None
        chosen_pack = pack

    bike = _free_bike_for_session(session)
    if bike is None:
        return None

    credit_pack_id = None
    if first_ride:
        credit_pack_id = None
    else:
        credit_pack_id = chosen_pack["id"]
        pack_svc.debit_one(chosen_pack)

    res = _create_reservation(session, member, bike["id"], None, credit_pack_id, first_ride)

    entry["promoted_reservation_id"] = res["id"]
    entry["status"] = "PROMOTED"
    touch(entry)

    # The new reservation took a seat: bump the session version + reconcile.
    touch(session)
    return res


# ----------------------------------------------------------------------------
# Cancellation cascades (PRD §3.5)
# ----------------------------------------------------------------------------
def _create_penalty(member, reservation, kind, amount_cents):
    now = clock.now()
    charge = {
        "member_id": member["id"],
        "reservation_id": reservation["id"],
        "kind": kind,
        "amount_cents": amount_cents,
        "counts_as_strike": True,
        "waived": False,
        "charged_at": now,
    }
    stamp_new(charge)
    db.penalty_charges[charge["id"]] = charge
    return charge


def early_cancel(reservation, session, studio):
    """attendance -> EARLY_CANCELLED, billing -> CREDIT_REFUNDED; restore
    CLASS_PACK credit; promote earliest waitlist entry. PRD §3.5."""
    reservation["attendance_status"] = "EARLY_CANCELLED"
    reservation["billing_status"] = "CREDIT_REFUNDED"
    touch(reservation)

    if reservation["credit_pack_id"]:
        pack = db.credit_packs.get(reservation["credit_pack_id"])
        if pack is not None:
            pack_svc.restore_one(pack)

    touch(session)  # version bump for the freeing cancel
    promote_next(session)


def late_cancel(reservation, session, studio):
    """attendance -> LATE_CANCELLED, billing -> FEE_CHARGED (credit NOT
    refunded); create LATE_CANCEL penalty; strike recompute -> possible
    suspend; shoe FORFEITED if RESERVED; promote earliest waitlist entry.
    PRD §3.5."""
    reservation["attendance_status"] = "LATE_CANCELLED"
    reservation["billing_status"] = "FEE_CHARGED"
    if reservation["shoe_status"] == "RESERVED":
        reservation["shoe_status"] = "FORFEITED"
    touch(reservation)

    member = db.members.get(reservation["member_id"])
    _create_penalty(member, reservation, "LATE_CANCEL", studio["late_cancel_fee_cents"])
    member_svc.apply_strike_suspension(member)

    touch(session)  # version bump for the freeing cancel
    promote_next(session)


# ----------------------------------------------------------------------------
# Session terminal transitions (PRD §3.2 cancel, §3.4 complete)
# ----------------------------------------------------------------------------
def cancel_session(session):
    """Studio cancels a SCHEDULED session (PRD §3.2 cascade).
    1. BOOKED reservations -> EARLY_CANCELLED + CREDIT_REFUNDED.
    2. Each CLASS_PACK refund: consumed_credits -= 1; EXHAUSTED -> ACTIVE.
    3. WAITING waitlist entries -> CANCELLED (no promotion).
    No penalty is ever created.
    """
    for r in list(db.reservations.values()):
        if r["session_id"] == session["id"] and r["attendance_status"] == "BOOKED":
            r["attendance_status"] = "EARLY_CANCELLED"
            r["billing_status"] = "CREDIT_REFUNDED"
            touch(r)
            if r["credit_pack_id"]:
                pack = db.credit_packs.get(r["credit_pack_id"])
                if pack is not None:
                    pack_svc.restore_one(pack)

    for w in list(db.waitlist_entries.values()):
        if w["session_id"] == session["id"] and w["status"] == "WAITING":
            w["status"] = "CANCELLED"
            touch(w)

    session["status"] = "CANCELLED"
    touch(session)


def complete_session(session, studio):
    """Mark a session COMPLETED (PRD §3.4 cascade).
    Every still-BOOKED reservation -> NO_SHOW + FEE_CHARGED; create NO_SHOW
    penalty; strike recompute -> possible suspend; RESERVED shoe -> FORFEITED.
    Every WAITING entry -> EXPIRED_OFF.
    """
    for r in list(db.reservations.values()):
        if r["session_id"] == session["id"] and r["attendance_status"] == "BOOKED":
            r["attendance_status"] = "NO_SHOW"
            r["billing_status"] = "FEE_CHARGED"
            if r["shoe_status"] == "RESERVED":
                r["shoe_status"] = "FORFEITED"
            touch(r)
            member = db.members.get(r["member_id"])
            _create_penalty(member, r, "NO_SHOW", studio["no_show_fee_cents"])
            member_svc.apply_strike_suspension(member)

    for w in list(db.waitlist_entries.values()):
        if w["session_id"] == session["id"] and w["status"] == "WAITING":
            w["status"] = "EXPIRED_OFF"
            touch(w)

    session["status"] = "COMPLETED"
    touch(session)


def check_in(reservation, session):
    """attendance BOOKED -> ATTENDED; billing CREDIT_HELD -> CREDIT_CONSUMED.
    completed_ride_count is recomputed (derived) at read time. PRD §3.4."""
    reservation["attendance_status"] = "ATTENDED"
    reservation["billing_status"] = "CREDIT_CONSUMED"
    touch(reservation)
    # completed_ride_count is a derived field; touching the member keeps its
    # version/updated_at consistent with the change (PRD §2.7).
    member = db.members.get(reservation["member_id"])
    if member is not None:
        touch(member)
