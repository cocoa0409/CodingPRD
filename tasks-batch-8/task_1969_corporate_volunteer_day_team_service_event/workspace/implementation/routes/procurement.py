"""ProcurementOrder endpoints with segregation of duties and the fiscal gate."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_err,
    ERR_ORDER_NOT_FOUND,
    ERR_EVENT_NOT_FOUND,
    ERR_PROJECT_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES_VIOLATION,
    ERR_INVALID_ORDER_TRANSITION,
    ERR_EVENT_STATE_FORBIDS_WRITE,
    ERR_PROJECT_EVENT_MISMATCH,
    ERR_BUDGET_WOULD_EXCEED,
    ERR_VALIDATION,
)
from middleware import authenticate, body
from response import success_object, success_list
from services import calc
from services.core import mint, bump, touch, refresh_event, ser_order, sort_entities
from validate import req_string, req_present, opt_string

bp = Blueprint("procurement", __name__)

EVENT_WRITABLE = ("PLANNING", "REGISTRATION_OPEN", "REGISTRATION_LOCKED")


def load_order(order_id):
    o = db.orders.get(order_id)
    if o is None:
        raise_err(ERR_ORDER_NOT_FOUND, "procurement order not found")
    return o


def _validate_lines(lines):
    if not isinstance(lines, list) or len(lines) < 1:
        raise_err(ERR_VALIDATION, "lines must contain at least one line")
    total = 0
    for line in lines:
        if not isinstance(line, dict):
            raise_err(ERR_VALIDATION, "each line must be an object")
        item_name = line.get("item_name")
        quantity = line.get("quantity")
        unit_cost = line.get("unit_cost_cents")
        if not isinstance(item_name, str):
            raise_err(ERR_VALIDATION, "line.item_name must be a string")
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
            raise_err(ERR_VALIDATION, "line.quantity must be an integer >= 1")
        if not isinstance(unit_cost, int) or isinstance(unit_cost, bool) or unit_cost < 0:
            raise_err(ERR_VALIDATION, "line.unit_cost_cents must be an integer >= 0")
        total += calc.procurement_line_total(quantity, unit_cost)
    return total


@bp.post("/procurement-orders")
def create_order():
    uid, _, _ = authenticate(["CommunityEngagementManager"])
    data = body()
    event_id = req_string(data, "event_id")
    project_id = req_string(data, "project_id")
    lines = req_present(data, "lines")
    # body FK existence (step 5)
    ev = db.events.get(event_id)
    if ev is None:
        raise_err(ERR_EVENT_NOT_FOUND, "service event not found")
    project = db.projects.get(project_id)
    if project is None:
        raise_err(ERR_PROJECT_NOT_FOUND, "service project not found")
    # state (step 6): event writable
    if ev["status"] not in EVENT_WRITABLE:
        raise_err(ERR_EVENT_STATE_FORBIDS_WRITE, "event state forbids procurement writes")
    # field validation (step 11)
    total = _validate_lines(lines)
    # cross-reference (step 12)
    if project["event_id"] != ev["id"]:
        raise_err(ERR_PROJECT_EVENT_MISMATCH, "project does not belong to this event")
    o = mint()
    o.update(
        {
            "event_id": ev["id"],
            "project_id": project["id"],
            "lines": lines,
            "order_total_cents": total,
            "status": "DRAFT",
            "created_by_user_id": uid,
            "rejection_reason": None,
        }
    )
    db.orders[o["id"]] = o
    return success_object(ser_order(o), 201)


@bp.get("/procurement-orders")
def list_orders():
    authenticate(["Any"])
    items = list(db.orders.values())
    for param in ("event_id", "project_id", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [o for o in items if str(o.get(param)) == val]
    return success_list([ser_order(o) for o in sort_entities(items)])


@bp.get("/procurement-orders/<orderId>")
def get_order(orderId):
    authenticate(["Any"])
    return success_object(ser_order(load_order(orderId)))


@bp.post("/procurement-orders/<orderId>/submit")
def submit_order(orderId):
    authenticate(["CommunityEngagementManager"])
    o = load_order(orderId)
    if o["status"] not in ("DRAFT", "REJECTED"):
        raise_err(ERR_INVALID_ORDER_TRANSITION, "only DRAFT or REJECTED orders can be submitted")
    ev = db.events.get(o["event_id"])
    if ev is None or ev["status"] not in EVENT_WRITABLE:
        raise_err(ERR_EVENT_STATE_FORBIDS_WRITE, "event state forbids procurement writes")
    o["status"] = "SUBMITTED"
    o["rejection_reason"] = None
    bump(o)
    refresh_event(ev)
    return success_object(ser_order(o))


@bp.post("/procurement-orders/<orderId>/approve")
def approve_order(orderId):
    uid, _, _ = authenticate(["ProcurementOfficer"])
    o = load_order(orderId)
    # segregation of duties (pipeline step 3)
    if uid == o["created_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES_VIOLATION, "approver must differ from the order creator")
    # state (step 6)
    if o["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_ORDER_TRANSITION, "only a SUBMITTED order can be approved")
    ev = db.events.get(o["event_id"])
    if ev is None or ev["status"] not in EVENT_WRITABLE:
        raise_err(ERR_EVENT_STATE_FORBIDS_WRITE, "event state forbids procurement approval")
    # fiscal gate (step 13): projected spend already includes this SUBMITTED order
    projected, _ = calc.event_spend(ev)
    if projected > ev["budget_cents"]:
        raise_err(ERR_BUDGET_WOULD_EXCEED, "projected spend would exceed the event budget")
    o["status"] = "APPROVED"
    bump(o)
    refresh_event(ev)
    return success_object(ser_order(o))


@bp.post("/procurement-orders/<orderId>/reject")
def reject_order(orderId):
    uid, _, _ = authenticate(["ProcurementOfficer"])
    o = load_order(orderId)
    if uid == o["created_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES_VIOLATION, "rejector must differ from the order creator")
    if o["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_ORDER_TRANSITION, "only a SUBMITTED order can be rejected")
    o["status"] = "REJECTED"
    o["rejection_reason"] = opt_string(body(), "rejection_reason")
    bump(o)
    ev = db.events.get(o["event_id"])
    if ev is not None:
        refresh_event(ev)
    return success_object(ser_order(o))


@bp.post("/procurement-orders/<orderId>/receive")
def receive_order(orderId):
    authenticate(["CommunityEngagementManager"])
    o = load_order(orderId)
    if o["status"] != "APPROVED":
        raise_err(ERR_INVALID_ORDER_TRANSITION, "only an APPROVED order can be received")
    o["status"] = "RECEIVED"
    bump(o)
    project = db.projects.get(o["project_id"])
    if project is not None:
        touch(project)
    ev = db.events.get(o["event_id"])
    if ev is not None:
        refresh_event(ev)
    return success_object(ser_order(o))


@bp.post("/procurement-orders/<orderId>/cancel")
def cancel_order(orderId):
    authenticate(["CommunityEngagementManager"])
    o = load_order(orderId)
    if o["status"] not in ("DRAFT", "SUBMITTED", "APPROVED"):
        raise_err(ERR_INVALID_ORDER_TRANSITION, "order cannot be cancelled from its current status")
    o["status"] = "CANCELLED"
    bump(o)
    ev = db.events.get(o["event_id"])
    if ev is not None:
        refresh_event(ev)
    return success_object(ser_order(o))
