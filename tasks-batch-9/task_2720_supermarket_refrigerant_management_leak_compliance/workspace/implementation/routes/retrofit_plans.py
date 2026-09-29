"""Retrofit and retirement plans (PRD 3.7)."""
from decimal import Decimal

from flask import Blueprint, request

import constants
import db
import response
import util
import validate
from errors import ApiError, invalid
from middleware import COMPLIANCE_MANAGER, REGULATOR, endpoint, read_endpoint
from services import ledger, plans, posture
from services import guards

bp = Blueprint("retrofit_plans", __name__)


@bp.post("/retrofit-plans")
@endpoint([COMPLIANCE_MANAGER])
def create_retrofit_plan():
    payload = validate.body()
    system_id = validate.req_id(payload, "system_id")
    plan_type = validate.req_enum(payload, "plan_type", constants.PLAN_TYPES)
    target_refrigerant_type_id = validate.opt_id(payload, "target_refrigerant_type_id")
    due_on = validate.req_instant(payload, "due_on")
    estimated_cost_usd = validate.req_decimal(payload, "estimated_cost_usd")
    expected_system_version = validate.req_int(payload, "expected_system_version")
    if due_on <= db.now():
        raise invalid("due_on must be later than the current logical clock")

    system = db.require("systems", system_id)
    target_type = None
    if target_refrigerant_type_id is not None:
        target_type = db.require("refrigerant_types", target_refrigerant_type_id)
    if expected_system_version != system["version"]:
        raise ApiError("ERR_STALE_SYSTEM_VERSION")
    guards.require_active_system(system)
    if target_type is not None and target_type["phasedown_status"] == "PROHIBITED":
        raise ApiError("ERR_TARGET_REFRIGERANT_PROHIBITED")
    if plan_type == "RETROFIT" and target_refrigerant_type_id is None:
        raise ApiError("ERR_RETROFIT_TARGET_REQUIRED")
    if plan_type == "RETIRE" and target_refrigerant_type_id is not None:
        raise ApiError("ERR_RETROFIT_TARGET_REQUIRED")
    if (estimated_cost_usd <= constants.PLAN_COST_FLOOR
            or estimated_cost_usd > constants.PLAN_COST_CEILING):
        raise ApiError("ERR_PLAN_COST_OUT_OF_RANGE")

    plan = db.new_entity()
    plan.update({
        "system_id": system_id,
        "plan_type": plan_type,
        "target_refrigerant_type_id": target_refrigerant_type_id,
        "due_on": due_on,
        "estimated_cost_usd": util.q2(estimated_cost_usd),
        "gwp_reduction_pct": util.q1(Decimal("0")),
        "compatibility_score": util.q1(Decimal("0")),
        "compatibility_result": "INCOMPATIBLE",
        "status": "DRAFT",
        "mandated": system["compliance_state"] == "RETROFIT_MANDATED",
        "submission_count": 0,
        "submitted_at": None,
        "submission_note": None,
        "decided_at": None,
        "completed_at": None,
        "rejection_reason_code": None,
    })
    plans.score_plan(plan, system, db.collection("refrigerant_types"))
    db.insert("retrofit_plans", plan)

    for other in db.values("retrofit_plans"):
        if (other["id"] != plan["id"] and other["system_id"] == system_id
                and other["status"] == "DRAFT"):
            other_snap = db.snapshot(other)
            other["status"] = "SUPERSEDED"
            db.commit(other, other_snap)

    db.touch(system)
    posture.recompute_store_by_id(system["store_id"])
    return response.created(plan)


@bp.get("/retrofit-plans")
@read_endpoint
def list_retrofit_plans():
    filters = {
        "system_id": request.args.get("system_id"),
        "target_refrigerant_type_id": request.args.get("target_refrigerant_type_id"),
        "status": request.args.get("status"),
        "plan_type": request.args.get("plan_type"),
        "mandated": response.bool_filter("mandated"),
    }
    return response.listing(db.values("retrofit_plans"), filters)


