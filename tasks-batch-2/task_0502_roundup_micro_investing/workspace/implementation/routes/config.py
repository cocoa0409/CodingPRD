"""Config routes: SubscriptionPlan, ModelPortfolio, FoundMoneyOffer,
plus the test-driving clock and lot-valuation endpoints (PRD §3.1, §2.10, §3.7).
"""

from flask import Blueprint

from db import store
from errors import err
from middleware import get_json, parse_iso8601, require_auth
from models import new_entity, recompute_bucket, serialize, touch
from response import success
from routes.helpers import (
    fetch_or_404,
    require_bool,
    require_enum,
    require_int,
    require_str,
)

bp = Blueprint("config", __name__)


# ---------------------------------------------------------------------------
# SubscriptionPlan (PRD §3.1)
# ---------------------------------------------------------------------------
@bp.route("/subscription-plans", methods=["POST"])
def create_subscription_plan():
    require_auth({"PlatformAdmin"})
    body = get_json()
    tier = require_enum(body, "tier", {"LITE", "PERSONAL", "FAMILY"})
    monthly_fee_cents = require_int(body, "monthly_fee_cents", minimum=0)
    allows_custodial = require_bool(body, "allows_custodial")
    allows_ira = require_bool(body, "allows_ira")
    management_fee_bps = require_int(body, "management_fee_bps", minimum=0, maximum=100)

    # Unique per tier (PRD §3.1).
    for p in store.subscription_plans.values():
        if p["tier"] == tier:
            raise err("ERR_DUPLICATE_TIER", "A plan for tier %s already exists." % tier)

    plan = new_entity(
        {
            "tier": tier,
            "monthly_fee_cents": monthly_fee_cents,
            "allows_custodial": allows_custodial,
            "allows_ira": allows_ira,
            "management_fee_bps": management_fee_bps,
            "status": "ACTIVE",
        }
    )
    store.subscription_plans[plan["id"]] = plan
    return success(serialize(plan), status=201)


@bp.route("/subscription-plans/<entity_id>", methods=["GET"])
def get_subscription_plan(entity_id):
    require_auth({"PlatformAdmin", "Investor", "CustodialGuardian"})
    plan = fetch_or_404(store.subscription_plans, entity_id)
    return success(serialize(plan))


# ---------------------------------------------------------------------------
# ModelPortfolio (PRD §3.1)
# ---------------------------------------------------------------------------
@bp.route("/model-portfolios", methods=["POST"])
def create_model_portfolio():
    require_auth({"PlatformAdmin"})
    body = get_json()
    risk_tier = require_int(body, "risk_tier", minimum=1, maximum=5)
    name = require_str(body, "name")
    drift_band_bps = require_int(body, "drift_band_bps", minimum=0)
    if "target_allocation" not in body or not isinstance(body["target_allocation"], dict):
        raise err("ERR_INVALID_REQUEST", "target_allocation must be an object.")
    target_allocation = body["target_allocation"]
    for k, v in target_allocation.items():
        if isinstance(v, bool) or not isinstance(v, int):
            raise err("ERR_INVALID_REQUEST", "target_allocation weights must be integers.")

    # Unique risk_tier (PRD §3.1).
    for p in store.model_portfolios.values():
        if p["risk_tier"] == risk_tier:
            raise err("ERR_DUPLICATE_TIER", "A portfolio for risk_tier %s already exists." % risk_tier)

    # Weights must sum to exactly 100 (PRD §3.1).
    if sum(target_allocation.values()) != 100:
        raise err("ERR_ALLOCATION_SUM", "target_allocation weights must sum to exactly 100.")

    portfolio = new_entity(
        {
            "risk_tier": risk_tier,
            "name": name,
            "target_allocation": target_allocation,
            "drift_band_bps": drift_band_bps,
            "status": "ACTIVE",
        }
    )
    store.model_portfolios[portfolio["id"]] = portfolio
    return success(serialize(portfolio), status=201)


@bp.route("/model-portfolios/<entity_id>", methods=["GET"])
def get_model_portfolio(entity_id):
    require_auth({"PlatformAdmin", "Investor", "CustodialGuardian"})
    portfolio = fetch_or_404(store.model_portfolios, entity_id)
    return success(serialize(portfolio))


