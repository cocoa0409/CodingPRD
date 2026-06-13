"""Applications: create, get, list, submit, approve, reject — PRD §3.1, §3.3."""
from flask import Blueprint, request, g

from db import db
from middleware import require_roles
from response import object_response
from models import stamp_new, touch, public
from services.validate import get_body, require_fields, require_enum
from services.resolve import get_application, get_customer, get_apy_tier_by_code
from services.application import (
    compute_kyc_risk, recompute_cip_status, open_account, KYC_APPROVAL_GATE,
)
from routes.common import paged_list
import errors
from errors import ApiError

bp = Blueprint("applications", __name__)

PRODUCT_TYPES = {"CHECKING", "SAVINGS"}
REJECTION_REASONS = {"CIP_MISMATCH", "SANCTIONS_HIT", "UNDERAGE", "DUPLICATE"}


def serialize_application(a):
    return public(a)


@bp.route("/applications", methods=["POST"])
@require_roles("Teller", "ComplianceOfficer")
def create_application():
    body = get_body()
    require_fields(body, "customer_id", "product_type", "requested_apy_tier_code")
    product_type = require_enum(body, "product_type", PRODUCT_TYPES)
    # Referenced customer must resolve (specialized not-found).
    get_customer(body["customer_id"], specialized=True)

    app_row = {
        "customer_id": body["customer_id"],
        "product_type": product_type,
        "requested_apy_tier_code": body["requested_apy_tier_code"],
        "submitted_by_user_id": None,
        "status": "DRAFT",
        "kyc_risk_score": None,
        "opened_account_id": None,
        "rejection_reason_code": None,
    }
    stamp_new(app_row)
    db.applications[app_row["id"]] = app_row
    return object_response(serialize_application(app_row), status=201)


@bp.route("/applications/<app_id>", methods=["GET"])
@require_roles("Teller", "ComplianceOfficer")
def get_one(app_id):
    a = get_application(app_id)
    return object_response(serialize_application(a))


@bp.route("/applications", methods=["GET"])
@require_roles("Teller", "ComplianceOfficer")
def list_applications():
    customer_id = request.args.get("customer_id")
    opened_account_id = request.args.get("opened_account_id")
    status = request.args.get("status")
    rows = list(db.applications.values())
    if customer_id is not None:
        rows = [a for a in rows if a["customer_id"] == customer_id]
    if opened_account_id is not None:
        rows = [a for a in rows if a["opened_account_id"] == opened_account_id]
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    return paged_list(rows)


@bp.route("/applications/<app_id>/submit", methods=["POST"])
@require_roles("Teller")
def submit(app_id):
    a = get_application(app_id)
    # State gate (priority 5).
    if a["status"] != "DRAFT":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Application is not in DRAFT")
    # Referenced customer must exist (specialized).
    customer = get_customer(a["customer_id"], specialized=True)

    a["kyc_risk_score"] = compute_kyc_risk(customer)
    a["submitted_by_user_id"] = g.user_id
    a["status"] = "SUBMITTED"
    touch(a)
    return object_response(serialize_application(a))


@bp.route("/applications/<app_id>/approve", methods=["POST"])
@require_roles("ComplianceOfficer")
def approve(app_id):
    a = get_application(app_id)
    # State gate (priority 5).
    if a["status"] != "SUBMITTED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Application is not SUBMITTED")
    # Segregation of duties (priority 6) precedes KYC gate (priority 7).
    if g.user_id == a["submitted_by_user_id"]:
        raise ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 409,
                       "Approver must differ from the submitter")
    # KYC gate (priority 7).
    if a["kyc_risk_score"] is not None and a["kyc_risk_score"] >= KYC_APPROVAL_GATE:
        raise ApiError(errors.ERR_KYC_RISK_TOO_HIGH, 409, "KYC risk score too high")
    # APY tier resolution for the product (specialized not-found).
    tier = get_apy_tier_by_code(a["requested_apy_tier_code"], a["product_type"])
    if tier is None:
        raise ApiError(errors.ERR_APY_TIER_NOT_FOUND, 404,
                       "requested_apy_tier_code does not resolve for this product")

    account = open_account(a)
    a["opened_account_id"] = account["id"]
    a["status"] = "APPROVED"
    touch(a)
    recompute_cip_status(a["customer_id"])
    return object_response(serialize_application(a))


@bp.route("/applications/<app_id>/reject", methods=["POST"])
@require_roles("ComplianceOfficer")
def reject(app_id):
    a = get_application(app_id)
    # State gate (priority 5).
    if a["status"] != "SUBMITTED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Application is not SUBMITTED")
    # Segregation of duties (priority 6).
    if g.user_id == a["submitted_by_user_id"]:
        raise ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 409,
                       "Rejecter must differ from the submitter")
    body = get_body()
    require_fields(body, "rejection_reason_code")
    reason = require_enum(body, "rejection_reason_code", REJECTION_REASONS)

    a["rejection_reason_code"] = reason
    a["status"] = "REJECTED"
    touch(a)
    recompute_cip_status(a["customer_id"])
    return object_response(serialize_application(a))
