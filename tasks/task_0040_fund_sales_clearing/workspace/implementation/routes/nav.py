"""NAV endpoints (publish, adjust, read)."""
from datetime import timedelta
from flask import Blueprint, g

import db
from db import (
    funds, nav_snapshots, dividend_plans, stamp_create, stamp_update, public,
)
from clock import now, iso, parse_iso, parse_iso_date, date_to_dt_utc
from errors import err
from middleware import require_auth
from response import success
from services import audit
from services.util import get_body, require_field, check_version
from services.calculations import compute_nav_components
from services.nav import find_nav_snapshot, confirmation_pass


bp = Blueprint("nav", __name__)


@bp.route("/funds/<id>/nav/publish", methods=["POST"])
@require_auth(roles={"NavOperator"})
def publish_nav(id):
    fund = funds.get(id)
    if not fund:
        raise err("ERR_NOT_FOUND", "Fund not found")
    body = get_body()
    require_field(body, "nav_date")
    require_field(body, "portfolio_market_value_cents")
    require_field(body, "portfolio_accrued_income_cents")

    # SoD: NAV publisher must differ from fund's shelf reviewer
    if g.user_id == fund.get("shelf_review_actor_id"):
        raise err("ERR_SOD_VIOLATION_NAV", "NAV publisher must differ from shelf reviewer")

    try:
        nav_date = parse_iso_date(body["nav_date"])
    except Exception:
        raise err("ERR_VALIDATION", "Invalid nav_date")

    # T+1 rule: clock >= nav_date + 1 day
    threshold = date_to_dt_utc(nav_date + timedelta(days=1))
    if now() < threshold:
        raise err("ERR_NAV_T_PLUS_1_NOT_ELAPSED", "Cannot publish NAV before T+1 boundary")

    pmv = body["portfolio_market_value_cents"]
    pai = body["portfolio_accrued_income_cents"]
    if not isinstance(pmv, int) or isinstance(pmv, bool):
        raise err("ERR_VALIDATION", "portfolio_market_value_cents must be int")
    if not isinstance(pai, int) or isinstance(pai, bool):
        raise err("ERR_VALIDATION", "portfolio_accrued_income_cents must be int")

    # Already published?
    existing = find_nav_snapshot(fund["id"], nav_date)
    if existing and existing["status"] in ("PUBLISHED", "ADJUSTED"):
        raise err("ERR_NAV_ALREADY_PUBLISHED", "NAV already published for this date")

    # Capture portfolio values onto fund (informational; required by NAV computation chain)
    fund["portfolio_market_value_cents"] = pmv
    fund["portfolio_accrued_income_cents"] = pai

    components = compute_nav_components(
        pmv, pai,
        fund["management_fee_bps_annual"],
        fund["custodian_fee_bps_annual"],
        fund["sales_service_fee_bps_annual"],
        fund["total_outstanding_shares"],
    )

    snap = {
        "fund_id": fund["id"],
        "nav_date": iso(date_to_dt_utc(nav_date)),
        "published_at": iso(now()),
        "gross_assets_cents": components["gross_assets_cents"],
        "management_fee_accrued_cents": components["management_fee_accrued_cents"],
        "custodian_fee_accrued_cents": components["custodian_fee_accrued_cents"],
        "sales_service_fee_accrued_cents": components["sales_service_fee_accrued_cents"],
        "net_assets_cents": components["net_assets_cents"],
        "shares_outstanding_at_nav": components["shares_outstanding_at_nav"],
        "nav_per_share_micros": components["nav_per_share_micros"],
        "status": "PUBLISHED",
        "adjustment_reason": None,
    }
    stamp_create(snap, common_fields=False)
    nav_snapshots[snap["id"]] = snap
    stamp_update(fund)
    audit.write(g.user_id, g.user_role, "NAV_PUBLISHED", "NavSnapshot", snap["id"],
                "PROVISIONAL", "PUBLISHED", {"nav_date": str(nav_date)})

    # Trigger confirmation cascade for orders whose trade_date == nav_date and confirm_date reached
    confirmation_pass(fund, snap, g.user_id, g.user_role)

    return success(public(snap), 201)


