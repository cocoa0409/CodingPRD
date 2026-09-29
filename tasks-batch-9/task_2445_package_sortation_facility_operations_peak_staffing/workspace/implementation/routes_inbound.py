"""Trailer appointments, jam recovery, package exceptions and injury reports
(PRD §3.3, §3.8 exception queue, §3.9 safety)."""

from flask import Blueprint, request

import services as sv
from core import (
    FACILITY_ADMIN,
    INBOUND_COORDINATOR,
    LABOR_PLANNER,
    OPERATOR_ROLES,
    OPS_MANAGER,
    SORT_SUPERVISOR,
    ApiError,
    authorize,
    body_dict,
    clock_raw,
    db,
    filter_enum,
    get_appointment,
    get_center,
    get_facility,
    get_labor,
    get_outbound,
    new_entity,
    opt_id,
    opt_int,
    pagination,
    paginate,
    present,
    req_enum,
    req_id,
    req_int,
    req_str,
    respond_entity,
    respond_list,
    touch,
)

bp = Blueprint("inbound", __name__)

APPOINTMENT_STATES = ("SCHEDULED", "ARRIVED", "UNLOADING", "JAM_HELD", "UNLOADED")
PRIORITY_CLASSES = ("CRITICAL", "EXPRESS", "STANDARD", "DEFERRED")


# --------------------------------------------------------------------------
# TrailerAppointment
# --------------------------------------------------------------------------


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


@bp.post("/sortation/trailer-appointments")
def create_appointment():
    authorize([INBOUND_COORDINATOR, FACILITY_ADMIN])
    body = body_dict()
    center_id = req_id(body, "sort_center_id")
    door_id = req_id(body, "door_id")
    trailer_code = req_str(body, "trailer_code")
    window_start_raw = req_str(body, "window_start")
    window_end_raw = req_str(body, "window_end")
    priority_class = req_enum(body, "priority_class", PRIORITY_CLASSES)
    manifest = req_int(body, "manifest_package_count", min_value=0)

    center = get_center(center_id)
    door = get_facility(db.dock_doors, door_id)

    start_dt = sv.parse_window(window_start_raw, "window_start")
    end_dt = sv.parse_window(window_end_raw, "window_end")
    sv.require_ordered(start_dt, end_dt)

    if _trailer_code_taken(center["id"], trailer_code):
        raise ApiError("ERR_DUPLICATE_TRAILER_CODE")

    if door["status"] != "ACTIVE" or door["kind"] != "INBOUND":
        raise ApiError("ERR_DOOR_OUT_OF_SERVICE")

    if sv.door_window_conflict(door, start_dt, end_dt):
        raise ApiError("ERR_DOOR_WINDOW_CONFLICT")

    row = new_entity(
        "TrailerAppointment",
        {
            "sort_center_id": center["id"],
            "door_id": door["id"],
            "trailer_code": trailer_code,
            "window_start": window_start_raw,
            "window_end": window_end_raw,
            "priority_class": priority_class,
            "manifest_package_count": manifest,
            "unload_sequence_rank": None,
            "jam_count": 0,
            "status": "SCHEDULED",
            "arrived_at": None,
            "unloaded_at": None,
            "_window_start": start_dt,
            "_window_end": end_dt,
        },
    )
    db.trailer_appointments[row["id"]] = row
    return respond_entity(row, 201)


