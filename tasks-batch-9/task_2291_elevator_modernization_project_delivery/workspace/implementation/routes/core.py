"""Jurisdictions, projects, hoistway groups, cars and the logical clock."""

from flask import Blueprint

import calc
import serialize
from db import db, fmt_dt, new_row, ordered, touch
from errors import ApiError
from middleware import (
    endpoint,
    project_of_car,
    project_of_group,
    touch_project,
)
from routes.common import (
    ALL_ROLES,
    eq_filter,
    enum_query,
    fetch,
    int_query,
    object_response,
    paged,
    read_one,
    require,
    str_query,
)
from validation import precheck_fks, validate

bp = Blueprint("core", __name__)

OCCUPANCY_TYPES = ["OCCUPIED", "VACANT"]
PROJECT_STATUSES = ["SURVEY", "SCOPING", "EXECUTION", "CLOSEOUT", "COMPLETED"]
CONTROLLER_TYPES = ["RELAY", "SOLID_STATE_ANALOG", "MICROPROCESSOR"]
MACHINE_TYPES = ["GEARED", "GEARLESS", "MRL_GEARLESS"]
WORK_STATUSES = [
    "SURVEY_PENDING",
    "SURVEYED",
    "SCOPED",
    "PROCURING",
    "OUTAGE_ACTIVE",
    "TESTING",
    "ACCEPTED",
    "IN_WARRANTY",
    "UNDER_CONTRACT",
]
COMPLIANCE_STATUSES = ["NOT_EVALUATED", "TRIGGERS_OPEN", "TRIGGERS_CLEARED", "CODE_ACCEPTED"]


# --- Jurisdiction ----------------------------------------------------------

@bp.post("/jurisdictions")
@endpoint(["SystemOperator"])
def create_jurisdiction():
    data = validate(
        [
            {"name": "name", "type": "string", "required": True},
            {"name": "code_edition_year", "type": "int", "required": True, "min": 2000, "max": 2030},
            {"name": "fire_service_required", "type": "bool", "required": True},
            {"name": "seismic_zone", "type": "int", "required": True, "min": 0, "max": 4},
            {"name": "door_protection_required", "type": "bool", "required": True},
            {"name": "inspection_lead_days", "type": "int", "default": 10},
            {"name": "witness_test_required", "type": "bool", "default": False},
            {"name": "reinspection_extension_hours", "type": "int", "default": 24},
            {
                "name": "permit_surcharge_pct",
                "type": "decimal",
                "min": "0.0000",
                "max": "0.2500",
                "default": calc.Decimal("0.0000"),
            },
        ]
    )
    row = new_row(**data)
    db.jurisdictions[row["id"]] = row
    return object_response(serialize.jurisdiction(row), 201)


@bp.get("/jurisdictions/<jurisdiction_id>")
@endpoint(ALL_ROLES)
def get_jurisdiction(jurisdiction_id):
    row = fetch(db.jurisdictions, jurisdiction_id)
    return read_one(row, serialize.jurisdiction, None)


@bp.get("/jurisdictions")
@endpoint(ALL_ROLES)
def list_jurisdictions():
    year = int_query("code_edition_year")
    rows = eq_filter(list(db.jurisdictions.values()), "code_edition_year", year)
    return paged(rows, serialize.jurisdiction, None)


# --- ModernizationProject --------------------------------------------------

@bp.post("/projects")
@endpoint(["ProjectManager"])
def create_project():
    precheck_fks([("jurisdiction_id", db.jurisdictions)])
    data = validate(
        [
            {"name": "jurisdiction_id", "type": "id", "required": True},
            {"name": "building_name", "type": "string", "required": True},
            {
                "name": "occupancy_type",
                "type": "enum",
                "required": True,
                "values": OCCUPANCY_TYPES,
            },
            {"name": "contract_value_cents", "type": "money", "required": True},
            {"name": "staging_area_sqft", "type": "int", "required": True, "min": 1},
            {"name": "max_concurrent_outages", "type": "int", "required": True, "min": 1},
            {"name": "outage_buffer_hours", "type": "int", "default": 4},
            {"name": "tenant_notice_lead_hours", "type": "int", "default": 72},
        ]
    )
    require(db.jurisdictions.get(data["jurisdiction_id"]))
    row = new_row(status="SURVEY", **data)
    db.projects[row["id"]] = row
    return object_response(serialize.project(row), 201)


