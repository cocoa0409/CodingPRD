"""Restock order and service ticket routes."""
from flask import Blueprint

import db
from auth import require_roles
from envelope import ok, ok_list
from errors import err
from helpers import (body, create_restock_order, get_or_404, paged,
                     pagination_params, qparam, req_datetime, req_enum,
                     req_int, req_str)
from util import new_record, parse_datetime, touch

bp = Blueprint("service", __name__)

ISSUE_CODES = {"JAM", "DOOR_FAULT", "NETWORK", "DISPLAY", "PLANOGRAM_CHANGE", "PREVENTIVE"}


# --- RestockOrder ----------------------------------------------------------

@bp.post("/restock-orders")
def create_restock():
    require_roles("VendingTechnician")
    b = body()
    machine_id = req_str(b, "machine_id")
    slot_id = req_str(b, "slot_id")
    qty = req_int(b, "qty", minimum=1)
    get_or_404(db.machines, machine_id, "ERR_MACHINE_NOT_FOUND")
    slot = get_or_404(db.slots, slot_id, "ERR_SLOT_NOT_FOUND")
    item = db.items.get(slot["item_id"])
    if item is not None and item["status"] != "ACTIVE":
        err("ERR_ITEM_DISCONTINUED", "item is DISCONTINUED")
    if slot["machine_id"] != machine_id:
        err("ERR_SLOT_ITEM_MISMATCH", "slot does not belong to machine")
    if item is not None and item["serialized_tracking"]:
        err("ERR_ITEM_NOT_SERIALIZED_CATEGORY",
            "restock orders require a non-serialized slot item")
    rec = create_restock_order(machine_id, slot, qty, "MANUAL")
    return ok(rec, 201)