@bp.get("/sortation/trailer-appointments")
def list_appointments():
    authorize(OPERATOR_ROLES)
    limit, offset = pagination()
    status = filter_enum("status", APPOINTMENT_STATES)
    priority_class = filter_enum("priority_class", PRIORITY_CLASSES)
    center_id = request.args.get("sort_center_id") or None
    door_id = request.args.get("door_id") or None
    rows = list(db.trailer_appointments.values())
    if center_id is not None:
        rows = [r for r in rows if r["sort_center_id"] == center_id]
    if door_id is not None:
        rows = [r for r in rows if r["door_id"] == door_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if priority_class is not None:
        rows = [r for r in rows if r["priority_class"] == priority_class]
    page, total = paginate(rows, limit, offset)
    return respond_list(page, total, limit, offset)


@bp.get("/sortation/trailer-appointments/<appointment_id>")
def read_appointment(appointment_id):
    authorize(OPERATOR_ROLES)
    return respond_entity(get_appointment(appointment_id))


@bp.post("/sortation/trailer-appointments/<appointment_id>/arrive")
def arrive(appointment_id):
    authorize([INBOUND_COORDINATOR])
    appointment = get_appointment(appointment_id)
    if appointment["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_APPOINTMENT_STATE")
    center = get_center(appointment["sort_center_id"])
    sv.require_not_frozen(center)

    appointment["status"] = "ARRIVED"
    appointment["arrived_at"] = clock_raw()
    touch(appointment)
    sv.rerank_arrived(center["id"])
    return respond_entity(appointment)


@bp.post("/sortation/trailer-appointments/<appointment_id>/start-unload")
def start_unload(appointment_id):
    authorize([INBOUND_COORDINATOR])
    appointment = get_appointment(appointment_id)
    if appointment["status"] != "ARRIVED":
        raise ApiError("ERR_INVALID_APPOINTMENT_STATE")
    center = get_center(appointment["sort_center_id"])
    sv.require_not_frozen(center)
    door = db.dock_doors.get(appointment["door_id"])
    if door is None or door["status"] != "ACTIVE":
        raise ApiError("ERR_DOOR_OUT_OF_SERVICE")

    appointment["status"] = "UNLOADING"
    appointment["unload_sequence_rank"] = None
    touch(appointment)
    sv.rerank_arrived(center["id"])
    return respond_entity(appointment)


@bp.post("/sortation/trailer-appointments/<appointment_id>/jam-hold")
def jam_hold(appointment_id):
    authorize([INBOUND_COORDINATOR, SORT_SUPERVISOR])
    body = body_dict()
    chute_id = req_id(body, "chute_id")
    jam_reason = req_str(body, "jam_reason")

    appointment = get_appointment(appointment_id)
    chute = get_facility(db.sort_chutes, chute_id)

    if appointment["status"] != "UNLOADING":
        raise ApiError("ERR_INVALID_APPOINTMENT_STATE")
    if chute["sort_center_id"] != appointment["sort_center_id"]:
        raise ApiError(
            "ERR_WORKER_CENTER_MISMATCH",
            "The named chute belongs to a different sort center than the appointment.",
        )
    if appointment["jam_count"] >= sv.JAM_RETRY_LIMIT:
        raise ApiError("ERR_JAM_RETRY_LIMIT_REACHED")

    # L1
    appointment["status"] = "JAM_HELD"
    appointment["jam_count"] = appointment["jam_count"] + 1
    appointment["unload_sequence_rank"] = None
    touch(appointment)
    # L2
    chute["status"] = "CONGESTED"
    chute["jam_hold_count"] = chute["jam_hold_count"] + 1
    touch(chute)
    # L3
    affected_lanes = set()
    for assignment in sv.chute_assignments_of_chute(chute["id"]):
        if assignment["status"] != "ACTIVE":
            continue
        assignment["status"] = "SUSPENDED"
        assignment["suspended_reason"] = jam_reason
        touch(assignment)
        affected_lanes.add(assignment["destination_lane_id"])
    # L4
    for lane_id in affected_lanes:
        lane = db.destination_lanes.get(lane_id)
        if lane is None:
            continue
        lane["backlog_package_count"] = (
            lane["backlog_package_count"] + lane["forecast_hourly_volume"]
        )
        sv.recompute_lane(lane)
        touch(lane)
    # L5
    center = db.sort_centers.get(appointment["sort_center_id"])
    if center is not None:
        touch(center)
        sv.recompute_center_posture(center)
    return respond_entity(appointment)


@bp.post("/sortation/trailer-appointments/<appointment_id>/resume-unload")
def resume_unload(appointment_id):
    authorize([INBOUND_COORDINATOR, SORT_SUPERVISOR])
    body = body_dict()
    chute_id = req_id(body, "chute_id")

    appointment = get_appointment(appointment_id)
    chute = get_facility(db.sort_chutes, chute_id)

    if appointment["status"] != "JAM_HELD":
        raise ApiError("ERR_INVALID_APPOINTMENT_STATE")
    if chute["sort_center_id"] != appointment["sort_center_id"]:
        raise ApiError(
            "ERR_WORKER_CENTER_MISMATCH",
            "The named chute belongs to a different sort center than the appointment.",
        )
    if chute["status"] != "CONGESTED":
        raise ApiError(
            "ERR_INVALID_APPOINTMENT_STATE", "The named chute is not currently CONGESTED."
        )

    appointment["status"] = "UNLOADING"
    touch(appointment)
    chute["status"] = "ACTIVE"
    touch(chute)
    affected_lanes = set()
    for assignment in sv.chute_assignments_of_chute(chute["id"]):
        if assignment["status"] != "SUSPENDED":
            continue
        assignment["status"] = "ACTIVE"
        assignment["suspended_reason"] = None
        touch(assignment)
        affected_lanes.add(assignment["destination_lane_id"])
    for lane_id in affected_lanes:
        lane = db.destination_lanes.get(lane_id)
        if lane is None:
            continue
        reduced = lane["backlog_package_count"] - lane["forecast_hourly_volume"]
        lane["backlog_package_count"] = reduced if reduced > 0 else 0
        sv.recompute_lane(lane)
        touch(lane)
    center = db.sort_centers.get(appointment["sort_center_id"])
    if center is not None:
        touch(center)
        sv.recompute_center_posture(center)
    return respond_entity(appointment)


@bp.post("/sortation/trailer-appointments/<appointment_id>/complete-unload")
def complete_unload(appointment_id):
    authorize([INBOUND_COORDINATOR])
    appointment = get_appointment(appointment_id)
    if appointment["status"] != "UNLOADING":
        raise ApiError("ERR_INVALID_APPOINTMENT_STATE")
    center = get_center(appointment["sort_center_id"])
    sv.require_not_frozen(center)

    appointment["status"] = "UNLOADED"
    appointment["unloaded_at"] = clock_raw()
    appointment["unload_sequence_rank"] = None
    touch(appointment)

    manifest = appointment["manifest_package_count"]
    center["packages_inducted_count"] = center["packages_inducted_count"] + manifest
    center["wip_package_count"] = center["wip_package_count"] + manifest
    touch(center)
    sv.recompute_center_posture(center)
    return respond_entity(appointment)


# --------------------------------------------------------------------------
# PackageException
# --------------------------------------------------------------------------

EXCEPTION_TYPES = ("DAMAGED", "UNLABELED", "OVERSIZED", "MISSORT")
RESOLUTIONS = ("REROUTE", "DISPOSE", "RELABEL")


@bp.post("/sortation/package-exceptions")
def create_exception():
    authorize([SORT_SUPERVISOR, INBOUND_COORDINATOR])
    body = body_dict()
    center_id = req_id(body, "sort_center_id")
    exception_type = req_enum(body, "exception_type", EXCEPTION_TYPES)
    package_count = req_int(body, "package_count", min_value=1)
    from_lane_id = opt_id(body, "from_destination_lane_id")
    load_id = opt_id(body, "outbound_load_id")
    appointment_id = opt_id(body, "trailer_appointment_id")

    if exception_type == "MISSORT" and from_lane_id is None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'from_destination_lane_id' is required for a MISSORT exception.",
        )

    center = get_center(center_id)
    from_lane = None
    if from_lane_id is not None:
        from_lane = get_facility(db.destination_lanes, from_lane_id)
    appointment = None
    if appointment_id is not None:
        appointment = get_appointment(appointment_id)
    load = None
    if load_id is not None:
        load = get_outbound(db.outbound_loads, load_id)

    if from_lane is not None:
        if package_count > from_lane["sorted_package_count"]:
            raise ApiError("ERR_EXCEPTION_COUNT_EXCEEDS_SOURCE")
    else:
        if package_count > center["wip_package_count"]:
            raise ApiError("ERR_EXCEPTION_COUNT_EXCEEDS_SOURCE")

    plan = sv.attributed_shift_plan(center["id"])

    row = new_entity(
        "PackageException",
        {
            "sort_center_id": center["id"],
            "exception_type": exception_type,
            "package_count": package_count,
            "from_destination_lane_id": from_lane["id"] if from_lane is not None else None,
            "to_destination_lane_id": None,
            "outbound_load_id": load["id"] if load is not None else None,
            "trailer_appointment_id": appointment["id"] if appointment is not None else None,
            "shift_plan_id": plan["id"] if plan is not None else None,
            "resolved_via_chute_id": None,
            "status": "OPEN",
            "resolution": None,
            "resolved_at": None,
        },
    )
    db.package_exceptions[row["id"]] = row

    if from_lane is not None:
        from_lane["sorted_package_count"] = from_lane["sorted_package_count"] - package_count
        touch(from_lane)
    else:
        center["wip_package_count"] = center["wip_package_count"] - package_count
    center["exception_hold_count"] = center["exception_hold_count"] + package_count
    touch(center)

    if plan is not None and exception_type == "MISSORT":
        plan["missort_package_count"] = plan["missort_package_count"] + package_count
        touch(plan)

    if load is not None and load["seal_status"] == "SEALED":
        load["seal_status"] = "BROKEN"
        load["seal_code"] = None
        touch(load)

    sv.recompute_center_posture(center)
    return respond_entity(row, 201)