@bp.route("/funds/<id>/nav/<nav_date>/adjust", methods=["POST"])
@require_auth(roles={"ComplianceReviewer"})
def adjust_nav(id, nav_date):
    fund = funds.get(id)
    if not fund:
        raise err("ERR_NOT_FOUND", "Fund not found")
    try:
        target_date = parse_iso_date(nav_date)
    except Exception:
        raise err("ERR_NOT_FOUND", "Invalid nav_date")
    snap = find_nav_snapshot(fund["id"], target_date)
    if not snap:
        raise err("ERR_NOT_FOUND", "NAV snapshot not found")

    body = get_body()
    require_field(body, "portfolio_market_value_cents")
    require_field(body, "portfolio_accrued_income_cents")
    require_field(body, "adjustment_reason")

    if not isinstance(body["adjustment_reason"], str) or not body["adjustment_reason"].strip():
        raise err("ERR_VALIDATION", "adjustment_reason must be non-empty string")

    if snap["status"] != "PUBLISHED":
        # PRD §3.4: adjusting requires snapshot in PUBLISHED. ADJUSTED again could be allowed but we keep strict per scaffold transition.
        raise err("ERR_INVALID_STATE", f"NavSnapshot.status={snap['status']}, expected PUBLISHED")

    # Check no DividendPlan with ex_dividend_date == nav_date in EX_DIVIDEND or PAID
    for plan in dividend_plans.values():
        if plan["fund_id"] != fund["id"]:
            continue
        if parse_iso_date(plan["ex_dividend_date"]) != target_date:
            continue
        if plan["status"] in ("EX_DIVIDEND", "PAID"):
            raise err("ERR_INVALID_STATE",
                      "Cannot adjust NAV: dividend plan in EX_DIVIDEND/PAID for this date")

    pmv = body["portfolio_market_value_cents"]
    pai = body["portfolio_accrued_income_cents"]
    if not isinstance(pmv, int) or isinstance(pmv, bool):
        raise err("ERR_VALIDATION", "portfolio_market_value_cents must be int")
    if not isinstance(pai, int) or isinstance(pai, bool):
        raise err("ERR_VALIDATION", "portfolio_accrued_income_cents must be int")

    components = compute_nav_components(
        pmv, pai,
        fund["management_fee_bps_annual"],
        fund["custodian_fee_bps_annual"],
        fund["sales_service_fee_bps_annual"],
        snap["shares_outstanding_at_nav"],
    )
    prev_nav = snap["nav_per_share_micros"]
    snap["gross_assets_cents"] = components["gross_assets_cents"]
    snap["management_fee_accrued_cents"] = components["management_fee_accrued_cents"]
    snap["custodian_fee_accrued_cents"] = components["custodian_fee_accrued_cents"]
    snap["sales_service_fee_accrued_cents"] = components["sales_service_fee_accrued_cents"]
    snap["net_assets_cents"] = components["net_assets_cents"]
    snap["nav_per_share_micros"] = components["nav_per_share_micros"]
    snap["status"] = "ADJUSTED"
    snap["adjustment_reason"] = body["adjustment_reason"]
    audit.write(g.user_id, g.user_role, "NAV_ADJUSTED", "NavSnapshot", snap["id"],
                str(prev_nav), str(snap["nav_per_share_micros"]),
                {"adjustment_reason": body["adjustment_reason"]})
    return success(public(snap), 200)


@bp.route("/funds/<id>/nav/<nav_date>", methods=["GET"])
@require_auth(roles={"PlatformAdmin", "ComplianceReviewer", "NavOperator", "Investor"})
def get_nav(id, nav_date):
    fund = funds.get(id)
    if not fund:
        raise err("ERR_NOT_FOUND", "Fund not found")
    try:
        target_date = parse_iso_date(nav_date)
    except Exception:
        raise err("ERR_NOT_FOUND", "Invalid nav_date")
    snap = find_nav_snapshot(fund["id"], target_date)
    if not snap:
        raise err("ERR_NOT_FOUND", "NAV snapshot not found")
    return success(public(snap), 200)
