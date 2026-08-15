"""RotationShift endpoints."""

from flask import Blueprint, request

from db import store, clock
from errors import (
    ApiError,
    ERR_ROTATION_SHIFT_NOT_FOUND,
    ERR_ROTATION_SHIFT_INVALID_STATE,
    ERR_STALE_ROTATION_SHIFT_VERSION,
    ERR_TECHNICIAN_NOT_FOUND,
    ERR_FATIGUE_REST_REQUIRED,
    ERR_SHIFT_OVERLAP,
    ERR_INVALID_REQUEST,
    ERR_NOT_ASSIGNED_TECHNICIAN,
)
from helpers import (
    body,
    req_dt,
    new_id,
    serialize_rotation_shift,
    touch,
    pagination_params,
)
from middleware import get_actor, require_role, require_supervisor_capable
from response import success_object, success_list
from services.calculations import compute_standby_provisional, fatigue_blocked

bp = Blueprint("rotation_shifts", __name__)

READ_ROLES = {"PropertyAdmin", "Dispatcher", "OnCallTechnician", "MaintenanceSupervisor"}


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open overlap: [a_start, a_end) vs [b_start, b_end)."""
    return a_start < b_end and b_start < a_end


def _check_overlap(technician_id, start_at, end_at, exclude_id=None):
    for s in store.rotation_shifts.values():
        if s["technician_id"] != technician_id:
            continue
        if s["status"] not in ("PUBLISHED", "ACTIVE"):
            continue
        if exclude_id is not None and s["id"] == exclude_id:
            continue
        if _overlaps(start_at, end_at, s["start_at"], s["end_at"]):
            raise ApiError(ERR_SHIFT_OVERLAP, "Shift overlaps an existing PUBLISHED/ACTIVE shift", 409)


@bp.route("/v1/rotation-shifts", methods=["POST"])
def create_shift():
    actor = get_actor()
    require_role(actor, {"PropertyAdmin", "MaintenanceSupervisor"})
    require_supervisor_capable(actor)
    data = body()
    technician_id = data.get("technician_id")
    if not isinstance(technician_id, str) or not technician_id:
        raise ApiError(ERR_INVALID_REQUEST, "technician_id is required", 400)
    start_at = req_dt(data, "start_at")
    end_at = req_dt(data, "end_at")
    if end_at <= start_at:
        raise ApiError(ERR_INVALID_REQUEST, "end_at must be strictly after start_at", 400)
    tech = store.technicians.get(technician_id)
    if tech is None:
        raise ApiError(ERR_TECHNICIAN_NOT_FOUND, "Technician not found", 404)
    # Fatigue: rest-blocked at the shift's start
    if fatigue_blocked(tech, start_at):
        raise ApiError(ERR_FATIGUE_REST_REQUIRED, "Technician is rest-blocked at shift start", 409)
    _check_overlap(technician_id, start_at, end_at)
    now = clock.now()
    rec = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 0,
        "technician_id": technician_id,
        "start_at": start_at,
        "end_at": end_at,
        "status": "PUBLISHED",
        "needs_coverage": False,
        "standby_minutes": None,
        "provisional_shift_pay_cents": None,
        "_seq": store.next_seq(),
    }
    store.rotation_shifts[rec["id"]] = rec
    return success_object(serialize_rotation_shift(rec), 201)


@bp.route("/v1/rotation-shifts", methods=["GET"])
def list_shifts():
    actor = get_actor()
    require_role(actor, READ_ROLES)
    limit, offset = pagination_params()
    technician_id = request.args.get("technician_id")
    status = request.args.get("status")
    items = [s for s in store.rotation_shifts.values()]
    if technician_id is not None:
        items = [s for s in items if s["technician_id"] == technician_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items.sort(key=lambda s: (s["created_at"], s["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_rotation_shift(s) for s in page], limit, offset, total)


@bp.route("/v1/rotation-shifts/<rotationShiftId>", methods=["GET"])
def get_shift(rotationShiftId):
    actor = get_actor()
    require_role(actor, READ_ROLES)
    rec = store.rotation_shifts.get(rotationShiftId)
    if rec is None:
        raise ApiError(ERR_ROTATION_SHIFT_NOT_FOUND, "Rotation shift not found", 404)
    return success_object(serialize_rotation_shift(rec))


def _self_or_admin_check(actor, shift):
    if actor.role == "OnCallTechnician" and actor.user_id != shift["technician_id"]:
        raise ApiError(ERR_NOT_ASSIGNED_TECHNICIAN, "Not the shift's technician", 403)


@bp.route("/v1/rotation-shifts/<rotationShiftId>/start", methods=["POST"])
def start_shift(rotationShiftId):
    actor = get_actor()
    require_role(actor, {"OnCallTechnician", "PropertyAdmin"})
    rec = store.rotation_shifts.get(rotationShiftId)
    if rec is None:
        raise ApiError(ERR_ROTATION_SHIFT_NOT_FOUND, "Rotation shift not found", 404)
    _self_or_admin_check(actor, rec)
    now = clock.now()
    if rec["status"] != "PUBLISHED":
        raise ApiError(ERR_ROTATION_SHIFT_INVALID_STATE, "Shift is not PUBLISHED", 409)
    if not (rec["start_at"] <= now < rec["end_at"]):
        raise ApiError(ERR_ROTATION_SHIFT_INVALID_STATE, "Now is outside the shift window", 409)
    rec["status"] = "ACTIVE"
    touch(rec)
    return success_object(serialize_rotation_shift(rec))


@bp.route("/v1/rotation-shifts/<rotationShiftId>/complete", methods=["POST"])
def complete_shift(rotationShiftId):
    actor = get_actor()
    require_role(actor, {"OnCallTechnician", "PropertyAdmin"})
    rec = store.rotation_shifts.get(rotationShiftId)
    if rec is None:
        raise ApiError(ERR_ROTATION_SHIFT_NOT_FOUND, "Rotation shift not found", 404)
    _self_or_admin_check(actor, rec)
    now = clock.now()
    if rec["status"] != "ACTIVE":
        raise ApiError(ERR_ROTATION_SHIFT_INVALID_STATE, "Shift is not ACTIVE", 409)
    if now < rec["end_at"]:
        raise ApiError(ERR_ROTATION_SHIFT_INVALID_STATE, "Shift window has not finished", 409)
    tech = store.technicians.get(rec["technician_id"])
    standby_minutes, provisional_pay = compute_standby_provisional(rec, tech)
    rec["status"] = "COMPLETED"
    rec["standby_minutes"] = standby_minutes
    rec["provisional_shift_pay_cents"] = provisional_pay
    touch(rec)
    return success_object(serialize_rotation_shift(rec))


@bp.route("/v1/rotation-shifts/<rotationShiftId>/transfer", methods=["POST"])
def transfer_shift(rotationShiftId):
    actor = get_actor()
    require_role(actor, {"PropertyAdmin", "MaintenanceSupervisor"})
    require_supervisor_capable(actor)
    rec = store.rotation_shifts.get(rotationShiftId)
    if rec is None:
        raise ApiError(ERR_ROTATION_SHIFT_NOT_FOUND, "Rotation shift not found", 404)
    data = body()
    to_technician_id = data.get("to_technician_id")
    if not isinstance(to_technician_id, str) or not to_technician_id:
        raise ApiError(ERR_INVALID_REQUEST, "to_technician_id is required", 400)
    expected_version = data.get("expected_rotation_shift_version")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise ApiError(ERR_INVALID_REQUEST, "expected_rotation_shift_version is required", 400)
    # Body FK existence (priority 3)
    target = store.technicians.get(to_technician_id)
    if target is None:
        raise ApiError(ERR_TECHNICIAN_NOT_FOUND, "Target technician not found", 404)
    # State (priority 5)
    if rec["status"] != "PUBLISHED":
        raise ApiError(ERR_ROTATION_SHIFT_INVALID_STATE, "Shift is not PUBLISHED", 409)
    if expected_version != rec["version"]:
        raise ApiError(ERR_STALE_ROTATION_SHIFT_VERSION, "Stale rotation shift version", 412)
    if target["status"] != "ACTIVE":
        raise ApiError(ERR_ROTATION_SHIFT_INVALID_STATE, "Target technician is not ACTIVE", 409)
    # Fatigue (priority 6): reference time is the shift's start_at
    if fatigue_blocked(target, rec["start_at"]):
        raise ApiError(ERR_FATIGUE_REST_REQUIRED, "Target technician is rest-blocked at shift start", 409)
    # Temporal (priority 8)
    _check_overlap(to_technician_id, rec["start_at"], rec["end_at"], exclude_id=rec["id"])
    rec["technician_id"] = to_technician_id
    rec["needs_coverage"] = False
    touch(rec)
    return success_object(serialize_rotation_shift(rec))


@bp.route("/v1/rotation-shifts/<rotationShiftId>/cancel", methods=["POST"])
def cancel_shift(rotationShiftId):
    actor = get_actor()
    require_role(actor, {"PropertyAdmin", "MaintenanceSupervisor"})
    require_supervisor_capable(actor)
    rec = store.rotation_shifts.get(rotationShiftId)
    if rec is None:
        raise ApiError(ERR_ROTATION_SHIFT_NOT_FOUND, "Rotation shift not found", 404)
    if rec["status"] != "PUBLISHED":
        raise ApiError(ERR_ROTATION_SHIFT_INVALID_STATE, "Shift is not PUBLISHED", 409)
    rec["status"] = "CANCELLED"
    touch(rec)
    return success_object(serialize_rotation_shift(rec))
