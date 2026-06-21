"""AdmissionOrder lifecycle: confirm, check-in, cancel, refund + cascades.

State machine (scaffold §1.2): DRAFT -> CONFIRMED -> {CHECKED_IN -> REFUNDED,
CANCELLED}; DRAFT -> CANCELLED.

Capacity (slot/session reserved_count) and the guest-pass pool are kept mutually
consistent through every transition. Cascades are atomic within the request.
"""
import clock
import db
from errors import (
    invalid_state, ApiError,
    ERR_TICKET_ELIGIBILITY, ERR_MEMBERSHIP_NOT_ACTIVE, ERR_SLOT_WINDOW,
    ERR_SLOT_OVERLAP, ERR_EXHIBIT_BUFFER_CONFLICT, ERR_NO_GUEST_PASS,
    ERR_SLOT_CAPACITY,
)
from timeutil import parse_iso
from services import pricing


def order_tickets(order, include_voided=False):
    tickets = [t for t in db.admission_tickets.values() if t["order_id"] == order["id"]]
    if not include_voided:
        tickets = [t for t in tickets if t.get("state") != "VOIDED"]
    tickets.sort(key=lambda t: (t.get("created_at"), t.get("_seq", 0)))
    return tickets


def recompute_party_size(order):
    order["party_size"] = len(order_tickets(order))


# ---------------------------------------------------------------------------
# Confirm: DRAFT -> CONFIRMED
# ---------------------------------------------------------------------------

