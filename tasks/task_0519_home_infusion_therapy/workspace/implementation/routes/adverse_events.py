"""AdverseEvent routes (PRD §3.9/§3.10/§3.11)."""
from flask import Blueprint, request

import errors
import helpers
from db import db, stamp_create, touch
from middleware import require
from response import object_response, array_response
from services import calculations as calc
from services import workflow

bp = Blueprint("adverse_events", __name__)

SEVERITY_GRADES = {1, 2, 3, 4}
VITAL_VALUES = {0, 1}
DISPOSITIONS = {"RESUME", "DISCONTINUE"}
READ_ROLES = ["VisitingNurse", "MedicalDirector", "Pharmacist"]


@bp.route("/adverse-events", methods=["POST"])
def report_event():
    user_id, role = require(["VisitingNurse", "MedicalDirector"])
    body = helpers.get_body()
    # existence (3) before other body validity (4) per PRD §2.8
    order_id = helpers.as_str(body, "order_id")
    visit_id = helpers.as_str(body, "visit_id", required=False, default=None)
    if order_id not in db.infusion_orders:
        raise errors.not_found("Infusion order not found")
    if visit_id is not None and visit_id not in db.nursing_visits:
        raise errors.not_found("Nursing visit not found")

    severity_grade = helpers.as_int(body, "severity_grade")
    reaction_count = helpers.as_int(body, "reaction_count")
    vital_instability = helpers.as_int(body, "vital_instability")
    if severity_grade not in SEVERITY_GRADES:
        raise errors.invalid_request("severity_grade must be one of {1,2,3,4}")
    if reaction_count < 0:
        raise errors.invalid_request("reaction_count must be >= 0")
    if vital_instability not in VITAL_VALUES:
        raise errors.invalid_request("vital_instability must be 0 or 1")

    score = calc.ae_severity_score(severity_grade, reaction_count, vital_instability)

    event = stamp_create({
        "order_id": order_id,
        "visit_id": visit_id,
        "severity_grade": severity_grade,
        "reaction_count": reaction_count,
        "vital_instability": vital_instability,
        "severity_score": score,
        "reported_by_role": role,
        "reported_by_user_id": user_id,
        "status": "REPORTED",
    })
    db.adverse_events[event["id"]] = event

    # Auto-hold cascade when severity_score >= AE_HOLD_THRESHOLD (PRD §3.9).
    order = db.infusion_orders[order_id]
    if score >= calc.AE_HOLD_THRESHOLD and order["status"] in ("RELEASED", "ACTIVE"):
        workflow.hold_order(order, "ADVERSE_EVENT")

    return object_response(event, 201)


@bp.route("/adverse-events/<id>", methods=["GET"])
def get_event(id):
    require(READ_ROLES)
    event = db.adverse_events.get(id)
    if event is None:
        raise errors.not_found("Adverse event not found")
    return object_response(event, 200)


@bp.route("/adverse-events", methods=["GET"])
def list_events():
    require(READ_ROLES)
    limit, offset = helpers.pagination_params()
    items = list(db.adverse_events.values())
    order_id = request.args.get("order_id")
    visit_id = request.args.get("visit_id")
    if order_id is not None:
        items = [e for e in items if e["order_id"] == order_id]
    if visit_id is not None:
        items = [e for e in items if e["visit_id"] == visit_id]
    items = helpers.sort_by_created(items)
    window, total, has_more = helpers.paginate(items, limit, offset)
    return array_response(window, limit, offset, total, has_more, 200)


@bp.route("/adverse-events/<id>/adjudicate", methods=["POST"])
def adjudicate_event(id):
    user_id, role = require(["MedicalDirector"])
    event = db.adverse_events.get(id)
    if event is None:
        raise errors.not_found("Adverse event not found")
    body = helpers.get_body()
    disposition = helpers.as_enum(body, "disposition", DISPOSITIONS)

    # (5) state legality
    if event["status"] != "REPORTED":
        raise errors.invalid_state("Adverse event is not in REPORTED state")
    order = db.infusion_orders.get(event["order_id"])
    if order is None or order["status"] != "ON_HOLD":
        raise errors.invalid_state("Order is not in ON_HOLD state")

    # (6) segregation of duties: adjudicating X-User-ID must differ from reporter.
    if user_id == event["reported_by_user_id"]:
        raise errors.ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 403,
                              "Cannot adjudicate an event you reported")

    if disposition == "RESUME":
        order["status"] = "ACTIVE"
        order["hold_reason"] = None
        touch(order)
        event["status"] = "ADJUDICATED"
        touch(event)
    else:  # DISCONTINUE
        event["status"] = "ADJUDICATED"
        touch(event)
        workflow.discontinue_cascade(order)

    return object_response(event, 200)
