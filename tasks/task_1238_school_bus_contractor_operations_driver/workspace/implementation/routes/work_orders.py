"""WorkOrder endpoints."""
from flask import Blueprint, request

import db
from envelope import success_list, success_object
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    raise_err,
)
from middleware import authenticate, get_or_404, require_roles
from services.coverage import maybe_return_bus_to_service
from validation import (
    get_body,
    opt_int,
    paginate,
    pagination_params,
    req_enum,
    req_str,
)

bp = Blueprint("work_orders", __name__)

ROLES = {"SystemAdmin", "ContractorOps", "FleetManager"}

EVENT_TRANSITIONS = {
    "DIAGNOSE": (("OPEN",), "DIAGNOSING"),
    "ORDER_PARTS": (("DIAGNOSING", "IN_REPAIR"), "WAITING_PARTS"),
    "START_REPAIR": (("DIAGNOSING",), "IN_REPAIR"),
    "PARTS_RECEIVED": (("WAITING_PARTS",), "IN_REPAIR"),
    "COMPLETE": (("IN_REPAIR",), "COMPLETED"),
    "CANCEL": (("OPEN", "DIAGNOSING", "WAITING_PARTS", "IN_REPAIR"), "CANCELLED"),
}


@bp.route("/busops/work-orders", methods=["POST"])
def create_work_order():
    body = get_body()
    bus_id = req_str(body, "bus_id")
    category = req_enum(body, "category", ("PM", "REPAIR", "INSPECTION_FOLLOWUP"))
    description = req_str(body, "description")
    actor = authenticate()
    require_roles(actor, {"FleetManager"})
    bus = get_or_404("buses", bus_id, "Bus")
    if bus["status"] == "DECOMMISSIONED":
        raise_err(ERR_ALREADY_TERMINAL, "Bus is DECOMMISSIONED (terminal)")

    rec = {
        "id": db.new_id(),
        "bus_id": bus_id,
        "category": category,
        "description": description,
        "status": "OPEN",
        "labor_minutes": None,
        "parts_cost_cents": None,
    }
    db.stamp_new(rec)
    db.STORES["work_orders"][rec["id"]] = rec

    # Bus transition on work-order creation.
    if bus["status"] == "IN_SERVICE":
        bus["status"] = "IN_SHOP"
        db.touch(bus)
    elif bus["status"] == "GROUNDED" and category in ("REPAIR", "INSPECTION_FOLLOWUP"):
        bus["status"] = "IN_SHOP"
        db.touch(bus)
    return success_object(db.public(rec), status=201)


@bp.route("/busops/work-orders", methods=["GET"])
def list_work_orders():
    limit, offset = pagination_params()
    actor = authenticate()
    require_roles(actor, ROLES)
    items = list(db.all_of("work_orders"))
    bus_id = request.args.get("bus_id")
    status = request.args.get("status")
    if bus_id is not None:
        items = [w for w in items if w["bus_id"] == bus_id]
    if status is not None:
        items = [w for w in items if w["status"] == status]
    page, info = paginate(items, limit, offset)
    return success_list(page, info)


@bp.route("/busops/work-orders/<rid>", methods=["GET"])
def get_work_order(rid):
    actor = authenticate()
    require_roles(actor, ROLES)
    rec = get_or_404("work_orders", rid, "WorkOrder")
    return success_object(db.public(rec))


@bp.route("/busops/work-orders/<rid>/events", methods=["POST"])
def work_order_events(rid):
    body = get_body()
    event_type = req_enum(
        body,
        "event_type",
        ("DIAGNOSE", "ORDER_PARTS", "START_REPAIR", "PARTS_RECEIVED", "COMPLETE", "CANCEL"),
    )
    labor_minutes = opt_int(body, "labor_minutes", default=None, minimum=0)
    parts_cost = opt_int(body, "parts_cost_cents", default=None, minimum=0)
    actor = authenticate()
    require_roles(actor, {"FleetManager"})
    rec = get_or_404("work_orders", rid, "WorkOrder")

    if event_type == "COMPLETE" and (labor_minutes is None or parts_cost is None):
        raise_err(
            ERR_INVALID_REQUEST,
            "COMPLETE requires labor_minutes and parts_cost_cents",
        )

    if rec["status"] in ("COMPLETED", "CANCELLED"):
        raise_err(ERR_ALREADY_TERMINAL, "WorkOrder is in a terminal state")
    from_states, to_state = EVENT_TRANSITIONS[event_type]
    if rec["status"] not in from_states:
        raise_err(
            ERR_INVALID_STATE,
            "WorkOrder in state %s cannot accept event %s" % (rec["status"], event_type),
        )

    rec["status"] = to_state
    if event_type == "COMPLETE":
        rec["labor_minutes"] = labor_minutes
        rec["parts_cost_cents"] = parts_cost
    db.touch(rec)

    if event_type in ("COMPLETE", "CANCEL"):
        bus = db.find("buses", rec["bus_id"])
        if bus is not None:
            maybe_return_bus_to_service(bus, check_inspection_due=True)
    return success_object(db.public(rec))
