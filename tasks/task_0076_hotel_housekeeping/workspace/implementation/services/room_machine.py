"""Room state-machine transitions and INSPECTED-grace sweep."""

from datetime import timedelta

from db import DB
from services.audit import append_room_status_event, append_audit
from services.calculations import recompute_discrepancy
from services.common import bump
from services.time_util import now_utc, parse_iso


INSPECTED_GRACE_MINUTES = 30

ALL_NON_OUT_OF_ORDER = {
    "VACANT_CLEAN", "VACANT_DIRTY",
    "OCCUPIED_CLEAN", "OCCUPIED_DIRTY",
    "INSPECTED",
}


def transition_room(room: dict, new_status: str, *,
                    change_reason: str, actor_id: str,
                    correction_note=None,
                    write_audit: bool = True):
    """Single-room status transition. Always bumps version/updated_at,
    appends a RoomStatusEvent, optionally an AuditLog, and recomputes
    discrepancy_flag.
    """
    if room["status"] == new_status:
        return
    prev = room["status"]
    room["status"] = new_status
    # Remember when this transition happened so the INSPECTED-grace sweep
    # can compute elapsed time.
    room["_last_status_change_at"] = now_utc().isoformat()
    bump(room)
    append_room_status_event(
        room_id=room["id"],
        previous_status=prev,
        new_status=new_status,
        change_reason=change_reason,
        actor_id=actor_id,
        correction_note=correction_note,
    )
    if write_audit:
        append_audit(
            actor_id=actor_id,
            actor_role=None,
            action_type=("MANUAL_CORRECTION"
                         if change_reason == "MANUAL_CORRECTION"
                         else "ROOM_STATUS_CHANGE"),
            subject_entity="Room",
            subject_id=room["id"],
            detail={
                "previous": prev,
                "next": new_status,
                "change_reason": change_reason,
                "correction_note": correction_note,
            },
        )
    recompute_discrepancy(room)


def inspected_grace_sweep():
    """Advance any room in INSPECTED past the grace window to VACANT_CLEAN."""
    now = now_utc()
    for room in list(DB["rooms"].values()):
        if room["status"] != "INSPECTED":
            continue
        if room.get("pms_occupancy") != "VACANT":
            continue
        last_change = parse_iso(room.get("_last_status_change_at"))
        if last_change is None:
            continue
        if (now - last_change) >= timedelta(minutes=INSPECTED_GRACE_MINUTES):
            transition_room(
                room, "VACANT_CLEAN",
                change_reason="TASK_COMPLETED",
                actor_id="system",
                write_audit=True,
            )
