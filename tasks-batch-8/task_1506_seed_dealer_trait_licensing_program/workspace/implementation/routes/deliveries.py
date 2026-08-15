"""DeliveryTicket endpoints: scheduling (window/capacity/remainder),
completion, cancellation."""

import db
from errors import (
    ApiError,
    ERR_INVALID_STATE_TRANSITION,
    ERR_ORDER_LINE_MISMATCH,
    ERR_DELIVERY_OUTSIDE_WINDOW,
    ERR_DELIVERY_TOO_EARLY,
    ERR_DELIVERY_CAPACITY_EXCEEDED,
    ERR_DELIVERY_EXCEEDS_REMAINING,
)
from middleware import authenticate, check_grower_ownership, GROWER
from response import success_obj, success_list
from routes import make_blueprint
from services import recompute_lot_status, recompute_fulfillment
from util import body_json, check_shape, pagination_params, paginate, apply_filters, require_fk, exist_body_fks, dt_of

bp = make_blueprint("deliveries")

READ_ROLES = ["DealerAdmin", "SalesRep", "Grower"]
TICKET_TYPES = ["DELIVERY", "PICKUP"]


@bp.post("/delivery-tickets")
def create_ticket():
    authenticate(["DealerAdmin", "SalesRep"])
    body = body_json()
    exist_body_fks(body, {
        "order_id": ("orders", "order"),
        "order_line_id": ("order_lines", "order line"),
    })
    check_shape(body, {
        "order_id": {"type": "string", "required": True},
        "order_line_id": {"type": "string", "required": True},
        "type": {"type": "enum", "required": True, "values": TICKET_TYPES},
        "scheduled_date": {"type": "datetime", "required": True},
        "units": {"type": "integer", "required": True, "min": 1},
    })
    order = db.get("orders", body["order_id"])
    line = db.get("order_lines", body["order_line_id"])
    if line["order_id"] != order["id"]:
        raise ApiError(ERR_ORDER_LINE_MISMATCH, 409, "order_line_id does not belong to order_id")
    if order["status"] != "CONFIRMED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "deliveries schedule against CONFIRMED orders only")
    program = db.get("programs", order["program_id"])
    scheduled = dt_of(body, "scheduled_date")
    if not (dt_of(program, "delivery_window_start") <= scheduled <= dt_of(program, "delivery_window_end")):
        raise ApiError(ERR_DELIVERY_OUTSIDE_WINDOW, 409, "scheduled_date outside the delivery window")
    # Daily capacity over the program's tickets sharing the UTC calendar date.
    target_date = scheduled.date()
    program_order_ids = {o["id"] for o in db.all_of("orders") if o["program_id"] == program["id"]}
    load = 0
    for t in db.all_of("delivery_tickets"):
        if (
            t["order_id"] in program_order_ids
            and t["status"] in ("SCHEDULED", "COMPLETED")
            and dt_of(t, "scheduled_date").date() == target_date
        ):
            load += t["units"]
    if load + body["units"] > program["daily_delivery_capacity_units"]:
        raise ApiError(ERR_DELIVERY_CAPACITY_EXCEEDED, 409, "daily delivery capacity exceeded")
    scheduled_on_line = sum(
        t["units"] for t in db.all_of("delivery_tickets")
        if t["order_line_id"] == line["id"] and t["status"] == "SCHEDULED"
    )
    remainder = line["reserved_units"] - line["delivered_units"] - scheduled_on_line
    if body["units"] > remainder:
        raise ApiError(ERR_DELIVERY_EXCEEDS_REMAINING, 409, "units exceed the line's deliverable remainder")
    ticket = db.new_entity("delivery_tickets", {
        "order_id": order["id"],
        "order_line_id": line["id"],
        "lot_id": line.get("inventory_lot_id"),
        "type": body["type"],
        "scheduled_date": body["scheduled_date"],
        "units": body["units"],
        "status": "SCHEDULED",
        "completed_at": None,
    })
    return success_obj(db.public(ticket), 201)


@bp.get("/delivery-tickets/<tid>")
def get_ticket(tid):
    uid, role = authenticate(READ_ROLES)
    ticket = require_fk("delivery_tickets", tid, "delivery ticket")
    if role == GROWER:
        order = db.get("orders", ticket["order_id"])
        check_grower_ownership(uid, role, order["grower_id"] if order else None)
    return success_obj(db.public(ticket), 200)


@bp.get("/delivery-tickets")
def list_tickets():
    uid, role = authenticate(READ_ROLES)
    limit, offset = pagination_params()
    items = db.all_of("delivery_tickets")
    if role == GROWER:
        own_orders = {o["id"] for o in db.all_of("orders") if o["grower_id"] == uid}
        items = [t for t in items if t["order_id"] in own_orders]
    items = apply_filters(items, ["order_id", "order_line_id", "lot_id", "status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(t) for t in page], limit, offset, total, has_more)


@bp.post("/delivery-tickets/<tid>/complete")
def complete_ticket(tid):
    authenticate(["DealerAdmin", "SalesRep"])
    ticket = require_fk("delivery_tickets", tid, "delivery ticket")
    if ticket["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "only a SCHEDULED ticket can be completed")
    order = db.get("orders", ticket["order_id"])
    if order is None or order["status"] != "CONFIRMED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "parent order is not CONFIRMED")
    if db.now() < dt_of(ticket, "scheduled_date"):
        raise ApiError(ERR_DELIVERY_TOO_EARLY, 409, "cannot complete before scheduled_date")
    units = ticket["units"]
    lot = db.get("inventory_lots", ticket.get("lot_id"))
    if lot is not None:
        lot["reserved_units"] -= units
        lot["on_hand_units"] -= units
        lot["delivered_units"] += units
        recompute_lot_status(lot)
        db.touch(lot)
    line = db.get("order_lines", ticket["order_line_id"])
    if line is not None:
        line["reserved_units"] -= units
        line["delivered_units"] += units
        db.touch(line)
    recompute_fulfillment(order)
    db.touch(order)
    ticket["completed_at"] = db.fmt_ts(db.now())
    ticket["status"] = "COMPLETED"
    db.touch(ticket)
    return success_obj(db.public(ticket), 200)


@bp.post("/delivery-tickets/<tid>/cancel")
def cancel_ticket(tid):
    authenticate(["DealerAdmin", "SalesRep"])
    ticket = require_fk("delivery_tickets", tid, "delivery ticket")
    if ticket["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "only a SCHEDULED ticket can be cancelled")
    ticket["status"] = "CANCELLED"
    db.touch(ticket)
    return success_obj(db.public(ticket), 200)