@bp.get("/sortation/package-exceptions")
def list_exceptions():
    authorize(
        [FACILITY_ADMIN, INBOUND_COORDINATOR, SORT_SUPERVISOR, OPS_MANAGER, LABOR_PLANNER]
    )
    limit, offset = pagination()
    exception_type = filter_enum("exception_type", EXCEPTION_TYPES)
    status = filter_enum("status", ("OPEN", "RESOLVED"))
    rows = list(db.package_exceptions.values())
    for field in (
        "sort_center_id",
        "from_destination_lane_id",
        "to_destination_lane_id",
        "outbound_load_id",
        "trailer_appointment_id",
        "shift_plan_id",
        "resolved_via_chute_id",
    ):
        value = request.args.get(field) or None
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    if exception_type is not None:
        rows = [r for r in rows if r["exception_type"] == exception_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return respond_list(page, total, limit, offset)


@bp.get("/sortation/package-exceptions/<exception_id>")
def read_exception(exception_id):
    authorize(
        [FACILITY_ADMIN, INBOUND_COORDINATOR, SORT_SUPERVISOR, OPS_MANAGER, LABOR_PLANNER]
    )
    return respond_entity(get_outbound(db.package_exceptions, exception_id))


@bp.post("/sortation/package-exceptions/<exception_id>/resolve")
def resolve_exception(exception_id):
    authorize([SORT_SUPERVISOR])
    body = body_dict()
    resolution = req_enum(body, "resolution", RESOLUTIONS)
    to_lane_id = opt_id(body, "to_destination_lane_id")
    if resolution == "REROUTE" and to_lane_id is None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'to_destination_lane_id' is required for a REROUTE resolution.",
        )

    exception = get_outbound(db.package_exceptions, exception_id)
    to_lane = None
    if to_lane_id is not None:
        to_lane = get_facility(db.destination_lanes, to_lane_id)

    if exception["status"] != "OPEN":
        raise ApiError("ERR_INVALID_EXCEPTION_STATE")
    center = get_center(exception["sort_center_id"])
    sv.require_not_frozen(center)

    chute = None
    if resolution == "REROUTE":
        if not sv.chute_assignments_of_lane(to_lane["id"]):
            raise ApiError("ERR_LANE_NOT_ASSIGNED_TO_CHUTE")
        if to_lane["status"] != "ACTIVE":
            raise ApiError("ERR_NO_ELIGIBLE_CHUTE", "The target destination lane is not ACTIVE.")
        chute = sv.reroute_chute_selection(to_lane["id"])
        if chute is None:
            raise ApiError("ERR_NO_ELIGIBLE_CHUTE")

    package_count = exception["package_count"]
    exception["status"] = "RESOLVED"
    exception["resolution"] = resolution
    exception["resolved_at"] = clock_raw()
    center["exception_hold_count"] = center["exception_hold_count"] - package_count

    if resolution == "REROUTE":
        exception["to_destination_lane_id"] = to_lane["id"]
        exception["resolved_via_chute_id"] = chute["id"]
        to_lane["sorted_package_count"] = to_lane["sorted_package_count"] + package_count
        touch(to_lane)
        center["missort_corrected_count"] = center["missort_corrected_count"] + package_count
    elif resolution == "DISPOSE":
        center["disposed_package_count"] = center["disposed_package_count"] + package_count
    else:
        center["wip_package_count"] = center["wip_package_count"] + package_count

    touch(exception)
    touch(center)
    sv.recompute_center_posture(center)
    return respond_entity(exception)


