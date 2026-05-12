"""Session slot transitions and cascades."""
from datetime import timedelta

from db import store, bump, parse_iso, now_dt, MATCH_CUTOFF_MINUTES, START_GRACE_MINUTES
from errors import (
    raise_error,
    ERR_SESSION_NOT_MATCHED, ERR_OUTSIDE_START_WINDOW, ERR_VENUE_NOT_ACTIVE,
    ERR_STAFFING_INCOMPLETE,
)
from audit import write_audit
from services import booking_service


def start_slot(slot: dict, actor_user_id: str, actor_role: str):
    # PRD §3.3 pins "match axis still OPEN → ERR_SESSION_NOT_MATCHED" as the
    # match-side state guard for start. PRD §3.7's deadline cascade can leave
    # an unmatched slot in match_status=MATCH_FAILED + schedule_status=CANCELLED,
    # which is also a "not MATCHED" condition; we surface ERR_SESSION_NOT_MATCHED
    # for both so the match-axis guarantee is reported uniformly.
    if slot["match_status"] != "MATCHED":
        raise_error(ERR_SESSION_NOT_MATCHED, "slot match axis is not MATCHED")
    if slot["schedule_status"] != "SCHEDULED":
        raise_error(ERR_OUTSIDE_START_WINDOW, "slot not in SCHEDULED status")
    starts_at = parse_iso(slot["starts_at"])
    now = now_dt()
    if not (starts_at - timedelta(minutes=START_GRACE_MINUTES) <= now <=
            starts_at + timedelta(minutes=START_GRACE_MINUTES)):
        raise_error(ERR_OUTSIDE_START_WINDOW, "outside start window")
    venue = store.venues.get(slot["venue_id"])
    if not venue or venue["status"] != "ACTIVE":
        raise_error(ERR_VENUE_NOT_ACTIVE, "venue not active")
    # Required staff present (HOST iff theme.required_host_qualifications is
    # non-empty; NPCs iff theme.required_npc_count > 0). PRD §3.10 names "If no
    # completed `HOST` assignment exists for `S`" as a legitimate state, so a
    # theme with no host qualifications need not have a HOST assignment.
    theme = store.themes[slot["theme_id"]]
    needed_npc = int(theme.get("required_npc_count", 0))
    host_quals = theme.get("required_host_qualifications") or []
    needs_host = len(host_quals) > 0
    assignments = [a for a in store.staff_assignments.values()
                   if a["slot_id"] == slot["id"]
                   and a["status"] in ("SCHEDULED", "ACTIVE")]
    host_count = sum(1 for a in assignments if a["role_type"] == "HOST")
    npc_count = sum(1 for a in assignments if a["role_type"] == "NPC")
    if needs_host and host_count < 1:
        raise_error(ERR_STAFFING_INCOMPLETE, "missing HOST")
    if npc_count < needed_npc:
        raise_error(ERR_STAFFING_INCOMPLETE, "missing required NPCs")

    slot["schedule_status"] = "LIVE"
    bump(slot)
    # Cascade SCHEDULED staff assignments -> ACTIVE
    for a in assignments:
        if a["status"] == "SCHEDULED":
            a["status"] = "ACTIVE"
            bump(a)


def complete_slot(slot: dict, actor_user_id: str, actor_role: str):
    from errors import ERR_INVALID_REQUEST
    if slot["schedule_status"] != "LIVE":
        raise_error(ERR_INVALID_REQUEST, "slot not LIVE")
    # All HOST/NPC StaffAssignments now in ACTIVE or HANDED_OFF
    assignments = [a for a in store.staff_assignments.values()
                   if a["slot_id"] == slot["id"]]
    for a in assignments:
        if a["status"] not in ("ACTIVE", "HANDED_OFF", "COMPLETED", "CANCELLED"):
            raise_error(ERR_STAFFING_INCOMPLETE, f"staff assignment {a['id']} not ACTIVE/HANDED_OFF")
    # Cascade
    slot["schedule_status"] = "COMPLETED"
    bump(slot)
    # Bookings: CHECKED_IN -> SETTLED ; CONFIRMED -> CANCELLED(NO_SHOW)
    booking_ids = [b["id"] for b in store.bookings.values() if b["slot_id"] == slot["id"]]
    for bid in booking_ids:
        b = store.bookings[bid]
        if b["status"] == "CHECKED_IN":
            b["status"] = "SETTLED"
            bump(b)
        elif b["status"] == "CONFIRMED":
            booking_service.cancel_booking(b, "NO_SHOW", actor_user_id, actor_role,
                                           sweep_waitlist=False)
        elif b["status"] == "PENDING_DEPOSIT":
            # Pre-deposit at completion — also no-op (treat as SYSTEM_MATCH_FAIL refund)
            booking_service.cancel_booking(b, "SYSTEM_MATCH_FAIL", actor_user_id, actor_role,
                                           sweep_waitlist=False)
    # Active staff -> COMPLETED
    for a in assignments:
        if a["status"] == "ACTIVE":
            a["status"] = "COMPLETED"
            bump(a)
    # Pin gross & net revenue
    booking_service.recompute_slot_aggregates(slot)
    bump(slot)


def cancel_slot(slot: dict, initiator: str, actor_user_id: str, actor_role: str,
                trigger: str = "operator"):
    """Cancel a slot. trigger ∈ {operator, venue_suspend, match_fail, content_revoked}.
    initiator for child bookings is one of: VENUE | SYSTEM_MATCH_FAIL.
    """
    if slot["schedule_status"] in ("CANCELLED", "COMPLETED"):
        return
    if slot["schedule_status"] == "LIVE":
        # Per PRD only SCHEDULED can be slot-cancelled
        from errors import ERR_INVALID_REQUEST
        raise_error(ERR_INVALID_REQUEST, "cannot cancel LIVE slot")

    slot["schedule_status"] = "CANCELLED"
    if trigger == "match_fail":
        slot["match_status"] = "MATCH_FAILED"
    bump(slot)

    # Cancel bookings
    booking_ids = [b["id"] for b in store.bookings.values() if b["slot_id"] == slot["id"]]
    for bid in booking_ids:
        b = store.bookings[bid]
        if b["status"] in ("PENDING_DEPOSIT", "CONFIRMED"):
            booking_service.cancel_booking(b, initiator, actor_user_id, actor_role,
                                           sweep_waitlist=False)
    # Expire waitlist
    for w in store.waitlist_entries.values():
        if w["slot_id"] == slot["id"] and w["status"] == "QUEUED":
            w["status"] = "EXPIRED"
            bump(w)
    # Cancel SCHEDULED staff assignments
    for a in store.staff_assignments.values():
        if a["slot_id"] == slot["id"] and a["status"] == "SCHEDULED":
            a["status"] = "CANCELLED"
            bump(a)


def check_in_booking(booking: dict, actor_user_id: str, actor_role: str):
    from errors import ERR_SESSION_NOT_LIVE
    slot = store.session_slots[booking["slot_id"]]
    if slot["schedule_status"] != "LIVE":
        raise_error(ERR_SESSION_NOT_LIVE, "slot not LIVE")
    if booking["status"] not in ("CONFIRMED",):
        from errors import ERR_INVALID_REQUEST
        raise_error(ERR_INVALID_REQUEST, "booking not CONFIRMED")
    booking["status"] = "CHECKED_IN"
    bump(booking)
