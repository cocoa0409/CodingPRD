"""Shared amenities, amenity allocations, hazardous-material permits and
commissioning (PRD 3.7, 3.8, 3.9)."""
from decimal import Decimal

from flask import Blueprint

import auth
import calc
import cascades
import clock
import constants
import db
import helpers
import queries
import response
import serializers
import validation
from errors import fail
from util import dec, q2

bp = Blueprint("facilities", __name__)

ZERO = Decimal("0.00")
LIVE_ALLOCATION_STATUSES = ("REQUESTED", "CONFIRMED")


# ------------------------------------------------------------- shared amenities
@bp.post("/buildings/<building_id>/shared-amenities")
def create_amenity(building_id):
    body = validation.body()
    fields = {
        "name": validation.req_str(body, "name"),
        "amenity_type": validation.req_enum(body, "amenity_type", constants.AMENITY_TYPES),
        "serving_floor_number": validation.req_int(body, "serving_floor_number", ge=1),
        "concurrent_capacity": validation.req_int(body, "concurrent_capacity", ge=1),
        "vibration_sensitive": validation.opt_bool(body, "vibration_sensitive", False),
        "utility_draw_kw": validation.opt_num(body, "utility_draw_kw", ZERO, ge=0),
    }
    auth.require(constants.ROLE_LANDLORD)
    building = helpers.fetch(db.buildings, building_id, "ERR_BUILDING_NOT_FOUND")
    if queries.floor_by_number(building["id"], fields["serving_floor_number"]) is None:
        fail("ERR_FLOOR_NOT_FOUND")
    fields["building_id"] = building["id"]
    record = db.create(db.amenities, fields)
    return response.created(serializers.amenity(record))


@bp.get("/buildings/<building_id>/shared-amenities")
def list_building_amenities(building_id):
    limit, offset = validation.pagination()
    amenity_type = validation.query_enum("amenity_type", constants.AMENITY_TYPES)
    auth.require(constants.ROLE_LANDLORD, constants.ROLE_ENGINEER, constants.ROLE_TENANT)
    building = helpers.fetch(db.buildings, building_id, "ERR_BUILDING_NOT_FOUND")
    records = helpers.filtered(queries.amenities_of(building["id"]),
                               {"amenity_type": amenity_type})
    return helpers.page(records, serializers.amenity, limit, offset)


@bp.get("/shared-amenities/<amenity_id>")
def get_amenity(amenity_id):
    auth.require(constants.ROLE_LANDLORD, constants.ROLE_ENGINEER, constants.ROLE_TENANT)
    record = helpers.fetch(db.amenities, amenity_id, "ERR_AMENITY_NOT_FOUND")
    return response.ok(serializers.amenity(record))


@bp.get("/shared-amenities")
def list_amenities():
    limit, offset = validation.pagination()
    filters = {
        "building_id": validation.query_str("building_id"),
        "amenity_type": validation.query_enum("amenity_type", constants.AMENITY_TYPES),
    }
    auth.require(constants.ROLE_LANDLORD, constants.ROLE_ENGINEER, constants.ROLE_TENANT)
    records = helpers.filtered(db.ordered(db.amenities.values()), filters)
    return helpers.page(records, serializers.amenity, limit, offset)


# ---------------------------------------------------------- amenity allocations
def _concurrency_exceeded(amenity, window_start, window_end, exclude_id=None):
    """PRD 3.7 aggregate interval-overlap count at every allocation start instant."""
    live = [a for a in queries.allocations_of_amenity(amenity["id"])
            if a["status"] in LIVE_ALLOCATION_STATUSES and a["id"] != exclude_id]
    instants = [window_start]
    for other in live:
        if window_start <= other["window_start"] < window_end:
            instants.append(other["window_start"])
    for instant in instants:
        count = 1
        for other in live:
            if other["window_start"] <= instant < other["window_end"]:
                count += 1
        if count > amenity["concurrent_capacity"]:
            return True
    return False


