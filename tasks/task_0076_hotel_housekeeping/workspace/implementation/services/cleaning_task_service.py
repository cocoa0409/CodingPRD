"""Cleaning-task lifecycle: create, auto-dispatch, cancellation cascades."""

from db import DB, new_id
from services.audit import append_audit
from services.calculations import (
    compute_estimated_minutes,
    refresh_priority,
)
from services.common import stamp_create, bump
from services.time_util import utc_now_iso


# --------------------------------------------------------------------------- #
# Selector policy
# --------------------------------------------------------------------------- #
def _select_housekeeper(room: dict):
    """Return the chosen housekeeper dict or None."""
    from services.workload import compute_provisional_workload
    candidates = [
        h for h in DB["housekeepers"].values()
        if h.get("shift_status") == "ON_SHIFT"
        and h.get("assigned_zone") == room["zone_code"]
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda h: (
        compute_provisional_workload(h["id"]),
        h["employee_code"],
    ))
    return candidates[0]


# --------------------------------------------------------------------------- #
# Create + auto-dispatch
# --------------------------------------------------------------------------- #
def build_cleaning_task(*, room: dict, task_source: str,
                        expedite_flag: bool = False,
                        early_check_in_at=None,
                        parent_task_id=None):
    task = {
        "room_id": room["id"],
        "task_source": task_source,
        "expedite_flag": bool(expedite_flag),
        "early_check_in_at": early_check_in_at,
        "parent_task_id": parent_task_id,
        "assigned_housekeeper_id": None,
        "accepted_at": None,
        "started_at": None,
        "submitted_at": None,
        "actual_minutes": None,
        "status": "PENDING",
    }
    task["estimated_minutes"] = compute_estimated_minutes(room, task_source)
    refresh_priority(task, room)
    stamp_create(task)
    DB["cleaning_tasks"][task["id"]] = task
    return task


def try_auto_dispatch(task: dict, room: dict):
    """Try to auto-dispatch. Mutates the task in place; no error if no eligible."""
    if task["status"] != "PENDING":
        return False
    hk = _select_housekeeper(room)
    if hk is None:
        return False
    task["assigned_housekeeper_id"] = hk["id"]
    task["status"] = "ASSIGNED"
    bump(task)
    return True


def create_and_dispatch(*, room, task_source, expedite_flag=False,
                        early_check_in_at=None, parent_task_id=None):
    task = build_cleaning_task(
        room=room,
        task_source=task_source,
        expedite_flag=expedite_flag,
        early_check_in_at=early_check_in_at,
        parent_task_id=parent_task_id,
    )
    try_auto_dispatch(task, room)
    return task


# --------------------------------------------------------------------------- #
# Cascade cancellation when a room goes OUT_OF_ORDER
# --------------------------------------------------------------------------- #
def cancel_open_tasks_for_room(room_id: str):
    """Cascade-cancel every PENDING/ASSIGNED/ACCEPTED/IN_PROGRESS task on this room."""
    for t in list(DB["cleaning_tasks"].values()):
        if t["room_id"] != room_id:
            continue
        if t["status"] in {"PENDING", "ASSIGNED", "ACCEPTED", "IN_PROGRESS"}:
            t["status"] = "CANCELLED"
            bump(t)
            append_audit(
                actor_id="system",
                actor_role=None,
                action_type="ROOM_STATUS_CHANGE",
                subject_entity="CleaningTask",
                subject_id=t["id"],
                detail={"cancelled_via": "ROOM_OUT_OF_ORDER_CASCADE"},
            )
