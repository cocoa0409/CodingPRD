"""Ticket orders: pricing, capacity and the two independent status axes."""
from flask import Blueprint

import calc
from core import (
    ALL_ROLES, ApiError, authenticate, body, db, fetch, get_enum, get_int,
    get_str, new_row, ok, ok_list, own_check, paged, pagination, public, q,
    q_enum, rows, touch,
)

bp = Blueprint("tickets", __name__)

PAYMENT_STATUSES = ("UNBILLED", "INVOICED", "PAID", "REFUNDED")
ORDER_TYPES = ("TABLE", "SEAT")


@bp.post("/api/ticket-orders")
def create_order():
    uid, role = authenticate(("EventOrganizer", "Bidder"))
    payload = body()
    event_id = get_str(payload, "event_id")
    bidder_id = get_str(payload, "bidder_id")
    table_id = get_str(payload, "table_id")
    order_type = get_enum(payload, "order_type", ORDER_TYPES)
    seat_count = get_int(payload, "seat_count", minimum=1)

    event = fetch("events", event_id)
    fetch("bidders", bidder_id)
    table = fetch("tables", table_id)
    if role == "Bidder":
        own_check(bidder_id == uid)
    calc.gate(event, restricted=True)

    if order_type == "TABLE" and seat_count != table["seat_count"]:
        raise ApiError("ERR_SEAT_CAPACITY_EXCEEDED",
                       "a TABLE order must buy every seat at the table")
    if table["seats_reserved"] + seat_count > table["seat_count"]:
        raise ApiError("ERR_SEAT_CAPACITY_EXCEEDED", "table capacity exceeded")

    priced = calc.price_ticket_order(event, table, order_type, seat_count)
    order = new_row(event_id=event_id, bidder_id=bidder_id, table_id=table_id,
                    invoice_id=None, order_type=order_type, seat_count=seat_count,
                    payment_status="UNBILLED", seating_status="UNSEATED", **priced)
    db.orders[order["id"]] = order

    calc.recompute_table(table)
    for hold in rows("holds"):
        if hold["status"] == "HELD" and hold["table_id"] == table_id \
                and hold["bidder_id"] == bidder_id:
            hold["status"] = "CONSUMED"
            touch(hold)
    return ok(public(order), 201)


@bp.get("/api/ticket-orders/<oid>")
def read_order(oid):
    authenticate(ALL_ROLES)
    return ok(public(fetch("orders", oid)))


@bp.get("/api/ticket-orders")
def list_orders():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    event_id = q("event_id")
    bidder_id = q("bidder_id")
    table_id = q("table_id")
    invoice_id = q("invoice_id")
    payment_status = q_enum("payment_status", PAYMENT_STATUSES)
    items = [o for o in rows("orders")
             if (event_id is None or o["event_id"] == event_id)
             and (bidder_id is None or o["bidder_id"] == bidder_id)
             and (table_id is None or o["table_id"] == table_id)
             and (invoice_id is None or o["invoice_id"] == invoice_id)
             and (payment_status is None or o["payment_status"] == payment_status)]
    window, total = paged(items, limit, offset)
    return ok_list(window, limit, offset, total)


@bp.post("/api/ticket-orders/<oid>/assign-seats")
def assign_seats(oid):
    authenticate(("EventOrganizer",))
    order = fetch("orders", oid)
    calc.gate(fetch("events", order["event_id"]))
    if order["seating_status"] != "UNSEATED":
        raise ApiError("ERR_INVALID_STATE", "order is not UNSEATED")
    table = db.tables.get(order["table_id"])
    if table is not None:
        others = 0
        for other in db.orders.values():
            if other["table_id"] != table["id"] or other["id"] == order["id"]:
                continue
            if other["payment_status"] == "REFUNDED" or other["seating_status"] == "RELEASED":
                continue
            others += other["seat_count"]
        if others + order["seat_count"] > table["seat_count"]:
            raise ApiError("ERR_SEAT_CAPACITY_EXCEEDED", "table capacity exceeded")
    order["seating_status"] = "SEATED"
    touch(order)
    return ok(public(order))


@bp.post("/api/ticket-orders/<oid>/cancel")
def cancel_order(oid):
    authenticate(("EventOrganizer",))
    order = fetch("orders", oid)
    calc.gate(fetch("events", order["event_id"]))
    if order["payment_status"] not in ("UNBILLED", "PAID"):
        raise ApiError("ERR_INVALID_STATE", "order cannot be cancelled from %s"
                       % order["payment_status"])
    order["payment_status"] = "REFUNDED"
    order["seating_status"] = "RELEASED"
    touch(order)
    table = db.tables.get(order["table_id"])
    if table is not None:
        calc.recompute_table(table)
    return ok(public(order))
