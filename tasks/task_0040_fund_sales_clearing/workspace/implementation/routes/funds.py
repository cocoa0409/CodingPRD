"""Fund product routes."""
from flask import Blueprint, g, request

import db
from db import funds, orders, stamp_create, stamp_update, public
from errors import err
from middleware import require_auth, get_pagination
from response import success, success_list
from services import audit
from services.util import get_body, require_field, check_version
from services.calculations import (
    validate_fee_tiers,
    confirmation_cycle_days_for_type,
)
from services.fund import (
    VALID_FUND_TYPES, VALID_RISK_RATING, FUND_CODE_RE,
    find_fund_by_code, cascade_suspend, stamp_confirmation_cycle,
)


bp = Blueprint("funds", __name__)


REQUIRED_FUND_FIELDS = [
    "fund_code", "fund_name", "fund_type", "risk_rating", "allowed_country_codes",
    "management_fee_bps_annual", "custodian_fee_bps_annual", "sales_service_fee_bps_annual",
    "subscription_fee_tiers", "redemption_fee_tiers", "conversion_fee_bps",
    "min_subscription_amount_cents", "min_redemption_shares",
]


@bp.route("/funds", methods=["POST"])
@require_auth(roles={"ProductOperator"})
def create_fund():
    body = get_body()
    for f in REQUIRED_FUND_FIELDS:
        if f not in body or body[f] is None:
            raise err("ERR_VALIDATION", f"Missing required field: {f}")

    if not isinstance(body["fund_code"], str) or not FUND_CODE_RE.match(body["fund_code"]):
        raise err("ERR_VALIDATION", "fund_code must match ^[0-9]{6}$")
    if find_fund_by_code(body["fund_code"]):
        raise err("ERR_VALIDATION", "fund_code must be unique")
    if body["fund_type"] not in VALID_FUND_TYPES:
        raise err("ERR_VALIDATION", "invalid fund_type")
    if body["risk_rating"] not in VALID_RISK_RATING:
        raise err("ERR_VALIDATION", "invalid risk_rating")
    acc = body["allowed_country_codes"]
    if not isinstance(acc, list):
        raise err("ERR_VALIDATION", "allowed_country_codes must be array")
    for c in acc:
        if not isinstance(c, str):
            raise err("ERR_VALIDATION", "country code must be string")

    if not validate_fee_tiers(body["subscription_fee_tiers"], body["redemption_fee_tiers"]):
        raise err("ERR_FEE_TIERS_INVALID", "Fee tiers invalid")

    fund = {
        "fund_code": body["fund_code"],
        "fund_name": body["fund_name"],
        "fund_type": body["fund_type"],
        "risk_rating": body["risk_rating"],
        "allowed_country_codes": list(acc),
        "status": "DRAFT",
        "shelf_review_actor_id": None,
        "shelf_creator_actor_id": None,
        "management_fee_bps_annual": body["management_fee_bps_annual"],
        "custodian_fee_bps_annual": body["custodian_fee_bps_annual"],
        "sales_service_fee_bps_annual": body["sales_service_fee_bps_annual"],
        "subscription_fee_tiers": body["subscription_fee_tiers"],
        "redemption_fee_tiers": body["redemption_fee_tiers"],
        "back_end_load_enabled": bool(body.get("back_end_load_enabled", False)),
        "conversion_fee_bps": body["conversion_fee_bps"],
        "large_redemption_threshold_pct_bps": body.get("large_redemption_threshold_pct_bps", 1000),
        "min_subscription_amount_cents": body["min_subscription_amount_cents"],
        "max_subscription_amount_cents": body.get("max_subscription_amount_cents"),
        "min_redemption_shares": body["min_redemption_shares"],
        "confirmation_cycle_days": None,
        "total_outstanding_shares": 0,
        "portfolio_market_value_cents": 0,
        "portfolio_accrued_income_cents": 0,
    }
    stamp_create(fund, common_fields=True)
    funds[fund["id"]] = fund
    return success(public(fund), 201)


@bp.route("/funds/<id>/submit-for-review", methods=["POST"])
@require_auth(roles={"ProductOperator"})
def submit_for_review(id):
    fund = funds.get(id)
    if not fund:
        raise err("ERR_NOT_FOUND", "Fund not found")
    body = get_body()
    check_version(body, fund)
    if fund["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", f"Fund.status is {fund['status']}, expected DRAFT")
    # Required fields are populated by virtue of POST /funds requiring them; nothing more here.
    fund["status"] = "UNDER_REVIEW"
    fund["shelf_creator_actor_id"] = g.user_id
    stamp_update(fund)
    audit.write(g.user_id, g.user_role, "FUND_SHELF_CHANGE", "Fund", fund["id"],
                "DRAFT", "UNDER_REVIEW", {})
    return success(public(fund), 200)