# --------------------------------------------------------------------------
# InjuryReport
# --------------------------------------------------------------------------

SEVERITIES = ("FIRST_AID", "RECORDABLE", "SERIOUS")


@bp.post("/sortation/injury-reports")
def create_injury_report():
    authorize([SORT_SUPERVISOR, OPS_MANAGER])
    body = body_dict()
    center_id = req_id(body, "sort_center_id")
    worker_id = req_id(body, "worker_id")
    severity = req_enum(body, "severity", SEVERITIES)
    body_part = req_str(body, "body_part")
    occurred_at_raw = req_str(body, "occurred_at")
    chute_id = opt_id(body, "chute_id")

    center = get_center(center_id)
    chute = None
    if chute_id is not None:
        chute = get_facility(db.sort_chutes, chute_id)
    worker = get_labor(db.workers, worker_id)

    occurred_at = sv.parse_window(occurred_at_raw, "occurred_at")

    if worker["sort_center_id"] != center["id"]:
        raise ApiError(
            "ERR_WORKER_CENTER_MISMATCH", "The worker belongs to a different sort center."
        )
    if chute is not None and chute["sort_center_id"] != center["id"]:
        raise ApiError(
            "ERR_WORKER_CENTER_MISMATCH", "The chute belongs to a different sort center."
        )

    row = new_entity(
        "InjuryReport",
        {
            "sort_center_id": center["id"],
            "worker_id": worker["id"],
            "chute_id": chute["id"] if chute is not None else None,
            "severity": severity,
            "body_part": body_part,
            "occurred_at": occurred_at_raw,
            "lost_time_days": 0,
            "status": "OPEN",
            "_occurred_at": occurred_at,
        },
    )
    db.injury_reports[row["id"]] = row

    touch(center)
    sv.recompute_center_posture(center)
    return respond_entity(row, 201)


