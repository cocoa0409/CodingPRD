"""RideSystem and QueueSegment endpoints."""

from flask import Blueprint

import auth
import calc
import domain
import response
import store
import validate as V
from errors import ApiError
from routes.common import body, check_project_version, check_ride_system_version, no_body, state

bp = Blueprint("rides", __name__)

RIDE_READ = (
    auth.OWNER_REP,
    auth.RIDE_ENGINEER,
    auth.CREATIVE_DIRECTOR,
    auth.CONTRACTOR_PM,
    auth.PROGRAM_ADMIN,
)
SEGMENT_READ = (auth.OWNER_REP, auth.CREATIVE_DIRECTOR, auth.CONTRACTOR_PM, auth.PROGRAM_ADMIN)

ENGINEERING_FIELDS = (
    "vehicle_count",
    "riders_per_vehicle",
    "block_zone_count",
    "cycle_time_seconds",
    "availability_pct",
    "load_efficiency_pct",
    "show_stops_per_hour",
)


# ------------------------------------------------------------------ RideSystem
@bp.post("/ride-systems")
def create_ride_system():
    auth.authenticate((auth.RIDE_ENGINEER,))
    data = body(
        V.ID("project_id"),
        V.S("vendor_name", min_len=1, max_len=120),
        V.E("system_type", V.RIDE_SYSTEM_TYPES),
        V.I("vehicle_count", minimum=1),
        V.I("riders_per_vehicle", minimum=1),
        V.I("block_zone_count", minimum=2),
        V.I("cycle_time_seconds", minimum=1),
        V.N("availability_pct", exclusive_min=0, maximum=100, max_dp=2),
        V.N("load_efficiency_pct", exclusive_min=0, maximum=100, max_dp=2),
        V.N("show_stops_per_hour", minimum=0, max_dp=2),
    )
    project = domain.get_project(data["project_id"])
    domain.check_not_frozen(project)

    row = store.base_row()
    row["project_id"] = project["id"]
    row["vendor_name"] = data["vendor_name"]
    row["system_type"] = data["system_type"]
    for field in ENGINEERING_FIELDS:
        row[field] = data[field]
    calc.apply_ride_system_capacity(row)
    row["safety_standard"] = None
    row["control_system_spec_ref"] = None
    row["status"] = "CANDIDATE"
    store.ride_systems[row["id"]] = row
    return response.created(store.public(row))


@bp.get("/ride-systems/<row_id>")
def read_ride_system(row_id):
    auth.authenticate(RIDE_READ)
    return response.ok(store.public(domain.get_ride_system(row_id)))


@bp.patch("/ride-systems/<row_id>")
def patch_ride_system(row_id):
    auth.authenticate((auth.RIDE_ENGINEER,))
    data = body(
        V.I("expected_ride_system_version"),
        V.I("vehicle_count", minimum=1, required=False),
        V.I("riders_per_vehicle", minimum=1, required=False),
        V.I("block_zone_count", minimum=2, required=False),
        V.I("cycle_time_seconds", minimum=1, required=False),
        V.N("availability_pct", exclusive_min=0, maximum=100, max_dp=2, required=False),
        V.N("load_efficiency_pct", exclusive_min=0, maximum=100, max_dp=2, required=False),
        V.N("show_stops_per_hour", minimum=0, max_dp=2, required=False),
    )
    system = domain.get_ride_system(row_id)
    check_ride_system_version(system, data["expected_ride_system_version"])
    project = domain.get_project(system["project_id"])
    domain.check_not_frozen(project)

    for field in ENGINEERING_FIELDS:
        if field in data:
            system[field] = data[field]
    calc.apply_ride_system_capacity(system)
    store.touch(system)
    return response.ok(store.public(system))


@bp.post("/ride-systems/<row_id>/select")
def select_ride_system(row_id):
    auth.authenticate((auth.OWNER_REP,))
    data = body(V.I("expected_project_version"))
    system = domain.get_ride_system(row_id)
    project = domain.get_project(system["project_id"])
    check_project_version(project, data["expected_project_version"])
    state(system, ("CANDIDATE",), "ERR_RIDE_SYSTEM_STATE_INVALID")
    domain.check_not_frozen(project)

    siblings = domain.ride_systems_of(project["id"])
    for other in siblings:
        if other["id"] != system["id"] and other["status"] in ("ENGINEERED", "COMMISSIONED"):
            raise ApiError("ERR_RIDE_SYSTEM_ALREADY_ENGINEERED", 409)
    if system["operational_hourly_capacity_guests"] < project["required_hourly_capacity_guests"]:
        raise ApiError("ERR_CAPACITY_TARGET_NOT_MET", 409)

    system["status"] = "SELECTED"
    store.touch(system)
    for other in siblings:
        if other["id"] != system["id"] and other["status"] == "SELECTED":
            other["status"] = "CANDIDATE"
            store.touch(other)
    project["selected_ride_system_id"] = system["id"]
    store.touch(project)
    return response.ok(store.public(system))


