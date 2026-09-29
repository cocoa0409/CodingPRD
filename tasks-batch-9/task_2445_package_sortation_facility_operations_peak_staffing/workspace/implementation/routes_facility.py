"""Logical clock, sort centers, dock doors, sort chutes, destination lanes and
chute assignments (PRD §3.1, §3.2)."""

from flask import Blueprint

import services as sv
from core import (
    ALL_ROLES,
    FACILITY_ADMIN,
    OPERATOR_ROLES,
    SORT_SUPERVISOR,
    ApiError,
    authorize,
    body_dict,
    db,
    filter_enum,
    get_center,
    get_facility,
    new_entity,
    opt_int,
    opt_num,
    pagination,
    paginate,
    parse_dt,
    present,
    q,
    req_bool,
    req_enum,
    req_id,
    req_int,
    req_num,
    req_str,
    respond_entity,
    respond_list,
    respond_object,
    touch,
)

bp = Blueprint("facility", __name__)


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------


@bp.post("/_clock/set_current_utc")
def set_clock():
    authorize(OPERATOR_ROLES)
    body = body_dict()
    raw = req_str(body, "current_utc")
    parsed = parse_dt(raw)
    if parsed is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'current_utc' must be an RFC 3339 instant.")
    db.clock_dt = parsed
    db.clock_raw = raw
    return respond_object({"current_utc": raw})


# --------------------------------------------------------------------------
# SortCenter
# --------------------------------------------------------------------------


@bp.post("/sortation/sort-centers")
def create_center():
    authorize([FACILITY_ADMIN])
    body = body_dict()
    code = req_str(body, "code", min_len=3, max_len=10)
    name = req_str(body, "name")
    automation = opt_num(
        body, "automation_utilization_pct", default=q(0, 2), min_value=0, max_value=100, places=2
    )
    flex_total = opt_int(body, "flex_pool_total", default=0, min_value=0)

    for existing in db.sort_centers.values():
        if existing["code"] == code:
            raise ApiError("ERR_DUPLICATE_FACILITY_RESOURCE", "Sort center code is already in use.")

    row = new_entity(
        "SortCenter",
        {
            "code": code,
            "name": name,
            "automation_utilization_pct": automation,
            "flex_pool_total": flex_total,
            "flex_pool_available": flex_total,
            "flex_pool_reserved": 0,
            "ops_posture": "OPEN",
            "open_jam_count": 0,
            "open_serious_injury_count": 0,
            "packages_inducted_count": 0,
            "wip_package_count": 0,
            "exception_hold_count": 0,
            "disposed_package_count": 0,
            "missort_corrected_count": 0,
            "last_posture_change_at": None,
        },
    )
    posture, _jams, _injuries = sv.derive_posture(row)
    row["ops_posture"] = posture
    db.sort_centers[row["id"]] = row
    return respond_entity(row, 201)


@bp.get("/sortation/sort-centers")
def list_centers():
    authorize(ALL_ROLES)
    limit, offset = pagination()
    code = None
    from flask import request

    if request.args.get("code"):
        code = request.args.get("code")
    posture = filter_enum("ops_posture", ("OPEN", "RESTRICTED", "FROZEN"))
    rows = list(db.sort_centers.values())
    if code is not None:
        rows = [r for r in rows if r["code"] == code]
    if posture is not None:
        rows = [r for r in rows if r["ops_posture"] == posture]
    page, total = paginate(rows, limit, offset)
    return respond_list(page, total, limit, offset)


@bp.get("/sortation/sort-centers/<center_id>")
def read_center(center_id):
    authorize(ALL_ROLES)
    return respond_entity(get_center(center_id))


@bp.patch("/sortation/sort-centers/<center_id>")
def update_center(center_id):
    authorize([FACILITY_ADMIN])
    body = body_dict()
    automation = req_num(
        body, "automation_utilization_pct", min_value=0, max_value=100, places=2
    )
    center = get_center(center_id)
    center["automation_utilization_pct"] = automation
    touch(center)
    sv.recompute_center_posture(center)
    return respond_entity(center)


# --------------------------------------------------------------------------
# DockDoor
# --------------------------------------------------------------------------


@bp.post("/sortation/sort-centers/<center_id>/dock-doors")
def create_door(center_id):
    authorize([FACILITY_ADMIN])
    body = body_dict()
    door_number = req_int(body, "door_number", min_value=1)
    kind = req_enum(body, "kind", ("INBOUND", "OUTBOUND"))
    buffer_min = opt_int(body, "turnaround_buffer_min", default=15, min_value=0)
    center = get_center(center_id)
    for existing in sv.doors_of(center["id"]):
        if existing["door_number"] == door_number:
            raise ApiError(
                "ERR_DUPLICATE_FACILITY_RESOURCE", "Door number is already in use at this center."
            )
    row = new_entity(
        "DockDoor",
        {
            "sort_center_id": center["id"],
            "door_number": door_number,
            "kind": kind,
            "status": "ACTIVE",
            "turnaround_buffer_min": buffer_min,
        },
    )
    db.dock_doors[row["id"]] = row
    return respond_entity(row, 201)


