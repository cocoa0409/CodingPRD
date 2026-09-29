"""SellerAccount and RestockQuota endpoints."""
from decimal import Decimal

from flask import Blueprint, request

import calc
import clock
import db as store
import response
import serialize
import validate
from db import db, mark_created, new_row, order_asc, order_desc, set_field
from errors import ApiError
from middleware import require_roles
from routes.common import filter_eq, finish, get_seller, listing_page

bp = Blueprint("sellers", __name__)


@bp.post("/fulfillment/sellers")
@require_roles("MarketplaceAdmin")
def create_seller():
    data = validate.body()
    legal_name = validate.req_str(data, "legal_name")
    entitlement = validate.req_num(data, "storage_cubic_feet_entitlement", exclusive_minimum=0)
    cap = validate.req_int(data, "unit_cost_cap_cents", minimum=0)

    row = new_row()
    row.update({
        "legal_name": legal_name,
        "storage_cubic_feet_entitlement": entitlement,
        "unit_cost_cap_cents": cap,
        "seller_status": "ACTIVE",
        "restock_reserved_units": 0,
        "open_discrepancy_units": 0,
        "suppressed_listing_count": 0,
        "storage_utilization_ratio": Decimal("0.0000"),
        "storage_fee_accrued_cents": 0,
        "reimbursement_credit_cents": 0,
        "mcf_fee_accrued_cents": 0,
    })
    db.sellers[row["id"]] = row
    mark_created(row)
    return finish(lambda: serialize.seller(row), 201)


@bp.get("/fulfillment/sellers/<seller_id>")
@require_roles("MarketplaceAdmin", "SellerOperator", "ClaimsAdjudicator")
def read_seller(seller_id):
    seller = get_seller(seller_id)
    return response.object_response(serialize.seller(seller), 200)


@bp.get("/fulfillment/sellers/<seller_id>/sku-listings")
@require_roles("MarketplaceAdmin", "SellerOperator")
def list_seller_listings(seller_id):
    get_seller(seller_id)
    rows = store.seller_listings(seller_id)
    rows = filter_eq(rows, request.args, "listing_status")
    rows = filter_eq(rows, request.args, "inventory_health")
    return listing_page(rows, serialize.listing, request.args)


@bp.get("/fulfillment/sellers/<seller_id>/restock-quotas")
@require_roles("MarketplaceAdmin", "SellerOperator")
def list_seller_quotas(seller_id):
    get_seller(seller_id)
    rows = order_desc([q for q in db.quotas.values() if q["seller_account_id"] == seller_id])
    rows = filter_eq(rows, request.args, "status")
    return listing_page(rows, serialize.quota, request.args)


@bp.post("/fulfillment/sellers/<seller_id>/restock-quotas")
@require_roles("MarketplaceAdmin")
def create_quota(seller_id):
    data = validate.body()
    period_start = validate.req_dt(data, "period_start")
    period_end = validate.req_dt(data, "period_end")
    if period_end <= period_start:
        validate.bad("period_end must be strictly after period_start.")
    base_capacity = validate.req_int(data, "base_capacity_units", minimum=1)
    sell_through = validate.req_num(data, "sell_through_rate", minimum=0)
    excess = validate.req_num(data, "excess_units_ratio", minimum=0, maximum=1)
    stranded = validate.req_num(data, "stranded_ratio", minimum=0, maximum=1)
    in_stock = validate.req_num(data, "in_stock_rate", minimum=0, maximum=1)

    seller = get_seller(seller_id)

    previous = store.active_quota(seller_id)
    if previous is not None:
        set_field(previous, "status", "SUPERSEDED")

    seeded = sum(p["allocated_units"] for p in store.seller_plans(seller_id)
                 if p["status"] in store.RESERVING_STATUSES)

    row = new_row()
    row.update({
        "seller_account_id": seller_id,
        "period_start": period_start,
        "period_end": period_end,
        "base_capacity_units": base_capacity,
        "sell_through_rate": sell_through,
        "excess_units_ratio": excess,
        "stranded_ratio": stranded,
        "in_stock_rate": in_stock,
        "iprs_score": 0,
        "base_capacity_tier": "TIER_RESTRICTED",
        "capacity_tier_downgrade_steps": 0,
        "capacity_tier": "TIER_RESTRICTED",
        "restock_limit_units": 0,
        "utilized_units": seeded,
        "status": "ACTIVE",
    })
    db.quotas[row["id"]] = row
    mark_created(row)
    calc.run_iprs(row)
    return finish(lambda: serialize.quota(row), 201)
