"""RemovalOrder endpoints: request, complete, cancel."""
from flask import Blueprint

import calc
import clock
import response
import serialize
import validate
from db import db, mark_created, mark_dirty, new_row, set_field
from errors import ApiError
from middleware import require_fc_scope, require_roles, require_seller_scope
from routes.common import finish, get_listing, get_lot, get_removal, get_seller

bp = Blueprint("removals", __name__)

REMOVAL_METHODS = ("DISPOSAL", "RETURN_TO_SELLER", "LIQUIDATION")
UNIT_POOLS = ("FULFILLABLE", "UNFULFILLABLE")
POOL_FIELD = {"FULFILLABLE": "fulfillable_units", "UNFULFILLABLE": "unfulfillable_units"}


def _windows_touch(a_start, a_end, b_start, b_end):
    """Closed [start, end] intervals: touching at an endpoint counts as a conflict."""
    return a_start <= b_end and b_start <= a_end


@bp.post("/fulfillment/removal-orders")
@require_roles("SellerOperator")
def create_removal():
    data = validate.body()
    inventory_lot_id = validate.req_str(data, "inventory_lot_id")
    removal_method = validate.req_enum(data, "removal_method", REMOVAL_METHODS)
    unit_pool = validate.req_enum(data, "unit_pool", UNIT_POOLS)
    requested_units = validate.req_int(data, "requested_units", minimum=1)
    window_start = validate.req_dt(data, "removal_window_start")
    window_end = validate.req_dt(data, "removal_window_end")
    if window_end <= window_start:
        validate.bad("removal_window_end must be strictly after removal_window_start.")
    expected_version = validate.req_int(data, "expected_inventory_lot_version")

    lot = get_lot(inventory_lot_id)
    listing = get_listing(lot["sku_listing_id"])
    require_seller_scope(listing["seller_account_id"])

    if expected_version != lot["version"]:
        raise ApiError("ERR_STALE_LOT_VERSION", 412)

    for other in db.removals.values():
        if other["inventory_lot_id"] != inventory_lot_id or other["status"] != "REQUESTED":
            continue
        if _windows_touch(other["removal_window_start"], other["removal_window_end"],
                          window_start, window_end):
            raise ApiError("ERR_REMOVAL_WINDOW_CONFLICT", 409)

    pool_field = POOL_FIELD[unit_pool]
    if requested_units > lot[pool_field]:
        raise ApiError("ERR_INSUFFICIENT_POOL_UNITS", 422)

    row = new_row()
    row.update({
        "inventory_lot_id": inventory_lot_id,
        "removal_method": removal_method,
        "unit_pool": unit_pool,
        "requested_units": requested_units,
        "removal_window_start": window_start,
        "removal_window_end": window_end,
        "status": "REQUESTED",
        "removal_fee_cents": 0,
        "liquidation_recovery_cents": 0,
        "net_settlement_cents": 0,
        "completed_at": None,
    })
    db.removals[row["id"]] = row
    mark_created(row)

    set_field(lot, pool_field, lot[pool_field] - requested_units)
    set_field(lot, "units_reserved_for_removal",
              lot["units_reserved_for_removal"] + requested_units)
    mark_dirty(lot)
    return finish(lambda: serialize.removal(row), 201)


@bp.get("/fulfillment/removal-orders/<removal_id>")
@require_roles("MarketplaceAdmin", "SellerOperator", "FcOperator")
def read_removal(removal_id):
    removal = get_removal(removal_id)
    return response.object_response(serialize.removal(removal), 200)


@bp.post("/fulfillment/removal-orders/<removal_id>/complete")
@require_roles("FcOperator")
def complete_removal(removal_id):
    data = validate.body()
    validate.opt_str(data, "completion_note")

    removal = get_removal(removal_id)
    lot = get_lot(removal["inventory_lot_id"])
    require_fc_scope(lot["fulfillment_center_id"])

    if removal["status"] != "REQUESTED":
        raise ApiError("ERR_REMOVAL_NOT_REQUESTED", 409)

    now = clock.now()
    if now < removal["removal_window_start"]:
        raise ApiError("ERR_REMOVAL_WINDOW_NOT_OPEN", 409)

    listing = get_listing(lot["sku_listing_id"])
    units = removal["requested_units"]

    set_field(lot, "units_reserved_for_removal", lot["units_reserved_for_removal"] - units)
    set_field(lot, "units_removed", lot["units_removed"] + units)
    set_field(lot, "last_removal_completed_at", now)
    calc.settle_lot_status(lot)

    fee, recovery, net = calc.run_removal_settlement(removal, listing)
    set_field(removal, "status", "COMPLETED")
    set_field(removal, "removal_fee_cents", fee)
    set_field(removal, "liquidation_recovery_cents", recovery)
    set_field(removal, "net_settlement_cents", net)
    set_field(removal, "completed_at", now)
    return finish(lambda: serialize.removal(removal), 200)


@bp.post("/fulfillment/removal-orders/<removal_id>/cancel")
@require_roles("SellerOperator")
def cancel_removal(removal_id):
    data = validate.body()
    validate.opt_str(data, "cancellation_reason")

    removal = get_removal(removal_id)
    lot = get_lot(removal["inventory_lot_id"])
    listing = get_listing(lot["sku_listing_id"])
    require_seller_scope(listing["seller_account_id"])

    if removal["status"] != "REQUESTED":
        raise ApiError("ERR_REMOVAL_NOT_REQUESTED", 409)

    units = removal["requested_units"]
    pool_field = POOL_FIELD[removal["unit_pool"]]
    set_field(lot, "units_reserved_for_removal", lot["units_reserved_for_removal"] - units)
    set_field(lot, pool_field, lot[pool_field] + units)
    set_field(removal, "status", "CANCELLED")
    return finish(lambda: serialize.removal(removal), 200)