def _amenity_vibration_conflict(amenity, window_start, window_end):
    if not amenity["vibration_sensitive"]:
        return False
    floor = queries.floor_by_number(amenity["building_id"], amenity["serving_floor_number"])
    if floor is None:
        return False
    for phase in db.phases.values():
        if phase["work_class"] != "VIBRATION_GENERATING":
            continue
        if phase["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        project = db.projects.get(phase["project_id"])
        if project is None or project["floor_id"] != floor["id"]:
            continue
        if phase["window_start"] is None or phase["window_end"] is None:
            continue
        if phase["window_start"] < window_end and window_start < phase["window_end"]:
            return True
    return False


@bp.post("/amenity-allocations")
def create_allocation():
    body = validation.body()
    amenity_id = validation.req_id(body, "amenity_id")
    project_id = validation.req_id(body, "project_id")
    window_start = validation.req_dt(body, "window_start")
    window_end = validation.req_dt(body, "window_end")
    headcount = validation.req_int(body, "headcount", ge=1)
    user_id, role = auth.require(constants.ROLE_TENANT, constants.ROLE_LANDLORD)

    amenity = helpers.fetch(db.amenities, amenity_id, "ERR_AMENITY_NOT_FOUND")
    project = helpers.fetch(db.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    auth.guard_project(project, user_id, role)

    if window_start >= window_end:
        fail("ERR_INVALID_WINDOW")
    building = queries.building_of_project(project)
    if building is None or amenity["building_id"] != building["id"]:
        fail("ERR_AMENITY_NOT_IN_BUILDING")
    if project["construction_status"] in ("C_SUSPENDED", "C_ACCEPTED"):
        fail("ERR_INVALID_PROJECT_STATE")
    if _concurrency_exceeded(amenity, window_start, window_end):
        fail("ERR_AMENITY_CAPACITY_EXCEEDED")
    if _amenity_vibration_conflict(amenity, window_start, window_end):
        fail("ERR_VIBRATION_WINDOW_CONFLICT")

    record = db.create(db.allocations, {
        "amenity_id": amenity["id"],
        "project_id": project["id"],
        "window_start": window_start,
        "window_end": window_end,
        "headcount": headcount,
        "status": "REQUESTED",
    })
    return response.created(serializers.allocation(record))


@bp.get("/amenity-allocations/<allocation_id>")
def get_allocation(allocation_id):
    user_id, role = auth.require(constants.ROLE_LANDLORD, constants.ROLE_ENGINEER,
                                 constants.ROLE_TENANT)
    record = helpers.fetch(db.allocations, allocation_id, "ERR_ALLOCATION_NOT_FOUND")
    auth.guard_by_project_id(record["project_id"], user_id, role)
    return response.ok(serializers.allocation(record))


@bp.get("/amenity-allocations")
def list_allocations():
    limit, offset = validation.pagination()
    filters = {
        "amenity_id": validation.query_str("amenity_id"),
        "project_id": validation.query_str("project_id"),
        "status": validation.query_enum("status", constants.ALLOCATION_STATUSES),
    }
    auth.require(constants.ROLE_LANDLORD, constants.ROLE_ENGINEER, constants.ROLE_TENANT)
    records = helpers.filtered(db.ordered(db.allocations.values()), filters)
    return helpers.page(records, serializers.allocation, limit, offset)


@bp.post("/amenity-allocations/<allocation_id>/confirm")
def confirm_allocation(allocation_id):
    auth.require(constants.ROLE_LANDLORD)
    record = helpers.fetch(db.allocations, allocation_id, "ERR_ALLOCATION_NOT_FOUND")
    if record["status"] != "REQUESTED":
        fail("ERR_INVALID_ALLOCATION_STATE")
    amenity = db.amenities.get(record["amenity_id"])
    if amenity is not None and _concurrency_exceeded(
            amenity, record["window_start"], record["window_end"], exclude_id=record["id"]):
        fail("ERR_AMENITY_CAPACITY_EXCEEDED")
    record["status"] = "CONFIRMED"
    db.touch(record)
    return response.ok(serializers.allocation(record))


@bp.post("/amenity-allocations/<allocation_id>/cancel")
def cancel_allocation(allocation_id):
    user_id, role = auth.require(constants.ROLE_TENANT, constants.ROLE_LANDLORD)
    record = helpers.fetch(db.allocations, allocation_id, "ERR_ALLOCATION_NOT_FOUND")

    if record["status"] not in LIVE_ALLOCATION_STATUSES:
        fail("ERR_INVALID_ALLOCATION_STATE")
    auth.guard_by_project_id(record["project_id"], user_id, role)
    if record["status"] == "CONFIRMED" and record["window_start"] <= clock.now():
        fail("ERR_INVALID_ALLOCATION_STATE")

    record["status"] = "CANCELLED"
    db.touch(record)
    return response.ok(serializers.allocation(record))


# -------------------------------------------------------------- hazmat permits
def _permit_basis(floor_id, hazard_class, control_area_index, statuses, project_id=None):
    total = Decimal("0")
    for permit in db.permits.values():
        if permit["floor_id"] != floor_id or permit["hazard_class"] != hazard_class:
            continue
        if permit["control_area_index"] != control_area_index:
            continue
        if permit["status"] not in statuses:
            continue
        if project_id is not None and permit["project_id"] != project_id:
            continue
        total = total + dec(permit["quantity_gal"])
    return q2(total)


@bp.post("/hazmat-permits")
def create_permit():
    body = validation.body()
    project_id = validation.req_id(body, "project_id")
    floor_id = validation.req_id(body, "floor_id")
    hazard_class = validation.req_enum(body, "hazard_class", constants.HAZARD_CLASSES)
    use_condition = validation.req_enum(body, "use_condition", constants.USE_CONDITIONS)
    quantity_gal = validation.req_num(body, "quantity_gal", gt=0)
    control_area_index = validation.req_int(body, "control_area_index")
    user_id, role = auth.require(constants.ROLE_LANDLORD, constants.ROLE_TENANT)

    project = helpers.fetch(db.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    floor = helpers.fetch(db.floors, floor_id, "ERR_FLOOR_NOT_FOUND")
    auth.guard_project(project, user_id, role)

    if control_area_index < 1 or control_area_index > calc.control_areas_allowed(floor):
        fail("ERR_CONTROL_AREA_OUT_OF_RANGE")
    if floor["id"] != project["floor_id"]:
        fail("ERR_FLOOR_NOT_IN_PREMISES")

    allowance = calc.allowance_per_control_area_gal(floor, hazard_class, use_condition)
    basis = _permit_basis(floor["id"], hazard_class, control_area_index,
                          constants.PER_CONTROL_AREA_STATUSES, project_id=project["id"])
    if q2(basis + quantity_gal) > allowance:
        fail("ERR_CONTROL_AREA_MAQ_EXCEEDED")

    record = db.create(db.permits, {
        "project_id": project["id"],
        "floor_id": floor["id"],
        "hazard_class": hazard_class,
        "use_condition": use_condition,
        "quantity_gal": quantity_gal,
        "control_area_index": control_area_index,
        "allowance_per_control_area_gal": allowance,
        "status": "REQUESTED",
        "decision_reason": None,
    })
    return response.created(serializers.permit(record))


@bp.get("/hazmat-permits/<permit_id>")
def get_permit(permit_id):
    user_id, role = auth.require(constants.ROLE_LANDLORD, constants.ROLE_ENGINEER,
                                 constants.ROLE_TENANT, constants.ROLE_AHJ)
    record = helpers.fetch(db.permits, permit_id, "ERR_PERMIT_NOT_FOUND")
    auth.guard_by_project_id(record["project_id"], user_id, role)
    return response.ok(serializers.permit(record))


@bp.get("/hazmat-permits")
def list_permits():
    limit, offset = validation.pagination()
    filters = {
        "project_id": validation.query_str("project_id"),
        "floor_id": validation.query_str("floor_id"),
        "hazard_class": validation.query_enum("hazard_class", constants.HAZARD_CLASSES),
        "control_area_index": validation.query_int("control_area_index"),
        "status": validation.query_enum("status", constants.HAZMAT_PERMIT_STATUSES),
    }
    auth.require(constants.ROLE_LANDLORD, constants.ROLE_ENGINEER, constants.ROLE_TENANT,
                 constants.ROLE_AHJ)
    records = helpers.filtered(db.ordered(db.permits.values()), filters)
    return helpers.page(records, serializers.permit, limit, offset)


@bp.post("/hazmat-permits/<permit_id>/decision")
def decide_hazmat_permit(permit_id):
    body = validation.body()
    decision = validation.req_enum(body, "decision", ["APPROVE", "DENY", "REVOKE"])
    decision_reason = validation.raw_opt_str(body, "decision_reason")
    auth.require(constants.ROLE_AHJ)
    record = helpers.fetch(db.permits, permit_id, "ERR_PERMIT_NOT_FOUND")

    if decision in ("APPROVE", "DENY"):
        if record["status"] != "REQUESTED":
            fail("ERR_INVALID_PERMIT_DECISION")
    elif record["status"] not in ("APPROVED", "ACTIVE"):
        fail("ERR_INVALID_PERMIT_DECISION")

    if decision == "APPROVE":
        project = db.projects.get(record["project_id"])
        if project is None or project["permit_status"] != "P_ISSUED":
            fail("ERR_PROJECT_NOT_PERMITTED")
        basis = _permit_basis(record["floor_id"], record["hazard_class"],
                              record["control_area_index"],
                              constants.AGGREGATE_FLOOR_STATUSES)
        if q2(basis + dec(record["quantity_gal"])) > dec(record["allowance_per_control_area_gal"]):
            fail("ERR_CONTROL_AREA_MAQ_EXCEEDED")

    if decision in ("DENY", "REVOKE") and helpers.blank(decision_reason):
        fail("ERR_DECISION_REASON_REQUIRED")

    if decision == "APPROVE":
        record["status"] = "APPROVED"
    elif decision == "DENY":
        record["status"] = "DENIED"
        record["decision_reason"] = decision_reason
    else:
        record["status"] = "REVOKED"
        record["decision_reason"] = decision_reason
    db.touch(record)
    return response.ok(serializers.permit(record))


# --------------------------------------------------------------- commissioning
@bp.post("/fit-out-projects/<project_id>/commissioning-records")
def create_commissioning_record(project_id):
    body = validation.body()
    script_type = validation.req_enum(body, "script_type", constants.SCRIPT_TYPES)
    scheduled_for = validation.req_dt(body, "scheduled_for")
    executed_by_user_id = validation.req_str(body, "executed_by_user_id")
    auth.require(constants.ROLE_CX)
    project = helpers.fetch(db.projects, project_id, "ERR_PROJECT_NOT_FOUND")

    if script_type not in project["required_commissioning_scripts"]:
        fail("ERR_SCRIPT_NOT_REQUIRED")
    for existing in queries.records_of_project(project["id"]):
        if existing["script_type"] == script_type and existing["status"] in ("SCHEDULED", "PASSED"):
            fail("ERR_DUPLICATE_COMMISSIONING_SCRIPT")

    record = db.create(db.records, {
        "project_id": project["id"],
        "script_type": script_type,
        "scheduled_for": scheduled_for,
        "executed_by_user_id": executed_by_user_id,
        "witnessed_by_user_id": None,
        "measured_value": None,
        "result": None,
        "status": "SCHEDULED",
    })
    return response.created(serializers.commissioning_record(record))


@bp.get("/fit-out-projects/<project_id>/commissioning-records")
def list_project_commissioning_records(project_id):
    limit, offset = validation.pagination()
    status = validation.query_enum("status", constants.COMMISSIONING_STATUSES)
    user_id, role = auth.require(constants.ROLE_LANDLORD, constants.ROLE_TENANT,
                                 constants.ROLE_CX, constants.ROLE_AHJ)
    project = helpers.fetch(db.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    auth.guard_project(project, user_id, role)
    records = helpers.filtered(queries.records_of_project(project["id"]), {"status": status})
    return helpers.page(records, serializers.commissioning_record, limit, offset)


@bp.get("/commissioning-records/<record_id>")
def get_commissioning_record(record_id):
    user_id, role = auth.require(constants.ROLE_LANDLORD, constants.ROLE_TENANT,
                                 constants.ROLE_CX, constants.ROLE_AHJ)
    record = helpers.fetch(db.records, record_id, "ERR_COMMISSIONING_RECORD_NOT_FOUND")
    auth.guard_by_project_id(record["project_id"], user_id, role)
    return response.ok(serializers.commissioning_record(record))


@bp.get("/commissioning-records")
def list_commissioning_records():
    limit, offset = validation.pagination()
    filters = {
        "project_id": validation.query_str("project_id"),
        "script_type": validation.query_enum("script_type", constants.SCRIPT_TYPES),
        "result": validation.query_enum("result", constants.RESULTS),
        "status": validation.query_enum("status", constants.COMMISSIONING_STATUSES),
    }
    auth.require(constants.ROLE_LANDLORD, constants.ROLE_TENANT, constants.ROLE_CX,
                 constants.ROLE_AHJ)
    records = helpers.filtered(db.ordered(db.records.values()), filters)
    return helpers.page(records, serializers.commissioning_record, limit, offset)


@bp.post("/commissioning-records/<record_id>/result")
def record_commissioning_result(record_id):
    body = validation.body()
    result = validation.req_enum(body, "result", constants.RESULTS)
    witnessed_by_user_id = validation.req_str(body, "witnessed_by_user_id")
    measured_value = validation.opt_num(body, "measured_value")
    auth.require(constants.ROLE_CX)
    record = helpers.fetch(db.records, record_id, "ERR_COMMISSIONING_RECORD_NOT_FOUND")
    project = db.projects.get(record["project_id"])

    if record["status"] != "SCHEDULED":
        fail("ERR_INVALID_COMMISSIONING_STATE")
    if project is None or project["construction_status"] != "C_SUBSTANTIAL_COMPLETION":
        fail("ERR_COMMISSIONING_INCOMPLETE")
    if witnessed_by_user_id == record["executed_by_user_id"]:
        fail("ERR_WITNESS_CONFLICT")

    record["result"] = result
    record["witnessed_by_user_id"] = witnessed_by_user_id
    record["measured_value"] = measured_value
    record["status"] = "PASSED" if result == "PASS" else "FAILED"
    db.touch(record)

    if result == "PASS":
        required = len(project["required_commissioning_scripts"])
        if required > 0 and calc.passed_script_count(project) >= required:
            cascades.accept_project(project)
    else:
        lease = queries.lease_of_project(project)
        if lease is not None:
            cascades.reverse_last_draw(lease)
    return response.ok(serializers.commissioning_record(record))