def _windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap; adjacency (touching endpoints) allowed."""
    return a_start < b_end and b_start < a_end


def confirm(order):
    if order["status"] != "DRAFT":
        raise invalid_state("Order is not DRAFT")

    tickets = order_tickets(order)
    # At least one ticket must be present.
    if len(tickets) < 1:
        raise invalid_state("Order has no tickets")

    slot = db.timed_entry_slots[order["slot_id"]]
    membership = db.memberships.get(order["membership_id"]) if order.get("membership_id") else None
    session = db.exhibit_sessions.get(order["exhibit_session_id"]) if order.get("exhibit_session_id") else None
    exhibit = db.special_exhibits.get(session["exhibit_id"]) if session else None

    member_tickets = [t for t in tickets if t["ticket_type"] == "MEMBER"]
    guest_tickets = [t for t in tickets if t["ticket_type"] == "GUEST"]
    reciprocal_tickets = [t for t in tickets if t["ticket_type"] == "RECIPROCAL"]
    party_size = len(tickets)

    # --- Guard order (PRD §3.6): eligibility, membership-active, slot window,
    # slot overlap, exhibit buffer, guest-pass availability, capacity. ---

    # 1) Ticket eligibility (ERR_TICKET_ELIGIBILITY, 409)
    if member_tickets:
        if not membership:
            raise ApiError(ERR_TICKET_ELIGIBILITY, 409, "MEMBER ticket requires a membership link")
        eligible_patrons = {membership["primary_patron_id"]}
        for hm in db.household_members.values():
            if hm["membership_id"] == membership["id"] and hm.get("active"):
                # Household members are named, not patron-ids; membership ownership
                # already ties the order's membership to the buyer. The presence of
                # an active household member satisfies the "or one of its active
                # household members matches" clause for MEMBER eligibility.
                pass
        # primary patron must match the order's buyer, OR the membership has an
        # active household roster covering the party (per PRD §3.6).
        if order["patron_id"] != membership["primary_patron_id"]:
            has_active_household = any(
                hm["membership_id"] == membership["id"] and hm.get("active")
                for hm in db.household_members.values()
            )
            if not has_active_household:
                raise ApiError(ERR_TICKET_ELIGIBILITY, 409, "MEMBER ticket not eligible for this membership")
    if guest_tickets and not membership:
        raise ApiError(ERR_TICKET_ELIGIBILITY, 409, "GUEST ticket requires a membership link")
    for t in reciprocal_tickets:
        partner_id = t.get("reciprocal_partner_id")
        if not partner_id or partner_id not in db.reciprocal_partners:
            raise ApiError(ERR_TICKET_ELIGIBILITY, 409, "RECIPROCAL ticket requires a resolvable partner")

    # 2) Membership active (ERR_MEMBERSHIP_NOT_ACTIVE, 409)
    if member_tickets and membership["status"] != "ACTIVE":
        raise ApiError(ERR_MEMBERSHIP_NOT_ACTIVE, 409, "Membership is not ACTIVE")

    # 3) Slot window (ERR_SLOT_WINDOW, 409): status OPEN and starts_at strictly future.
    if slot["status"] != "OPEN":
        raise ApiError(ERR_SLOT_WINDOW, 409, "Slot is not OPEN")
    slot_start = parse_iso(slot["starts_at"])
    slot_end = parse_iso(slot["ends_at"])
    if not (slot_start > clock.now()):
        raise ApiError(ERR_SLOT_WINDOW, 409, "Slot window has already opened")

    # 4) Slot overlap (ERR_SLOT_OVERLAP, 409): half-open windows; adjacency allowed.
    for other in db.admission_orders.values():
        if other["id"] == order["id"]:
            continue
        if other["patron_id"] != order["patron_id"]:
            continue
        if other["status"] not in ("CONFIRMED", "CHECKED_IN"):
            continue
        o_slot = db.timed_entry_slots.get(other["slot_id"])
        if not o_slot:
            continue
        o_start = parse_iso(o_slot["starts_at"])
        o_end = parse_iso(o_slot["ends_at"])
        if _windows_overlap(slot_start, slot_end, o_start, o_end):
            raise ApiError(ERR_SLOT_OVERLAP, 409, "Patron has an overlapping slot booking")

    # 5) Exhibit buffer (ERR_EXHIBIT_BUFFER_CONFLICT, 409): closed buffered interval.
    if session is not None:
        from datetime import timedelta
        buffer_minutes = exhibit.get("buffer_minutes", 0) if exhibit else 0
        s_start = parse_iso(session["starts_at"])
        s_end = parse_iso(session["ends_at"])
        buf = timedelta(minutes=buffer_minutes)
        for other in db.admission_orders.values():
            if other["id"] == order["id"]:
                continue
            if other["patron_id"] != order["patron_id"]:
                continue
            if other["status"] not in ("CONFIRMED", "CHECKED_IN"):
                continue
            other_session_id = other.get("exhibit_session_id")
            if not other_session_id:
                continue
            o_sess = db.exhibit_sessions.get(other_session_id)
            if not o_sess:
                continue
            o_start = parse_iso(o_sess["starts_at"])
            o_end = parse_iso(o_sess["ends_at"])
            # Closed interval, buffered: conflict if windows come within buffer
            # of each other (a booking exactly buffer_minutes away is disallowed).
            if (s_start - buf) <= o_end and o_start <= (s_end + buf):
                raise ApiError(ERR_EXHIBIT_BUFFER_CONFLICT, 409, "Exhibit buffer conflict")

    # 6) Guest-pass availability (ERR_NO_GUEST_PASS, 409)
    if guest_tickets:
        unused = _unused_passes(membership["id"])
        if len(unused) < len(guest_tickets):
            raise ApiError(ERR_NO_GUEST_PASS, 409, "Not enough UNUSED guest passes")

    # 7) Capacity (ERR_SLOT_CAPACITY, 409): reaching limit exactly is allowed.
    if slot["reserved_count"] + party_size > slot["capacity_total"]:
        raise ApiError(ERR_SLOT_CAPACITY, 409, "Slot capacity would be exceeded")
    if session is not None:
        if session["reserved_count"] + party_size > session["capacity_total"]:
            raise ApiError(ERR_SLOT_CAPACITY, 409, "Session capacity would be exceeded")

    # --- All guards passed: commit atomically. ---

    # Lock final pricing.
    final_total = pricing.compute_final(order)
    order["final_total_cents"] = final_total
    order["status"] = "CONFIRMED"
    db.touch(order)

    # Capacity reservations.
    slot["reserved_count"] += party_size
    db.touch(slot)
    if session is not None:
        session["reserved_count"] += party_size
        db.touch(session)

    # Reserve guest passes: oldest UNUSED first (created_at tie-break).
    if guest_tickets:
        unused = _unused_passes(membership["id"])
        unused.sort(key=lambda g: (g.get("created_at"), g.get("_seq", 0)))
        for t in guest_tickets:
            gp = unused.pop(0)
            gp["status"] = "RESERVED"
            gp["reserved_order_id"] = order["id"]
            db.touch(gp)
            t["guest_pass_id"] = gp["id"]
            db.touch(t)

    # Donation receipt.
    if order.get("donation_cents", 0) > 0:
        _create_order_donation(order)

    return order


def _unused_passes(membership_id):
    return [
        g for g in db.guest_passes.values()
        if g["membership_id"] == membership_id and g["status"] == "UNUSED"
    ]


def _create_order_donation(order):
    don = {
        "order_id": order["id"],
        "membership_id": None,
        "amount_cents": order["donation_cents"],
    }
    don["id"] = db.new_id()
    don["created_at"] = db.now_iso()
    don["_seq"] = db.next_seq()
    db.donations[don["id"]] = don
    return don


# ---------------------------------------------------------------------------
# Check-in: CONFIRMED -> CHECKED_IN
# ---------------------------------------------------------------------------

def check_in(order):
    if order["status"] != "CONFIRMED":
        raise invalid_state("Order is not CONFIRMED")
    slot = db.timed_entry_slots[order["slot_id"]]
    start = parse_iso(slot["starts_at"])
    end = parse_iso(slot["ends_at"])
    now = clock.now()
    if not (start <= now < end):
        raise ApiError(ERR_SLOT_WINDOW, 409, "Check-in outside the entry window")
    order["status"] = "CHECKED_IN"
    db.touch(order)
    for t in order_tickets(order, include_voided=True):
        if t.get("state") == "ACTIVE":
            t["state"] = "SCANNED"
            db.touch(t)
    for gp in _order_reserved_passes(order):
        gp["status"] = "REDEEMED"
        db.touch(gp)
    return order


def _order_reserved_passes(order):
    return [
        g for g in db.guest_passes.values()
        if g.get("reserved_order_id") == order["id"] and g["status"] == "RESERVED"
    ]


def _order_redeemed_passes(order):
    return [
        g for g in db.guest_passes.values()
        if g.get("reserved_order_id") == order["id"] and g["status"] == "REDEEMED"
    ]


# ---------------------------------------------------------------------------
# Cancel: DRAFT -> CANCELLED  /  CONFIRMED -> CANCELLED
# ---------------------------------------------------------------------------

def cancel(order):
    status = order["status"]
    if status not in ("DRAFT", "CONFIRMED"):
        raise invalid_state("Order is not cancellable")
    party_size = order["party_size"]

    if status == "DRAFT":
        # Void all tickets; no capacity was held.
        for t in order_tickets(order, include_voided=True):
            if t.get("state") != "VOIDED":
                t["state"] = "VOIDED"
                db.touch(t)
        order["status"] = "CANCELLED"
        db.touch(order)
        return order

    # CONFIRMED -> CANCELLED: full release.
    slot = db.timed_entry_slots[order["slot_id"]]
    session = db.exhibit_sessions.get(order["exhibit_session_id"]) if order.get("exhibit_session_id") else None

    for t in order_tickets(order, include_voided=True):
        if t.get("state") == "ACTIVE":
            t["state"] = "VOIDED"
            db.touch(t)
    # Release held capacity by party_size (floored at 0).
    slot["reserved_count"] = max(0, slot["reserved_count"] - party_size)
    db.touch(slot)
    if session is not None:
        session["reserved_count"] = max(0, session["reserved_count"] - party_size)
        db.touch(session)
    # Return RESERVED guest passes to UNUSED.
    for gp in _order_reserved_passes(order):
        gp["status"] = "UNUSED"
        gp["reserved_order_id"] = None
        db.touch(gp)
    order["status"] = "CANCELLED"
    db.touch(order)
    return order


# ---------------------------------------------------------------------------
# Refund: CHECKED_IN -> REFUNDED
# ---------------------------------------------------------------------------

def refund(order):
    if order["status"] != "CHECKED_IN":
        raise invalid_state("Order is not CHECKED_IN")
    party_size = order["party_size"]
    slot = db.timed_entry_slots[order["slot_id"]]
    session = db.exhibit_sessions.get(order["exhibit_session_id"]) if order.get("exhibit_session_id") else None

    for t in order_tickets(order, include_voided=True):
        if t.get("state") != "VOIDED":
            t["state"] = "VOIDED"
            db.touch(t)
    slot["reserved_count"] = max(0, slot["reserved_count"] - party_size)
    db.touch(slot)
    if session is not None:
        session["reserved_count"] = max(0, session["reserved_count"] - party_size)
        db.touch(session)
    # Redeemed passes are consumed -> EXPIRED (not returned to the pool).
    for gp in _order_redeemed_passes(order):
        gp["status"] = "EXPIRED"
        db.touch(gp)
    order["status"] = "REFUNDED"
    db.touch(order)
    return order


# ---------------------------------------------------------------------------
# Membership-cancel cascade: release a single RESERVED guest pass.
# Voids its linked GUEST ticket and decrements the order's slot/session
# reserved_count by 1 (cascade depth 3, PRD §3.3 / §3.7).
# ---------------------------------------------------------------------------

def release_guest_pass_on_membership_cancel(gp):
    order_id = gp.get("reserved_order_id")
    order = db.admission_orders.get(order_id) if order_id else None
    # Find the linked GUEST ticket (guest_pass_id == gp.id).
    linked = [
        t for t in db.admission_tickets.values()
        if t.get("guest_pass_id") == gp["id"] and t.get("state") == "ACTIVE"
    ]
    if order is not None and order["status"] == "CONFIRMED":
        slot = db.timed_entry_slots.get(order["slot_id"])
        session = db.exhibit_sessions.get(order["exhibit_session_id"]) if order.get("exhibit_session_id") else None
        for t in linked:
            t["state"] = "VOIDED"
            db.touch(t)
            # Decrement the order's slot reserved_count by 1 for the freed seat.
            if slot is not None:
                slot["reserved_count"] = max(0, slot["reserved_count"] - 1)
                db.touch(slot)
            if session is not None:
                session["reserved_count"] = max(0, session["reserved_count"] - 1)
                db.touch(session)
    else:
        # Order no longer CONFIRMED (or absent): just void any active linked ticket
        # without capacity change (capacity already released by the order's own flow).
        for t in linked:
            t["state"] = "VOIDED"
            db.touch(t)
    # Clear the reservation link.
    gp["reserved_order_id"] = None
