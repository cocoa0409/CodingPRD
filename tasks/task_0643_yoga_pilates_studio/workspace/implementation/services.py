"""Shared business-logic helpers: capacity postures, waitlist/queue management,
credit ledger, fee creation, and member standing cascades.

These operate directly on the in-memory store records and keep derived counts
and capacity-posture states consistent (PRD §2.5, §3.5, §3.6).
"""
import constants as C
from db import store
from models import touch, make_fee_charge, recompute_credits_remaining
from calculations import fee_amount_cents

# Reservation states that count as occupying a booked seat.
BOOKED_OCCUPYING = {"BOOKED", "CHECKED_IN"}


# ---------------------------------------------------------------------------
# Derived counts + capacity posture
# ---------------------------------------------------------------------------

def session_reservations(session_id):
    return [r for r in store.reservations.values()
            if r["class_session_id"] == session_id]


def recompute_session_counts(session):
    sid = session["id"]
    booked = 0
    waitlisted = 0
    for r in store.reservations.values():
        if r["class_session_id"] != sid:
            continue
        if r["status"] in BOOKED_OCCUPYING:
            booked += 1
        elif r["status"] == "WAITLISTED":
            waitlisted += 1
    session["booked_count"] = booked
    session["waitlisted_count"] = waitlisted


def effective_capacity(session):
    room = store.rooms.get(session["room_id"])
    if room is None:
        return session["published_capacity"]
    return min(session["published_capacity"], room["station_capacity"])


def recompute_session_posture(session):
    """OPEN <-> FULL recompute based on booked_count vs published_capacity.

    Only applies while the session is in a bookable posture (OPEN/FULL).
    Terminal/in-progress/scheduled states are untouched.
    """
    if session["status"] not in ("OPEN", "FULL"):
        return
    cap = effective_capacity(session)
    if session["booked_count"] >= cap:
        if session["status"] != "FULL":
            session["status"] = "FULL"
            touch(session)
    else:
        # booked < cap: FULL -> OPEN only when no waitlist can fill it.
        if session["status"] == "FULL" and session["waitlisted_count"] == 0:
            session["status"] = "OPEN"
            touch(session)


# ---------------------------------------------------------------------------
# Credit ledger
# ---------------------------------------------------------------------------

def charge_credit(ent):
    ent["credits_used"] += 1
    recompute_credits_remaining(ent)
    touch(ent)


def refund_credit(ent):
    ent["credits_used"] -= 1
    recompute_credits_remaining(ent)
    touch(ent)


# ---------------------------------------------------------------------------
# Waitlist queue management (per session)
# ---------------------------------------------------------------------------

def waitlisted_in_order(session_id):
    """WAITLISTED reservations on a session ordered by waitlist_position ASC."""
    wl = [r for r in store.reservations.values()
          if r["class_session_id"] == session_id and r["status"] == "WAITLISTED"]
    wl.sort(key=lambda r: (r["waitlist_position"]
                           if r["waitlist_position"] is not None else 1 << 30,
                           r["_seq"]))
    return wl


def repack_waitlist(session_id):
    """Renumber waitlist positions 1..N by current ascending order."""
    wl = waitlisted_in_order(session_id)
    for idx, r in enumerate(wl, start=1):
        if r["waitlist_position"] != idx:
            r["waitlist_position"] = idx
            touch(r)


def promote_waitlist_head(session):
    """Auto-promote the lowest-position WAITLISTED reservation into a freed seat,
    if a seat is open. Re-packs remaining positions. Recomputes posture.

    Returns the promoted reservation or None.
    """
    recompute_session_counts(session)
    cap = effective_capacity(session)
    if session["booked_count"] >= cap:
        return None
    wl = waitlisted_in_order(session["id"])
    if not wl:
        return None
    head = wl[0]
    head["status"] = "BOOKED"
    head["waitlist_position"] = None
    # credit remains charged
    touch(head)
    repack_waitlist(session["id"])
    recompute_session_counts(session)
    recompute_session_posture(session)
    return head


# ---------------------------------------------------------------------------
# Fees + member standing
# ---------------------------------------------------------------------------

def raise_fee(member, reservation, fee_type):
    """Create a FeeCharge with the assessed amount and bump outstanding_fee_cents.

    strikes_before_this reads member.no_show_strike_count BEFORE any increment
    this event performs (the caller increments strikes separately for NO_SHOW).
    """
    strikes_before = member["no_show_strike_count"]
    amount = fee_amount_cents(fee_type, strikes_before, member["is_new_student"])
    fee = make_fee_charge(member["id"], reservation["id"], fee_type, amount)
    store.fee_charges[fee["id"]] = fee
    member["outstanding_fee_cents"] += amount
    touch(member)
    return fee


def add_no_show_strike(member):
    member["no_show_strike_count"] += 1
    if member["no_show_strike_count"] >= C.NO_SHOW_SUSPEND_THRESHOLD:
        member["account_status"] = "SUSPENDED"
    touch(member)


def mark_attended(member):
    member["lifetime_attended_count"] += 1
    if member["lifetime_attended_count"] >= 1:
        member["is_new_student"] = False
    touch(member)
