"""SkuListing, VelocityForecast and listing reverse-lookup endpoints."""
from flask import Blueprint, request

import calc
import db as store
import response
import serialize
import validate
from db import db, mark_created, new_row, order_asc, order_desc, set_field
from errors import ApiError
from middleware import require_roles, require_seller_scope
from routes.common import filter_eq, finish, get_listing, get_seller, listing_page

bp = Blueprint("listings", __name__)

FORECAST_VARIANTS = ("TRAILING_30", "SEASONAL_WEIGHTED")


@bp.post("/fulfillment/sku-listings")
@require_roles("SellerOperator")
def create_listing():
    data = validate.body()
    seller_account_id = validate.req_str(data, "seller_account_id")
    sku = validate.req_str(data, "sku")
    unit_cubic_feet = validate.req_num(data, "unit_cubic_feet", exclusive_minimum=0)
    unit_cost_cents = validate.req_int(data, "unit_cost_cents", minimum=0)

    get_seller(seller_account_id)
    require_seller_scope(seller_account_id)

    for existing in db.listings.values():
        if existing["seller_account_id"] == seller_account_id and existing["sku"] == sku:
            raise ApiError("ERR_DUPLICATE_SKU", 409)

    row = new_row()
    row.update({
        "seller_account_id": seller_account_id,
        "sku": sku,
        "unit_cubic_feet": unit_cubic_feet,
        "unit_cost_cents": unit_cost_cents,
        "listing_status": "ACTIVE",
        "suppression_reason": "NONE",
        "inventory_health": "OUT_OF_STOCK",
        "fulfillable_units": 0,
        "unfulfillable_units": 0,
        "missing_units": 0,
        "aged_over_365_units": 0,
        "recommended_replenishment_units": 0,
        "lot_ever_created": False,
    })
    db.listings[row["id"]] = row
    mark_created(row)
    return finish(lambda: serialize.listing(row), 201)


@bp.get("/fulfillment/sku-listings/<listing_id>")
@require_roles("MarketplaceAdmin", "SellerOperator", "ClaimsAdjudicator", "FcOperator")
def read_listing(listing_id):
    listing = get_listing(listing_id)
    return response.object_response(serialize.listing(listing), 200)


@bp.post("/fulfillment/sku-listings/<listing_id>/reinstate")
@require_roles("SellerOperator")
def reinstate_listing(listing_id):
    data = validate.body()
    validate.opt_str(data, "reinstatement_note")
    listing = get_listing(listing_id)
    require_seller_scope(listing["seller_account_id"])

    if listing["listing_status"] != "SUPPRESSED":
        raise ApiError("ERR_LISTING_NOT_SUPPRESSED", 409)
    if listing["fulfillable_units"] < 1:
        raise ApiError("ERR_SUPPRESSION_CONDITION_PERSISTS", 409)

    set_field(listing, "listing_status", "ACTIVE")
    set_field(listing, "suppression_reason", "NONE")
    return finish(lambda: serialize.listing(listing), 200)


@bp.get("/fulfillment/sku-listings/<listing_id>/line-items")
@require_roles("MarketplaceAdmin", "SellerOperator")
def list_listing_line_items(listing_id):
    get_listing(listing_id)
    rows = order_asc([li for li in db.line_items.values()
                      if li["sku_listing_id"] == listing_id])
    return listing_page(rows, serialize.line_item, request.args)


@bp.get("/fulfillment/sku-listings/<listing_id>/velocity-forecasts")
@require_roles("MarketplaceAdmin", "SellerOperator")
def list_forecasts(listing_id):
    get_listing(listing_id)
    rows = order_desc([f for f in db.forecasts.values()
                       if f["sku_listing_id"] == listing_id])
    rows = filter_eq(rows, request.args, "forecast_variant")
    return listing_page(rows, serialize.forecast, request.args)


@bp.post("/fulfillment/sku-listings/<listing_id>/velocity-forecasts")
@require_roles("SellerOperator")
def create_forecast(listing_id):
    data = validate.body()
    payload = {
        "forecast_variant": validate.req_enum(data, "forecast_variant", FORECAST_VARIANTS),
        "trailing_30_units_sold": validate.req_int(data, "trailing_30_units_sold", minimum=0),
        "prior_year_same_period_units_sold": validate.req_int(
            data, "prior_year_same_period_units_sold", minimum=0),
        "seasonal_index": validate.req_num(data, "seasonal_index", minimum=0),
        "coverage_target_days": validate.req_int(data, "coverage_target_days", minimum=0),
        "lead_time_days": validate.req_int(data, "lead_time_days", minimum=0),
    }
    listing = get_listing(listing_id)
    require_seller_scope(listing["seller_account_id"])

    result = calc.run_velocity_forecast(listing, payload)
    row = new_row(with_common=False)
    row["sku_listing_id"] = listing_id
    row.update(payload)
    row.update(result)
    db.forecasts[row["id"]] = row
    mark_created(row)

    set_field(listing, "recommended_replenishment_units",
              result["recommended_replenishment_units"])
    return finish(lambda: serialize.forecast(row), 201)


@bp.get("/fulfillment/sku-listings/<listing_id>/multi-channel-orders")
@require_roles("MarketplaceAdmin", "SellerOperator")
def list_listing_mcf_orders(listing_id):
    get_listing(listing_id)
    rows = order_asc([o for o in db.mcf_orders.values()
                      if o["sku_listing_id"] == listing_id])
    rows = filter_eq(rows, request.args, "fulfillment_channel")
    return listing_page(rows, serialize.mcf_order, request.args)