@bp.get("/projects/<project_id>")
@endpoint(ALL_ROLES)
def get_project(project_id):
    row = fetch(db.projects, project_id)
    return read_one(row, serialize.project, row)


@bp.get("/projects")
@endpoint(ALL_ROLES)
def list_projects():
    jurisdiction_id = str_query("jurisdiction_id")
    status = enum_query("status", PROJECT_STATUSES)
    rows = list(db.projects.values())
    rows = eq_filter(rows, "jurisdiction_id", jurisdiction_id)
    rows = eq_filter(rows, "status", status)
    return paged(rows, serialize.project, lambda r: r)


@bp.get("/projects/<project_id>/posture")
@endpoint(["ProjectManager", "BuildingRepresentative", "ServiceManager", "SystemOperator"])
def project_posture(project_id):
    project = fetch(db.projects, project_id)
    from middleware import enforce_scope

    enforce_scope(project)
    return object_response(
        {
            "downtime_posture": calc.downtime_posture(project),
            "active_outage_count": calc.project_active_outage_count(project),
            "staging_committed_sqft": calc.project_staging_committed(project),
            "groups_below_floor": calc.groups_below_floor(project),
        }
    )


@bp.patch("/projects/<project_id>")
@endpoint(["ProjectManager"])
def patch_project(project_id):
    project = fetch(db.projects, project_id)
    data = validate(
        [
            {"name": "max_concurrent_outages", "type": "int", "min": 1},
            {"name": "outage_buffer_hours", "type": "int"},
            {"name": "tenant_notice_lead_hours", "type": "int"},
            {"name": "contract_value_cents", "type": "money"},
        ]
    )
    for field in (
        "max_concurrent_outages",
        "outage_buffer_hours",
        "tenant_notice_lead_hours",
        "contract_value_cents",
    ):
        if data[field] is not None:
            project[field] = data[field]
    touch_project(project)
    return object_response(serialize.project(project))


# --- ElevatorGroup ---------------------------------------------------------

@bp.post("/elevator-groups")
@endpoint(["ProjectManager"])
def create_group():
    precheck_fks([("project_id", db.projects)])
    data = validate(
        [
            {"name": "project_id", "type": "id", "required": True},
            {"name": "group_label", "type": "string", "required": True},
            {"name": "min_cars_in_service", "type": "int", "required": True},
        ]
    )
    require(db.projects.get(data["project_id"]))
    row = new_row(**data)
    db.groups[row["id"]] = row
    return object_response(serialize.group(row), 201)


@bp.get("/elevator-groups/<group_id>")
@endpoint(ALL_ROLES)
def get_group(group_id):
    row = fetch(db.groups, group_id)
    return read_one(row, serialize.group, project_of_group(row))


@bp.get("/elevator-groups")
@endpoint(ALL_ROLES)
def list_groups():
    project_id = str_query("project_id")
    rows = eq_filter(list(db.groups.values()), "project_id", project_id)
    return paged(rows, serialize.group, project_of_group)


@bp.patch("/elevator-groups/<group_id>")
@endpoint(["ProjectManager", "BuildingRepresentative"])
def patch_group(group_id):
    group = fetch(db.groups, group_id)
    project = project_of_group(group)
    from middleware import enforce_scope

    enforce_scope(project)
    data = validate([{"name": "min_cars_in_service", "type": "int", "required": True}])
    group["min_cars_in_service"] = data["min_cars_in_service"]
    touch(group)
    touch_project(project)
    return object_response(serialize.group(group))


# --- ElevatorCar -----------------------------------------------------------

