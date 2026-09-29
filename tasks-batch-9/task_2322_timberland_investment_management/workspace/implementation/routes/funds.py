"""Fund formation, reads and the investor reporting pack (PRD 3.1 / 3.3)."""

from decimal import Decimal

from flask import Blueprint

import db
import middleware
import response
import serializers
import services
import validate
from db import store
from routes.helpers import paginated

bp = Blueprint("funds", __name__)


@bp.post("/funds")
def create_fund():
    middleware.require("FundAdmin")
    body = validate.json_body()
    name = validate.string(body, "name", 1, 120)
    vintage_year = validate.integer(body, "vintage_year", 2000, 2100)
    committed = validate.number(body, "committed_capital_usd", minimum=0,
                                exclusive_min=True, dp=2)
    target_bps = validate.integer(body, "target_cash_yield_bps", 0, 5000)
    opening = validate.number(body, "opening_cash_usd", minimum=0, dp=2)

    rec = db.base_fields()
    rec.update({
        "name": name,
        "vintage_year": vintage_year,
        "committed_capital_usd": committed,
        "target_cash_yield_bps": target_bps,
        "opening_cash_usd": opening,
        "cash_balance_usd": opening,
        "net_operating_cash_usd": Decimal("0.00"),
        "cash_yield_bps": 0,
        "harvest_acceleration_required": 0 < target_bps,
        "nav_usd": opening,
        "replan_property_count": 0,
        "valuation_basis_stale_count": 0,
    })
    store.funds[rec["id"]] = rec
    return response.created(serializers.fund(rec))


@bp.get("/funds/<fund_id>")
def get_fund(fund_id):
    middleware.require(*middleware.ANY_ROLE)
    fund = services.find(store.funds, fund_id, "ERR_FUND_NOT_FOUND")
    services.apply_lazy_stale_for_fund(fund)
    return response.ok(serializers.fund(fund))


@bp.get("/funds/<fund_id>/properties")
def list_fund_properties(fund_id):
    middleware.require(*middleware.ANY_ROLE)
    fund = services.find(store.funds, fund_id, "ERR_FUND_NOT_FOUND")
    return paginated(services.properties_of_fund(fund["id"]), serializers.prop)


@bp.get("/funds/<fund_id>/investor-report")
def investor_report(fund_id):
    middleware.require("FundAdmin", "InvestmentCommittee", "IndependentAppraiser")
    fund = services.find(store.funds, fund_id, "ERR_FUND_NOT_FOUND")
    services.apply_lazy_stale_for_fund(fund)
    extras = services.recompute_fund(fund)
    return response.ok({
        "nav_usd": fund["nav_usd"],
        "cash_balance_usd": fund["cash_balance_usd"],
        "net_operating_cash_usd": fund["net_operating_cash_usd"],
        "cash_yield_bps": fund["cash_yield_bps"],
        "target_cash_yield_bps": fund["target_cash_yield_bps"],
        "harvest_acceleration_required": fund["harvest_acceleration_required"],
        "replan_property_count": fund["replan_property_count"],
        "valuation_basis_stale_count": fund["valuation_basis_stale_count"],
        "owned_property_count": extras["owned_property_count"],
        "appraised_value_total_usd": extras["appraised_value_total_usd"],
        "standing_inventory_tons": extras["standing_inventory_tons"],
    })
