"""PlanOffering + PlanTier catalog endpoints (PRD §3.2)."""
from __future__ import annotations

from flask import Blueprint, request

import db
import errors as E
from middleware import (
    authenticate, authorize,
    BENEFITS_ADMIN, PAYROLL_OFFICER, COMPLIANCE_OFFICER, DEPENDENT_VERIFIER,
)
import response
from services import common as C
from routes._helpers import get_or_404

bp = Blueprint("catalog", __name__)

ALL_ROLES = {BENEFITS_ADMIN, PAYROLL_OFFICER, COMPLIANCE_OFFICER, DEPENDENT_VERIFIER}

BENEFIT_TYPES = {"MEDICAL", "DENTAL", "VISION", "VOLUNTARY_LIFE"}
COVERAGE_LEVELS = {
    "EMPLOYEE_ONLY", "EMPLOYEE_PLUS_SPOUSE",
    "EMPLOYEE_PLUS_CHILDREN", "EMPLOYEE_PLUS_FAMILY",
}


# ---------------------------------------------------------------------------
# PlanOffering
# ---------------------------------------------------------------------------
@bp.route("/plan-offerings", methods=["POST"])
def create_plan_offering():
    role = authenticate()
    authorize(role, {BENEFITS_ADMIN})
    body = C.get_body()
    C.require_fields(body, ["benefit_type", "name"])
    benefit_type = C.require_enum(body, "benefit_type", BENEFIT_TYPES)
    name = C.require_str(body, "name")

    requires_eoi = body.get("requires_eoi", False)
    if requires_eoi is None:
        requires_eoi = False
    if not C.is_bool(requires_eoi):
        raise E.invalid_request("requires_eoi must be a boolean")

    gi = body.get("guaranteed_issue_amount_cents", 0)
    if gi is None:
        gi = 0
    if not C.is_int(gi) or gi < 0:
        raise E.invalid_request("guaranteed_issue_amount_cents must be a non-negative integer")

    off = C.new_common_fields()
    off.update({
        "benefit_type": benefit_type,
        "name": name,
        "requires_eoi": requires_eoi,
        "guaranteed_issue_amount_cents": gi,
        "status": "ACTIVE",
    })
    db.plan_offerings[off["id"]] = off
    return response.ok_object(C.serialize(off), 201)


@bp.route("/plan-offerings/<off_id>", methods=["GET"])
def get_plan_offering(off_id):
    role = authenticate()
    authorize(role, ALL_ROLES)
    off = get_or_404(db.plan_offerings, off_id, "PlanOffering")
    return response.ok_object(C.serialize(off), 200)


@bp.route("/plan-offerings/<off_id>/archive", methods=["POST"])
def archive_plan_offering(off_id):
    role = authenticate()
    authorize(role, {BENEFITS_ADMIN})
    off = get_or_404(db.plan_offerings, off_id, "PlanOffering")
    if off["status"] != "ACTIVE":
        raise E.invalid_state("PlanOffering must be ACTIVE to archive")
    off["status"] = "ARCHIVED"
    C.touch(off)
    return response.ok_object(C.serialize(off), 200)


# ---------------------------------------------------------------------------
# PlanTier
# ---------------------------------------------------------------------------
@bp.route("/plan-tiers", methods=["POST"])
def create_plan_tier():
    role = authenticate()
    authorize(role, {BENEFITS_ADMIN})
    body = C.get_body()
    C.require_fields(body, [
        "plan_offering_id", "coverage_level",
        "monthly_premium_cents", "employer_contribution_pct",
    ])
    # Existence (priority 3): FK validated after path (no path here) before body shape.
    offering_id = body["plan_offering_id"]
    if not C.is_str(offering_id):
        raise E.invalid_request("plan_offering_id must be a string")
    off = get_or_404(db.plan_offerings, offering_id, "PlanOffering")

    coverage_level = C.require_enum(body, "coverage_level", COVERAGE_LEVELS)

    monthly_premium = C.require_int(body, "monthly_premium_cents")
    if monthly_premium <= 0:
        raise E.invalid_request("monthly_premium_cents must be a positive integer")

    pct = body.get("employer_contribution_pct")
    if not C.is_number(pct):
        raise E.invalid_request("employer_contribution_pct must be a number")
    if pct < 0 or pct > 1:
        raise E.invalid_request("employer_contribution_pct must be between 0.0 and 1.0")

    rate = body.get("rate_per_1000_monthly_cents", 0)
    if rate is None:
        rate = 0
    if not C.is_int(rate) or rate < 0:
        raise E.invalid_request("rate_per_1000_monthly_cents must be a non-negative integer")

    is_lowest = body.get("is_lowest_cost_self_only", False)
    if is_lowest is None:
        is_lowest = False
    if not C.is_bool(is_lowest):
        raise E.invalid_request("is_lowest_cost_self_only must be a boolean")

    tier = C.new_common_fields()
    tier.update({
        "plan_offering_id": offering_id,
        "coverage_level": coverage_level,
        "monthly_premium_cents": monthly_premium,
        "employer_contribution_pct": pct,
        "rate_per_1000_monthly_cents": rate,
        "is_lowest_cost_self_only": is_lowest,
    })
    db.plan_tiers[tier["id"]] = tier
    return response.ok_object(C.serialize(tier), 201)


@bp.route("/plan-tiers/<tier_id>", methods=["GET"])
def get_plan_tier(tier_id):
    role = authenticate()
    authorize(role, ALL_ROLES)
    tier = get_or_404(db.plan_tiers, tier_id, "PlanTier")
    return response.ok_object(C.serialize(tier), 200)


@bp.route("/plan-tiers", methods=["GET"])
def list_plan_tiers():
    role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = C.parse_pagination()
    plan_offering_id = request.args.get("plan_offering_id")
    items = list(db.plan_tiers.values())
    if plan_offering_id is not None:
        items = [t for t in items if t["plan_offering_id"] == plan_offering_id]
    items = C.order_by_created(items)
    page, total = C.paginate(items, limit, offset)
    return response.ok_array(C.serialize_list(page), limit, offset, total, 200)
