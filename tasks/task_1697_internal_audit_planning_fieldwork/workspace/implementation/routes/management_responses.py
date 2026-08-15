"""ManagementResponse endpoints (PRD 3.6): the management negotiation cycle;
creation bubbles the finding to UNDER_REVIEW, adjudication bubbles to
AGREED/REBUTTED with negotiation-round accounting."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_FINDING_NOT_AWAITING_RESPONSE,
    ERR_NEGOTIATION_ROUNDS_EXHAUSTED,
    ERR_RESPONSE_INVALID_STATE,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, query_str
from services.core import new_record, public, touch
from validate import (
    body_ref,
    check_unknown_fields,
    get_body,
    req_datetime,
    req_str,
    require_path,
)

bp = Blueprint("management_responses", __name__)

CREATE_FIELDS = {"finding_id", "response_text", "proposed_due_date"}
REBUT_FIELDS = {"rebuttal_note"}


@bp.post("/audit/management-responses")
def create_response():
    caller = authorized(["ManagementOwner"])
    body = get_body()
    # Stage 4: body FK existence
    body_ref(body, "finding_id", "findings")
    # Stage 5: shape
    check_unknown_fields(body, CREATE_FIELDS)
    finding_id = req_str(body, "finding_id")
    response_text = req_str(body, "response_text")
    proposed_due_date = req_datetime(body, "proposed_due_date")
    finding = db["findings"][finding_id]
    # Stage 7: the finding must be awaiting a response
    if finding["status"] not in ("PENDING_RESPONSE", "REBUTTED"):
        raise_error(ERR_FINDING_NOT_AWAITING_RESPONSE,
                    f"finding is {finding['status']}, not awaiting a response")
    # Exhaustion rule: at REBUTTED with rounds == 3 escalation is the only path
    if finding["status"] == "REBUTTED" and finding["negotiation_rounds"] >= 3:
        raise_error(ERR_NEGOTIATION_ROUNDS_EXHAUSTED,
                    "negotiation rounds exhausted; escalate instead")
    rec = new_record("management_responses", {
        "finding_id": finding_id,
        "responder_user_id": caller.user_id,
        "response_text": response_text,
        "proposed_due_date": proposed_due_date,
        "status": "SUBMITTED",
        "reviewed_by_user_id": None,
    })
    # Bubble up: PENDING_RESPONSE/REBUTTED -> UNDER_REVIEW (negotiation cycle)
    finding["status"] = "UNDER_REVIEW"
    touch(finding)
    return success_object(public(rec), status=201)


@bp.get("/audit/management-responses")
def list_responses():
    filters = {
        "finding_id": query_str("finding_id"),
        "status": query_str("status"),
    }
    return list_response("management_responses", filters)


@bp.get("/audit/management-responses/<rid>")
def get_response(rid):
    return get_one("management_responses", rid)


@bp.post("/audit/management-responses/<rid>/accept")
def accept_response(rid):
    caller = authorized(["AuditManager"])
    resp = require_path("management_responses", rid)
    # Stage 7: must be SUBMITTED
    if resp["status"] != "SUBMITTED":
        raise_error(ERR_RESPONSE_INVALID_STATE, "response is not SUBMITTED")
    resp["status"] = "ACCEPTED"
    resp["reviewed_by_user_id"] = caller.user_id
    touch(resp)
    # Bubble up: UNDER_REVIEW -> AGREED
    finding = db["findings"][resp["finding_id"]]
    finding["status"] = "AGREED"
    touch(finding)
    return success_object(public(resp))


@bp.post("/audit/management-responses/<rid>/rebut")
def rebut_response(rid):
    caller = authorized(["AuditManager"])
    resp = require_path("management_responses", rid)
    # Stage 5: shape (rebuttal_note required)
    body = get_body()
    check_unknown_fields(body, REBUT_FIELDS)
    req_str(body, "rebuttal_note")
    # Stage 7: must be SUBMITTED
    if resp["status"] != "SUBMITTED":
        raise_error(ERR_RESPONSE_INVALID_STATE, "response is not SUBMITTED")
    finding = db["findings"][resp["finding_id"]]
    # Stage 11: rebuttal allowed only while negotiation_rounds < 3
    if finding["negotiation_rounds"] >= 3:
        raise_error(ERR_NEGOTIATION_ROUNDS_EXHAUSTED,
                    "negotiation rounds exhausted; escalate instead")
    resp["status"] = "REBUTTED"
    resp["reviewed_by_user_id"] = caller.user_id
    touch(resp)
    # Bubble up: UNDER_REVIEW -> REBUTTED, round increments
    finding["status"] = "REBUTTED"
    finding["negotiation_rounds"] = finding["negotiation_rounds"] + 1
    touch(finding)
    return success_object(public(resp))