# ---------------------------------------------------------------------------
# FoundMoneyOffer (PRD §3.1)
# ---------------------------------------------------------------------------
@bp.route("/found-money-offers", methods=["POST"])
def create_found_money_offer():
    require_auth({"PlatformAdmin"})
    body = get_json()
    brand_name = require_str(body, "brand_name")
    rebate_mode = require_enum(body, "rebate_mode", {"PERCENT", "FLAT"})
    max_rebate_cents = require_int(body, "max_rebate_cents", minimum=0)
    min_spend_cents = require_int(body, "min_spend_cents", minimum=0)
    hold_days = require_int(body, "hold_days", minimum=0)

    if "active_from" not in body or "active_until" not in body:
        raise err("ERR_INVALID_REQUEST", "active_from and active_until are required.")
    active_from = parse_iso8601(body["active_from"])
    active_until = parse_iso8601(body["active_until"])

    rebate_percent_bps = None
    rebate_flat_cents = None
    if rebate_mode == "PERCENT":
        rebate_percent_bps = require_int(body, "rebate_percent_bps", minimum=0, maximum=10000)
    else:  # FLAT
        rebate_flat_cents = require_int(body, "rebate_flat_cents", minimum=0)

    # active_until must be strictly greater than active_from (PRD §3.1).
    if not (active_until > active_from):
        raise err("ERR_INVALID_REQUEST", "active_until must be strictly after active_from.")

    # Half-open window must not overlap any existing ACTIVE offer of same brand (PRD §3.1).
    for o in store.found_money_offers.values():
        if o["status"] != "ACTIVE" or o["brand_name"] != brand_name:
            continue
        existing_from = parse_iso8601(o["active_from"])
        existing_until = parse_iso8601(o["active_until"])
        # Overlap of [a_from, a_until) and [e_from, e_until): a_from < e_until and e_from < a_until.
        if active_from < existing_until and existing_from < active_until:
            raise err("ERR_OFFER_WINDOW_OVERLAP", "Offer window overlaps an existing active offer of the same brand.")

    offer = new_entity(
        {
            "brand_name": brand_name,
            "rebate_mode": rebate_mode,
            "rebate_percent_bps": rebate_percent_bps,
            "rebate_flat_cents": rebate_flat_cents,
            "max_rebate_cents": max_rebate_cents,
            "min_spend_cents": min_spend_cents,
            "hold_days": hold_days,
            "active_from": body["active_from"],
            "active_until": body["active_until"],
            "status": "ACTIVE",
        }
    )
    store.found_money_offers[offer["id"]] = offer
    return success(serialize(offer), status=201)


@bp.route("/found-money-offers/<entity_id>", methods=["GET"])
def get_found_money_offer(entity_id):
    require_auth({"PlatformAdmin", "Investor", "CustodialGuardian"})
    offer = fetch_or_404(store.found_money_offers, entity_id)
    return success(serialize(offer))


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.10)
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_auth({"PlatformAdmin"})
    body = get_json()
    if "to_iso8601" not in body:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 is required.")
    dt = parse_iso8601(body["to_iso8601"])
    store.set_clock(dt)
    return success({})


# ---------------------------------------------------------------------------
# Lot valuation injection (PRD §3.7)
# ---------------------------------------------------------------------------
@bp.route("/_lots/<entity_id>/set_valuation", methods=["POST"])
def set_lot_valuation(entity_id):
    require_auth({"PlatformAdmin"})
    lot = fetch_or_404(store.tax_lots, entity_id)
    body = get_json()
    if "unit_gain_ratio_bps" not in body or body["unit_gain_ratio_bps"] is None:
        raise err("ERR_INVALID_REQUEST", "unit_gain_ratio_bps is required.")
    val = body["unit_gain_ratio_bps"]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "unit_gain_ratio_bps must be an integer.")

    # Only an OPEN lot may receive a valuation (PRD §3.7).
    if lot["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Valuation may only be injected on an OPEN lot.")

    lot["unit_gain_ratio_bps"] = val
    lot["market_value_cents"] = (lot["remaining_basis_cents"] * (10000 + val)) // 10000
    touch(lot)

    bucket = store.buckets.get(lot["bucket_id"])
    if bucket:
        recompute_bucket(bucket)

    return success(serialize(lot))
