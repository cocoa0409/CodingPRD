"""Duty rotation: shift creation, assignment, swaps and outcomes."""
from datetime import timedelta

from flask import Blueprint, g

import responses
import services
import store
import validators as V
from auth import endpoint, require_action_role, require_owner
from constants import API_PREFIX, DUTY_POINTS, SHIFT_TYPES
from errors import ApiError

DIRECTOR = ["ResidenceDirector"]
RA_OR_DIRECTOR = ["ResidentAssistant", "ResidenceDirector"]
bp = Blueprint("duty", __name__)


def _ra_gates(ra, shift):
    services.ra_certified_gate(ra)
    services.ra_active_gate(ra)


def _floor_gate(ra, shift):
    if ra.get("assigned_floor_id") != shift["floor_id"]:
        raise ApiError("ERR_FLOOR_MISMATCH")


@bp.route("%s/duty-shifts" % API_PREFIX, methods=["POST"])
@endpoint(DIRECTOR)
def create_shift():
    body = V.body()
    floor_id = V.s_id(body, "floor_id")
    shift_type = V.s_enum(body, "shift_type", SHIFT_TYPES)
    start_at = V.s_dt(body, "start_at")
    end_at = V.s_dt(body, "end_at")
    if end_at <= start_at:
        raise ApiError("ERR_INVALID_REQUEST", "end_at must be later than start_at.")
    if end_at - start_at > timedelta(hours=24):
        raise ApiError("ERR_INVALID_REQUEST", "A duty shift may not exceed 24 hours.")
    floor = store.get("floors", floor_id)
    if floor is None:
        raise ApiError("ERR_FLOOR_NOT_FOUND")
    row = store.insert("shifts", "DutyShift", {
        "floor_id": floor_id,
        "shift_type": shift_type,
        "start_at": store.fmt_iso(start_at),
        "end_at": store.fmt_iso(end_at),
        "assigned_ra_id": None,
        "swap_requested_ra_id": None,
        "status": "OPEN",
        "points_value": DUTY_POINTS[shift_type],
        "checked_in_at": None,
        "completed_at": None,
        "filled_by_selector": False,
    })
    return responses.obj(row, 201)


@bp.route("%s/duty-shifts/<shift_id>/assignment" % API_PREFIX, methods=["POST"])
@endpoint(DIRECTOR)
def assign_shift(shift_id):
    shift = V.must_get("DutyShift", shift_id)
    body = V.body()
    ra_id = V.s_id(body, "ra_id")
    ra = store.get("ras", ra_id)
    if ra is None:
        raise ApiError("ERR_RA_NOT_FOUND")
    if shift["status"] != "OPEN":
        raise ApiError("ERR_SHIFT_STATE_INVALID")
    _ra_gates(ra, shift)
    services.duty_conflict_gate(ra["id"], shift)
    if store.parse_iso(shift["start_at"]) <= store.now():
        raise ApiError("ERR_SHIFT_WINDOW_NOT_REACHED")
    _floor_gate(ra, shift)
    shift["status"] = "ASSIGNED"
    shift["assigned_ra_id"] = ra["id"]
    shift["filled_by_selector"] = False
    return responses.obj(shift)


@bp.route("%s/duty-shifts/<shift_id>/auto-fill" % API_PREFIX, methods=["POST"])
@endpoint(DIRECTOR)
def auto_fill(shift_id):
    shift = V.must_get("DutyShift", shift_id)
    body = V.body()
    exclude = V.s_list(body, "exclude_ra_ids", required=False, default=[])
    for item in exclude:
        if not isinstance(item, str):
            raise ApiError("ERR_INVALID_REQUEST", "exclude_ra_ids must be strings.")
    if shift["status"] != "OPEN":
        raise ApiError("ERR_SHIFT_STATE_INVALID")
    if store.parse_iso(shift["start_at"]) <= store.now():
        raise ApiError("ERR_SHIFT_WINDOW_NOT_REACHED")
    ra = services.select_auto_fill_ra(shift, set(exclude))
    shift["status"] = "ASSIGNED"
    shift["assigned_ra_id"] = ra["id"]
    shift["filled_by_selector"] = True
    return responses.obj(shift)


