"""Verification endpoints (create under order, report, dispute, resolve)."""

from flask import Blueprint

from db import db
from errors import raise_api
from middleware import require_roles
from response import success, list_success
from util import (
    stamp_common_create, stamp_update, get_order, get_verification,
    get_json_body, require_fields, check_occ, parse_pagination, page, sort_by_created_at,
)
from services.audit import append_audit
from services.engine import (
    recompute_order_posture_after_report, recompute_order_posture_after_resolve,
    adverse_action_for_order, verifications_for_order,
)


bp = Blueprint("verifications", __name__)

VERIFICATION_TYPES = {"CRIMINAL", "MVR", "EDUCATION"}


def _serialize(v):
    return {
        "id": v["id"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
        "order_id": v["order_id"],
        "verification_type": v["verification_type"],
        "status": v["status"],
        "result": v.get("result"),
        "report_payload": v.get("report_payload"),
        "reported_at": v.get("reported_at"),
        "disputed_at": v.get("disputed_at"),
    }


@bp.route("/api/v1/background-check-orders/<oid>/verifications", methods=["POST"])
@require_roles("Recruiter")
def create_verification(oid, _user_id, _role):
    order = get_order(oid)
    body = get_json_body()
    require_fields(body, "verification_type")
    vtype = body["verification_type"]
    if vtype not in VERIFICATION_TYPES:
        raise_api("ERR_INVALID_REQUEST", f"verification_type must be one of {sorted(VERIFICATION_TYPES)}")
    # Order should allow children — only PENDING accepts new verifications
    if order["status"] != "PENDING":
        raise_api("ERR_INVALID_STATE", "Verifications can only be created on PENDING orders")
    # Unique within order
    for v in db.verifications.values():
        if v["order_id"] == oid and v["verification_type"] == vtype:
            raise_api("ERR_DUPLICATE_VERIFICATION_TYPE", f"{vtype} already exists for this order")
    v = {
        "order_id": oid,
        "verification_type": vtype,
        "status": "PENDING",
        "result": None,
        "report_payload": None,
        "reported_at": None,
        "disputed_at": None,
    }
    stamp_common_create(v)
    db.verifications[v["id"]] = v
    return success(_serialize(v), 201)


@bp.route("/api/v1/verifications/<vid>", methods=["GET"])
@require_roles("Recruiter", "ComplianceOfficer", "VerificationProvider", "Applicant")
def get_verification_route(vid, _user_id, _role):
    v = get_verification(vid)
    return success(_serialize(v))


@bp.route("/api/v1/background-check-orders/<oid>/verifications", methods=["GET"])
@require_roles("Recruiter", "ComplianceOfficer", "VerificationProvider", "Applicant")
def list_verifications_for_order(oid, _user_id, _role):
    get_order(oid)
    limit, offset = parse_pagination()
    items = [v for v in db.verifications.values() if v["order_id"] == oid]
    items = sort_by_created_at(items)
    page_items, total = page(items, limit, offset)
    return list_success([_serialize(v) for v in page_items], limit, offset, total)


@bp.route("/api/v1/verifications/<vid>/report", methods=["POST"])
@require_roles("VerificationProvider")
def report_verification(vid, _user_id, _role):
    v = get_verification(vid)
    body = get_json_body()
    require_fields(body, "result", "report_payload", "expected_verification_version")
    # State priority 50
    if v["status"] != "PENDING":
        raise_api("ERR_INVALID_STATE", "Verification must be PENDING to be reported")
    order = db.orders.get(v["order_id"])
    if order is None or order["status"] not in {"PENDING", "IN_REVIEW"}:
        raise_api("ERR_INVALID_STATE", "Parent order must be PENDING or IN_REVIEW")
    # OCC
    check_occ(body, "expected_verification_version", v["version"])
    result = body["result"]
    if result not in {"PASS", "FAIL"}:
        raise_api("ERR_INVALID_REQUEST", "result must be PASS or FAIL")
    report_payload = body["report_payload"]
    if not isinstance(report_payload, dict):
        raise_api("ERR_INVALID_REQUEST", "report_payload must be a JSON object")
    prior = v["status"]
    v["status"] = "REPORTED"
    v["result"] = result
    v["report_payload"] = report_payload
    v["reported_at"] = db.current_utc_iso()
    stamp_update(v)
    append_audit(_role, _user_id, "VERIFICATION_REPORT", "Verification", v["id"], prior, v["status"])
    # Recompute parent posture
    recompute_order_posture_after_report(order, _role, _user_id, just_reported_id=v["id"])
    return success(_serialize(v))


@bp.route("/api/v1/verifications/<vid>/dispute", methods=["POST"])
@require_roles("Applicant")
def dispute_verification(vid, _user_id, _role):
    v = get_verification(vid)
    body = get_json_body()
    require_fields(body, "dispute_reason", "expected_verification_version")
    if v["status"] != "REPORTED":
        raise_api("ERR_INVALID_STATE", "Verification must be REPORTED to be disputed")
    order = db.orders.get(v["order_id"])
    if order is None or order["status"] not in {"IN_REVIEW", "COMPLETE"}:
        raise_api("ERR_INVALID_STATE", "Parent order must be IN_REVIEW or COMPLETE")
    aa = adverse_action_for_order(order["id"])
    if aa is not None and aa["status"] != "PRE_ADVERSE_SENT":
        raise_api("ERR_INVALID_STATE", "Cannot dispute after AdverseAction left PRE_ADVERSE_SENT")
    check_occ(body, "expected_verification_version", v["version"])
    dispute_reason = body["dispute_reason"]
    if not isinstance(dispute_reason, str) or not dispute_reason.strip():
        raise_api("ERR_INVALID_REQUEST", "dispute_reason must be a non-empty string")
    prior = v["status"]
    v["status"] = "DISPUTED"
    v["disputed_at"] = db.current_utc_iso()
    stamp_update(v)
    # Cascade AdverseAction PRE_ADVERSE_SENT -> DISPUTED
    if aa is not None and aa["status"] == "PRE_ADVERSE_SENT":
        aa["status"] = "DISPUTED"
        aa["dispute_reason"] = dispute_reason
        stamp_update(aa)
    append_audit(_role, _user_id, "VERIFICATION_DISPUTE", "Verification", v["id"], prior, v["status"])
    return success(_serialize(v))


@bp.route("/api/v1/verifications/<vid>/resolve", methods=["POST"])
@require_roles("VerificationProvider")
def resolve_verification(vid, _user_id, _role):
    v = get_verification(vid)
    body = get_json_body()
    require_fields(body, "new_result", "expected_verification_version")
    if v["status"] != "DISPUTED":
        raise_api("ERR_INVALID_STATE", "Verification must be DISPUTED to resolve")
    check_occ(body, "expected_verification_version", v["version"])
    new_result = body["new_result"]
    if new_result not in {"PASS", "FAIL"}:
        raise_api("ERR_INVALID_REQUEST", "new_result must be PASS or FAIL")
    prior = v["status"]
    v["status"] = "RESOLVED"
    v["result"] = new_result
    stamp_update(v)
    order = db.orders.get(v["order_id"])
    recompute_order_posture_after_resolve(order)
    append_audit(_role, _user_id, "VERIFICATION_RESOLVE", "Verification", v["id"], prior, v["status"])
    return success(_serialize(v))
