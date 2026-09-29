"""Inspection appointments, warranty transitions and maintenance contracts."""

from flask import Blueprint, g

import calc
import serialize
from db import db, fmt_dt, new_row, ordered, touch
from errors import ApiError
from middleware import (
    endpoint,
    enforce_scope,
    project_of_car,
    project_of_contract,
    project_of_inspection,
    project_of_transition,
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

bp = Blueprint("closeout", __name__)

INSPECTION_STATUSES = [
    "REQUESTED",
    "SCHEDULED",
    "PASSED",
    "CONDITIONAL",
    "FAILED",
    "CANCELLED",
]
RESULTS = ["PASSED", "CONDITIONAL", "FAILED"]
TRANSITION_STATUSES = ["PENDING", "ENROLLED", "UNDER_CONTRACT", "LAPSED"]
CONTRACT_STATUSES = ["DRAFT", "ACTIVE"]
RESCHEDULE_LIMIT = 2


def _jurisdiction_of_car(car):
    project = project_of_car(car)
    return db.jurisdictions.get(project["jurisdiction_id"]) if project else None


# --- InspectionAppointment -------------------------------------------------

@bp.post("/inspection-appointments")
@endpoint(["ProjectManager", "ServiceManager"])
def create_inspection():
    precheck_fks([("car_id", db.cars)])
    data = validate(
        [
            {"name": "car_id", "type": "id", "required": True},
            {"name": "requested_date", "type": "datetime", "required": True},
            {"name": "witness_requested", "type": "bool"},
        ]
    )
    car = require(db.cars.get(data["car_id"]))
    project = project_of_car(car)
    jurisdiction = db.jurisdictions[project["jurisdiction_id"]]
    lead_days = calc.whole_days_between(db.clock_dt, data["requested_date"]["dt"])
    if lead_days < jurisdiction["inspection_lead_days"]:
        raise ApiError("ERR_INSPECTION_LEAD_UNMET")
    witness = data["witness_requested"]
    if witness is None:
        witness = jurisdiction["witness_test_required"]
    row = new_row(
        car_id=data["car_id"],
        requested_date=data["requested_date"]["raw"],
        witness_requested=witness,
        scheduled_at=None,
        recorded_by_jurisdiction_id=project["jurisdiction_id"],
        lead_days_at_request=lead_days,
        reschedule_count=0,
        punch_list_count=0,
        status="REQUESTED",
    )
    row["_requested_date"] = data["requested_date"]["dt"]
    row["_scheduled_at"] = None
    db.inspections[row["id"]] = row
    return object_response(serialize.inspection(row), 201)


@bp.get("/inspection-appointments/<inspection_appointment_id>")
@endpoint(ALL_ROLES)
def get_inspection(inspection_appointment_id):
    row = fetch(db.inspections, inspection_appointment_id)
    return read_one(row, serialize.inspection, project_of_inspection(row))


@bp.get("/inspection-appointments")
@endpoint(ALL_ROLES)
def list_inspections():
    car_id = str_query("car_id")
    status = enum_query("status", INSPECTION_STATUSES)
    rows = eq_filter(list(db.inspections.values()), "car_id", car_id)
    rows = eq_filter(rows, "status", status)
    return paged(rows, serialize.inspection, project_of_inspection)


def _inspection_context(appointment_id):
    appointment = fetch(db.inspections, appointment_id)
    car = db.cars.get(appointment["car_id"])
    project = project_of_car(car)
    enforce_scope(project)
    return appointment, car, project


@bp.post("/inspection-appointments/<inspection_appointment_id>/schedule")
@endpoint(["AHJInspector"])
def schedule_inspection(inspection_appointment_id):
    appointment, car, _project = _inspection_context(inspection_appointment_id)
    data = validate([{"name": "scheduled_at", "type": "datetime", "required": True}])
    if appointment["status"] != "REQUESTED":
        raise ApiError("ERR_INSPECTION_STATE_INVALID")
    jurisdiction = _jurisdiction_of_car(car)
    lead_days = calc.whole_days_between(db.clock_dt, data["scheduled_at"]["dt"])
    if lead_days < jurisdiction["inspection_lead_days"]:
        raise ApiError("ERR_INSPECTION_LEAD_UNMET")
    appointment["status"] = "SCHEDULED"
    appointment["scheduled_at"] = data["scheduled_at"]["raw"]
    appointment["_scheduled_at"] = data["scheduled_at"]["dt"]
    touch(appointment)
    return object_response(serialize.inspection(appointment))


@bp.post("/inspection-appointments/<inspection_appointment_id>/reschedule")
@endpoint(["AHJInspector", "ProjectManager"])
def reschedule_inspection(inspection_appointment_id):
    appointment, car, _project = _inspection_context(inspection_appointment_id)
    data = validate([{"name": "scheduled_at", "type": "datetime", "required": True}])
    if appointment["status"] in ("PASSED", "CONDITIONAL", "FAILED", "CANCELLED"):
        raise ApiError("ERR_INSPECTION_NOT_RESCHEDULABLE")
    if appointment["status"] != "SCHEDULED":
        raise ApiError("ERR_INSPECTION_STATE_INVALID")
    jurisdiction = _jurisdiction_of_car(car)
    lead_days = calc.whole_days_between(db.clock_dt, data["scheduled_at"]["dt"])
    if lead_days < jurisdiction["inspection_lead_days"]:
        raise ApiError("ERR_INSPECTION_LEAD_UNMET")
    if appointment["reschedule_count"] >= RESCHEDULE_LIMIT:
        raise ApiError("ERR_RESCHEDULE_LIMIT")
    appointment["scheduled_at"] = data["scheduled_at"]["raw"]
    appointment["_scheduled_at"] = data["scheduled_at"]["dt"]
    appointment["reschedule_count"] += 1
    appointment["lead_days_at_request"] = lead_days
    touch(appointment)
    return object_response(serialize.inspection(appointment))


def _latest_completed_window(car_id):
    rows = [w for w in calc.windows_of_car(car_id) if w["status"] == "COMPLETED"]
    if not rows:
        return None
    best = rows[0]
    for row in rows[1:]:
        if row["_completed_at"] is None:
            continue
        if best["_completed_at"] is None or row["_completed_at"] > best["_completed_at"]:
            best = row
    return best


def _project_all_cars_accepted(project):
    cars = calc.cars_of_project(project["id"])
    if not cars:
        return False
    return all(c["work_status"] in ("ACCEPTED", "IN_WARRANTY", "UNDER_CONTRACT") for c in cars)


@bp.post("/inspection-appointments/<inspection_appointment_id>/record-result")
@endpoint(["AHJInspector"])
def record_result(inspection_appointment_id):
    appointment, car, project = _inspection_context(inspection_appointment_id)
    data = validate(
        [
            {"name": "result", "type": "enum", "required": True, "values": RESULTS},
            {"name": "punch_list_count", "type": "int"},
        ]
    )
    if appointment["status"] != "SCHEDULED":
        raise ApiError("ERR_INSPECTION_STATE_INVALID")
    if car["work_status"] not in ("TESTING", "ACCEPTED"):
        raise ApiError("ERR_CAR_STATE_INVALID")
    result = data["result"]
    punch = data["punch_list_count"]
    if result == "CONDITIONAL" and (punch is None or punch < 1):
        raise ApiError("ERR_PUNCH_LIST_REQUIRED")

    option = calc.live_option_of_car(car["id"])
    appointment["status"] = result
    appointment["recorded_by_jurisdiction_id"] = g.user_id
    if punch is not None:
        appointment["punch_list_count"] = punch
    touch(appointment)

    if result == "PASSED":
        if car["work_status"] == "TESTING":
            car["work_status"] = "ACCEPTED"
        if car["compliance_status"] == "TRIGGERS_CLEARED":
            car["compliance_status"] = "CODE_ACCEPTED"
        touch(car)
        if option is not None:
            for trigger in calc.triggers_of_option(option["id"]):
                if trigger["status"] in ("PRICED", "WAIVED"):
                    trigger["status"] = "SATISFIED"
                    touch(trigger)
        if project["status"] == "EXECUTION" and _project_all_cars_accepted(project):
            project["status"] = "CLOSEOUT"
    elif result == "CONDITIONAL":
        if car["work_status"] == "TESTING":
            car["work_status"] = "ACCEPTED"
            touch(car)
        if project["status"] == "EXECUTION" and _project_all_cars_accepted(project):
            project["status"] = "CLOSEOUT"
    else:
        car["work_status"] = "OUTAGE_ACTIVE"
        if car["compliance_status"] in ("TRIGGERS_CLEARED", "CODE_ACCEPTED"):
            car["compliance_status"] = "TRIGGERS_OPEN"
        touch(car)
        if option is not None:
            for trigger in calc.triggers_of_option(option["id"]):
                if trigger["status"] in ("PRICED", "SATISFIED"):
                    trigger["status"] = "REQUIRED"
                    touch(trigger)
        window = _latest_completed_window(car["id"])
        if window is not None:
            jurisdiction = db.jurisdictions[project["jurisdiction_id"]]
            hours = jurisdiction["reinspection_extension_hours"]
            window["status"] = "ACTIVE"
            window["extension_hours"] += hours
            new_end = window["_end_at"] + calc.timedelta(hours=hours)
            window["_end_at"] = new_end
            window["end_at"] = fmt_dt(new_end)
            touch(window)
        if project["status"] == "CLOSEOUT":
            project["status"] = "EXECUTION"

    touch_project(project)
    return object_response(serialize.inspection(appointment))


# --- WarrantyTransition ----------------------------------------------------

@bp.post("/warranty-transitions")
@endpoint(["ServiceManager", "ProjectManager"])
def create_transition():
    precheck_fks([("car_id", db.cars)])
    data = validate(
        [
            {"name": "car_id", "type": "id", "required": True},
            {"name": "warranty_months", "type": "int", "required": True, "min": 12, "max": 60},
        ]
    )
    car = require(db.cars.get(data["car_id"]))
    project = project_of_car(car)
    if car["work_status"] != "ACCEPTED":
        raise ApiError("ERR_CAR_STATE_INVALID")
    if car["compliance_status"] != "CODE_ACCEPTED":
        raise ApiError("ERR_CAR_NOT_CODE_ACCEPTED")
    start = db.clock_dt
    end = calc.add_months(start, data["warranty_months"])
    row = new_row(
        car_id=data["car_id"],
        maintenance_contract_id=None,
        warranty_months=data["warranty_months"],
        warranty_start=db.clock_str,
        warranty_end=fmt_dt(end),
        provisional_credit_cents=0,
        final_credit_cents=0,
        status="PENDING",
    )
    row["_warranty_start"] = start
    row["_warranty_end"] = end
    db.warranty_transitions[row["id"]] = row
    car["work_status"] = "IN_WARRANTY"
    touch(car)
    touch_project(project)
    return object_response(serialize.warranty_transition(row), 201)


@bp.get("/warranty-transitions/<warranty_transition_id>")
@endpoint(ALL_ROLES)
def get_transition(warranty_transition_id):
    row = fetch(db.warranty_transitions, warranty_transition_id)
    return read_one(row, serialize.warranty_transition, project_of_transition(row))


@bp.get("/warranty-transitions")
@endpoint(ALL_ROLES)
def list_transitions():
    car_id = str_query("car_id")
    contract_id = str_query("maintenance_contract_id")
    status = enum_query("status", TRANSITION_STATUSES)
    rows = eq_filter(list(db.warranty_transitions.values()), "car_id", car_id)
    rows = eq_filter(rows, "maintenance_contract_id", contract_id)
    rows = eq_filter(rows, "status", status)
    return paged(rows, serialize.warranty_transition, project_of_transition)


@bp.get("/warranty-transitions/<warranty_transition_id>/credit-preview")
@endpoint(["ProjectManager", "BuildingRepresentative", "ServiceManager", "SystemOperator"])
def credit_preview(warranty_transition_id):
    transition = fetch(db.warranty_transitions, warranty_transition_id)
    enforce_scope(project_of_transition(transition))
    basis = enum_query("basis", calc.CREDIT_BASES, required=True)
    contract = db.contracts.get(transition["maintenance_contract_id"])
    days, rate, credit = calc.credit_for(transition, contract, basis)
    return object_response(
        {
            "basis": basis,
            "day_count": days,
            "per_car_monthly_cents": rate,
            "credit_cents": credit,
        }
    )


@bp.post("/warranty-transitions/<warranty_transition_id>/enroll")
@endpoint(["ServiceManager"])
def enroll_transition(warranty_transition_id):
    transition = fetch(db.warranty_transitions, warranty_transition_id)
    car = db.cars.get(transition["car_id"])
    project = project_of_car(car)
    enforce_scope(project)
    precheck_fks([("maintenance_contract_id", db.contracts)])
    data = validate([{"name": "maintenance_contract_id", "type": "id", "required": True}])
    contract = require(db.contracts.get(data["maintenance_contract_id"]))
    if transition["status"] != "PENDING":
        raise ApiError("ERR_WARRANTY_STATE_INVALID")
    if contract["status"] != "DRAFT":
        raise ApiError("ERR_CONTRACT_STATE_INVALID")
    if contract["project_id"] != car["project_id"]:
        raise ApiError("ERR_CONTRACT_PROJECT_MISMATCH")
    transition["maintenance_contract_id"] = contract["id"]
    _days, _rate, credit = calc.credit_for(transition, contract, "THIRTY_360")
    transition["provisional_credit_cents"] = credit
    transition["status"] = "ENROLLED"
    touch(transition)
    touch_project(project)
    return object_response(serialize.warranty_transition(transition))


# --- MaintenanceContract ---------------------------------------------------

@bp.post("/maintenance-contracts")
@endpoint(["ServiceManager"])
def create_contract():
    precheck_fks([("project_id", db.projects)])
    data = validate(
        [
            {"name": "project_id", "type": "id", "required": True},
            {"name": "monthly_base_cents", "type": "money", "required": True},
            {"name": "coverage_start", "type": "datetime", "required": True},
        ]
    )
    require(db.projects.get(data["project_id"]))
    row = new_row(
        project_id=data["project_id"],
        monthly_base_cents=data["monthly_base_cents"],
        coverage_start=data["coverage_start"]["raw"],
        monthly_total_cents=0,
        cars_covered=0,
        total_final_credit_cents=0,
        status="DRAFT",
    )
    row["_coverage_start"] = data["coverage_start"]["dt"]
    db.contracts[row["id"]] = row
    return object_response(serialize.maintenance_contract(row), 201)


@bp.get("/maintenance-contracts/<maintenance_contract_id>")
@endpoint(ALL_ROLES)
def get_contract(maintenance_contract_id):
    row = fetch(db.contracts, maintenance_contract_id)
    return read_one(row, serialize.maintenance_contract, project_of_contract(row))


@bp.get("/maintenance-contracts")
@endpoint(ALL_ROLES)
def list_contracts():
    project_id = str_query("project_id")
    status = enum_query("status", CONTRACT_STATUSES)
    rows = eq_filter(list(db.contracts.values()), "project_id", project_id)
    rows = eq_filter(rows, "status", status)
    return paged(rows, serialize.maintenance_contract, project_of_contract)


@bp.post("/maintenance-contracts/<maintenance_contract_id>/activate")
@endpoint(["ServiceManager"])
def activate_contract(maintenance_contract_id):
    contract = fetch(db.contracts, maintenance_contract_id)
    project = project_of_contract(contract)
    enforce_scope(project)
    validate([])
    if contract["status"] != "DRAFT":
        raise ApiError("ERR_CONTRACT_STATE_INVALID")
    covered = [
        t
        for t in ordered(list(db.warranty_transitions.values()))
        if t["maintenance_contract_id"] == contract["id"] and t["status"] == "ENROLLED"
    ]
    if not covered:
        raise ApiError("ERR_NO_ENROLLED_TRANSITIONS")

    monthly_total = 0
    final_total = 0
    for transition in covered:
        car = db.cars.get(transition["car_id"])
        monthly_total += calc.per_car_monthly_cents(contract, car)
        _days, _rate, credit = calc.credit_for(transition, contract, "ACTUAL_CALENDAR")
        transition["final_credit_cents"] = credit
        transition["status"] = "UNDER_CONTRACT"
        touch(transition)
        final_total += credit
        if car is not None and car["work_status"] == "IN_WARRANTY":
            car["work_status"] = "UNDER_CONTRACT"
            touch(car)

    contract["status"] = "ACTIVE"
    contract["monthly_total_cents"] = monthly_total
    contract["cars_covered"] = len(covered)
    contract["total_final_credit_cents"] = final_total
    touch(contract)

    if project["status"] == "CLOSEOUT" and contract["cars_covered"] == calc.project_car_count(
        project
    ):
        project["status"] = "COMPLETED"
    touch_project(project)
    return object_response(serialize.maintenance_contract(contract))
