"""Equipment surveys, scope options and code triggers."""

from flask import Blueprint, g

import calc
import serialize
from db import db, new_row, touch
from errors import ApiError
from middleware import (
    endpoint,
    enforce_scope,
    project_of_car,
    project_of_option,
    project_of_survey,
    project_of_trigger,
    touch_project,
)
from routes.common import (
    ALL_ROLES,
    enum_query,
    eq_filter,
    fetch,
    object_response,
    paged,
    read_one,
    require,
    str_query,
)
from validation import precheck_fks, validate

bp = Blueprint("scoping", __name__)

SURVEY_STATUSES = ["SUBMITTED", "COUNTERSIGNED", "VOID"]
OPTION_STATUSES = ["DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED"]
TRIGGER_STATUSES = ["REQUIRED", "PRICED", "WAIVED", "SATISFIED"]
TRIGGER_TYPES = [
    "FIRE_SERVICE_PHASE_I_II",
    "SEISMIC_RESTRAINT",
    "DOOR_PROTECTION_REOPENING",
    "MACHINE_BRAKE_MONITOR",
]
DEGRADED_DOOR_GRADES = ("FAIR", "POOR", "FAILED", "NOT_OBSERVED")

SOURCE_RULES = {
    "FIRE_SERVICE_PHASE_I_II": "ASME A17.1 2.27.3 Phase I/II firefighters service",
    "SEISMIC_RESTRAINT": "ASME A17.1 8.4 seismic restraint of machine and counterweight",
    "DOOR_PROTECTION_REOPENING": "ASME A17.1 2.13.5 door reopening protective device",
    "MACHINE_BRAKE_MONITOR": "ASME A17.1 2.26.10 brake and rope monitoring",
}

REVISION_LIMIT = 3


# --- EquipmentSurvey -------------------------------------------------------

@bp.post("/equipment-surveys")
@endpoint(["SurveyTechnician"])
def create_survey():
    precheck_fks([("car_id", db.cars)])
    data = validate(
        [
            {"name": "car_id", "type": "id", "required": True},
            {
                "name": "controller_condition",
                "type": "enum",
                "required": True,
                "values": calc.CONDITION_GRADES,
            },
            {
                "name": "machine_condition",
                "type": "enum",
                "required": True,
                "values": calc.CONDITION_GRADES,
            },
            {
                "name": "door_equipment_condition",
                "type": "enum",
                "required": True,
                "values": calc.CONDITION_GRADES,
            },
        ]
    )
    car = require(db.cars.get(data["car_id"]))
    if car["work_status"] not in ("SURVEY_PENDING", "SURVEYED"):
        raise ApiError("ERR_CAR_STATE_INVALID")

    voided = False
    for prior in calc.surveys_of_car(car["id"]):
        if prior["status"] in ("SUBMITTED", "COUNTERSIGNED"):
            prior["status"] = "VOID"
            touch(prior)
            voided = True

    row = new_row(
        surveyed_by_user_id=g.user_id,
        countersigned_by_user_id=None,
        provisional_score=None,
        final_score=None,
        recommended_scope_tier=None,
        status="SUBMITTED",
        **data
    )
    score, _weight = calc.score_survey(row, "OBSERVED_ONLY")
    row["provisional_score"] = score
    row["recommended_scope_tier"] = calc.tier_for_score(score)
    db.surveys[row["id"]] = row

    if voided:
        car["condition_score"] = None
        car["recommended_scope_tier"] = None
        car["work_status"] = "SURVEY_PENDING"
        touch(car)
    return object_response(serialize.survey(row), 201)


@bp.get("/equipment-surveys/<survey_id>")
@endpoint(ALL_ROLES)
def get_survey(survey_id):
    row = fetch(db.surveys, survey_id)
    return read_one(row, serialize.survey, project_of_survey(row))


@bp.get("/equipment-surveys")
@endpoint(ALL_ROLES)
def list_surveys():
    car_id = str_query("car_id")
    status = enum_query("status", SURVEY_STATUSES)
    rows = eq_filter(list(db.surveys.values()), "car_id", car_id)
    rows = eq_filter(rows, "status", status)
    return paged(rows, serialize.survey, project_of_survey)


@bp.get("/equipment-surveys/<survey_id>/score-preview")
@endpoint(
    ["ProjectManager", "SurveyTechnician", "BuildingRepresentative", "ServiceManager", "SystemOperator"]
)
def score_preview(survey_id):
    row = fetch(db.surveys, survey_id)
    enforce_scope(project_of_survey(row))
    basis = enum_query("basis", calc.SCORE_BASES, required=True)
    score, weight = calc.score_survey(row, basis)
    return object_response(
        {
            "basis": basis,
            "score": calc.as_number(score),
            "recommended_scope_tier": calc.tier_for_score(score),
            "observed_weight_total": calc.as_number(weight),
        }
    )