@bp.route("%s/duty-shifts/<shift_id>/swap" % API_PREFIX, methods=["POST"])
@endpoint(RA_OR_DIRECTOR)
def swap_shift(shift_id):
    shift = V.must_get("DutyShift", shift_id)
    body = V.body()
    raw_action = body.get("action")
    if raw_action == "REQUEST":
        require_action_role("ResidentAssistant")
        require_owner(shift.get("assigned_ra_id"))
    elif raw_action in ("APPROVE", "WITHDRAW"):
        require_action_role("ResidenceDirector")
    action = V.s_enum(body, "action", ("REQUEST", "APPROVE", "WITHDRAW"))
    if action == "REQUEST":
        replacement_id = V.s_id(body, "replacement_ra_id")
        replacement = store.get("ras", replacement_id)
        if replacement is None:
            raise ApiError("ERR_RA_NOT_FOUND")
        if shift["status"] != "ASSIGNED":
            raise ApiError("ERR_SHIFT_STATE_INVALID")
        _ra_gates(replacement, shift)
        services.duty_conflict_gate(replacement["id"], shift)
        if store.parse_iso(shift["start_at"]) <= store.now():
            raise ApiError("ERR_SHIFT_WINDOW_NOT_REACHED")
        _floor_gate(replacement, shift)
        shift["status"] = "SWAP_PENDING"
        shift["swap_requested_ra_id"] = replacement["id"]
        return responses.obj(shift)

    if shift["status"] != "SWAP_PENDING":
        raise ApiError("ERR_SHIFT_STATE_INVALID")
    if action == "APPROVE":
        replacement = store.get("ras", shift.get("swap_requested_ra_id"))
        if replacement is None:
            raise ApiError("ERR_RA_NOT_FOUND")
        _ra_gates(replacement, shift)
        services.duty_conflict_gate(replacement["id"], shift)
        _floor_gate(replacement, shift)
        shift["assigned_ra_id"] = replacement["id"]
    shift["swap_requested_ra_id"] = None
    shift["status"] = "ASSIGNED"
    return responses.obj(shift)


@bp.route("%s/duty-shifts/<shift_id>/outcome" % API_PREFIX, methods=["POST"])
@endpoint(RA_OR_DIRECTOR)
def shift_outcome(shift_id):
    shift = V.must_get("DutyShift", shift_id)
    body = V.body()
    raw_action = body.get("action")
    if raw_action in ("CHECK_IN", "COMPLETE"):
        require_action_role("ResidentAssistant")
        require_owner(shift.get("assigned_ra_id"))
    elif raw_action in ("MARK_MISSED", "VOID"):
        require_action_role("ResidenceDirector")
    action = V.s_enum(body, "action", ("CHECK_IN", "COMPLETE", "MARK_MISSED", "VOID"))
    current = store.now()
    start_at = store.parse_iso(shift["start_at"])
    end_at = store.parse_iso(shift["end_at"])

    if action == "CHECK_IN":
        if shift["status"] != "ASSIGNED":
            raise ApiError("ERR_SHIFT_STATE_INVALID")
        if not (start_at <= current < end_at):
            raise ApiError("ERR_SHIFT_WINDOW_NOT_REACHED")
        shift["status"] = "CHECKED_IN"
        shift["checked_in_at"] = store.now_iso()
    elif action == "COMPLETE":
        if shift["status"] != "CHECKED_IN":
            raise ApiError("ERR_SHIFT_STATE_INVALID")
        if current < end_at:
            raise ApiError("ERR_SHIFT_WINDOW_NOT_REACHED")
        shift["status"] = "COMPLETED"
        shift["completed_at"] = store.now_iso()
    elif action == "MARK_MISSED":
        if shift["status"] != "ASSIGNED":
            raise ApiError("ERR_SHIFT_STATE_INVALID")
        if current < end_at:
            raise ApiError("ERR_SHIFT_WINDOW_NOT_REACHED")
        shift["status"] = "MISSED"
    else:
        if shift["status"] not in ("OPEN", "COMPLETED"):
            raise ApiError("ERR_SHIFT_STATE_INVALID")
        shift["status"] = "VOID"
    return responses.obj(shift)
