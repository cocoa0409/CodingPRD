"""BackgroundCheckOrder endpoints (and its sub-resources: verifications, risk-score, adverse-action)."""

from flask import Blueprint, request

from db import db
from errors import raise_api
from middleware import require_roles
from response import success, list_success
from util import (
    stamp_common_create, stamp_update, get_order, get_application, get_consent,
    get_json_body, require_fields, check_occ, parse_pagination, page, sort_by_created_at,
)
from services.audit import append_audit
from services.engine import compute_risk_score, adverse_action_for_order, verifications_for_order


bp = Blueprint("orders", __name__)


def _serialize(o):
    return {
        "id": o["id"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
        "application_id": o["application_id"],
        "consent_id": o["consent_id"],
        "ordered_at": o["ordered_at"],
        "status": o["status"],
        "overall_result": o.get("overall_result"),
    }


@bp.route("/api/v1/background-check-orders", methods=["POST"])
@require_roles("Recruiter")
def create_order(_user_id, _role):
    body = get_json_body()
    require_fields(body, "application_id", "consent_id", "expected_application_version")
    application_id = body["application_id"]
    consent_id = body["consent_id"]
    # Existence checks (priority 40)
    application = get_application(application_id)
    consent = get_consent(consent_id)
    # OCC (priority 55)
    check_occ(body, "expected_application_version", application["version"])
    # Ban-the-Box gate (priority 60)
    jurisdiction = db.jurisdictions[application["jurisdiction_id"]]
    if jurisdiction.get("ban_the_box_enabled") and application["status"] != "CONDITIONAL_OFFER":
        raise_api(
            "ERR_BAN_THE_BOX_PREMATURE_INQUIRY",
            "Background check requires CONDITIONAL_OFFER in ban-the-box jurisdictions",
        )
    # Application must at minimum be SUBMITTED or CONDITIONAL_OFFER
    if application["status"] not in {"SUBMITTED", "CONDITIONAL_OFFER"}:
        raise_api("ERR_INVALID_STATE", f"Application.status={application['status']} not orderable")
    # Consent must be GRANTED and tied to the same application
    if consent["consent_status"] != "GRANTED":
        raise_api("ERR_CONSENT_NOT_GRANTED", "Consent must be GRANTED")
    if consent["application_id"] != application_id:
        raise_api("ERR_CONSENT_NOT_GRANTED", "Consent belongs to a different application")
    # Also check applicant chain matches (defensive — consent.application_id == application_id already)
    consent_app = db.applications.get(consent["application_id"])
    if consent_app is None or consent_app["applicant_id"] != application["applicant_id"]:
        raise_api("ERR_CONSENT_NOT_GRANTED", "Consent applicant does not match application applicant")

    now_iso = db.current_utc_iso()
    o = {
        "application_id": application_id,
        "consent_id": consent_id,
        "ordered_at": now_iso,
        "status": "PENDING",
        "overall_result": None,
    }
    stamp_common_create(o)
    db.orders[o["id"]] = o
    # Side effect: Application.version += 1
    stamp_update(application)
    append_audit(_role, _user_id, "ORDER_CREATE", "BackgroundCheckOrder", o["id"], None, "PENDING")
    return success(_serialize(o), 201)


@bp.route("/api/v1/background-check-orders/<oid>", methods=["GET"])
@require_roles("Recruiter", "ComplianceOfficer", "Applicant", "VerificationProvider")
def get_order_route(oid, _user_id, _role):
    o = get_order(oid)
    return success(_serialize(o))


@bp.route("/api/v1/background-check-orders", methods=["GET"])
@require_roles("Recruiter", "ComplianceOfficer", "Applicant")
def list_orders(_user_id, _role):
    limit, offset = parse_pagination()
    application_id = request.args.get("application_id")
    consent_id = request.args.get("consent_id")
    status = request.args.get("status")
    items = list(db.orders.values())
    if application_id is not None:
        items = [o for o in items if o["application_id"] == application_id]
    if consent_id is not None:
        items = [o for o in items if o["consent_id"] == consent_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    items = sort_by_created_at(items)
    page_items, total = page(items, limit, offset)
    return list_success([_serialize(o) for o in page_items], limit, offset, total)


@bp.route("/api/v1/background-check-orders/<oid>/cancel", methods=["POST"])
@require_roles("Recruiter")
def cancel_order(oid, _user_id, _role):
    o = get_order(oid)
    body = get_json_body()
    if o["status"] != "PENDING":
        raise_api("ERR_INVALID_STATE", "Only PENDING orders can be cancelled")
    check_occ(body, "expected_background_check_order_version", o["version"])
    prior = o["status"]
    o["status"] = "CANCELLED"
    stamp_update(o)
    for v in db.verifications.values():
        if v["order_id"] == oid and v["status"] == "PENDING":
            v["status"] = "RESOLVED"
            v["result"] = None
            stamp_update(v)
    append_audit(_role, _user_id, "ORDER_CANCEL", "BackgroundCheckOrder", o["id"], prior, "CANCELLED")
    return success(_serialize(o))


@bp.route("/api/v1/background-check-orders/<oid>/risk-score", methods=["GET"])
@require_roles("Recruiter", "ComplianceOfficer")
def order_risk_score(oid, _user_id, _role):
    get_order(oid)
    return success(compute_risk_score(oid))
