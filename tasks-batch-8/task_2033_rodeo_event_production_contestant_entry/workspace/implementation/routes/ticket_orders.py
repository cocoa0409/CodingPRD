"""TicketOrder endpoints: capacity-checked sales and refunds (PRD 3.6)."""
from flask import Blueprint, request

from db import DB, new_id
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import get_or_404, ser, sorted_created, stamp, touch
from util import as_int_range, as_str, body, pagination_args, required

bp = Blueprint("ticket_orders", __name__, url_prefix="/api")


@bp.post("/ticket-orders")
def create_ticket_order():
    auth(["BoxOffice"])
    data = body()
    performance_id = data.get("performance_id")
    if performance_id is not None:
        get_or_404("performances", performance_id)
    if not isinstance(performance_id, str):
        raise ApiError(
            "ERR_VALIDATION", 400, "Missing required field: performance_id"
        )
    section = as_str(required(data, "section"), "section")
    quantity = as_int_range(required(data, "quantity"), "quantity", 1, None)
    unit_price_cents = as_int_range(
        required(data, "unit_price_cents"), "unit_price_cents", 0, None
    )
    perf = DB["performances"][performance_id]
    # Capacity threshold: exactly reaching capacity succeeds.
    sold = sum(
        o["quantity"]
        for o in DB["ticket_orders"].values()
        if o["performance_id"] == performance_id and o["status"] == "PAID"
    )
    if sold + quantity > perf["arena_capacity"]:
        raise ApiError(
            "ERR_CAPACITY_EXCEEDED",
            409,
            "Order would push sold_tickets above arena_capacity",
        )
    rec = {
        "id": new_id(),
        "performance_id": performance_id,
        "section": section,
        "quantity": quantity,
        "unit_price_cents": unit_price_cents,
        "total_cents": quantity * unit_price_cents,
        "status": "PAID",
    }
    stamp(rec)
    DB["ticket_orders"][rec["id"]] = rec
    perf["sold_tickets"] += quantity
    touch(perf)
    return ok(ser(rec), status=201)


@bp.get("/ticket-orders")
def list_ticket_orders():
    auth(ALL_ROLES)
    performance_id = request.args.get("performance_id")
    status = request.args.get("status")
    items = DB["ticket_orders"].values()
    if performance_id is not None:
        items = [o for o in items if o["performance_id"] == performance_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    items = sorted_created(items)
    limit, offset = pagination_args()
    return ok_list(
        [ser(o) for o in items[offset : offset + limit]], len(items), limit, offset
    )


@bp.get("/ticket-orders/<order_id>")
def get_ticket_order(order_id):
    auth(ALL_ROLES)
    return ok(ser(get_or_404("ticket_orders", order_id)))


@bp.post("/ticket-orders/<order_id>/transition")
def transition_ticket_order(order_id):
    auth(["BoxOffice"])
    order = get_or_404("ticket_orders", order_id)
    data = body()
    action = data.get("action")
    if action != "REFUND":
        raise ApiError("ERR_VALIDATION", 400, "Field action must be REFUND")
    if order["status"] != "PAID":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"REFUND is not valid from status {order['status']}",
        )
    order["status"] = "REFUNDED"
    touch(order)
    perf = DB["performances"][order["performance_id"]]
    perf["sold_tickets"] -= order["quantity"]
    touch(perf)
    return ok(ser(order))