@bp.post("/elevator-cars")
@endpoint(["ProjectManager"])
def create_car():
    precheck_fks([("project_id", db.projects), ("group_id", db.groups)])
    data = validate(
        [
            {"name": "project_id", "type": "id", "required": True},
            {"name": "group_id", "type": "id", "required": True},
            {"name": "car_designation", "type": "string", "required": True},
            {"name": "rated_load_lbs", "type": "int", "required": True, "min": 500},
            {
                "name": "controller_type_legacy",
                "type": "enum",
                "required": True,
                "values": CONTROLLER_TYPES,
            },
            {"name": "machine_type", "type": "enum", "required": True, "values": MACHINE_TYPES},
            {"name": "duty_rank", "type": "int", "required": True, "min": 1},
        ]
    )
    project = require(db.projects.get(data["project_id"]))
    require(db.groups.get(data["group_id"]))
    if project["status"] == "COMPLETED":
        raise ApiError("ERR_PROJECT_STATE_INVALID")
    row = new_row(
        work_status="SURVEY_PENDING",
        compliance_status="NOT_EVALUATED",
        condition_score=None,
        recommended_scope_tier=None,
        **data
    )
    db.cars[row["id"]] = row
    touch_project(project)
    return object_response(serialize.car(row), 201)


@bp.get("/elevator-cars/<car_id>")
@endpoint(ALL_ROLES)
def get_car(car_id):
    row = fetch(db.cars, car_id)
    return read_one(row, serialize.car, project_of_car(row))


@bp.get("/elevator-cars")
@endpoint(ALL_ROLES)
def list_cars():
    project_id = str_query("project_id")
    group_id = str_query("group_id")
    work_status = enum_query("work_status", WORK_STATUSES)
    compliance_status = enum_query("compliance_status", COMPLIANCE_STATUSES)
    rows = list(db.cars.values())
    rows = eq_filter(rows, "project_id", project_id)
    rows = eq_filter(rows, "group_id", group_id)
    rows = eq_filter(rows, "work_status", work_status)
    rows = eq_filter(rows, "compliance_status", compliance_status)
    return paged(rows, serialize.car, project_of_car)


def latest_stamped_window(car_id):
    """The car's most recently completed window: greatest completed_at, earliest created_at."""
    rows = [w for w in calc.windows_of_car(car_id) if w.get("_completed_at") is not None]
    if not rows:
        return None
    best = rows[0]
    for row in rows[1:]:
        if row["_completed_at"] > best["_completed_at"]:
            best = row
    return best


@bp.post("/elevator-cars/<car_id>/begin-testing")
@endpoint(["ProjectManager", "ServiceManager"])
def begin_testing(car_id):
    car = fetch(db.cars, car_id)
    project = project_of_car(car)
    from middleware import enforce_scope

    enforce_scope(project)
    if car["work_status"] != "OUTAGE_ACTIVE":
        raise ApiError("ERR_CAR_STATE_INVALID")
    window = latest_stamped_window(car_id)
    if window is None or window["status"] != "COMPLETED":
        raise ApiError("ERR_OUTAGE_STATE_INVALID")
    option = calc.approved_option_of_car(car_id)
    live = []
    if option is not None:
        live = [o for o in calc.orders_of_option(option["id"]) if o["status"] != "CANCELLED"]
    if not live or any(o["status"] != "INSTALLED" for o in live):
        raise ApiError("ERR_PROCUREMENT_NOT_INSTALLED")
    if calc.downtime_posture(project) == "FROZEN":
        raise ApiError("ERR_PROJECT_FROZEN")
    car["work_status"] = "TESTING"
    touch(car)
    touch_project(project)
    return object_response(serialize.car(car))


# --- logical clock ---------------------------------------------------------

@bp.post("/_clock/set_current_utc")
@endpoint(["SystemOperator"])
def set_clock():
    data = validate([{"name": "to_iso8601", "type": "datetime", "required": True}])
    moment = data["to_iso8601"]["dt"]
    db.clock_dt = moment
    db.clock_str = fmt_dt(moment)
    lapsed = 0
    for transition in ordered(list(db.warranty_transitions.values())):
        if transition["status"] != "PENDING":
            continue
        if transition["_warranty_end"] <= moment:
            transition["status"] = "LAPSED"
            touch(transition)
            lapsed += 1
    return object_response(
        {"current_utc": db.clock_str, "lapsed_warranty_transition_count": lapsed}
    )
