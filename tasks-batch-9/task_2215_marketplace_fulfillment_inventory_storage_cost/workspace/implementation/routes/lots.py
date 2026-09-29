"""InventoryLot endpoints and the lot reverse lookups."""
from flask import Blueprint, request

import clock
import response
import serialize
import validate
from db import db, order_asc, set_field
from errors import ApiError
from middleware import require_fc_scope, require_roles
from routes.common import filter_eq, finish, get_lot, listing_page

bp = Blueprint("lots", __name__)


@bp.get("/fulfillment/inventory-lots")
@require_roles("MarketplaceAdmin", "SellerOperator", "FcOperator")
def list_lots():
    rows = order_asc(list(db.lots.values()))
    rows = filter_eq(rows, request.args, "sku_listing_id")
    rows = filter_eq(rows, request.args, "fulfillment_center_id")
    rows = filter_eq(rows, request.args, "lot_status")
    rows = filter_eq(rows, request.args, "reconciliation_status")
    rows = filter_eq(rows, request.args, "aged_bucket")
    return listing_page(rows, serialize.lot, request.args)


@bp.get("/fulfillment/inventory-lots/<lot_id>")
@require_roles("MarketplaceAdmin", "SellerOperator", "FcOperator", "ClaimsAdjudicator")
def read_lot(lot_id):
    lot = get_lot(lot_id)
    return response.object_response(serialize.lot(lot), 200)


@bp.post("/fulfillment/inventory-lots/<lot_id>/unfulfillable-classification")
@require_roles("FcOperator")
def classify_unfulfillable(lot_id):
    data = validate.body()
    units = validate.req_int(data, "units", minimum=1)
    validate.req_str(data, "disposition_reason")

    lot = get_lot(lot_id)
    require_fc_scope(lot["fulfillment_center_id"])

    if units > lot["fulfillable_units"]:
        raise ApiError("ERR_INSUFFICIENT_POOL_UNITS", 422)

    set_field(lot, "fulfillable_units", lot["fulfillable_units"] - units)
    set_field(lot, "unfulfillable_units", lot["unfulfillable_units"] + units)
    set_field(lot, "unfulfillable_recorded_at", clock.now())
    return finish(lambda: serialize.lot(lot), 200)


@bp.get("/fulfillment/inventory-lots/<lot_id>/storage-fee-assessments")
@require_roles("MarketplaceAdmin", "SellerOperator")
def list_lot_assessments(lot_id):
    get_lot(lot_id)
    rows = order_asc([a for a in db.assessments.values() if a["inventory_lot_id"] == lot_id])
    return listing_page(rows, serialize.assessment, request.args)


@bp.get("/fulfillment/inventory-lots/<lot_id>/removal-orders")
@require_roles("MarketplaceAdmin", "SellerOperator", "FcOperator")
def list_lot_removals(lot_id):
    get_lot(lot_id)
    rows = order_asc([r for r in db.removals.values() if r["inventory_lot_id"] == lot_id])
    rows = filter_eq(rows, request.args, "status")
    return listing_page(rows, serialize.removal, request.args)


@bp.get("/fulfillment/inventory-lots/<lot_id>/reimbursement-claims")
@require_roles("MarketplaceAdmin", "SellerOperator", "ClaimsAdjudicator")
def list_lot_claims(lot_id):
    get_lot(lot_id)
    rows = order_asc([c for c in db.claims.values() if c["inventory_lot_id"] == lot_id])
    rows = filter_eq(rows, request.args, "status")
    return listing_page(rows, serialize.claim, request.args)
