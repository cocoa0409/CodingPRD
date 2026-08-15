"""Shift endpoints: creation (gated on a SUBMITTED snapshot), lock, and the
OCC-guarded direct assignment creation."""

from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_UNIT_NOT_FOUND,
    ERR_SHIFT_NOT_FOUND,
    ERR_NURSE_NOT_FOUND,
    ERR_SHIFT_ALREADY_EXISTS,
    ERR_ACUITY_SNAPSHOT_REQUIRED,
    ERR_SHIFT_NOT_OPEN,
    ERR_STALE_SHIFT_VERSION,
    ERR_COMPETENCY_NOT_HELD,
    ERR_NOT_CHARGE_QUALIFIED,
    ERR_SHIFT_OVERLAP,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services.core import (
    SHIFT_CODES,
    evaluate_posture,
    governing_snapshot_for,
    shift_for_slot,
    shift_window,
    lock_shift,
    create_assignment,
    nurse_has_overlap,
    refresh_shift,
    pub,
)
from util import (
    get_json_body,
    req_iso_date,
    req_enum,
    opt_bool,
    fmt_dt,
    parse_pagination,
    paginate,
    apply_filters,
)

bp = Blueprint("shifts", __name__)


@bp.post("/shifts")
@require_roles("NurseAdmin")
def create_shift(_user_id: str, _role: str):
    body = get_json_body()

    # Body FK: presence, then existence.
    if "unit_id" not in body or body["unit_id"] is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: unit_id")
    unit_id = body["unit_id"]
    if not isinstance(unit_id, str) or unit_id == "":
        raise_err(ERR_INVALID_REQUEST, "unit_id must be a string")
    unit = db.units.get(unit_id)
    if unit is None:
        raise_err(ERR_UNIT_NOT_FOUND, "Unit not found")

    shift_date = req_iso_date(body, "shift_date").isoformat()
    shift_code = req_enum(body, "shift_code", SHIFT_CODES)

    # Uniqueness (tier 8) before the referential prerequisite (tier 9).
    if shift_for_slot(unit_id, shift_date, shift_code) is not None:
        raise_err(ERR_SHIFT_ALREADY_EXISTS, "A shift already exists for this unit/date/code")

    governing = governing_snapshot_for(unit_id, shift_date, shift_code)
    if governing is None:
        raise_err(ERR_ACUITY_SNAPSHOT_REQUIRED, "No SUBMITTED acuity snapshot exists for the shift slot")

    start_dt, end_dt = shift_window(shift_date, shift_code)
    required = governing["required_nurses"]
    posture = evaluate_posture(0, required, False)

    shift = {
        "unit_id": unit_id,
        "shift_date": shift_date,
        "shift_code": shift_code,
        "start_at": fmt_dt(start_dt),
        "end_at": fmt_dt(end_dt),
        "governing_snapshot_id": governing["id"],
        "required_nurses": required,
        "counted_assignments": 0,
        "sitter_diversion_count": 0,
        "effective_assignments": 0,
        "charge_covered": False,
        "staffing_posture": posture,
        "status": "STAFFED" if posture == "ADEQUATE" else "OPEN",
        "posture_at_lock": None,
        "counted_at_lock": None,
        "_start_dt": start_dt,
        "_end_dt": end_dt,
    }
    db.stamp_new(shift)
    db.shifts[shift["id"]] = shift
    return success_object(pub(shift), 201)


@bp.get("/shifts")
@require_roles(*ALL_ROLES)
def list_shifts(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sorted(db.shifts.values(), key=lambda s: s["created_at"])
    items = apply_filters(items, {
        "unit_id": request.args.get("unit_id"),
        "shift_date": request.args.get("shift_date"),
        "shift_code": request.args.get("shift_code"),
        "status": request.args.get("status"),
        "staffing_posture": request.args.get("staffing_posture"),
        "governing_snapshot_id": request.args.get("governing_snapshot_id"),
    })
    page, total = paginate(items, limit, offset)
    return success_list([pub(s) for s in page], limit, offset, total)


@bp.get("/shifts/<shiftId>")
@require_roles(*ALL_ROLES)
def get_shift(shiftId: str, _user_id: str, _role: str):
    shift = db.shifts.get(shiftId)
    if shift is None:
        raise_err(ERR_SHIFT_NOT_FOUND, "Shift not found")
    return success_object(pub(shift))


@bp.post("/shifts/<shiftId>/lock")
@require_roles("ChargeNurse")
def lock_shift_endpoint(shiftId: str, _user_id: str, _role: str):
    shift = db.shifts.get(shiftId)
    if shift is None:
        raise_err(ERR_SHIFT_NOT_FOUND, "Shift not found")
    if shift["status"] == "LOCKED":
        raise_err(ERR_SHIFT_NOT_OPEN, "Shift is already LOCKED")
    # Freeze from freshly derived live values, then lock + cascade.
    refresh_shift(shift)
    lock_shift(shift)
    return success_object(pub(shift), 200)


@bp.post("/shifts/<shiftId>/assignments")
@require_roles("ChargeNurse")
def create_direct_assignment(shiftId: str, _user_id: str, _role: str):
    # Path existence.
    shift = db.shifts.get(shiftId)
    if shift is None:
        raise_err(ERR_SHIFT_NOT_FOUND, "Shift not found")

    body = get_json_body()

    # Body FK: presence, then existence.
    if "nurse_id" not in body or body["nurse_id"] is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: nurse_id")
    nurse_id = body["nurse_id"]
    if not isinstance(nurse_id, str) or nurse_id == "":
        raise_err(ERR_INVALID_REQUEST, "nurse_id must be a string")
    nurse = db.nurses.get(nurse_id)
    if nurse is None:
        raise_err(ERR_NURSE_NOT_FOUND, "Nurse not found")

    # Remaining shape checks.
    is_charge = opt_bool(body, "is_charge", False)
    if "expected_shift_version" not in body or body["expected_shift_version"] is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: expected_shift_version")
    expected_shift_version = body["expected_shift_version"]
    if not isinstance(expected_shift_version, int) or isinstance(expected_shift_version, bool):
        raise_err(ERR_INVALID_REQUEST, "expected_shift_version must be an integer")

    # State precondition, then OCC (evaluated after state per PRD 2.5 tier 6).
    if shift["status"] == "LOCKED":
        raise_err(ERR_SHIFT_NOT_OPEN, "Shift is LOCKED")
    if expected_shift_version != shift["version"]:
        raise_err(ERR_STALE_SHIFT_VERSION, "expected_shift_version does not match the shift's current version")

    # Business safety: competency, charge qualification, half-open overlap.
    unit = db.units[shift["unit_id"]]
    if unit["unit_type"] not in nurse["competencies"]:
        raise_err(ERR_COMPETENCY_NOT_HELD, "Nurse's competencies do not include the shift's unit_type")
    if is_charge and not nurse["charge_qualified"]:
        raise_err(ERR_NOT_CHARGE_QUALIFIED, "Nurse is not charge qualified")
    if nurse_has_overlap(nurse_id, shift["_start_dt"], shift["_end_dt"]):
        raise_err(ERR_SHIFT_OVERLAP, "Assignment overlaps an existing live commitment")

    assignment = create_assignment(
        shift, nurse, source="DIRECT", status="PROPOSED", is_charge=is_charge
    )
    # Pinned side effect: creating a direct assignment advances Shift.version by 1.
    db.touch(shift)
    return success_object(pub(assignment), 201)
