"""AdverseAction endpoints (get, sub-resource, finalize)."""

from flask import Blueprint

from db import db, parse_iso
from errors import raise_api
from middleware import require_roles
from response import success, list_success
from util import (
    stamp_update, get_order, get_adverse_action,
    get_json_body, check_occ, parse_pagination, page, sort_by_created_at,
)
from services.audit import append_audit


bp = Blueprint("adverse_actions", __name__)


def _serialize(a):
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "order_id": a["order_id"],
        "status": a["status"],
        "pre_adverse_sent_at": a["pre_adverse_sent_at"],
        "earliest_final_at": a["earliest_final_at"],
        "finalized_at": a.get("finalized_at"),
        "finalized_by_user_id": a.get("finalized_by_user_id"),
        "dispute_reason": a.get("dispute_reason"),
    }


@bp.route("/api/v1/adverse-actions/<aid>", methods=["GET"])
@require_roles("Recruiter", "ComplianceOfficer", "Applicant")
def get_adverse_action_route(aid, _user_id, _role):
    a = get_adverse_action(aid)
    return success(_serialize(a))


@bp.route("/api/v1/background-check-orders/<oid>/adverse-action", methods=["GET"])
@require_roles("Recruiter", "ComplianceOfficer", "Applicant")
def list_adverse_action_for_order(oid, _user_id, _role):
    get_order(oid)
    limit, offset = parse_pagination()
    items = [a for a in db.adverse_actions.values() if a["order_id"] == oid]
    items = sort_by_created_at(items)
    page_items, total = page(items, limit, offset)
    return list_success([_serialize(a) for a in page_items], limit, offset, total)


@bp.route("/api/v1/adverse-actions/<aid>/finalize", methods=["POST"])
@require_roles("ComplianceOfficer")
def finalize_adverse_action(aid, _user_id, _role):
    a = get_adverse_action(aid)
    body = get_json_body()
    # State priority 50
    if a["status"] != "PRE_ADVERSE_SENT":
        raise_api("ERR_INVALID_STATE", "AdverseAction must be PRE_ADVERSE_SENT to finalize")
    # OCC priority 55
    check_occ(body, "expected_adverse_action_version", a["version"])
    # Segregation of duties (priority 70) — BEFORE waiting period check per scaffold order
    order = db.orders.get(a["order_id"])
    if order is None:
        raise_api("ERR_NOT_FOUND", "Parent order not found")
    application = db.applications.get(order["application_id"])
    if application is None:
        raise_api("ERR_NOT_FOUND", "Parent application not found")
    recruiter_user_id = db.conditional_offer_actor.get(application["id"])
    if recruiter_user_id is not None and recruiter_user_id == _user_id:
        raise_api(
            "ERR_SEGREGATION_OF_DUTIES",
            "Finalizing operator must differ from the recruiter who extended the conditional offer",
        )
    # Waiting period (priority 75)
    earliest = parse_iso(a["earliest_final_at"])
    if db.current_utc_dt() < earliest:
        raise_api(
            "ERR_WAITING_PERIOD_NOT_ELAPSED",
            "FCRA waiting period has not elapsed",
        )
    # Parent order must be COMPLETE + CONSIDER
    if order["status"] != "COMPLETE" or order.get("overall_result") != "CONSIDER":
        raise_api("ERR_INVALID_STATE", "Parent order must be COMPLETE with overall_result=CONSIDER")
    prior = a["status"]
    a["status"] = "FINALIZED"
    a["finalized_at"] = db.current_utc_iso()
    a["finalized_by_user_id"] = _user_id
    stamp_update(a)
    # Cascade: Application -> REJECTED
    app_prior = application["status"]
    application["status"] = "REJECTED"
    stamp_update(application)
    append_audit(_role, _user_id, "FINAL_ADVERSE_ISSUE", "AdverseAction", a["id"], prior, "FINALIZED")
    append_audit(_role, _user_id, "APPLICATION_REJECTED", "Application", application["id"], app_prior, "REJECTED")
    return success(_serialize(a))
