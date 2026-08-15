"""SeedReturn endpoints: the REQUESTED -> APPROVED -> RECEIVED -> CREDITED
pipeline with provisional and final credit variants."""

import db
from errors import (
    ApiError,
    ERR_INVALID_STATE_TRANSITION,
    ERR_ORDER_LINE_MISMATCH,
    ERR_RETURN_WINDOW_CLOSED,
    ERR_RETURN_NOT_ALLOWED_TREATED,
    ERR_RETURN_QUANTITY_EXCEEDS,
    ERR_NOTHING_TO_RETURN,
)
from middleware import authenticate, check_grower_ownership, GROWER
from response import success_obj, success_list
from routes import make_blueprint
from services import recompute_lot_status, recompute_fulfillment, select_rebate_bps
from util import body_json, check_shape, pagination_params, paginate, apply_filters, require_fk, exist_body_fks, dt_of, rhu_div

bp = make_blueprint("returns")

READ_ROLES = ["DealerAdmin", "SalesRep", "Grower"]
REASONS = ["OVERSTOCK", "WRONG_HYBRID", "DAMAGED", "OTHER"]
IN_FLIGHT = ("REQUESTED", "APPROVED", "RECEIVED")


def _returnable_remainder(line):
    in_flight = sum(
        r["units"] for r in db.all_of("returns")
        if r["order_line_id"] == line["id"] and r["status"] in IN_FLIGHT
    )
    return line["delivered_units"] - line["returned_units"] - in_flight


@bp.post("/returns")
def create_return():
    uid, role = authenticate(["SalesRep", "Grower"])
    body = body_json()
    fks = {
        "order_id": ("orders", "order"),
        "order_line_id": ("order_lines", "order line"),
    }
    if body.get("delivery_ticket_id") is not None:
        fks["delivery_ticket_id"] = ("delivery_tickets", "delivery ticket")
    exist_body_fks(body, fks)
    check_shape(body, {
        "order_id": {"type": "string", "required": True},
        "order_line_id": {"type": "string", "required": True},
        "units": {"type": "integer", "required": True, "min": 1},
        "reason": {"type": "enum", "required": True, "values": REASONS},
        "delivery_ticket_id": {"type": "string"},
    })
    order = db.get("orders", body["order_id"])
    check_grower_ownership(uid, role, order["grower_id"])
    line = db.get("order_lines", body["order_line_id"])
    if line["order_id"] != order["id"]:
        raise ApiError(ERR_ORDER_LINE_MISMATCH, 409, "order_line_id does not belong to order_id")
    program = db.get("programs", order["program_id"])
    if db.now() > dt_of(program, "return_window_end"):
        raise ApiError(ERR_RETURN_WINDOW_CLOSED, 409, "return window has closed")
    if program.get("returns_untreated_only") and line.get("treatment_option_id"):
        raise ApiError(ERR_RETURN_NOT_ALLOWED_TREATED, 409, "program allows returns of untreated seed only")
    remainder = _returnable_remainder(line)
    if remainder <= 0:
        raise ApiError(ERR_NOTHING_TO_RETURN, 409, "no returnable units remain on the line")
    if body["units"] > remainder:
        raise ApiError(ERR_RETURN_QUANTITY_EXCEEDS, 409, "requested units exceed the returnable remainder")
    ret = db.new_entity("returns", {
        "order_id": order["id"],
        "order_line_id": line["id"],
        "delivery_ticket_id": body.get("delivery_ticket_id"),
        "units": body["units"],
        "reason": body["reason"],
        "status": "REQUESTED",
        "requested_at": db.fmt_ts(db.now()),
        "restocking_fee_cents": None,
        "credit_estimate_cents": None,
        "credit_cents": None,
        "reject_note": None,
    })
    return success_obj(db.public(ret), 201)


@bp.get("/returns/<rid>")
def get_return(rid):
    uid, role = authenticate(READ_ROLES)
    ret = require_fk("returns", rid, "return")
    if role == GROWER:
        order = db.get("orders", ret["order_id"])
        check_grower_ownership(uid, role, order["grower_id"] if order else None)
    return success_obj(db.public(ret), 200)


