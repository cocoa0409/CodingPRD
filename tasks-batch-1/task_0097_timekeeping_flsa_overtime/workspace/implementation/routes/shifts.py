"""Shift scheduling and the time-punch lifecycle (PRD §3.2, §3.3)."""
from datetime import timezone

from flask import Blueprint, g, request

import db
from errors import err
from middleware import require_role
from response import object_response, array_response
from util import (
    as_str, body, paginate, pagination, parse_datetime, public, public_list,
)
from services.helpers import (
    get_or_404, date_of, covering_week_for_punch,
)
from services.wages import (
    has_governing_ruleset, recompute_timesheet, DETENTION_GRACE_MINUTES,
)

bp = Blueprint("shifts", __name__)


def _parse_iso(raw):
    from datetime import datetime
    s = raw
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _worked_minutes(clock_in_dt, clock_out_dt):
    """Whole minutes between effective clock_in and clock_out."""
    delta = clock_out_dt - clock_in_dt
    return int(delta.total_seconds() // 60)


# ---------------------------------------------------------------------------
# Shifts
# ---------------------------------------------------------------------------
@bp.post("/shifts")
def create_shift():
    require_role("Supervisor")
    data = body()
    employee_id = as_str(data, "employee_id", required=True)
    worksite_id = as_str(data, "worksite_id", required=True)
    scheduled_start = parse_datetime(data, "scheduled_start", required=True)
    scheduled_end = parse_datetime(data, "scheduled_end", required=True)

    # Existence, left-to-right (priority 4).
    employee = get_or_404(db.employees, employee_id)
    get_or_404(db.worksites, worksite_id)

    # No governing wage rule set -> ERR_NO_WAGE_RULESET (priority 5).
    if not has_governing_ruleset(employee):
        raise err("ERR_NO_WAGE_RULESET",
                  "No wage rule set governs this employer and state.")

    # scheduled_end strictly after scheduled_start (priority 15).
    if not (scheduled_end > scheduled_start):
        raise err("ERR_INVALID_SCHEDULE",
                  "scheduled_end must be strictly after scheduled_start.")

    # No overlap with an existing non-CANCELLED shift for the same employee;
    # half-open intervals [start, end) (priority 16).
    for s in db.shifts.values():
        if s.get("employee_id") != employee_id:
            continue
        if s.get("status") == "CANCELLED":
            continue
        existing_start = _parse_iso(s["scheduled_start"])
        existing_end = _parse_iso(s["scheduled_end"])
        if scheduled_start < existing_end and existing_start < scheduled_end:
            raise err("ERR_SHIFT_OVERLAP",
                      "Shift overlaps an existing non-cancelled shift.")

    record = db.base_fields()
    record.update({
        "employee_id": employee_id,
        "worksite_id": worksite_id,
        "scheduled_start": data["scheduled_start"],
        "scheduled_end": data["scheduled_end"],
        "status": "SCHEDULED",
        "detention_minutes": 0,
        "detention_flagged": False,
    })
    db.shifts[record["id"]] = record
    return object_response(public(record), 201)


@bp.get("/shifts")
def list_shifts():
    require_role("PayrollAdmin", "Supervisor", "Employee")
    limit, offset = pagination()
    employee_id = request.args.get("employee_id")
    worksite_id = request.args.get("worksite_id")
    matches = list(db.shifts.values())
    if employee_id is not None:
        matches = [s for s in matches if s.get("employee_id") == employee_id]
    if worksite_id is not None:
        matches = [s for s in matches if s.get("worksite_id") == worksite_id]
    page, total = paginate(matches, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@bp.get("/shifts/<shift_id>")
def get_shift(shift_id):
    require_role("PayrollAdmin", "Supervisor", "Employee")
    record = get_or_404(db.shifts, shift_id)
    return object_response(public(record))


@bp.post("/shifts/<shift_id>/cancel")
def cancel_shift(shift_id):
    require_role("Supervisor")
    shift = get_or_404(db.shifts, shift_id)
    # Only while SCHEDULED (no punch opened) (priority 7).
    if shift.get("status") != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Shift can only be cancelled while SCHEDULED.")
    shift["status"] = "CANCELLED"
    db.touch(shift)
    return object_response(public(shift))


# ---------------------------------------------------------------------------
# Punches
# ---------------------------------------------------------------------------
@bp.post("/shifts/<shift_id>/punches")
def open_punch(shift_id):
    require_role("Employee")
    shift = get_or_404(db.shifts, shift_id)
    data = body()
    clock_in = parse_datetime(data, "clock_in", required=True)

    # Ownership: acting Employee.id == shift.employee_id (priority 6).
    if g.user_id != shift.get("employee_id"):
        raise err("ERR_NOT_RESOURCE_OWNER",
                  "Acting employee does not own this shift.")

    # State: shift must be SCHEDULED to open the first punch (priority 7).
    if shift.get("status") != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Shift is not SCHEDULED.")

    employee_id = shift["employee_id"]

    # New punch interval must not overlap an existing non-VOIDED CLOSED punch
    # for the same employee; intervals CLOSED on both ends (priority 13).
    # The open punch has no clock_out yet; per PRD an open establishes the
    # interval at clock_in — collision is checked against the clock_in instant
    # falling within any existing closed punch interval (inclusive ends).
    for p in db.punches.values():
        if p.get("employee_id") != employee_id:
            continue
        if p.get("status") != "CLOSED":
            continue
        p_in = _parse_iso(p["clock_in"])
        p_out = _parse_iso(p["clock_out"])
        # Closed-on-both-ends: clock_in within [p_in, p_out] collides.
        if p_in <= clock_in <= p_out:
            raise err("ERR_PUNCH_OVERLAP",
                      "Punch overlaps an existing closed punch.")

    # At most one OPEN punch per employee (priority 14).
    for p in db.punches.values():
        if p.get("employee_id") == employee_id and p.get("status") == "OPEN":
            raise err("ERR_PUNCH_ALREADY_OPEN",
                      "Employee already has an OPEN punch.")

    record = db.base_fields()
    record.update({
        "employee_id": employee_id,
        "shift_id": shift_id,
        "clock_in": data["clock_in"],
        "clock_out": None,
        "status": "OPEN",
        "worked_minutes": 0,
        "workday_date": None,
        "edited": False,
    })
    db.punches[record["id"]] = record

    # Shift SCHEDULED -> OPEN.
    shift["status"] = "OPEN"
    db.touch(shift)

    return object_response(public(record), 201)


@bp.get("/shifts/<shift_id>/punches")
def list_shift_punches(shift_id):
    require_role("PayrollAdmin", "Supervisor", "Employee")
    get_or_404(db.shifts, shift_id)
    limit, offset = pagination()
    matches = [p for p in db.punches.values() if p.get("shift_id") == shift_id]
    page, total = paginate(matches, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@bp.get("/punches")
def list_punches():
    require_role("PayrollAdmin", "Supervisor", "Employee")
    limit, offset = pagination()
    employee_id = request.args.get("employee_id")
    shift_id = request.args.get("shift_id")
    workday_date = request.args.get("workday_date")
    matches = list(db.punches.values())
    if employee_id is not None:
        matches = [p for p in matches if p.get("employee_id") == employee_id]
    if shift_id is not None:
        matches = [p for p in matches if p.get("shift_id") == shift_id]
    if workday_date is not None:
        matches = [p for p in matches if p.get("workday_date") == workday_date]
    page, total = paginate(matches, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@bp.get("/punches/<punch_id>")
def get_punch(punch_id):
    require_role("PayrollAdmin", "Supervisor", "Employee")
    record = get_or_404(db.punches, punch_id)
    return object_response(public(record))


@bp.post("/punches/<punch_id>/close")
def close_punch(punch_id):
    require_role("Employee")
    punch = get_or_404(db.punches, punch_id)
    data = body()
    clock_out = parse_datetime(data, "clock_out", required=True)

    # Ownership: acting Employee.id == punch.employee_id (priority 6).
    if g.user_id != punch.get("employee_id"):
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting employee does not own this punch.")

    # State: must be OPEN (priority 7).
    if punch.get("status") != "OPEN":
        raise err("ERR_INVALID_STATE", "Punch is not OPEN.")

    clock_in = _parse_iso(punch["clock_in"])
    # clock_out strictly after effective clock_in (priority 12).
    if not (clock_out > clock_in):
        raise err("ERR_NEGATIVE_DURATION",
                  "clock_out must be strictly after clock_in.")

    punch["clock_out"] = data["clock_out"]
    punch["status"] = "CLOSED"
    punch["worked_minutes"] = _worked_minutes(clock_in, clock_out)
    punch["workday_date"] = date_of(punch["clock_in"])
    db.touch(punch)

    # Advance owning shift OPEN -> CLOSED and recompute detention.
    shift = db.shifts.get(punch["shift_id"])
    if shift is not None:
        _recompute_detention(shift, clock_out)
        shift["status"] = "CLOSED"
        db.touch(shift)

    return object_response(public(punch))


def _recompute_detention(shift, clock_out_dt):
    sched_end = _parse_iso(shift["scheduled_end"])
    over = clock_out_dt - sched_end
    minutes = int(over.total_seconds() // 60)
    detention = max(0, minutes)
    shift["detention_minutes"] = detention
    shift["detention_flagged"] = detention > DETENTION_GRACE_MINUTES


@bp.post("/punches/<punch_id>/edits")
def edit_punch(punch_id):
    require_role("Supervisor")
    punch = get_or_404(db.punches, punch_id)
    data = body()

    # State: punch must be CLOSED (priority 7).
    if punch.get("status") != "CLOSED":
        raise err("ERR_INVALID_STATE", "Punch is not CLOSED.")

    # Frozen-timesheet guard (priority 8): covering week not APPROVED/LOCKED.
    week = covering_week_for_punch(punch)
    if week is not None and week.get("status") in ("APPROVED", "LOCKED"):
        raise err("ERR_TIMESHEET_FROZEN",
                  "Cannot edit a punch in an APPROVED or LOCKED timesheet week.")

    # Field + new_value (validated as structural request fields).
    field = data.get("field")
    if field not in ("CLOCK_IN", "CLOCK_OUT"):
        raise err("ERR_INVALID_REQUEST", "field must be CLOCK_IN or CLOCK_OUT.")
    if "new_value" not in data or data["new_value"] is None:
        raise err("ERR_INVALID_REQUEST", "new_value is required.")
    new_value = parse_datetime(data, "new_value", required=True)

    # Reason must be non-empty (priority 11).
    reason = data.get("reason")
    if not isinstance(reason, str) or reason.strip() == "":
        raise err("ERR_EDIT_REASON_REQUIRED", "A non-empty reason is required.")

    # Resulting interval: clock_out strictly after clock_in (priority 12).
    if field == "CLOCK_IN":
        old_value = punch["clock_in"]
        resulting_in = new_value
        resulting_out = _parse_iso(punch["clock_out"])
    else:
        old_value = punch["clock_out"]
        resulting_in = _parse_iso(punch["clock_in"])
        resulting_out = new_value
    if not (resulting_out > resulting_in):
        raise err("ERR_NEGATIVE_DURATION",
                  "Resulting clock_out must be strictly after clock_in.")

    # Append immutable TimeEdit audit record (id + created_at only).
    from response import now_iso
    edit = {
        "id": db.new_id(),
        "created_at": now_iso(),
        "punch_id": punch_id,
        "editor_user_id": g.user_id,
        "field": field,
        "old_value": old_value,
        "new_value": data["new_value"],
        "reason": reason,
        "_seq": next(db._seq),
    }
    db.time_edits[edit["id"]] = edit

    # Apply new value, recompute worked_minutes, set edited=true, bump version.
    if field == "CLOCK_IN":
        punch["clock_in"] = data["new_value"]
    else:
        punch["clock_out"] = data["new_value"]
    punch["worked_minutes"] = _worked_minutes(resulting_in, resulting_out)
    punch["workday_date"] = date_of(punch["clock_in"])
    punch["edited"] = True
    db.touch(punch)

    # Recompute owning shift detention when CLOCK_OUT changed.
    if field == "CLOCK_OUT":
        shift = db.shifts.get(punch["shift_id"])
        if shift is not None and shift.get("status") == "CLOSED":
            _recompute_detention(shift, resulting_out)
            db.touch(shift)

    # Cascade recompute when a DRAFT/SUBMITTED/REJECTED week covers the workday.
    cover = covering_week_for_punch(punch)
    if cover is not None and cover.get("status") in ("DRAFT", "SUBMITTED", "REJECTED"):
        recompute_timesheet(cover)
        db.touch(cover)

    return object_response(_public_edit(edit), 201)


def _public_edit(edit):
    return {k: v for k, v in edit.items() if not k.startswith("_")}


@bp.get("/punches/<punch_id>/edits")
def list_punch_edits(punch_id):
    require_role("PayrollAdmin", "Supervisor")
    get_or_404(db.punches, punch_id)
    limit, offset = pagination()
    matches = [e for e in db.time_edits.values() if e.get("punch_id") == punch_id]
    page, total = paginate(matches, limit, offset)
    return array_response([_public_edit(e) for e in page], limit, offset, total)


@bp.post("/punches/<punch_id>/void")
def void_punch(punch_id):
    require_role("Supervisor")
    punch = get_or_404(db.punches, punch_id)
    status = punch.get("status")

    if status == "OPEN":
        punch["status"] = "VOIDED"
        db.touch(punch)
        # Revert owning shift to SCHEDULED if it had no other punch.
        shift = db.shifts.get(punch["shift_id"])
        if shift is not None:
            others = [
                p for p in db.punches.values()
                if p.get("shift_id") == shift["id"]
                and p["id"] != punch_id
                and p.get("status") != "VOIDED"
            ]
            if not others:
                shift["status"] = "SCHEDULED"
                db.touch(shift)
        return object_response(public(punch))

    if status == "CLOSED":
        # Frozen-timesheet guard (priority 8).
        week = covering_week_for_punch(punch)
        if week is not None and week.get("status") in ("APPROVED", "LOCKED"):
            raise err("ERR_TIMESHEET_FROZEN",
                      "Cannot void a punch in an APPROVED or LOCKED timesheet week.")
        punch["status"] = "VOIDED"
        punch["worked_minutes"] = 0
        db.touch(punch)
        # Cascade recompute owning timesheet week.
        cover = covering_week_for_punch(punch)
        if cover is not None and cover.get("status") in ("DRAFT", "SUBMITTED", "REJECTED"):
            recompute_timesheet(cover)
            db.touch(cover)
        return object_response(public(punch))

    # Already VOIDED (terminal) -> invalid state.
    raise err("ERR_INVALID_STATE", "Punch is already VOIDED.")