@bp.post("/ride-systems/<row_id>/mark-engineered")
def mark_engineered(row_id):
    auth.authenticate((auth.RIDE_ENGINEER,))
    data = body(
        V.E("safety_standard", V.SAFETY_STANDARDS),
        V.S("control_system_spec_ref", min_len=1, max_len=64, nullable=True),
    )
    system = domain.get_ride_system(row_id)
    state(system, ("SELECTED",), "ERR_RIDE_SYSTEM_STATE_INVALID")
    project = domain.get_project(system["project_id"])
    domain.check_not_frozen(project)
    domain.check_phase_in(project, ("SCHEMATIC", "DESIGN_DEVELOPMENT", "PRODUCTION"))

    system["safety_standard"] = data["safety_standard"]
    system["control_system_spec_ref"] = data["control_system_spec_ref"]
    system["status"] = "ENGINEERED"
    store.touch(system)
    return response.ok(store.public(system))


@bp.post("/ride-systems/<row_id>/commission")
def commission_ride_system(row_id):
    auth.authenticate((auth.RIDE_ENGINEER,))
    no_body()
    system = domain.get_ride_system(row_id)
    state(system, ("ENGINEERED",), "ERR_RIDE_SYSTEM_STATE_INVALID")
    project = domain.get_project(system["project_id"])
    domain.check_not_frozen(project)
    domain.check_phase_in(project, ("INSTALLATION",))
    if project["open_critical_finding_count"] != 0 or not domain.has_cleared_review(project, system["id"]):
        raise ApiError("ERR_SAFETY_REVIEW_NOT_CLEARED", 409)

    system["status"] = "COMMISSIONED"
    store.touch(system)
    return response.ok(store.public(system))


# ---------------------------------------------------------------- QueueSegment
@bp.post("/queue-segments")
def create_queue_segment():
    auth.authenticate((auth.CREATIVE_DIRECTOR,))
    data = body(
        V.ID("project_id"),
        V.S("segment_label", min_len=1, max_len=80),
        V.N("length_meters", exclusive_min=0, max_dp=2),
        V.N("width_meters", exclusive_min=0, max_dp=2),
        V.E("routing_type", V.ROUTING_TYPES),
        V.I("position_index", minimum=1),
    )
    project = domain.get_project(data["project_id"])
    domain.check_not_frozen(project)

    for other in domain.segments_of(project["id"]):
        if other["status"] in ("PROPOSED", "ACCEPTED") and other["position_index"] == data["position_index"]:
            raise ApiError("ERR_QUEUE_POSITION_DUPLICATE", 409)
    if data["width_meters"] < calc.min_width(data["routing_type"]):
        raise ApiError("ERR_QUEUE_WIDTH_BELOW_MINIMUM", 422)

    row = store.base_row()
    row["project_id"] = project["id"]
    row["segment_label"] = data["segment_label"]
    row["length_meters"] = data["length_meters"]
    row["width_meters"] = data["width_meters"]
    row["routing_type"] = data["routing_type"]
    row["position_index"] = data["position_index"]
    row["capacity_guests"] = calc.queue_segment_capacity(
        data["length_meters"], data["width_meters"], data["routing_type"]
    )
    row["status"] = "PROPOSED"
    store.queue_segments[row["id"]] = row
    return response.created(store.public(row))


@bp.get("/queue-segments/<row_id>")
def read_queue_segment(row_id):
    auth.authenticate(SEGMENT_READ)
    return response.ok(store.public(domain.get_queue_segment(row_id)))


@bp.post("/queue-segments/<row_id>/accept")
def accept_queue_segment(row_id):
    auth.authenticate((auth.OWNER_REP,))
    data = body(V.I("expected_project_version"))
    segment = domain.get_queue_segment(row_id)
    project = domain.get_project(segment["project_id"])
    check_project_version(project, data["expected_project_version"])
    state(segment, ("PROPOSED",), "ERR_QUEUE_SEGMENT_STATE_INVALID")
    domain.check_not_frozen(project)
    if calc.dec(project["virtual_queue_share_pct"]) > calc.MAX_VIRTUAL_QUEUE_SHARE_PCT:
        raise ApiError("ERR_VIRTUAL_QUEUE_SHARE_EXCEEDED", 422)

    segment["status"] = "ACCEPTED"
    store.touch(segment)
    domain.recompute_queue_total(project)
    store.touch(project)
    return response.ok(store.public(segment))


@bp.post("/queue-segments/<row_id>/retire")
def retire_queue_segment(row_id):
    auth.authenticate((auth.OWNER_REP,))
    data = body(V.I("expected_project_version"))
    segment = domain.get_queue_segment(row_id)
    project = domain.get_project(segment["project_id"])
    check_project_version(project, data["expected_project_version"])
    state(segment, ("ACCEPTED",), "ERR_QUEUE_SEGMENT_STATE_INVALID")
    domain.check_not_frozen(project)

    segment["status"] = "RETIRED"
    store.touch(segment)
    domain.recompute_queue_total(project)
    store.touch(project)
    return response.ok(store.public(segment))