@bp.get("/restock-orders")
def list_restocks():
    require_roles("Any")
    limit, offset = pagination_params()
    rows = list(db.restock_orders.values())
    for param in ("machine_id", "slot_id", "item_id", "status"):
        v = qparam(param)
        if v is not None:
            rows = [o for o in rows if o.get(param) == v]
    page, total = paged(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/restock-orders/<orderId>")
def get_restock(orderId):
    require_roles("Any")
    return ok(get_or_404(db.restock_orders, orderId, "ERR_RESTOCK_ORDER_NOT_FOUND"))


@bp.post("/restock-orders/<orderId>/pick")
def pick_restock(orderId):
    require_roles("VendingTechnician")
    body()
    order = get_or_404(db.restock_orders, orderId, "ERR_RESTOCK_ORDER_NOT_FOUND")
    if order["status"] != "SUGGESTED":
        err("ERR_RESTOCK_ORDER_INVALID_STATE", "pick requires SUGGESTED")
    order["status"] = "PICKED"
    touch(order)
    return ok(order)


@bp.post("/restock-orders/<orderId>/load")
def load_restock(orderId):
    require_roles("VendingTechnician")
    body()
    order = get_or_404(db.restock_orders, orderId, "ERR_RESTOCK_ORDER_NOT_FOUND")
    machine = db.machines.get(order["machine_id"])
    if machine is None or machine["status"] not in ("ACTIVE", "OFFLINE"):
        err("ERR_MACHINE_NOT_ACTIVE", "load requires machine ACTIVE or OFFLINE")
    if order["status"] != "PICKED":
        err("ERR_RESTOCK_ORDER_INVALID_STATE", "load requires PICKED")
    slot = db.slots.get(order["slot_id"])
    if slot is not None and slot["on_hand_qty"] + order["qty"] > slot["capacity"]:
        err("ERR_CAPACITY_EXCEEDED", "load would exceed slot capacity")
    order["status"] = "LOADED"
    touch(order)
    if slot is not None:
        slot["on_hand_qty"] += order["qty"]
        touch(slot)
    return ok(order)


@bp.post("/restock-orders/<orderId>/cancel")
def cancel_restock(orderId):
    require_roles("VendingTechnician")
    body()
    order = get_or_404(db.restock_orders, orderId, "ERR_RESTOCK_ORDER_NOT_FOUND")
    if order["status"] not in ("SUGGESTED", "PICKED"):
        err("ERR_RESTOCK_ORDER_INVALID_STATE",
            "cancel requires SUGGESTED or PICKED")
    order["status"] = "CANCELLED"
    touch(order)
    return ok(order)


# --- ServiceTicket ---------------------------------------------------------

@bp.post("/service-tickets")
def create_ticket():
    require_roles("VendingTechnician")
    b = body()
    machine_id = req_str(b, "machine_id")
    issue = req_enum(b, "issue_code", ISSUE_CODES)
    ws = req_datetime(b, "window_start")
    we = req_datetime(b, "window_end")
    if parse_datetime(we) <= parse_datetime(ws):
        err("ERR_VALIDATION_FAILED", "window_end must be > window_start")
    get_or_404(db.machines, machine_id, "ERR_MACHINE_NOT_FOUND")
    nws, nwe = parse_datetime(ws), parse_datetime(we)
    for t in db.service_tickets.values():
        if (t["machine_id"] == machine_id and t["status"] in ("OPEN", "IN_PROGRESS")):
            ows, owe = parse_datetime(t["window_start"]), parse_datetime(t["window_end"])
            # half-open intersection; adjacency (end == start) allowed
            if nws < owe and nwe > ows:
                err("ERR_SERVICE_WINDOW_OVERLAP",
                    "service window intersects another open ticket")
    rec = new_record({
        "machine_id": machine_id,
        "issue_code": issue,
        "window_start": ws,
        "window_end": we,
        "status": "OPEN",
    })
    db.service_tickets[rec["id"]] = rec
    return ok(rec, 201)


@bp.get("/service-tickets")
def list_tickets():
    require_roles("Any")
    limit, offset = pagination_params()
    rows = list(db.service_tickets.values())
    for param in ("machine_id", "status"):
        v = qparam(param)
        if v is not None:
            rows = [t for t in rows if t.get(param) == v]
    page, total = paged(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/service-tickets/<ticketId>")
def get_ticket(ticketId):
    require_roles("Any")
    return ok(get_or_404(db.service_tickets, ticketId, "ERR_SERVICE_TICKET_NOT_FOUND"))


@bp.post("/service-tickets/<ticketId>/start")
def start_ticket(ticketId):
    require_roles("VendingTechnician")
    body()
    ticket = get_or_404(db.service_tickets, ticketId, "ERR_SERVICE_TICKET_NOT_FOUND")
    machine = db.machines.get(ticket["machine_id"])
    if machine is None or machine["status"] not in ("ACTIVE", "OFFLINE"):
        err("ERR_MACHINE_NOT_ACTIVE", "service start requires machine ACTIVE or OFFLINE")
    if ticket["status"] != "OPEN":
        err("ERR_SERVICE_TICKET_INVALID_STATE", "start requires OPEN")
    if not (parse_datetime(ticket["window_start"]) <= db.clock
            < parse_datetime(ticket["window_end"])):
        err("ERR_SERVICE_WINDOW_NOT_REACHED",
            "logical clock outside [window_start, window_end)")
    ticket["status"] = "IN_PROGRESS"
    touch(ticket)
    # machine enters IN_SERVICE; its open restock orders are cancelled
    machine["status"] = "IN_SERVICE"
    touch(machine)
    for o in db.restock_orders.values():
        if o["machine_id"] == machine["id"] and o["status"] in ("SUGGESTED", "PICKED"):
            o["status"] = "CANCELLED"
            touch(o)
    return ok(ticket)


@bp.post("/service-tickets/<ticketId>/resolve")
def resolve_ticket(ticketId):
    require_roles("VendingTechnician")
    body()
    ticket = get_or_404(db.service_tickets, ticketId, "ERR_SERVICE_TICKET_NOT_FOUND")
    if ticket["status"] != "IN_PROGRESS":
        err("ERR_SERVICE_TICKET_INVALID_STATE", "resolve requires IN_PROGRESS")
    ticket["status"] = "RESOLVED"
    touch(ticket)
    machine = db.machines.get(ticket["machine_id"])
    if machine is not None and machine["status"] == "IN_SERVICE":
        machine["status"] = "ACTIVE"
        touch(machine)
        # post-service restock sweep (AUTO_PAR)
        for slot in db.slots.values():
            if slot["machine_id"] != machine["id"]:
                continue
            item = db.items.get(slot["item_id"])
            if item is None or item["serialized_tracking"]:
                continue
            if slot["on_hand_qty"] <= slot["par_level"]:
                if not any(o["slot_id"] == slot["id"]
                           and o["status"] in ("SUGGESTED", "PICKED")
                           for o in db.restock_orders.values()):
                    create_restock_order(machine["id"], slot,
                                         slot["capacity"] - slot["on_hand_qty"],
                                         "AUTO_PAR")
    return ok(ticket)
