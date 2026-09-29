"""Outbound loads: staging, scanning by size class, closing, sealing, dispatch
(PRD §3.8, state machines 7 and 8)."""

from flask import Blueprint, request

import services as sv
from core import (
    OPERATOR_ROLES,
    OPS_MANAGER,
    SORT_SUPERVISOR,
    ApiError,
    authorize,
    body_dict,
    clock_dt,
    clock_raw,
    db,
    filter_enum,
    get_center,
    get_facility,
    get_outbound,
    new_entity,
    opt_int,
    pagination,
    paginate,
    q,
    req_id,
    req_num,
    req_str,
    respond_entity,
    respond_list,
    touch,
)

bp = Blueprint("outbound", __name__)

LOAD_STATES = ("STAGING", "LOADING", "LOADED", "DISPATCHED")
SEAL_STATES = ("UNSEALED", "SEALED", "BROKEN")


def _trailer_code_taken(center_id, trailer_code):
    for appointment in db.trailer_appointments.values():
        if (
            appointment["sort_center_id"] == center_id
            and appointment["trailer_code"] == trailer_code
            and appointment["status"] != "UNLOADED"
        ):
            return True
    for load in db.outbound_loads.values():
        if (
            load["sort_center_id"] == center_id
            and load["trailer_code"] == trailer_code
            and load["load_status"] != "DISPATCHED"
        ):
            return True
    return False


@bp.post("/sortation/outbound-loads")
def create_load():
    authorize([SORT_SUPERVISOR])
    body = body_dict()
    center_id = req_id(body, "sort_center_id")
    door_id = req_id(body, "door_id")
    lane_id = req_id(body, "destination_lane_id")
    trailer_code = req_str(body, "trailer_code")
    trailer_cube = req_num(
        body, "trailer_cube_cuft", min_value=0, exclusive_min=True, places=2
    )
    cut_raw = req_str(body, "dispatch_cut_time")

    center = get_center(center_id)
    door = get_facility(db.dock_doors, door_id)
    lane = get_facility(db.destination_lanes, lane_id)

    cut_dt = sv.parse_window(cut_raw, "dispatch_cut_time")

    if _trailer_code_taken(center["id"], trailer_code):
        raise ApiError("ERR_DUPLICATE_TRAILER_CODE")

    if door["status"] != "ACTIVE" or door["kind"] != "OUTBOUND":
        raise ApiError("ERR_DOOR_OUT_OF_SERVICE")

    if not sv.chute_assignments_of_lane(lane["id"]):
        raise ApiError("ERR_LANE_NOT_ASSIGNED_TO_CHUTE")

    if door["sort_center_id"] != center["id"]:
        raise ApiError(
            "ERR_WORKER_CENTER_MISMATCH", "The dock door belongs to a different sort center."
        )
    if lane["sort_center_id"] != center["id"]:
        raise ApiError(
            "ERR_WORKER_CENTER_MISMATCH",
            "The destination lane belongs to a different sort center.",
        )

    row = new_entity(
        "OutboundLoad",
        {
            "sort_center_id": center["id"],
            "door_id": door["id"],
            "destination_lane_id": lane["id"],
            "trailer_code": trailer_code,
            "trailer_cube_cuft": trailer_cube,
            "cube_used_cuft": q(0, 2),
            "cube_utilization_pct": q(0, 2),
            "package_count": 0,
            "dispatch_cut_time": cut_raw,
            "load_status": "STAGING",
            "seal_status": "UNSEALED",
            "seal_code": None,
            "dispatched_at": None,
            "_dispatch_cut_time": cut_dt,
        },
    )
    db.outbound_loads[row["id"]] = row
    return respond_entity(row, 201)


@bp.get("/sortation/outbound-loads")
def list_loads():
    authorize(OPERATOR_ROLES)
    limit, offset = pagination()
    load_status = filter_enum("load_status", LOAD_STATES)
    seal_status = filter_enum("seal_status", SEAL_STATES)
    rows = list(db.outbound_loads.values())
    for field in ("sort_center_id", "door_id", "destination_lane_id"):
        value = request.args.get(field) or None
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    if load_status is not None:
        rows = [r for r in rows if r["load_status"] == load_status]
    if seal_status is not None:
        rows = [r for r in rows if r["seal_status"] == seal_status]
    page, total = paginate(rows, limit, offset)
    return respond_list(page, total, limit, offset)