@bp.get("/sortation/sort-centers/<center_id>/dock-doors")
def list_doors(center_id):
    authorize(OPERATOR_ROLES)
    limit, offset = pagination()
    kind = filter_enum("kind", ("INBOUND", "OUTBOUND"))
    status = filter_enum("status", ("ACTIVE", "OUT_OF_SERVICE"))
    center = get_center(center_id)
    rows = sv.doors_of(center["id"])
    if kind is not None:
        rows = [r for r in rows if r["kind"] == kind]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return respond_list(page, total, limit, offset)


@bp.get("/sortation/dock-doors/<door_id>")
def read_door(door_id):
    authorize(OPERATOR_ROLES)
    return respond_entity(get_facility(db.dock_doors, door_id))


@bp.patch("/sortation/dock-doors/<door_id>")
def update_door(door_id):
    authorize([FACILITY_ADMIN])
    body = body_dict()
    status = None
    if present(body, "status"):
        status = req_enum(body, "status", ("ACTIVE", "OUT_OF_SERVICE"))
    buffer_min = opt_int(body, "turnaround_buffer_min", default=None, min_value=0)
    door = get_facility(db.dock_doors, door_id)
    if status is not None:
        door["status"] = status
    if buffer_min is not None:
        door["turnaround_buffer_min"] = buffer_min
    touch(door)
    return respond_entity(door)


# --------------------------------------------------------------------------
# SortChute
# --------------------------------------------------------------------------


@bp.post("/sortation/sort-centers/<center_id>/sort-chutes")
def create_chute(center_id):
    authorize([FACILITY_ADMIN])
    body = body_dict()
    chute_number = req_int(body, "chute_number", min_value=1)
    throughput = req_int(body, "throughput_pph", min_value=1)
    max_concurrent = opt_int(body, "max_concurrent_destinations", default=2, min_value=1)
    center = get_center(center_id)
    for existing in sv.chutes_of(center["id"]):
        if existing["chute_number"] == chute_number:
            raise ApiError(
                "ERR_DUPLICATE_FACILITY_RESOURCE", "Chute number is already in use at this center."
            )
    row = new_entity(
        "SortChute",
        {
            "sort_center_id": center["id"],
            "chute_number": chute_number,
            "throughput_pph": throughput,
            "max_concurrent_destinations": max_concurrent,
            "status": "ACTIVE",
            "jam_hold_count": 0,
        },
    )
    db.sort_chutes[row["id"]] = row
    return respond_entity(row, 201)


