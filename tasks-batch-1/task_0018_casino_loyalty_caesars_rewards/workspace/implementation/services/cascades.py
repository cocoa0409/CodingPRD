"""Cascade orchestration when a Member state transitions.

These functions are called from inside transition handlers and apply the
depth-2/3 cascades documented in PRD §2.6 / §3.7 / SCAFFOLD §1.2.

Every touched child entity gets its own updated_at refresh and version bump.
"""
import db
from common import stamp_update


def cascade_on_exclusion(member: dict) -> None:
    """When Member.exclusion_status transitions to EXCLUDED:

    - HostAssignment{member, status IN (PENDING_APPROVAL, ACTIVE)} -> REVOKED
    - CompRoomBooking{member, status IN (PENDING, CONFIRMED)} -> CANCELLED
    - If any revoked assignment was ACTIVE, clear member.assigned_host_id.

    The member's own version/updated_at bump is the caller's responsibility
    (single Member.version bump per logical operation, including cascade).
    """
    mid = member["id"]
    had_active_assignment = False
    for a in db.host_assignments.values():
        if a["member_id"] != mid:
            continue
        if a["status"] in ("PENDING_APPROVAL", "ACTIVE"):
            if a["status"] == "ACTIVE":
                had_active_assignment = True
            a["status"] = "REVOKED"
            stamp_update(a)
    for b in db.comp_room_bookings.values():
        if b["member_id"] != mid:
            continue
        if b["status"] in ("PENDING", "CONFIRMED"):
            b["status"] = "CANCELLED"
            stamp_update(b)
    if had_active_assignment:
        member["assigned_host_id"] = None


def cascade_on_velocity_suspended(member: dict) -> None:
    """When Member.velocity_status transitions to SUSPENDED:

    - CompRoomBooking{member, status IN (PENDING, CONFIRMED)} -> CANCELLED.
    """
    mid = member["id"]
    for b in db.comp_room_bookings.values():
        if b["member_id"] != mid:
            continue
        if b["status"] in ("PENDING", "CONFIRMED"):
            b["status"] = "CANCELLED"
            stamp_update(b)