@bp.get("/sortation/injury-reports")
def list_injury_reports():
    authorize([FACILITY_ADMIN, SORT_SUPERVISOR, OPS_MANAGER, LABOR_PLANNER])
    limit, offset = pagination()
    severity = filter_enum("severity", SEVERITIES)
    status = filter_enum("status", ("OPEN", "CLOSED"))
    rows = list(db.injury_reports.values())
    for field in ("sort_center_id", "worker_id", "chute_id"):
        value = request.args.get(field) or None
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    if severity is not None:
        rows = [r for r in rows if r["severity"] == severity]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return respond_list(page, total, limit, offset)


@bp.get("/sortation/injury-reports/<report_id>")
def read_injury_report(report_id):
    authorize([FACILITY_ADMIN, SORT_SUPERVISOR, OPS_MANAGER, LABOR_PLANNER])
    return respond_entity(get_labor(db.injury_reports, report_id))


@bp.post("/sortation/injury-reports/<report_id>/close")
def close_injury_report(report_id):
    authorize([OPS_MANAGER])
    body = body_dict()
    lost_time_days = req_int(body, "lost_time_days", min_value=0)
    report = get_labor(db.injury_reports, report_id)
    if report["status"] != "OPEN":
        raise ApiError("ERR_INVALID_EXCEPTION_STATE")

    report["status"] = "CLOSED"
    report["lost_time_days"] = lost_time_days
    touch(report)
    center = db.sort_centers.get(report["sort_center_id"])
    if center is not None:
        touch(center)
        sv.recompute_center_posture(center)
    return respond_entity(report)