@bp.get("/sortation/outbound-loads/<load_id>")
def read_load(load_id):
    authorize(OPERATOR_ROLES)
    return respond_entity(get_outbound(db.outbound_loads, load_id))


@bp.post("/sortation/outbound-loads/<load_id>/scan-packages")
def scan_packages(load_id):
    authorize([SORT_SUPERVISOR])
    body = body_dict()
    counts = {
        "SMALL": opt_int(body, "small_count", default=0, min_value=0),
        "MEDIUM": opt_int(body, "medium_count", default=0, min_value=0),
        "LARGE": opt_int(body, "large_count", default=0, min_value=0),
        "OVERSIZED": opt_int(body, "oversized_count", default=0, min_value=0),
    }
    load = get_outbound(db.outbound_loads, load_id)

    if load["load_status"] not in ("STAGING", "LOADING"):
        raise ApiError("ERR_INVALID_LOAD_STATE")

    center = get_center(load["sort_center_id"])
    sv.require_not_frozen(center)

    new_cube = sv.calc_cube(load, counts)
    if new_cube > load["trailer_cube_cuft"]:
        raise ApiError("ERR_TRAILER_CUBE_EXCEEDED")

    scanned = counts["SMALL"] + counts["MEDIUM"] + counts["LARGE"] + counts["OVERSIZED"]

    load["cube_used_cuft"] = new_cube
    load["cube_utilization_pct"] = sv.cube_utilization(new_cube, load["trailer_cube_cuft"])
    load["package_count"] = load["package_count"] + scanned
    load["load_status"] = "LOADING"
    touch(load)

    center["wip_package_count"] = center["wip_package_count"] - scanned
    touch(center)

    lane = db.destination_lanes.get(load["destination_lane_id"])
    if lane is not None:
        lane["sorted_package_count"] = lane["sorted_package_count"] + scanned
        sv.recompute_lane(lane)
        touch(lane)

    plan = sv.attributed_shift_plan(center["id"])
    if plan is not None:
        plan["sorted_package_count"] = plan["sorted_package_count"] + scanned
        touch(plan)

    sv.recompute_center_posture(center)
    return respond_entity(load)


@bp.post("/sortation/outbound-loads/<load_id>/close-load")
def close_load(load_id):
    authorize([SORT_SUPERVISOR])
    load = get_outbound(db.outbound_loads, load_id)
    if load["load_status"] != "LOADING":
        raise ApiError("ERR_INVALID_LOAD_STATE")
    load["load_status"] = "LOADED"
    load["cube_utilization_pct"] = sv.cube_utilization(
        load["cube_used_cuft"], load["trailer_cube_cuft"]
    )
    touch(load)
    return respond_entity(load)


@bp.post("/sortation/outbound-loads/<load_id>/seal")
def seal_load(load_id):
    authorize([SORT_SUPERVISOR])
    body = body_dict()
    seal_code = req_str(body, "seal_code")
    load = get_outbound(db.outbound_loads, load_id)
    if load["load_status"] not in ("LOADING", "LOADED"):
        raise ApiError("ERR_INVALID_LOAD_STATE")
    if load["seal_status"] not in ("UNSEALED", "BROKEN"):
        raise ApiError("ERR_INVALID_LOAD_STATE")
    load["seal_status"] = "SEALED"
    load["seal_code"] = seal_code
    touch(load)
    return respond_entity(load)


@bp.post("/sortation/outbound-loads/<load_id>/dispatch")
def dispatch_load(load_id):
    authorize([OPS_MANAGER])
    load = get_outbound(db.outbound_loads, load_id)
    if load["load_status"] != "LOADED":
        raise ApiError("ERR_INVALID_LOAD_STATE")
    center = get_center(load["sort_center_id"])
    sv.require_not_frozen(center)
    if load["seal_status"] != "SEALED":
        raise ApiError("ERR_LOAD_NOT_SEALED")
    if not clock_dt() < load["_dispatch_cut_time"]:
        raise ApiError("ERR_DISPATCH_CUT_PASSED")

    load["load_status"] = "DISPATCHED"
    load["dispatched_at"] = clock_raw()
    touch(load)
    return respond_entity(load)