@bp.get("/sortation/sort-centers/<center_id>/sort-chutes")
def list_chutes(center_id):
    authorize(OPERATOR_ROLES)
    limit, offset = pagination()
    status = filter_enum("status", ("ACTIVE", "CONGESTED"))
    center = get_center(center_id)
    rows = sv.chutes_of(center["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return respond_list(page, total, limit, offset)


@bp.get("/sortation/sort-chutes/<chute_id>")
def read_chute(chute_id):
    authorize(OPERATOR_ROLES)
    return respond_entity(get_facility(db.sort_chutes, chute_id))


# --------------------------------------------------------------------------
# DestinationLane
# --------------------------------------------------------------------------


@bp.post("/sortation/sort-centers/<center_id>/destination-lanes")
def create_lane(center_id):
    authorize([FACILITY_ADMIN])
    body = body_dict()
    lane_code = req_str(body, "lane_code")
    region = req_str(body, "region")
    service_class = req_enum(body, "service_class", ("GROUND", "EXPRESS", "FREIGHT"))
    forecast = req_int(body, "forecast_hourly_volume", min_value=0)
    center = get_center(center_id)
    for existing in sv.lanes_of(center["id"]):
        if existing["lane_code"] == lane_code:
            raise ApiError(
                "ERR_DUPLICATE_FACILITY_RESOURCE", "Lane code is already in use at this center."
            )
    row = new_entity(
        "DestinationLane",
        {
            "sort_center_id": center["id"],
            "lane_code": lane_code,
            "region": region,
            "service_class": service_class,
            "forecast_hourly_volume": forecast,
            "sorted_package_count": 0,
            "backlog_package_count": 0,
            "assigned_capacity_pph": 0,
            "lane_pressure_ratio": q(0, 4),
            "status": "ACTIVE",
        },
    )
    db.destination_lanes[row["id"]] = row
    return respond_entity(row, 201)


@bp.get("/sortation/sort-centers/<center_id>/destination-lanes")
def list_lanes(center_id):
    authorize(OPERATOR_ROLES)
    limit, offset = pagination()
    status = filter_enum("status", ("ACTIVE", "CLOSED"))
    service_class = filter_enum("service_class", ("GROUND", "EXPRESS", "FREIGHT"))
    center = get_center(center_id)
    rows = sv.lanes_of(center["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if service_class is not None:
        rows = [r for r in rows if r["service_class"] == service_class]
    page, total = paginate(rows, limit, offset)
    return respond_list(page, total, limit, offset)


@bp.get("/sortation/destination-lanes/<lane_id>")
def read_lane(lane_id):
    authorize(OPERATOR_ROLES)
    return respond_entity(get_facility(db.destination_lanes, lane_id))


@bp.patch("/sortation/destination-lanes/<lane_id>")
def update_lane(lane_id):
    authorize([FACILITY_ADMIN])
    body = body_dict()
    status = None
    if present(body, "status"):
        status = req_enum(body, "status", ("ACTIVE", "CLOSED"))
    forecast = opt_int(body, "forecast_hourly_volume", default=None, min_value=0)
    lane = get_facility(db.destination_lanes, lane_id)
    if status is not None:
        lane["status"] = status
    if forecast is not None:
        lane["forecast_hourly_volume"] = forecast
    sv.recompute_lane(lane)
    touch(lane)
    center = db.sort_centers.get(lane["sort_center_id"])
    if center is not None:
        sv.recompute_center_posture(center)
    return respond_entity(lane)


# --------------------------------------------------------------------------
# ChuteAssignment
# --------------------------------------------------------------------------


@bp.post("/sortation/chute-assignments")
def create_chute_assignment():
    authorize([SORT_SUPERVISOR, FACILITY_ADMIN])
    body = body_dict()
    chute_id = req_id(body, "chute_id")
    lane_id = req_id(body, "destination_lane_id")
    window_start_raw = req_str(body, "window_start")
    window_end_raw = req_str(body, "window_end")
    expected_version = req_int(body, "expected_chute_version")
    supersede = req_bool(body, "supersede", default=False)

    chute = get_facility(db.sort_chutes, chute_id)
    lane = get_facility(db.destination_lanes, lane_id)

    start_dt = sv.parse_window(window_start_raw, "window_start")
    end_dt = sv.parse_window(window_end_raw, "window_end")
    sv.require_ordered(start_dt, end_dt)

    if expected_version != chute["version"]:
        raise ApiError("ERR_STALE_CHUTE_VERSION")

    prior = None
    if supersede:
        candidates = [
            a
            for a in sv.chute_assignments_of_chute(chute["id"])
            if a["status"] == "ACTIVE" and a["destination_lane_id"] == lane["id"]
        ]
        if candidates:
            candidates.sort(key=lambda a: a["_seq"])
            prior = candidates[-1]

    excluded = {prior["id"]} if prior is not None else set()
    if sv.chute_concurrency_exceeded(chute, start_dt, end_dt, excluded):
        raise ApiError("ERR_CHUTE_CONCURRENCY_EXCEEDED")

    if chute["sort_center_id"] != lane["sort_center_id"]:
        raise ApiError(
            "ERR_WORKER_CENTER_MISMATCH",
            "The chute and the destination lane belong to different sort centers.",
        )

    row = new_entity(
        "ChuteAssignment",
        {
            "chute_id": chute["id"],
            "destination_lane_id": lane["id"],
            "window_start": window_start_raw,
            "window_end": window_end_raw,
            "status": "ACTIVE",
            "suspended_reason": None,
            "effective_window_end": None,
            "_window_start": start_dt,
            "_window_end": end_dt,
        },
    )
    db.chute_assignments[row["id"]] = row

    affected_lanes = {lane["id"]}
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        prior["effective_window_end"] = window_start_raw
        touch(prior)
        affected_lanes.add(prior["destination_lane_id"])

    touch(chute)
    for affected in affected_lanes:
        target = db.destination_lanes.get(affected)
        if target is not None:
            sv.recompute_lane_and_touch(target)

    center = db.sort_centers.get(chute["sort_center_id"])
    if center is not None:
        touch(center)
        sv.recompute_center_posture(center)
    return respond_entity(row, 201)


@bp.get("/sortation/chute-assignments")
def list_chute_assignments():
    authorize(OPERATOR_ROLES)
    limit, offset = pagination()
    from flask import request

    status = filter_enum("status", ("ACTIVE", "SUSPENDED", "SUPERSEDED", "ENDED"))
    chute_id = request.args.get("chute_id") or None
    lane_id = request.args.get("destination_lane_id") or None
    if chute_id is not None:
        get_facility(db.sort_chutes, chute_id)
    if lane_id is not None:
        get_facility(db.destination_lanes, lane_id)
    rows = list(db.chute_assignments.values())
    if chute_id is not None:
        rows = [r for r in rows if r["chute_id"] == chute_id]
    if lane_id is not None:
        rows = [r for r in rows if r["destination_lane_id"] == lane_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return respond_list(page, total, limit, offset)


@bp.get("/sortation/chute-assignments/<assignment_id>")
def read_chute_assignment(assignment_id):
    authorize(OPERATOR_ROLES)
    return respond_entity(get_facility(db.chute_assignments, assignment_id))
