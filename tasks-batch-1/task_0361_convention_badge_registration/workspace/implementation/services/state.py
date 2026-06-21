"""Cross-entity state operations: capacity counter reconciliation, badge void
cascade, and session-waitlist promotion (PRD §2.5, §3.4, §3.5, §3.6)."""
import common
import db

# Badge statuses that count toward capacity (non-voided) — PRD §3.1 / calc capacity_counters.
COUNTED_BADGE_STATUSES = {"ISSUED", "PICKED_UP", "PRINTED"}


def recompute_convention_count(convention):
    """Recompute Convention.badges_issued_count from the authoritative badge set.

    Counting badges whose status IN {ISSUED, PICKED_UP, PRINTED} across all orders
    of this convention (PRD §3.4, calc capacity_counters). Recomputing IS a mutation
    of the convention, so it touches updated_at/version (PRD §2.4).
    """
    conv_id = convention["id"]
    count = 0
    for badge in db.badges.values():
        order = db.orders.get(badge["order_id"])
        if order is None:
            continue
        if order["convention_id"] == conv_id and badge["status"] in COUNTED_BADGE_STATUSES:
            count += 1
    convention["badges_issued_count"] = count
    common.touch(convention)


def recompute_ticket_type_count(ticket_type):
    """Recompute TicketType.tier_issued_count from the authoritative badge set."""
    tt_id = ticket_type["id"]
    count = 0
    for badge in db.badges.values():
        if badge["ticket_type_id"] == tt_id and badge["status"] in COUNTED_BADGE_STATUSES:
            count += 1
    ticket_type["tier_issued_count"] = count
    common.touch(ticket_type)


def recompute_session_seats(session):
    """Recompute Session.seats_taken from CONFIRMED reservations (PRD §3.6)."""
    sess_id = session["id"]
    count = sum(
        1 for r in db.session_reservations.values()
        if r["session_id"] == sess_id and r["status"] == "CONFIRMED"
    )
    session["seats_taken"] = count
    common.touch(session)


def promote_waitlist(session):
    """Promote the highest-waitlist_score WAITLISTED reservation on the session to
    CONFIRMED while a seat is free (PRD §3.6 cascade C hop / §3.4 cascade B hop 3).

    Tie-break by earliest created_at (creation sequence). Promotion may occur only
    while seats_taken < seat_capacity. A single freed seat promotes at most one row.
    """
    if session["seats_taken"] >= session["seat_capacity"]:
        return
    waitlisted = [
        r for r in db.session_reservations.values()
        if r["session_id"] == session["id"] and r["status"] == "WAITLISTED"
    ]
    if not waitlisted:
        return
    # priority_score DESC, then created_at ASC (creation sequence).
    waitlisted.sort(key=lambda r: (-r["waitlist_score"], r["_seq"]))
    top = waitlisted[0]
    top["status"] = "CONFIRMED"
    top["waitlist_score"] = 0
    common.touch(top)
    # Recompute seats_taken after promotion (PRD §3.6).
    recompute_session_seats(session)


def cancel_reservations_for_badge(badge):
    """Cancel a badge's CONFIRMED/WAITLISTED reservations and, for each freed
    CONFIRMED seat, promote the top waitlisted reservation on that session
    (PRD §3.5 void cascade / §3.4 cascade B hop 2-3)."""
    reservations = [
        r for r in db.session_reservations.values()
        if r["badge_id"] == badge["id"] and r["status"] in {"CONFIRMED", "WAITLISTED"}
    ]
    # Process in creation order for determinism.
    reservations.sort(key=lambda r: r["_seq"])
    for res in reservations:
        was_confirmed = res["status"] == "CONFIRMED"
        res["status"] = "CANCELLED"
        common.touch(res)
        if was_confirmed:
            session = db.sessions.get(res["session_id"])
            if session is not None:
                recompute_session_seats(session)
                promote_waitlist(session)


def void_badge(badge):
    """Void a badge: status->VOID, rfid->DEACTIVATED, cancel reservations (with
    waitlist promotion), then recompute capacity counters (PRD §3.5).

    Counter recomputation is performed by the caller after all badges in a batch
    are voided so the convention/ticket-type counts settle once per affected row.
    """
    badge["status"] = "VOID"
    badge["rfid_status"] = "DEACTIVATED"
    common.touch(badge)
    cancel_reservations_for_badge(badge)