@bp.post("/equipment-surveys/<survey_id>/countersign")
@endpoint(["SurveyTechnician", "ProjectManager"])
def countersign(survey_id):
    row = fetch(db.surveys, survey_id)
    car = db.cars.get(row["car_id"])
    project = project_of_car(car)
    enforce_scope(project)
    if g.user_id == row["surveyed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    validate([])
    if row["status"] != "SUBMITTED":
        raise ApiError("ERR_SURVEY_STATE_INVALID")

    score, _weight = calc.score_survey(row, "IMPUTED_FAILED")
    tier = calc.tier_for_score(score)
    row["status"] = "COUNTERSIGNED"
    row["countersigned_by_user_id"] = g.user_id
    row["final_score"] = score
    row["recommended_scope_tier"] = tier
    touch(row)

    car["condition_score"] = score
    car["recommended_scope_tier"] = tier
    if car["work_status"] == "SURVEY_PENDING":
        car["work_status"] = "SURVEYED"
    touch(car)

    if project["status"] == "SURVEY":
        project["status"] = "SCOPING"
    touch_project(project)
    return object_response(serialize.survey(row))


# --- code trigger synthesis ------------------------------------------------

def synthesize_triggers(option, car, jurisdiction):
    survey = calc.latest_countersigned_survey(car["id"])
    tier = option["tier"]
    emitted = []
    if jurisdiction["fire_service_required"]:
        emitted.append("FIRE_SERVICE_PHASE_I_II")
    if jurisdiction["seismic_zone"] >= 2 and tier in ("CONTROLLER_MACHINE", "FULL_REPLACEMENT"):
        emitted.append("SEISMIC_RESTRAINT")
    if jurisdiction["door_protection_required"] and survey is not None:
        if survey["door_equipment_condition"] in DEGRADED_DOOR_GRADES:
            emitted.append("DOOR_PROTECTION_REOPENING")
    if tier == "FULL_REPLACEMENT" or (
        tier == "CONTROLLER_MACHINE" and car["machine_type"] == "GEARED"
    ):
        emitted.append("MACHINE_BRAKE_MONITOR")

    created = []
    for trigger_type in emitted:
        row = new_row(
            scope_option_id=option["id"],
            trigger_type=trigger_type,
            source_rule=SOURCE_RULES[trigger_type],
            status="REQUIRED",
            cost_cents=0,
            waiver_reference=None,
        )
        db.code_triggers[row["id"]] = row
        created.append(row)
    return created


# --- ScopeOption -----------------------------------------------------------

@bp.post("/scope-options")
@endpoint(["ProjectManager"])
def create_scope_option():
    precheck_fks([("car_id", db.cars)])
    data = validate(
        [
            {"name": "car_id", "type": "id", "required": True},
            {"name": "tier", "type": "enum", "required": True, "values": calc.SCOPE_TIERS},
            {"name": "base_price_cents", "type": "money", "required": True},
            {"name": "expected_project_version", "type": "int", "required": True},
        ]
    )
    car = require(db.cars.get(data["car_id"]))
    project = project_of_car(car)
    if project["version"] != data["expected_project_version"]:
        raise ApiError("ERR_STALE_PROJECT_VERSION")
    if calc.latest_countersigned_survey(car["id"]) is None:
        raise ApiError("ERR_CAR_STATE_INVALID")
    if project["status"] == "COMPLETED":
        raise ApiError("ERR_PROJECT_STATE_INVALID")

    car_touched = False
    for prior in calc.options_of_car(car["id"]):
        if prior["status"] in ("DRAFT", "SUBMITTED", "REJECTED", "APPROVED"):
            was_approved = prior["status"] == "APPROVED"
            prior["status"] = "SUPERSEDED"
            touch(prior)
            if was_approved and car["work_status"] == "PROCURING":
                car["work_status"] = "SCOPED"
                car_touched = True

    row = new_row(
        car_id=data["car_id"],
        tier=data["tier"],
        base_price_cents=data["base_price_cents"],
        code_upgrade_cents=0,
        max_lead_time_days=0,
        escalation_pct=calc.Decimal("0.0000"),
        escalation_fee_cents=0,
        volume_discount_pct=calc.Decimal("0.0000"),
        volume_discount_cents=0,
        total_price_cents=0,
        revision_count=0,
        rejection_note=None,
        status="DRAFT",
    )
    db.scope_options[row["id"]] = row

    jurisdiction = db.jurisdictions[project["jurisdiction_id"]]
    created = synthesize_triggers(row, car, jurisdiction)
    car["compliance_status"] = "TRIGGERS_OPEN" if created else "TRIGGERS_CLEARED"
    car_touched = True

    calc.recompute_pricing(row)
    if car_touched:
        touch(car)
    touch_project(project)
    return object_response(serialize.scope_option(row), 201)


@bp.get("/scope-options/<scope_option_id>")
@endpoint(ALL_ROLES)
def get_scope_option(scope_option_id):
    row = fetch(db.scope_options, scope_option_id)
    return read_one(row, serialize.scope_option, project_of_option(row))


@bp.get("/scope-options")
@endpoint(ALL_ROLES)
def list_scope_options():
    car_id = str_query("car_id")
    status = enum_query("status", OPTION_STATUSES)
    rows = eq_filter(list(db.scope_options.values()), "car_id", car_id)
    rows = eq_filter(rows, "status", status)
    return paged(rows, serialize.scope_option, project_of_option)


def _option_context(scope_option_id):
    option = fetch(db.scope_options, scope_option_id)
    car = db.cars.get(option["car_id"])
    project = project_of_car(car)
    enforce_scope(project)
    return option, car, project


@bp.post("/scope-options/<scope_option_id>/submit")
@endpoint(["ProjectManager"])
def submit_scope_option(scope_option_id):
    option, car, project = _option_context(scope_option_id)
    validate([])
    if option["status"] != "DRAFT":
        raise ApiError("ERR_SCOPE_OPTION_STATE_INVALID")
    option["status"] = "SUBMITTED"
    touch(option)
    if car["work_status"] == "SURVEYED":
        car["work_status"] = "SCOPED"
        touch(car)
    touch_project(project)
    return object_response(serialize.scope_option(option))


@bp.post("/scope-options/<scope_option_id>/approve")
@endpoint(["BuildingRepresentative"])
def approve_scope_option(scope_option_id):
    option, car, project = _option_context(scope_option_id)
    validate([])
    if option["status"] != "SUBMITTED":
        raise ApiError("ERR_SCOPE_OPTION_STATE_INVALID")
    if any(t["status"] == "REQUIRED" for t in calc.triggers_of_option(option["id"])):
        raise ApiError("ERR_CODE_TRIGGER_OPEN")
    recommended = car.get("recommended_scope_tier")
    if recommended is not None:
        if calc.TIER_RANK[option["tier"]] < calc.TIER_RANK[recommended]:
            raise ApiError("ERR_SCOPE_TIER_BELOW_RECOMMENDATION")
    current = calc.project_approved_scope_value(project)
    if current + option["total_price_cents"] > project["contract_value_cents"]:
        raise ApiError("ERR_SCOPE_BUDGET_EXCEEDED")

    option["status"] = "APPROVED"
    touch(option)
    if car["work_status"] == "SCOPED":
        car["work_status"] = "PROCURING"
        touch(car)
    if project["status"] == "SCOPING":
        project["status"] = "EXECUTION"
    touch_project(project)
    return object_response(serialize.scope_option(option))


@bp.post("/scope-options/<scope_option_id>/reject")
@endpoint(["BuildingRepresentative"])
def reject_scope_option(scope_option_id):
    option, _car, project = _option_context(scope_option_id)
    data = validate([{"name": "rejection_note", "type": "string", "required": True}])
    if option["status"] != "SUBMITTED":
        raise ApiError("ERR_SCOPE_OPTION_STATE_INVALID")
    option["status"] = "REJECTED"
    option["rejection_note"] = data["rejection_note"]
    touch(option)
    touch_project(project)
    return object_response(serialize.scope_option(option))


@bp.post("/scope-options/<scope_option_id>/revise")
@endpoint(["ProjectManager"])
def revise_scope_option(scope_option_id):
    option, car, project = _option_context(scope_option_id)
    data = validate([{"name": "base_price_cents", "type": "money"}])
    if option["status"] != "REJECTED":
        raise ApiError("ERR_SCOPE_OPTION_STATE_INVALID")
    if option["revision_count"] >= REVISION_LIMIT:
        raise ApiError("ERR_REVISION_LIMIT")
    option["status"] = "DRAFT"
    option["revision_count"] += 1
    option["rejection_note"] = None
    if data["base_price_cents"] is not None:
        option["base_price_cents"] = data["base_price_cents"]
    calc.recompute_pricing(option)
    touch(option)
    if car["work_status"] == "SCOPED":
        car["work_status"] = "SURVEYED"
        touch(car)
    touch_project(project)
    return object_response(serialize.scope_option(option))


@bp.post("/scope-options/<scope_option_id>/rescind")
@endpoint(["ProjectManager"])
def rescind_scope_option(scope_option_id):
    option, car, project = _option_context(scope_option_id)
    validate([])
    if option["status"] != "APPROVED":
        raise ApiError("ERR_SCOPE_OPTION_STATE_INVALID")

    option["status"] = "SUPERSEDED"
    touch(option)

    for order in calc.orders_of_option(option["id"]):
        if order["status"] in ("DRAFT", "ORDERED", "STAGED"):
            order["status"] = "CANCELLED"
            touch(order)
            for reservation in _reservations_of_order(order["id"]):
                if reservation["status"] == "HELD":
                    reservation["status"] = "RELEASED"
                    reservation["released_at"] = db.clock_str
                    reservation["_released_at"] = db.clock_dt
                    touch(reservation)

    if car["work_status"] == "PROCURING":
        car["work_status"] = "SCOPED"
    car["compliance_status"] = "NOT_EVALUATED"
    touch(car)

    for window in calc.windows_of_car(car["id"]):
        if window["status"] == "PLANNED":
            window["status"] = "CANCELLED"
            touch(window)

    for appointment in _appointments_of_car(car["id"]):
        if appointment["status"] == "REQUESTED":
            appointment["status"] = "CANCELLED"
            touch(appointment)

    touch_project(project)
    return object_response(serialize.scope_option(option))


def _reservations_of_order(order_id):
    from db import ordered

    return ordered(
        [r for r in db.staging_reservations.values() if r["procurement_order_id"] == order_id]
    )


def _appointments_of_car(car_id):
    from db import ordered

    return ordered([a for a in db.inspections.values() if a["car_id"] == car_id])


# --- CodeTrigger -----------------------------------------------------------

@bp.get("/code-triggers/<code_trigger_id>")
@endpoint(ALL_ROLES)
def get_code_trigger(code_trigger_id):
    row = fetch(db.code_triggers, code_trigger_id)
    return read_one(row, serialize.code_trigger, project_of_trigger(row))


@bp.get("/code-triggers")
@endpoint(ALL_ROLES)
def list_code_triggers():
    scope_option_id = str_query("scope_option_id")
    status = enum_query("status", TRIGGER_STATUSES)
    trigger_type = enum_query("trigger_type", TRIGGER_TYPES)
    rows = eq_filter(list(db.code_triggers.values()), "scope_option_id", scope_option_id)
    rows = eq_filter(rows, "status", status)
    rows = eq_filter(rows, "trigger_type", trigger_type)
    return paged(rows, serialize.code_trigger, project_of_trigger)


def _clear_compliance(option, car):
    if any(t["status"] == "REQUIRED" for t in calc.triggers_of_option(option["id"])):
        return False
    if car["compliance_status"] == "TRIGGERS_OPEN":
        car["compliance_status"] = "TRIGGERS_CLEARED"
        return True
    return False


@bp.post("/code-triggers/<code_trigger_id>/price")
@endpoint(["ProjectManager"])
def price_code_trigger(code_trigger_id):
    trigger = fetch(db.code_triggers, code_trigger_id)
    option = db.scope_options[trigger["scope_option_id"]]
    car = db.cars[option["car_id"]]
    project = project_of_car(car)
    enforce_scope(project)
    data = validate([{"name": "cost_cents", "type": "money", "required": True}])
    if trigger["status"] != "REQUIRED":
        raise ApiError("ERR_CODE_TRIGGER_STATE_INVALID")
    trigger["status"] = "PRICED"
    trigger["cost_cents"] = data["cost_cents"]
    touch(trigger)
    calc.recompute_pricing(option)
    if option["status"] in ("DRAFT", "SUBMITTED"):
        touch(option)
    if _clear_compliance(option, car):
        touch(car)
    touch_project(project)
    return object_response(serialize.code_trigger(trigger))


@bp.post("/code-triggers/<code_trigger_id>/waive")
@endpoint(["AHJInspector"])
def waive_code_trigger(code_trigger_id):
    trigger = fetch(db.code_triggers, code_trigger_id)
    option = db.scope_options[trigger["scope_option_id"]]
    car = db.cars[option["car_id"]]
    project = project_of_car(car)
    enforce_scope(project)
    data = validate([{"name": "waiver_reference", "type": "string", "required": True}])
    if trigger["status"] not in ("REQUIRED", "PRICED"):
        raise ApiError("ERR_CODE_TRIGGER_STATE_INVALID")
    trigger["status"] = "WAIVED"
    trigger["waiver_reference"] = data["waiver_reference"]
    touch(trigger)
    calc.recompute_pricing(option)
    if option["status"] in ("DRAFT", "SUBMITTED"):
        touch(option)
    if _clear_compliance(option, car):
        touch(car)
    touch_project(project)
    return object_response(serialize.code_trigger(trigger))