@bp.get("/retrofit-plans/<plan_id>")
@read_endpoint
def get_retrofit_plan(plan_id):
    return response.ok(db.require("retrofit_plans", plan_id))


@bp.post("/retrofit-plans/<plan_id>/submission")
@endpoint([COMPLIANCE_MANAGER])
def submit_retrofit_plan(plan_id):
    payload = validate.body()
    submission_note = validate.opt_str(payload, "submission_note")
    plan = db.require("retrofit_plans", plan_id)
    guards.require_state(plan["status"] in ("DRAFT", "REJECTED"))
    system = db.require("systems", plan["system_id"])
    guards.require_active_system(system)
    target_type = db.get("refrigerant_types", plan["target_refrigerant_type_id"])
    if target_type is not None and target_type["phasedown_status"] == "PROHIBITED":
        raise ApiError("ERR_TARGET_REFRIGERANT_PROHIBITED")
    rescored = dict(plan)
    plans.score_plan(rescored, system, db.collection("refrigerant_types"))
    if rescored["compatibility_result"] == "INCOMPATIBLE":
        raise ApiError("ERR_RETROFIT_INCOMPATIBLE")
    snap = db.snapshot(plan)
    for field in ("compatibility_score", "compatibility_result", "gwp_reduction_pct"):
        plan[field] = rescored[field]
    plan["status"] = "SUBMITTED"
    plan["submitted_at"] = db.now()
    plan["submission_count"] = plan["submission_count"] + 1
    plan["rejection_reason_code"] = None
    if submission_note is not None:
        plan["submission_note"] = submission_note
    db.commit(plan, snap)
    return response.ok(plan)


@bp.post("/retrofit-plans/<plan_id>/decision")
@endpoint([REGULATOR])
def decide_retrofit_plan(plan_id):
    payload = validate.body()
    decision = validate.req_enum(payload, "decision", ("APPROVE", "REJECT"))
    rejection_reason_code = None
    if decision == "REJECT":
        rejection_reason_code = validate.req_str(payload, "rejection_reason_code")
    plan = db.require("retrofit_plans", plan_id)
    guards.require_state(plan["status"] == "SUBMITTED")
    snap = db.snapshot(plan)
    plan["decided_at"] = db.now()
    if decision == "APPROVE":
        plan["status"] = "APPROVED"
        plan["rejection_reason_code"] = None
    else:
        plan["status"] = "REJECTED"
        plan["rejection_reason_code"] = rejection_reason_code
    db.commit(plan, snap)
    return response.ok(plan)


@bp.post("/retrofit-plans/<plan_id>/completion")
@endpoint([COMPLIANCE_MANAGER])
def complete_retrofit_plan(plan_id):
    payload = validate.body()
    service_record_id = validate.req_id(payload, "service_record_id")
    plan = db.require("retrofit_plans", plan_id)
    db.require("service_records", service_record_id)
    guards.require_state(plan["status"] == "IN_PROGRESS")
    system = db.require("systems", plan["system_id"])
    events = ledger.system_events(system["id"])
    guards.require_state(not any(
        event["status"] in constants.OVERDUE_LEAK_EVENT_STATUSES for event in events))

    clock = db.now()
    snap = db.snapshot(plan)
    plan["status"] = "COMPLETED"
    plan["completed_at"] = clock
    db.commit(plan, snap)

    if plan["plan_type"] == "RETROFIT" and plan["target_refrigerant_type_id"]:
        system["refrigerant_type_id"] = plan["target_refrigerant_type_id"]
        target_type = db.require("refrigerant_types", system["refrigerant_type_id"])
        from routes.systems import rederive
        rederive(system, target_type)
    for event in events:
        if event["status"] == "RETROFIT_MANDATED":
            event_snap = db.snapshot(event)
            event["status"] = "VERIFIED_CLOSED"
            event["closed_at"] = clock
            db.commit(event, event_snap)
    system["retrofit_due_on"] = None
    ledger.recompute_charge(system)
    ledger.recompute_leak_rate(system)
    posture.system_cascade(system)
    return response.ok(plan)
