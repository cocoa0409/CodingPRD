"""Carrier loss-control recommendations (PRD 3.6): issue, respond, review."""

from flask import Blueprint, request

import db
from errors import ApiError
from middleware import auth, paginate, NON_CONTRACTOR_ROLES
from response import ok, ok_list
from services import core

bp = Blueprint("recommendations", __name__)


@bp.route("/safety/loss-control-recommendations", methods=["POST"])
def create_recommendation():
    auth(["CarrierConsultant"])
    body = core.body_json()
    program_id = core.req_str(body, "program_id")
    carrier_name = core.req_str(body, "carrier_name")
    priority = core.req_enum(body, "priority", ("LOW", "MEDIUM", "HIGH"))
    description = core.req_str(body, "description")
    due_date = core.req_datetime(body, "due_date")
    p = core.get_or_404("programs", program_id, "SafetyProgram")
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_NOT_ACTIVE", 409,
                       "Recommendations can be issued only against an ACTIVE program")
    r = core.stamp_new({
        "id": core.new_id(),
        "program_id": program_id,
        "carrier_name": carrier_name,
        "priority": priority,
        "description": description,
        "due_date": due_date,
        "response_text": None,
        "evidence_control_id": None,
        "responded_by": None,
        "reviewed_by": None,
        "review_note": None,
        "status": "ISSUED",
    })
    db.DB["recommendations"][r["id"]] = r
    return ok(core.recommendation_view(r), 201)


@bp.route("/safety/loss-control-recommendations", methods=["GET"])
def list_recommendations():
    auth(NON_CONTRACTOR_ROLES)
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    priority = request.args.get("priority")
    evidence_control_id = request.args.get("evidence_control_id")
    items = list(db.DB["recommendations"].values())
    if program_id is not None:
        items = [r for r in items if r["program_id"] == program_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if priority is not None:
        items = [r for r in items if r["priority"] == priority]
    if evidence_control_id is not None:
        items = [r for r in items if r["evidence_control_id"] == evidence_control_id]
    items = core.sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([core.recommendation_view(r) for r in page], total, limit, offset)


@bp.route("/safety/loss-control-recommendations/<rid>", methods=["GET"])
def get_recommendation(rid):
    auth(NON_CONTRACTOR_ROLES)
    r = core.get_or_404("recommendations", rid, "LossControlRecommendation")
    return ok(core.recommendation_view(r))


@bp.route("/safety/loss-control-recommendations/<rid>/respond", methods=["POST"])
def respond_recommendation(rid):
    user_id, _ = auth(["SafetyManager"])
    r = core.get_or_404("recommendations", rid, "LossControlRecommendation")
    body = core.body_json()
    response_text = core.req_str(body, "response_text")
    evidence_control_id = core.opt_str(body, "evidence_control_id", default=None)
    evidence = None
    if evidence_control_id is not None:
        evidence = core.get_or_404("controls", evidence_control_id, "ControlItem")
    if r["status"] not in ("ISSUED", "OVERDUE", "CARRIER_REJECTED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an ISSUED, OVERDUE, or CARRIER_REJECTED recommendation "
                       "can be answered")
    if evidence is not None and evidence["status"] != "VERIFIED":
        raise ApiError("ERR_CONTROL_NOT_VERIFIED", 422,
                       "evidence_control_id must reference a VERIFIED control")
    r["response_text"] = response_text
    if evidence_control_id is not None:
        r["evidence_control_id"] = evidence_control_id
    r["responded_by"] = user_id
    r["status"] = "RESPONSE_SUBMITTED"
    core.touch(r)
    return ok(core.recommendation_view(r))


@bp.route("/safety/loss-control-recommendations/<rid>/review-response",
          methods=["POST"])
def review_response(rid):
    user_id, _ = auth(["CarrierConsultant"])
    r = core.get_or_404("recommendations", rid, "LossControlRecommendation")
    body = core.body_json()
    outcome = core.req_enum(body, "outcome", ("ACCEPT", "REJECT"))
    review_note = core.opt_str(body, "review_note", default=None)
    if outcome == "REJECT" and review_note is None:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "A REJECT outcome requires a review_note")
    if r["status"] != "RESPONSE_SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a RESPONSE_SUBMITTED recommendation can be reviewed")
    if review_note is not None:
        r["review_note"] = review_note
    r["reviewed_by"] = user_id
    r["status"] = "CLOSED_ACCEPTED" if outcome == "ACCEPT" else "CARRIER_REJECTED"
    core.touch(r)
    return ok(core.recommendation_view(r))
