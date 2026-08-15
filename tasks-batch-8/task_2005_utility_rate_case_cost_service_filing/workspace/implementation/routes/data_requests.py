"""DataRequest endpoints (PRD 3.4): issue, respond, object, rule, withdraw."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_FORBIDDEN_OWNERSHIP,
    ERR_INVALID_CASE_STATE,
    ERR_INVALID_REQUEST_STATE,
    ERR_DISCOVERY_WINDOW_CLOSED,
    ERR_ADJUSTMENT_NOT_IN_CASE,
    ERR_PARTY_NOT_IN_CASE,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, query_arg
from services.core import new_record, public, touch
from util import CLOCK, parse_datetime, plus_days_iso
from validate import (
    get_body,
    no_unknown_fields,
    opt_nullable_str,
    req_enum,
    req_str,
    require_fk,
    require_path_resource,
)

bp = Blueprint("data_requests", __name__)

_OPEN_STATES = ("ISSUED", "OBJECTED", "OVERDUE", "RESPOND_REQUIRED")


@bp.post("/data-requests")
def create_data_request():
    body = get_body()
    no_unknown_fields(body, {
        "rate_case_id", "subject", "body", "issuing_intervenor_id",
        "referenced_adjustment_id",
    })
    rate_case_id = req_str(body, "rate_case_id")
    subject = req_str(body, "subject")
    text = req_str(body, "body")
    issuing_intervenor_id = opt_nullable_str(body, "issuing_intervenor_id")
    referenced_adjustment_id = opt_nullable_str(body, "referenced_adjustment_id")
    caller = authorized(["IntervenorRep", "CommissionStaff"])
    # Role-derived issuer rules (shape-level, role-dependent)
    if caller.role == "IntervenorRep":
        if issuing_intervenor_id is None:
            raise_error(ERR_INVALID_REQUEST,
                        "issuing_intervenor_id is required for IntervenorRep callers")
        # Ownership (p3): must equal the caller's identity
        if issuing_intervenor_id != caller.user_id:
            raise_error(ERR_FORBIDDEN_OWNERSHIP,
                        "issuing_intervenor_id must equal X-User-ID")
        issuer_kind = "INTERVENOR"
    else:
        if issuing_intervenor_id is not None:
            raise_error(ERR_INVALID_REQUEST,
                        "issuing_intervenor_id must be absent for CommissionStaff callers")
        issuer_kind = "STAFF"
    # Existence (p5)
    case = require_fk("rate_cases", rate_case_id, "rate_case_id")
    intervenor = require_fk("intervenors", issuing_intervenor_id, "issuing_intervenor_id")
    adjustment = require_fk("adjustments", referenced_adjustment_id, "referenced_adjustment_id")
    # State (p6): case must be in DISCOVERY
    if case["status"] != "DISCOVERY":
        raise_error(ERR_INVALID_CASE_STATE, "data requests may be issued only in DISCOVERY")
    # Temporal (p8): within the discovery window (inclusive at the deadline)
    if case["discovery_close_at"] is not None and CLOCK.now() > parse_datetime(case["discovery_close_at"]):
        raise_error(ERR_DISCOVERY_WINDOW_CLOSED, "the discovery window has closed")
    # Referential (p9)
    if adjustment is not None and adjustment["rate_case_id"] != case["id"]:
        raise_error(ERR_ADJUSTMENT_NOT_IN_CASE,
                    "referenced_adjustment_id belongs to a different case")
    if intervenor is not None and intervenor["rate_case_id"] != case["id"]:
        raise_error(ERR_PARTY_NOT_IN_CASE,
                    "issuing_intervenor_id belongs to a different case")
    now = CLOCK.now()
    rec = new_record("data_requests", {
        "rate_case_id": rate_case_id,
        "issuer_kind": issuer_kind,
        "issuing_intervenor_id": issuing_intervenor_id,
        "subject": subject,
        "body": text,
        "referenced_adjustment_id": referenced_adjustment_id,
        "issued_at": CLOCK.now_iso(),
        "response_due_at": plus_days_iso(now, 10),
        "extended_due_at": None,
        "response_text": None,
        "objection_reason": None,
        "ruling": None,
        "status": "ISSUED",
    })
    return success_object(public(rec), status=201)


@bp.get("/data-requests")
def list_data_requests():
    filters = {
        "rate_case_id": query_arg("rate_case_id"),
        "issuing_intervenor_id": query_arg("issuing_intervenor_id"),
        "referenced_adjustment_id": query_arg("referenced_adjustment_id"),
        "status": query_arg("status"),
    }
    return list_response("data_requests", filters)


@bp.get("/data-requests/<request_id>")
def get_data_request(request_id):
    return get_one("data_requests", request_id)


def _leave_overdue(dr):
    if dr["status"] == "OVERDUE":
        case = db["rate_cases"].get(dr["rate_case_id"])
        if case is not None:
            case["overdue_data_request_count"] -= 1
            touch(case)


@bp.post("/data-requests/<request_id>/respond")
def respond_data_request(request_id):
    body = get_body()
    no_unknown_fields(body, {"response_text"})
    response_text = req_str(body, "response_text")
    authorized(["UtilityFiler"])
    dr = require_path_resource("data_requests", request_id)
    if dr["status"] not in ("ISSUED", "OVERDUE", "RESPOND_REQUIRED"):
        raise_error(ERR_INVALID_REQUEST_STATE,
                    "respond requires ISSUED, OVERDUE, or RESPOND_REQUIRED")
    _leave_overdue(dr)
    dr["response_text"] = response_text
    dr["status"] = "RESPONDED"
    touch(dr)
    return success_object(public(dr))


@bp.post("/data-requests/<request_id>/object")
def object_data_request(request_id):
    body = get_body()
    no_unknown_fields(body, {"objection_reason"})
    objection_reason = req_str(body, "objection_reason")
    authorized(["UtilityFiler"])
    dr = require_path_resource("data_requests", request_id)
    if dr["status"] != "ISSUED":
        raise_error(ERR_INVALID_REQUEST_STATE, "object requires ISSUED")
    dr["objection_reason"] = objection_reason
    dr["status"] = "OBJECTED"
    touch(dr)
    return success_object(public(dr))


@bp.post("/data-requests/<request_id>/rule")
def rule_data_request(request_id):
    body = get_body()
    no_unknown_fields(body, {"ruling"})
    ruling = req_enum(body, "ruling", ("SUSTAINED", "OVERRULED"))
    authorized(["ALJ"])
    dr = require_path_resource("data_requests", request_id)
    if dr["status"] != "OBJECTED":
        raise_error(ERR_INVALID_REQUEST_STATE, "rule requires OBJECTED")
    dr["ruling"] = ruling
    if ruling == "SUSTAINED":
        dr["status"] = "CLOSED"
    else:
        dr["status"] = "RESPOND_REQUIRED"
        dr["extended_due_at"] = plus_days_iso(CLOCK.now(), 5)
    touch(dr)
    return success_object(public(dr))


@bp.post("/data-requests/<request_id>/withdraw")
def withdraw_data_request(request_id):
    body = get_body()
    no_unknown_fields(body, set())
    caller = authorized(["IntervenorRep", "CommissionStaff"])
    dr = require_path_resource("data_requests", request_id)
    # Ownership (p3): the issuing party only
    if dr["issuer_kind"] == "INTERVENOR":
        if caller.role != "IntervenorRep" or caller.user_id != dr["issuing_intervenor_id"]:
            raise_error(ERR_FORBIDDEN_OWNERSHIP,
                        "only the issuing intervenor may withdraw the request")
    else:  # STAFF
        if caller.role != "CommissionStaff":
            raise_error(ERR_FORBIDDEN_OWNERSHIP,
                        "only CommissionStaff may withdraw a staff-issued request")
    if dr["status"] not in _OPEN_STATES:
        raise_error(ERR_INVALID_REQUEST_STATE,
                    "withdraw requires ISSUED, OBJECTED, OVERDUE, or RESPOND_REQUIRED")
    _leave_overdue(dr)
    dr["status"] = "WITHDRAWN"
    touch(dr)
    return success_object(public(dr))
