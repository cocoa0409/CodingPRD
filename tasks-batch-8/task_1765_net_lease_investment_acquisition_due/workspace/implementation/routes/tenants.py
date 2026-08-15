"""Tenant registration and credit assessment (PRD §3.1)."""

from flask import Blueprint

import db
from errors import ApiError
from middleware import bump, require_role
from response import created, ok, ok_list
from routes.common import body, opt_bool, req_enum, req_int, req_str
from services import domain

bp = Blueprint("tenants", __name__)

READ_ROLES = ("AcquisitionsAnalyst", "UnderwritingCommittee", "DueDiligenceOfficer",
              "PlatformAdmin")
CREDIT_RATINGS = {"INVESTMENT_GRADE", "NON_INVESTMENT_GRADE", "UNRATED"}


@bp.route("/tenants", methods=["POST"])
def create_tenant():
    require_role("AcquisitionsAnalyst")
    data = body()
    legal_name = req_str(data, "legal_name")
    credit_rating = req_enum(data, "credit_rating", CREDIT_RATINGS)
    credit_score = req_int(data, "credit_score")
    if credit_score < 0 or credit_score > 1000:
        raise ApiError("ERR_FIELD_CONSTRAINT_VIOLATION",
                       "credit_score must be between 0 and 1000", 400)
    annual_revenue = req_int(data, "annual_revenue_cents")
    is_guaranteed = opt_bool(data, "is_guaranteed", False)
    tenant = db.make_record({
        "legal_name": legal_name,
        "credit_rating": credit_rating,
        "credit_score": credit_score,
        "annual_revenue_cents": annual_revenue,
        "is_guaranteed": is_guaranteed,
        "credit_assessment_status": "PENDING",
    })
    db.stores["tenants"][tenant["id"]] = tenant
    return created(db.pub(tenant))


@bp.route("/tenants", methods=["GET"])
def list_tenants():
    require_role(*READ_ROLES)
    return ok_list(list(db.stores["tenants"].values()))


@bp.route("/tenants/<tenant_id>", methods=["GET"])
def get_tenant(tenant_id):
    require_role(*READ_ROLES)
    return ok(db.pub(domain.get_tenant(tenant_id)))


@bp.route("/tenants/<tenant_id>/analyze-credit", methods=["POST"])
def analyze_credit(tenant_id):
    require_role("UnderwritingCommittee")
    tenant = domain.get_tenant(tenant_id)
    if tenant["credit_assessment_status"] != "PENDING":
        raise ApiError("ERR_TENANT_CREDIT_INVALID_STATE",
                       "analyze-credit requires credit_assessment_status PENDING", 409)
    tenant["credit_assessment_status"] = "ANALYZED"
    bump(tenant)
    return ok(db.pub(tenant))


@bp.route("/tenants/<tenant_id>/approve-credit", methods=["POST"])
def approve_credit(tenant_id):
    require_role("UnderwritingCommittee")
    tenant = domain.get_tenant(tenant_id)
    if tenant["credit_assessment_status"] != "ANALYZED":
        raise ApiError("ERR_TENANT_CREDIT_INVALID_STATE",
                       "approve-credit requires credit_assessment_status ANALYZED", 409)
    if tenant["credit_rating"] == "UNRATED" and not tenant["is_guaranteed"]:
        raise ApiError("ERR_UNRATED_UNGUARANTEED_TENANT",
                       "UNRATED tenant without a parent guarantee cannot be credit-approved", 422)
    tenant["credit_assessment_status"] = "APPROVED"
    bump(tenant)
    return ok(db.pub(tenant))


@bp.route("/tenants/<tenant_id>/reject-credit", methods=["POST"])
def reject_credit(tenant_id):
    require_role("UnderwritingCommittee")
    tenant = domain.get_tenant(tenant_id)
    if tenant["credit_assessment_status"] != "ANALYZED":
        raise ApiError("ERR_TENANT_CREDIT_INVALID_STATE",
                       "reject-credit requires credit_assessment_status ANALYZED", 409)
    tenant["credit_assessment_status"] = "REJECTED"
    bump(tenant)
    return ok(db.pub(tenant))
