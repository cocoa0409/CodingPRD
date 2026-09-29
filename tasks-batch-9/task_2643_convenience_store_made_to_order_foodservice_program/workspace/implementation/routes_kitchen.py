"""The make line: station queues, ticket claiming, completion and rework."""

from flask import Blueprint

from apihttp import authenticate, get_body, ok, paginate, query_str
from calc import (
    enter_ready,
    find_kitchen_ticket,
    find_order,
    find_store,
    ready_gate_holds,
    ticket_lines,
    tickets_of_order,
)
from core import db, sort_created, touch
from errors import ApiError
from serialize import kitchen_ticket_out

bp = Blueprint("kitchen", __name__)


def _filter_station_status(tickets):
    station = query_str("station")
    status = query_str("status")
    if station is not None:
        tickets = [t for t in tickets if t["station"] == station]
    if status is not None:
        tickets = [t for t in tickets if t["status"] == status]
    return tickets


@bp.get("/orders/<order_id>/kitchen-tickets")
def list_order_tickets(order_id):
    authenticate((
        "KitchenAssociate", "ShiftLead", "StoreManager", "StoreTerminal", "Customer",
    ))
    order = find_order(order_id)
    tickets = _filter_station_status(tickets_of_order(order["id"]))
    return paginate(sort_created(tickets), kitchen_ticket_out)


@bp.get("/stores/<store_id>/kitchen-queue")
def store_kitchen_queue(store_id):
    authenticate(("KitchenAssociate", "ShiftLead", "StoreManager"))
    store = find_store(store_id)
    tickets = [t for t in db.kitchen_tickets.values() if t["store_id"] == store["id"]]
    tickets = _filter_station_status(tickets)
    tickets.sort(key=lambda t: (t["sequence_position"], t["created_at"], t["_seq"]))
    return paginate(tickets, kitchen_ticket_out)


@bp.get("/kitchen-tickets/<ticket_id>")
def read_kitchen_ticket(ticket_id):
    authenticate(("KitchenAssociate", "ShiftLead", "StoreManager", "StoreTerminal"))
    return ok(kitchen_ticket_out(find_kitchen_ticket(ticket_id)))


@bp.get("/kitchen-tickets")
def list_kitchen_tickets():
    authenticate(("KitchenAssociate", "ShiftLead", "StoreManager"))
    tickets = list(db.kitchen_tickets.values())
    order_id = query_str("order_id")
    order_line_id = query_str("order_line_id")
    if order_id is not None:
        tickets = [t for t in tickets if t["order_id"] == order_id]
    if order_line_id is not None:
        line = db.order_lines.get(order_line_id)
        if line is None:
            tickets = []
        else:
            tickets = [
                t for t in tickets
                if t["order_id"] == line["order_id"] and t["station"] == line["station"]
            ]
    tickets = _filter_station_status(tickets)
    return paginate(sort_created(tickets), kitchen_ticket_out)


@bp.post("/kitchen-tickets/<ticket_id>/start")
def start_kitchen_ticket(ticket_id):
    user_id, _role = authenticate(("KitchenAssociate",))
    ticket = find_kitchen_ticket(ticket_id)
    order = db.orders[ticket["order_id"]]
    if ticket["status"] != "QUEUED":
        raise ApiError("ERR_TICKET_STATE_INVALID")
    if order["production_status"] not in ("PLACED", "IN_PRODUCTION"):
        raise ApiError("ERR_ORDER_PRODUCTION_STATE_INVALID")
    if order["settlement_status"] != "AUTHORIZED":
        raise ApiError("ERR_ORDER_NOT_AUTHORIZED")
    ticket["status"] = "IN_PROGRESS"
    ticket["started_by_user_id"] = user_id
    touch(ticket)
    if order["production_status"] == "PLACED":
        order["production_status"] = "IN_PRODUCTION"
        touch(order)
    return ok(kitchen_ticket_out(ticket))


@bp.post("/kitchen-tickets/<ticket_id>/complete")
def complete_kitchen_ticket(ticket_id):
    user_id, _role = authenticate(("KitchenAssociate",))
    ticket = find_kitchen_ticket(ticket_id)
    order = db.orders[ticket["order_id"]]
    if ticket["status"] != "IN_PROGRESS":
        raise ApiError("ERR_TICKET_STATE_INVALID")
    ticket["status"] = "DONE"
    ticket["completed_by_user_id"] = user_id
    touch(ticket)
    open_left = any(
        t["status"] in ("QUEUED", "IN_PROGRESS") for t in tickets_of_order(order["id"])
    )
    if not open_left and order["production_status"] == "IN_PRODUCTION":
        store = db.stores[order["store_id"]]
        order["production_status"] = "ASSEMBLED"
        touch(order)
        if ready_gate_holds(order):
            enter_ready(order, store)
    return ok(kitchen_ticket_out(ticket))


@bp.post("/kitchen-tickets/<ticket_id>/reopen")
def reopen_kitchen_ticket(ticket_id):
    user_id, _role = authenticate(("ShiftLead",))
    body = get_body()
    body.string("reason", min_len=1)
    ticket = find_kitchen_ticket(ticket_id)
    order = db.orders[ticket["order_id"]]
    if user_id == ticket["completed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if ticket["status"] != "DONE":
        raise ApiError("ERR_TICKET_STATE_INVALID")
    if order["production_status"] not in ("IN_PRODUCTION", "ASSEMBLED"):
        raise ApiError("ERR_ORDER_NOT_REWORKABLE")
    ticket["status"] = "IN_PROGRESS"
    ticket["rework_count"] += 1
    touch(ticket)
    order["rework_count"] += 1
    if order["production_status"] == "ASSEMBLED":
        order["production_status"] = "IN_PRODUCTION"
    touch(order)
    store = db.stores[order["store_id"]]
    rework_cost = sum(
        item["unit_food_cost_cents"] * line["qty"] for line, item in ticket_lines(ticket)
    )
    store["rework_waste_cents_mtd"] += rework_cost
    touch(store)
    return ok(kitchen_ticket_out(ticket))
