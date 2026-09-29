"""MultiChannelOrder endpoint: the fee comparison and the FIFO draw."""
from flask import Blueprint

import calc
import serialize
import validate
from db import db, mark_created, new_row, set_field
from errors import ApiError
from middleware import require_roles, require_seller_scope
from routes.common import finish, get_listing

bp = Blueprint("orders", __name__)

ZONES = ("ZONE_1", "ZONE_2", "ZONE_3")
CHANNELS = ("MCF", "SELF_FULFILLED")


@bp.post("/fulfillment/multi-channel-orders")
@require_roles("SellerOperator")
def create_order():
    data = validate.body()
    sku_listing_id = validate.req_str(data, "sku_listing_id")
    units = validate.req_int(data, "units", minimum=1)
    billable_weight_lb = validate.req_num(data, "billable_weight_lb", exclusive_minimum=0)
    destination_zone = validate.req_enum(data, "destination_zone", ZONES)
    fulfillment_channel = validate.req_enum(data, "fulfillment_channel", CHANNELS)
    self_fulfilled_cost_cents = validate.req_int(data, "self_fulfilled_cost_cents", minimum=0)

    listing = get_listing(sku_listing_id)
    require_seller_scope(listing["seller_account_id"])

    draw_plan = None
    if fulfillment_channel == "MCF":
        draw_plan = calc.mcf_draw_plan(sku_listing_id, units)
        if draw_plan is None:
            raise ApiError("ERR_NO_FULFILLABLE_INVENTORY", 422)

    quote = calc.run_mcf_quote(units, billable_weight_lb, destination_zone,
                               self_fulfilled_cost_cents)

    row = new_row()
    row.update({
        "sku_listing_id": sku_listing_id,
        "units": units,
        "billable_weight_lb": billable_weight_lb,
        "destination_zone": destination_zone,
        "fulfillment_channel": fulfillment_channel,
        "self_fulfilled_cost_cents": self_fulfilled_cost_cents,
        "order_status": "SELF_SHIPPED",
        "consumed_lot_allocations": [],
    })
    row.update(quote)

    if fulfillment_channel == "MCF":
        allocations = []
        for lot, drawn in draw_plan:
            set_field(lot, "fulfillable_units", lot["fulfillable_units"] - drawn)
            set_field(lot, "units_shipped_mcf", lot["units_shipped_mcf"] + drawn)
            calc.settle_lot_status(lot)
            allocations.append({"inventory_lot_id": lot["id"], "units": drawn})
        row["consumed_lot_allocations"] = allocations
        row["order_status"] = "MCF_SHIPPED"

    db.mcf_orders[row["id"]] = row
    mark_created(row)
    return finish(lambda: serialize.mcf_order(row), 201)
