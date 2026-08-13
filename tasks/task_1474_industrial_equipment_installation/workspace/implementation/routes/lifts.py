"""LiftPermit endpoints: fleet-wide crane booking, execution window, equipment charge."""
from flask import Blueprint, request

import db
from errors import (ApiError, ERR_CRANE_WINDOW_CONFLICT, ERR_INVALID_STATE,
                    ERR_INVALID_WINDOW, ERR_OUTSIDE_LIFT_WINDOW,
                    ERR_RIGGING_PLAN_NOT_APPROVED, ERR_SAFETY_HOLD,
                    ERR_VALIDATION)
from helpers import lift_or_404, project_or_404, sorted_items, touch
from middleware import ROLES, require_roles
from response import success, success_list
from serialize import lift_json
from util import D, new_id, now_iso, num, round_half_up_int
from validators import get_body, pagination, req_bool, req_datetime, req_str

bp = Blueprint("lift_permits", __name__)


def _duration_hours(starts_dt, ends_dt):
    seconds = D(str((ends_dt - starts_dt).total_seconds()))
    return num(seconds / D(3600))


@bp.post("/v1/lift-permits")
@require_roles("SiteSupervisor")
def create_lift_permit():
    body = get_body()
    # existence (priority 3)
    pid = body.get("project_id")
    project = project_or_404(pid) if isinstance(pid, str) else None
    # state gate (priority 5): project must be INSTALLING
    if project is not None and project["work_status"] != "INSTALLING":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "lift permits can only be booked while the project is INSTALLING")
    # schema (priority 7)
    req_str(body, "project_id")
    crane_ref = req_str(body, "crane_ref")
    starts_dt = req_datetime(body, "lift_starts_at")
    ends_dt = req_datetime(body, "lift_ends_at")
    road_required = req_bool(body, "road_permit_required")
    number_present = "road_permit_number" in body and body["road_permit_number"] is not None
    if road_required:
        road_permit_number = req_str(body, "road_permit_number")
    else:
        if number_present:
            raise ApiError(ERR_VALIDATION, 400,
                           "'road_permit_number': must be omitted when road_permit_required is false")
        road_permit_number = None
    # safety interlock (priority 8; PRD 3.5 includes booking under the hold block)
    if project["hold_status"] != "CLEAR":
        raise ApiError(ERR_SAFETY_HOLD, 409, "project is under SAFETY_HOLD")
    # priority 11: an approved rigging plan must be pinned
    if project["approved_rigging_plan_id"] is None:
        raise ApiError(ERR_RIGGING_PLAN_NOT_APPROVED, 409,
                       "no rigging plan currently APPROVED for the project")
    # priority 22: window well-formedness
    if not ends_dt > starts_dt:
        raise ApiError(ERR_INVALID_WINDOW, 422,
                       "lift_ends_at must be strictly after lift_starts_at")
    # priority 24: fleet-wide half-open overlap against ISSUED windows on the same crane
    for l in db.lift_permits.values():
        if l["crane_ref"] != crane_ref or l["status"] != "ISSUED":
            continue
        if starts_dt < l["_ends_dt"] and l["_starts_dt"] < ends_dt:
            raise ApiError(ERR_CRANE_WINDOW_CONFLICT, 409,
                           "lift window overlaps an existing ISSUED booking for this crane")
    ts = now_iso()
    l = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "project_id": project["id"],
        "crane_ref": crane_ref,
        "lift_starts_at": body["lift_starts_at"],
        "lift_ends_at": body["lift_ends_at"],
        "road_permit_required": road_required,
        "road_permit_number": road_permit_number,
        "duration_hours": _duration_hours(starts_dt, ends_dt),
        "equipment_charge_cents": None,
        "status": "ISSUED",
        "_starts_dt": starts_dt,
        "_ends_dt": ends_dt,
        "_seq": db.next_seq(),
    }
    db.lift_permits[l["id"]] = l
    return success(lift_json(l), 201)


@bp.get("/v1/projects/<pid>/lift-permits")
@require_roles(*ROLES)
def list_lift_permits(pid):
    project_or_404(pid)
    limit, offset = pagination()
    crane = request.args.get("crane_ref")
    status = request.args.get("status")
    items = [l for l in db.lift_permits.values() if l["project_id"] == pid]
    if crane is not None:
        items = [l for l in items if l["crane_ref"] == crane]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    items = sorted_items(items)
    total = len(items)
    return success_list([lift_json(l) for l in items[offset:offset + limit]],
                        limit, offset, total)


@bp.post("/v1/lift-permits/<lid>/execute")
@require_roles("SiteSupervisor")
def execute_lift(lid):
    l = lift_or_404(lid)
    if l["status"] != "ISSUED":
        raise ApiError(ERR_INVALID_STATE, 409, "only an ISSUED lift permit can be executed")
    project = db.projects[l["project_id"]]
    # priority 8
    if project["hold_status"] != "CLEAR":
        raise ApiError(ERR_SAFETY_HOLD, 409, "project is under SAFETY_HOLD")
    # priority 25: current logical time within [lift_starts_at, lift_ends_at)
    now = db.clock_now()
    if not (l["_starts_dt"] <= now < l["_ends_dt"]):
        raise ApiError(ERR_OUTSIDE_LIFT_WINDOW, 409,
                       "current time is outside the booked lift window")
    seconds = D(str((l["_ends_dt"] - l["_starts_dt"]).total_seconds()))
    charge = round_half_up_int(
        seconds * D(project["equipment_hourly_rate_cents"]) / D(3600))
    l["equipment_charge_cents"] = charge
    l["status"] = "EXECUTED"
    touch(l)
    # rollup re-evaluation mutates the project
    touch(project)
    return success(lift_json(l))


@bp.post("/v1/lift-permits/<lid>/cancel")
@require_roles("SiteSupervisor")
def cancel_lift(lid):
    l = lift_or_404(lid)
    if l["status"] != "ISSUED":
        raise ApiError(ERR_INVALID_STATE, 409, "only an ISSUED lift permit can be cancelled")
    l["status"] = "CANCELLED"
    touch(l)
    return success(lift_json(l))