@bp.route("/funds/<id>/approve-shelf", methods=["POST"])
@require_auth(roles={"ComplianceReviewer"})
def approve_shelf(id):
    fund = funds.get(id)
    if not fund:
        raise err("ERR_NOT_FOUND", "Fund not found")
    body = get_body()
    check_version(body, fund)
    if fund["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", f"Fund.status is {fund['status']}, expected UNDER_REVIEW")
    if g.user_id == fund.get("shelf_creator_actor_id"):
        raise err("ERR_SOD_VIOLATION_SHELF",
                  "Approver must differ from creator")
    if not validate_fee_tiers(fund["subscription_fee_tiers"], fund["redemption_fee_tiers"]):
        raise err("ERR_FEE_TIERS_INVALID", "Fee tiers invalid")
    prev = fund["status"]
    fund["status"] = "ON_SHELF"
    fund["shelf_review_actor_id"] = g.user_id
    stamp_confirmation_cycle(fund)
    stamp_update(fund)
    audit.write(g.user_id, g.user_role, "FUND_SHELF_CHANGE", "Fund", fund["id"],
                prev, "ON_SHELF", {})
    return success(public(fund), 200)


@bp.route("/funds/<id>/reject-shelf", methods=["POST"])
@require_auth(roles={"ComplianceReviewer"})
def reject_shelf(id):
    fund = funds.get(id)
    if not fund:
        raise err("ERR_NOT_FOUND", "Fund not found")
    body = get_body()
    check_version(body, fund)
    if fund["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", f"Fund.status is {fund['status']}, expected UNDER_REVIEW")
    if g.user_id == fund.get("shelf_creator_actor_id"):
        raise err("ERR_SOD_VIOLATION_SHELF", "Rejecter must differ from creator")
    fund["status"] = "DRAFT"
    fund["shelf_creator_actor_id"] = None
    stamp_update(fund)
    audit.write(g.user_id, g.user_role, "FUND_SHELF_CHANGE", "Fund", fund["id"],
                "UNDER_REVIEW", "DRAFT", {})
    return success(public(fund), 200)


@bp.route("/funds/<id>/suspend", methods=["POST"])
@require_auth(roles={"ComplianceReviewer"})
def suspend_fund(id):
    fund = funds.get(id)
    if not fund:
        raise err("ERR_NOT_FOUND", "Fund not found")
    body = get_body()
    check_version(body, fund)
    if fund["status"] != "ON_SHELF":
        raise err("ERR_INVALID_STATE", f"Fund.status is {fund['status']}, expected ON_SHELF")
    fund["status"] = "SUSPENDED"
    stamp_update(fund)
    audit.write(g.user_id, g.user_role, "FUND_SHELF_CHANGE", "Fund", fund["id"],
                "ON_SHELF", "SUSPENDED", {})
    cascade_suspend(fund, g.user_id, g.user_role)
    return success(public(fund), 200)


@bp.route("/funds/<id>/resume", methods=["POST"])
@require_auth(roles={"ComplianceReviewer"})
def resume_fund(id):
    fund = funds.get(id)
    if not fund:
        raise err("ERR_NOT_FOUND", "Fund not found")
    body = get_body()
    check_version(body, fund)
    if fund["status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", f"Fund.status is {fund['status']}, expected SUSPENDED")
    fund["status"] = "ON_SHELF"
    stamp_update(fund)
    audit.write(g.user_id, g.user_role, "FUND_SHELF_CHANGE", "Fund", fund["id"],
                "SUSPENDED", "ON_SHELF", {})
    return success(public(fund), 200)


@bp.route("/funds/<id>/off-shelf", methods=["POST"])
@require_auth(roles={"ComplianceReviewer"})
def off_shelf(id):
    fund = funds.get(id)
    if not fund:
        raise err("ERR_NOT_FOUND", "Fund not found")
    body = get_body()
    check_version(body, fund)
    if fund["status"] not in ("ON_SHELF", "SUSPENDED"):
        raise err("ERR_INVALID_STATE",
                  f"Fund.status is {fund['status']}, expected ON_SHELF or SUSPENDED")
    if fund["total_outstanding_shares"] != 0:
        raise err("ERR_FUND_HAS_HOLDERS", "Fund has outstanding shares")
    prev = fund["status"]
    fund["status"] = "OFF_SHELF"
    stamp_update(fund)
    audit.write(g.user_id, g.user_role, "FUND_SHELF_CHANGE", "Fund", fund["id"],
                prev, "OFF_SHELF", {})
    return success(public(fund), 200)


@bp.route("/funds", methods=["GET"])
@require_auth(roles={"PlatformAdmin", "ComplianceReviewer", "ProductOperator",
                      "NavOperator", "ClearingOperator", "Investor"})
def list_funds():
    status_q = request.args.get("status")
    type_q = request.args.get("fund_type")
    items = list(funds.values())
    if status_q:
        items = [x for x in items if x["status"] == status_q]
    if type_q:
        items = [x for x in items if x["fund_type"] == type_q]
    items.sort(key=lambda x: (x["created_at"], x["_seq"]))
    limit, offset = get_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([public(x) for x in page], limit, offset, total, 200)


@bp.route("/funds/<id>", methods=["GET"])
@require_auth(roles={"PlatformAdmin", "ComplianceReviewer", "ProductOperator",
                      "NavOperator", "ClearingOperator", "Investor"})
def read_fund(id):
    fund = funds.get(id)
    if not fund:
        raise err("ERR_NOT_FOUND", "Fund not found")
    return success(public(fund), 200)