@bp.get("/returns")
def list_returns():
    uid, role = authenticate(READ_ROLES)
    limit, offset = pagination_params()
    items = db.all_of("returns")
    if role == GROWER:
        own_orders = {o["id"] for o in db.all_of("orders") if o["grower_id"] == uid}
        items = [r for r in items if r["order_id"] in own_orders]
    items = apply_filters(items, ["order_id", "order_line_id", "delivery_ticket_id", "status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(r) for r in page], limit, offset, total, has_more)


@bp.post("/returns/<rid>/approve")
def approve_return(rid):
    authenticate(["DealerAdmin", "SalesRep"])
    ret = require_fk("returns", rid, "return")
    if ret["status"] != "REQUESTED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "only a REQUESTED return can be approved")
    order = db.get("orders", ret["order_id"])
    line = db.get("order_lines", ret["order_line_id"])
    program = db.get("programs", order["program_id"])
    fee_base = ret["units"] * line["discounted_unit_price_cents"]
    ret["restocking_fee_cents"] = rhu_div(fee_base * program["return_restocking_bps"], 10000)
    ret["credit_estimate_cents"] = fee_base - ret["restocking_fee_cents"]
    ret["status"] = "APPROVED"
    db.touch(ret)
    return success_obj(db.public(ret), 200)


@bp.post("/returns/<rid>/receive")
def receive_return(rid):
    authenticate(["DealerAdmin", "SalesRep"])
    ret = require_fk("returns", rid, "return")
    if ret["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "only an APPROVED return can be received")
    line = db.get("order_lines", ret["order_line_id"])
    lot = db.get("inventory_lots", line.get("inventory_lot_id")) if line else None
    if ret["reason"] != "DAMAGED" and lot is not None and lot["status"] != "EXPIRED":
        lot["on_hand_units"] += ret["units"]
        lot["returned_units"] += ret["units"]
        recompute_lot_status(lot)
        db.touch(lot)
    ret["status"] = "RECEIVED"
    db.touch(ret)
    return success_obj(db.public(ret), 200)


@bp.post("/returns/<rid>/credit")
def credit_return(rid):
    authenticate(["DealerAdmin"])
    ret = require_fk("returns", rid, "return")
    if ret["status"] != "RECEIVED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "only a RECEIVED return can be credited")
    order = db.get("orders", ret["order_id"])
    line = db.get("order_lines", ret["order_line_id"])
    program = db.get("programs", order["program_id"])
    # FINAL variant: reprice the order with the returned units removed.
    lines = [l for l in db.all_of("order_lines") if l["order_id"] == order["id"]]
    new_gross = 0
    new_total_units = 0
    for l in lines:
        units = l["units"] - ret["units"] if l["id"] == line["id"] else l["units"]
        adder = 0
        if l.get("treatment_option_id"):
            topt = db.get("treatment_options", l["treatment_option_id"])
            adder = topt["adder_cents_per_unit"] if topt else 0
        new_gross += l["discounted_unit_price_cents"] * units + adder * units
        new_total_units += units
    new_rebate_bps = select_rebate_bps(order, program, new_total_units)
    new_rebate = rhu_div(new_gross * new_rebate_bps, 10000)
    old_net = order["gross_amount_cents"] - order["rebate_amount_cents"]
    new_net = new_gross - new_rebate
    ret["credit_cents"] = old_net - new_net - ret["restocking_fee_cents"]
    line["returned_units"] += ret["units"]
    db.touch(line)
    grower = db.get("growers", order["grower_id"])
    if grower is not None:
        grower["outstanding_balance_cents"] -= ret["credit_cents"]
        db.touch(grower)
    recompute_fulfillment(order)
    db.touch(order)
    ret["status"] = "CREDITED"
    db.touch(ret)
    return success_obj(db.public(ret), 200)


@bp.post("/returns/<rid>/reject")
def reject_return(rid):
    authenticate(["DealerAdmin", "SalesRep"])
    ret = require_fk("returns", rid, "return")
    body = body_json()
    check_shape(body, {"note": {"type": "string"}})
    if ret["status"] not in ("REQUESTED", "APPROVED"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "only a REQUESTED or APPROVED return can be rejected")
    ret["reject_note"] = body.get("note")
    ret["status"] = "REJECTED"
    db.touch(ret)
    return success_obj(db.public(ret), 200)
