"""Test-task routes: create under a sample, read, assign/reassign/start/
complete/cancel."""

from flask import Blueprint, g

from db import DB, new_id, LOCK, next_priority_seq
from errors import (
    ERR_NOT_FOUND, ERR_VALIDATION, ERR_INVALID_STATE, ERR_FORBIDDEN,
    ERR_TEST_METHOD_NOT_SUPPORTED, ERR_NO_QUALIFIED_TESTER,
    ERR_TESTER_WORKLOAD_EXCEEDED, raise_error,
)
from middleware import auth_required
from response import success_response
from services.common import get_json_body, require_fields
from services.serializers import serialize_task
from services.time_util import now_iso, parse_iso
from services.calculations import (
    METHOD_TO_CATEGORY, BASE_FEE_CENTS, booking_duration_minutes_ceil,
)
from services.state import (
    find_assignment_candidate, assign_task_to_tester, release_task_assignment,
    recompute_sample_after_completion, touch,
)

bp = Blueprint("tasks", __name__)

VALID_METHODS = set(METHOD_TO_CATEGORY.keys())


@bp.post("/samples/<sid>/tasks")
@auth_required(["LabClerk"])
def create_task(sid):
    body = get_json_body()
    sample = DB["samples"].get(sid)
    if sample is None:
        raise_error(ERR_NOT_FOUND, "Sample not found")
    require_fields(body, ["test_method"])
    method = body["test_method"]
    if method not in VALID_METHODS:
        raise_error(ERR_VALIDATION, "test_method invalid")
    urgent = body.get("urgent", False)
    if not isinstance(urgent, bool):
        raise_error(ERR_VALIDATION, "urgent must be boolean")
    # Test-method to material-category coupling
    if METHOD_TO_CATEGORY[method] != sample.get("material_category"):
        raise_error(ERR_TEST_METHOD_NOT_SUPPORTED,
                    "Test method not supported for this material_category")
    # Sample must not be DISPOSED
    if sample.get("status") == "DISPOSED":
        raise_error(ERR_INVALID_STATE, "Sample is DISPOSED")

    with LOCK:
        now = now_iso()
        # priority_seq: urgent vs non-urgent ranks via composite key. We use
        # an integer where urgent contributes a large negative offset so the
        # sort comparison "smaller is higher priority" naturally yields urgent
        # ahead of non-urgent at the same instant. We expose this as a plain
        # monotonic integer with urgent task seq << non-urgent. To keep both
        # streams strictly monotonic in created order while still ranking
        # urgent first, we encode urgent as -seq and non-urgent as +seq with
        # a magnitude that gives urgent strictly lower rank values.
        seq = next_priority_seq()
        priority_seq = (-seq) if urgent else seq

        row = {
            "id": new_id(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "sample_id": sid,
            "test_method": method,
            "urgent": urgent,
            "assigned_tester_id": None,
            "instrument_booking_id": None,
            "status": "PENDING_ASSIGNMENT",
            "retest_count": 0,
            "priority_seq": priority_seq,
        }
        DB["tasks"][row["id"]] = row

        # Synchronously attempt to assign — if no eligible tester, leave it
        # PENDING_ASSIGNMENT silently.
        candidate, reason = find_assignment_candidate(row)
        if candidate is not None:
            assign_task_to_tester(row, candidate)

        # Advance sample if this is its first task
        if sample.get("status") == "REGISTERED":
            sample["status"] = "IN_TESTING"
            touch(sample)
    return success_response(serialize_task(row), 201)


@bp.get("/tasks/<tid>")
@auth_required(["LabManager", "LabClerk", "Tester"])
def read_task(tid):
    row = DB["tasks"].get(tid)
    if row is None:
        raise_error(ERR_NOT_FOUND, "Task not found")
    return success_response(serialize_task(row), 200)


@bp.post("/tasks/<tid>/assign")
@auth_required(["LabManager"])
def assign_task(tid):
    row = DB["tasks"].get(tid)
    if row is None:
        raise_error(ERR_NOT_FOUND, "Task not found")
    if row.get("status") != "PENDING_ASSIGNMENT":
        raise_error(ERR_INVALID_STATE, "Task must be PENDING_ASSIGNMENT to be assigned")
    with LOCK:
        row = DB["tasks"].get(tid)
        if row is None:
            raise_error(ERR_NOT_FOUND, "Task not found")
        if row.get("status") != "PENDING_ASSIGNMENT":
            raise_error(ERR_INVALID_STATE, "Task must be PENDING_ASSIGNMENT to be assigned")
        candidate, reason = find_assignment_candidate(row)
        if candidate is None:
            if reason == "workload_exceeded":
                raise_error(ERR_TESTER_WORKLOAD_EXCEEDED,
                            "All qualified testers are at workload cap")
            else:
                raise_error(ERR_NO_QUALIFIED_TESTER,
                            "No qualified tester available")
        assign_task_to_tester(row, candidate)
    return success_response(serialize_task(row), 200)


@bp.post("/tasks/<tid>/reassign")
@auth_required(["LabManager"])
def reassign_task(tid):
    row = DB["tasks"].get(tid)
    if row is None:
        raise_error(ERR_NOT_FOUND, "Task not found")
    if row.get("status") not in ("ASSIGNED", "IN_PROGRESS"):
        raise_error(ERR_INVALID_STATE, "Task not in a reassignable status")
    with LOCK:
        row = DB["tasks"].get(tid)
        if row is None:
            raise_error(ERR_NOT_FOUND, "Task not found")
        if row.get("status") not in ("ASSIGNED", "IN_PROGRESS"):
            raise_error(ERR_INVALID_STATE, "Task not in a reassignable status")
        release_task_assignment(row, cancel_booking=True)
        row["status"] = "PENDING_ASSIGNMENT"
        touch(row)
    return success_response(serialize_task(row), 200)


@bp.post("/tasks/<tid>/start")
@auth_required(["Tester"])
def start_task(tid):
    row = DB["tasks"].get(tid)
    if row is None:
        raise_error(ERR_NOT_FOUND, "Task not found")
    if row.get("status") != "ASSIGNED":
        raise_error(ERR_INVALID_STATE, "Task must be ASSIGNED to start")
    if row.get("assigned_tester_id") != g.user_id:
        raise_error(ERR_INVALID_STATE, "Only the assigned tester can start the task")
    bid = row.get("instrument_booking_id")
    if not bid:
        raise_error(ERR_INVALID_STATE, "Task has no instrument booking")
    booking = DB["bookings"].get(bid)
    if booking is None or booking.get("status") != "RESERVED":
        raise_error(ERR_INVALID_STATE, "Instrument booking is not RESERVED")
    instrument = DB["instruments"].get(booking["instrument_id"])
    if instrument is None or instrument.get("status") != "AVAILABLE":
        raise_error(ERR_INVALID_STATE, "Instrument is not AVAILABLE")
    with LOCK:
        row["status"] = "IN_PROGRESS"
        touch(row)
    return success_response(serialize_task(row), 200)


@bp.post("/tasks/<tid>/complete")
@auth_required(["Tester"])
def complete_task(tid):
    row = DB["tasks"].get(tid)
    if row is None:
        raise_error(ERR_NOT_FOUND, "Task not found")
    if row.get("status") != "IN_PROGRESS":
        raise_error(ERR_INVALID_STATE, "Task must be IN_PROGRESS to complete")
    if row.get("assigned_tester_id") != g.user_id:
        raise_error(ERR_FORBIDDEN, "Only the assigned tester can complete the task")
    # Precondition: exactly one SUBMITTED non-abnormal record on this task.
    with LOCK:
        row = DB["tasks"].get(tid)
        if row is None or row.get("status") != "IN_PROGRESS":
            raise_error(ERR_INVALID_STATE, "Task not in IN_PROGRESS")
        recs = [r for r in DB["records"].values() if r.get("task_id") == tid and r.get("status") == "SUBMITTED"]
        ok = [r for r in recs if r.get("abnormal_flag") is False]
        if len(ok) != 1:
            raise_error(ERR_INVALID_STATE,
                        "Completion requires exactly one SUBMITTED non-abnormal record")
        row["status"] = "COMPLETED"
        touch(row)
        # Decrement tester active count
        tester = DB["testers"].get(row.get("assigned_tester_id"))
        if tester is not None:
            tester["active_task_count"] = max(0, tester.get("active_task_count", 0) - 1)
            touch(tester)
        # Complete the booking and accrue usage
        bid = row.get("instrument_booking_id")
        if bid:
            booking = DB["bookings"].get(bid)
            if booking is not None and booking.get("status") == "RESERVED":
                booking["status"] = "COMPLETED"
                instrument = DB["instruments"].get(booking["instrument_id"])
                if instrument is not None:
                    minutes = booking_duration_minutes_ceil(booking["slot_start"], booking["slot_end"])
                    instrument["usage_minutes_total"] = instrument.get("usage_minutes_total", 0) + minutes
                    touch(instrument)
        # Sample maturity
        recompute_sample_after_completion(row["sample_id"])
    return success_response(serialize_task(row), 200)


@bp.post("/tasks/<tid>/cancel")
@auth_required(["LabManager"])
def cancel_task(tid):
    row = DB["tasks"].get(tid)
    if row is None:
        raise_error(ERR_NOT_FOUND, "Task not found")
    if row.get("status") not in ("ASSIGNED", "PENDING_ASSIGNMENT"):
        raise_error(ERR_INVALID_STATE, "Task not cancellable in its current state")
    # No TestRecord must exist
    with LOCK:
        row = DB["tasks"].get(tid)
        if row is None or row.get("status") not in ("ASSIGNED", "PENDING_ASSIGNMENT"):
            raise_error(ERR_INVALID_STATE, "Task not cancellable in its current state")
        if any(r.get("task_id") == tid for r in DB["records"].values()):
            raise_error(ERR_INVALID_STATE, "Cannot cancel after a record exists")
        prev_tester_id = row.get("assigned_tester_id")
        if prev_tester_id:
            tester = DB["testers"].get(prev_tester_id)
            if tester is not None:
                tester["active_task_count"] = max(0, tester.get("active_task_count", 0) - 1)
                touch(tester)
        bid = row.get("instrument_booking_id")
        if bid:
            b = DB["bookings"].get(bid)
            if b is not None and b.get("status") == "RESERVED":
                b["status"] = "CANCELLED"
        row["assigned_tester_id"] = None
        row["instrument_booking_id"] = None
        row["status"] = "CANCELLED"
        touch(row)
    return success_response(serialize_task(row), 200)
