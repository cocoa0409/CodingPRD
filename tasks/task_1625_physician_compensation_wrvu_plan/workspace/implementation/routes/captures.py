"""ProductionCapture endpoints (PRD 3.4)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_AGREEMENT_NOT_EFFECTIVE,
    ERR_COMPLIANCE_HOLD, ERR_PERIOD_LOCKED, ERR_RATE_NOT_FOUND,
    ERR_NOT_OWN_RESOURCE,
)
from middleware import authorized
from response import success_object
from routes.helpers import list_response
from services.core import new_record, touch, public, compute_compliance_hold
from services.ledger import (
    resolve_rate, credit_capture, allocate_supervision, recompute_ytd,
)
from util import CLOCK
from validate import (
    get_body, req_str, req_int, req_date, opt_date, require_path_resource,
)

bp = Blueprint("captures", __name__)

CAPTURE_READ_ROLES = ["CompAnalyst", "CompCommittee", "Physician"]


def _capture_owner(capture):
    agr = db["physician_agreements"].get(capture["agreement_id"])
    return agr["physician_id"] if agr else None


def _check_capture_ownership(caller, capture):
    if caller.role == "Physician" and _capture_owner(capture) != caller.user_id:
        raise_error(ERR_NOT_OWN_RESOURCE, "a Physician may read only its own captures")


@bp.post("/physician-agreements/<rid>/production-captures")
def post_capture(rid):
    caller = authorized(["CompAnalyst"])
    agr = require_path_resource("physician_agreements", rid)
    # Guards in PRD 3.4 order: EFFECTIVE -> compliance hold -> shape -> period lock
    if agr["status"] != "EFFECTIVE":
        raise_error(ERR_AGREEMENT_NOT_EFFECTIVE,
                    "production capture posting requires an EFFECTIVE agreement")
    if compute_compliance_hold(agr):
        raise_error(ERR_COMPLIANCE_HOLD,
                    "agreement is under a compliance hold (stale FMV review)")
    body = get_body()
    cpt_code = req_str(body, "cpt_code")
    units = req_int(body, "units", minimum=1)
    service_date = req_date(body, "service_date")
    posting_date = opt_date(body, "posting_date")
    service_period = service_date[:7]
    for s in db["comp_statements"].values():
        if (s["agreement_id"] == agr["id"] and s["status"] == "FINALIZED"
                and f"{s['period_year']:04d}-{s['period_month']:02d}" == service_period):
            raise_error(ERR_PERIOD_LOCKED,
                        "service_date falls inside a FINALIZED statement period")
    rec = new_record("production_captures", {
        "agreement_id": agr["id"],
        "capture_kind": "CLINICAL",
        "cpt_code": cpt_code,
        "units": units,
        "service_date": service_date,
        "posting_date": posting_date or CLOCK.today().isoformat(),
        "wrvu_value_applied": None,
        "credited_wrvu": None,
        "credited_period": None,
        "capture_status": "POSTED",
        "credit_status": "UNCREDITED",
        "reversal_of_capture_id": None,
        "source_capture_id": None,
        "reversed_reason": None,
        "created_by_user_id": caller.user_id,
    })
    return success_object(public(rec), status=201)


@bp.get("/physician-agreements/<rid>/production-captures")
def list_captures(rid):
    caller = authorized(CAPTURE_READ_ROLES)
    agr = db["physician_agreements"].get(rid)
    if agr is not None and caller.role == "Physician" and agr["physician_id"] != caller.user_id:
        raise_error(ERR_NOT_OWN_RESOURCE, "a Physician may read only its own captures")
    if agr is None:
        raise_error(ERR_NOT_FOUND, f"agreement not found: {rid}")
    filters = {"agreement_id": rid, "credit_status": request.args.get("credit_status")}
    return list_response("production_captures", filters)


@bp.get("/production-captures/<rid>")
def get_capture(rid):
    caller = authorized(CAPTURE_READ_ROLES)
    rec = db["production_captures"].get(rid)
    if rec is not None:
        _check_capture_ownership(caller, rec)
    if rec is None:
        raise_error(ERR_NOT_FOUND, f"capture not found: {rid}")
    return success_object(public(rec))


@bp.get("/production-captures/<rid>/corrections")
def list_corrections(rid):
    caller = authorized(CAPTURE_READ_ROLES)
    rec = db["production_captures"].get(rid)
    if rec is not None:
        _check_capture_ownership(caller, rec)
    if rec is None:
        raise_error(ERR_NOT_FOUND, f"capture not found: {rid}")
    return list_response("production_captures", {"reversal_of_capture_id": rid})


@bp.get("/production-captures/<rid>/supervision-credits")
def list_supervision_credits(rid):
    caller = authorized(CAPTURE_READ_ROLES)
    rec = db["production_captures"].get(rid)
    if rec is not None:
        _check_capture_ownership(caller, rec)
    if rec is None:
        raise_error(ERR_NOT_FOUND, f"capture not found: {rid}")
    return list_response("production_captures", {"source_capture_id": rid})


@bp.get("/production-captures/<rid>/disputes")
def list_capture_disputes(rid):
    caller = authorized(CAPTURE_READ_ROLES)
    rec = db["production_captures"].get(rid)
    if rec is not None:
        _check_capture_ownership(caller, rec)
    if rec is None:
        raise_error(ERR_NOT_FOUND, f"capture not found: {rid}")
    return list_response("disputes", {"subject_capture_id": rid})


@bp.post("/production-captures/<rid>/validate")
def validate_capture(rid):
    authorized(["CompAnalyst"])
    cap = require_path_resource("production_captures", rid)
    if not (cap["capture_status"] == "POSTED" and cap["credit_status"] == "UNCREDITED"):
        raise_error(ERR_INVALID_STATE,
                    "validate requires capture_status POSTED and credit_status UNCREDITED")
    agr = db["physician_agreements"][cap["agreement_id"]]
    if compute_compliance_hold(agr):
        raise_error(ERR_COMPLIANCE_HOLD,
                    "agreement is under a compliance hold (stale FMV review)")
    plan = db["comp_plans"][agr["plan_id"]]
    rate = resolve_rate(plan["id"], cap["cpt_code"], cap["service_date"])
    if rate is None:
        raise_error(ERR_RATE_NOT_FOUND,
                    "no CptRate row covers this CPT code on the service date")
    credit_capture(cap, agr, rate["wrvu_value"])
    touch("production_captures", cap)
    recompute_ytd(agr)
    touch("physician_agreements", agr)
    allocate_supervision(cap, agr)
    return success_object(public(cap))


@bp.post("/production-captures/<rid>/void")
def void_capture(rid):
    authorized(["CompAnalyst"])
    cap = require_path_resource("production_captures", rid)
    if not (cap["capture_status"] == "POSTED" and cap["credit_status"] == "UNCREDITED"):
        raise_error(ERR_INVALID_STATE,
                    "void requires capture_status POSTED and credit_status UNCREDITED")
    cap["capture_status"] = "VOIDED"
    touch("production_captures", cap)
    return success_object(public(cap))
