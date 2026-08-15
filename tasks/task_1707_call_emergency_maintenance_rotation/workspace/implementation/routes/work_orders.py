"""WorkOrder endpoints."""

from flask import Blueprint, request

from db import store, clock
from errors import (
    ApiError,
    ERR_WORK_ORDER_NOT_FOUND,
    ERR_WORK_ORDER_INVALID_STATE,
    ERR_CALL_TICKET_NOT_FOUND,
    ERR_TECHNICIAN_NOT_FOUND,
    ERR_FATIGUE_REST_REQUIRED,
    ERR_NOT_ASSIGNED_TECHNICIAN,
    ERR_VENDOR_MISMATCH,
    ERR_FOLLOWUP_PARENT_NOT_FINISHED,
    ERR_INVALID_REQUEST,
)
from helpers import (
    body,
    req_string,
    new_id,
    serialize_work_order,
    touch,
    pagination_params,
)
from middleware import get_actor, require_role, require_supervisor_capable
from response import success_object, success_list
from services.calculations import fatigue_blocked

bp = Blueprint("work_orders", __name__)

READ_ROLES = {
    "PropertyAdmin", "Dispatcher", "OnCallTechnician", "MaintenanceSupervisor", "Vendor",
}


@bp.route("/v1/work-orders", methods=["POST"])
def create_work_order():
    actor = get_actor()
    require_role(actor, {"Dispatcher", "MaintenanceSupervisor", "PropertyAdmin"})
    require_supervisor_capable(actor)
    data = body()
    call_ticket_id = data.get("call_ticket_id")
    if not isinstance(call_ticket_id, str) or not call_ticket_id:
        raise ApiError(ERR_INVALID_REQUEST, "call_ticket_id is required", 400)
    title = req_string(data, "title")
    description = req_string(data, "description")
    parent_id = data.get("parent_work_order_id")
    if parent_id is not None and (not isinstance(parent_id, str) or not parent_id):
        raise ApiError(ERR_INVALID_REQUEST, "parent_work_order_id must be a string", 400)
    # Body FK existence (priority 3), left-to-right: ticket then parent
    ticket = store.call_tickets.get(call_ticket_id)
    if ticket is None:
        raise ApiError(ERR_CALL_TICKET_NOT_FOUND, "Call ticket not found", 404)
    parent = None
    if parent_id is not None:
        parent = store.work_orders.get(parent_id)
        if parent is None:
            raise ApiError(ERR_WORK_ORDER_NOT_FOUND, "Parent work order not found", 404)
    # Referential (priority 7): parent must be finished
    if parent is not None and parent["status"] not in ("COMPLETED", "VERIFIED"):
        raise ApiError(ERR_FOLLOWUP_PARENT_NOT_FINISHED, "Parent work order not finished", 409)
    now = clock.now()
    rec = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 0,
        "call_ticket_id": call_ticket_id,
        "unit_id": ticket["unit_id"],
        "parent_work_order_id": parent_id,
        "title": title,
        "description": description,
        "priority": "STANDARD",
        "status": "OPEN",
        "assigned_technician_id": None,
        "_seq": store.next_seq(),
    }
    store.work_orders[rec["id"]] = rec
    return success_object(serialize_work_order(rec), 201)


@bp.route("/v1/work-orders", methods=["GET"])
def list_work_orders():
    actor = get_actor()
    require_role(actor, READ_ROLES)
    limit, offset = pagination_params()
    call_ticket_id = request.args.get("call_ticket_id")
    unit_id = request.args.get("unit_id")
    parent_id = request.args.get("parent_work_order_id")
    status = request.args.get("status")
    assigned = request.args.get("assigned_technician_id")
    items = list(store.work_orders.values())
    if call_ticket_id is not None:
        items = [w for w in items if w["call_ticket_id"] == call_ticket_id]
    if unit_id is not None:
        items = [w for w in items if w["unit_id"] == unit_id]
    if parent_id is not None:
        items = [w for w in items if w["parent_work_order_id"] == parent_id]
    if status is not None:
        items = [w for w in items if w["status"] == status]
    if assigned is not None:
        items = [w for w in items if w["assigned_technician_id"] == assigned]
    items.sort(key=lambda w: (w["created_at"], w["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_work_order(w) for w in page], limit, offset, total)


def _get_wo_or_404(work_order_id):
    rec = store.work_orders.get(work_order_id)
    if rec is None:
        raise ApiError(ERR_WORK_ORDER_NOT_FOUND, "Work order not found", 404)
    return rec


@bp.route("/v1/work-orders/<workOrderId>", methods=["GET"])
def get_work_order(workOrderId):
    actor = get_actor()
    require_role(actor, READ_ROLES)
    rec = _get_wo_or_404(workOrderId)
    return success_object(serialize_work_order(rec))


@bp.route("/v1/work-orders/<workOrderId>/assign", methods=["POST"])
def assign_work_order(workOrderId):
    actor = get_actor()
    require_role(actor, {"MaintenanceSupervisor"})
    require_supervisor_capable(actor)
    rec = _get_wo_or_404(workOrderId)
    data = body()
    technician_id = data.get("technician_id")
    if not isinstance(technician_id, str) or not technician_id:
        raise ApiError(ERR_INVALID_REQUEST, "technician_id is required", 400)
    tech = store.technicians.get(technician_id)
    if tech is None:
        raise ApiError(ERR_TECHNICIAN_NOT_FOUND, "Technician not found", 404)
    if rec["status"] not in ("OPEN", "REOPENED"):
        raise ApiError(ERR_WORK_ORDER_INVALID_STATE, "Work order not OPEN or REOPENED", 409)
    # technician must be ACTIVE and not fatigue-blocked; either failure -> ERR_FATIGUE_REST_REQUIRED
    now = clock.now()
    if tech["status"] != "ACTIVE" or fatigue_blocked(tech, now):
        raise ApiError(
            ERR_FATIGUE_REST_REQUIRED,
            "Technician is inactive or rest-blocked",
            409,
        )
    rec["assigned_technician_id"] = technician_id
    rec["status"] = "ASSIGNED"
    touch(rec)
    return success_object(serialize_work_order(rec))


@bp.route("/v1/work-orders/<workOrderId>/begin", methods=["POST"])
def begin_work_order(workOrderId):
    actor = get_actor()
    require_role(actor, {"OnCallTechnician"})
    rec = _get_wo_or_404(workOrderId)
    if rec["status"] != "ASSIGNED":
        raise ApiError(ERR_WORK_ORDER_INVALID_STATE, "Work order not ASSIGNED", 409)
    if rec["assigned_technician_id"] is None or actor.user_id != rec["assigned_technician_id"]:
        raise ApiError(ERR_NOT_ASSIGNED_TECHNICIAN, "Not the assigned technician", 403)
    rec["status"] = "IN_PROGRESS"
    touch(rec)
    return success_object(serialize_work_order(rec))


@bp.route("/v1/work-orders/<workOrderId>/complete", methods=["POST"])
def complete_work_order(workOrderId):
    actor = get_actor()
    require_role(actor, {"OnCallTechnician", "Vendor"})
    rec = _get_wo_or_404(workOrderId)
    if rec["status"] != "IN_PROGRESS":
        raise ApiError(ERR_WORK_ORDER_INVALID_STATE, "Work order not IN_PROGRESS", 409)
    if actor.role == "OnCallTechnician":
        if rec["assigned_technician_id"] is None or actor.user_id != rec["assigned_technician_id"]:
            raise ApiError(ERR_NOT_ASSIGNED_TECHNICIAN, "Not the assigned technician", 403)
    else:  # Vendor
        engaged = False
        for a in store.vendor_authorizations.values():
            if (
                a["work_order_id"] == rec["id"]
                and a["vendor_id"] == actor.user_id
                and a["status"] in ("AUTHORIZED", "INVOICED")
            ):
                engaged = True
                break
        if not engaged:
            raise ApiError(ERR_VENDOR_MISMATCH, "Vendor is not engaged on this work order", 403)
    rec["status"] = "COMPLETED"
    touch(rec)
    return success_object(serialize_work_order(rec))


@bp.route("/v1/work-orders/<workOrderId>/verify", methods=["POST"])
def verify_work_order(workOrderId):
    actor = get_actor()
    require_role(actor, {"MaintenanceSupervisor"})
    require_supervisor_capable(actor)
    rec = _get_wo_or_404(workOrderId)
    if rec["status"] != "COMPLETED":
        raise ApiError(ERR_WORK_ORDER_INVALID_STATE, "Work order not COMPLETED", 409)
    rec["status"] = "VERIFIED"
    touch(rec)
    return success_object(serialize_work_order(rec))


@bp.route("/v1/work-orders/<workOrderId>/reopen", methods=["POST"])
def reopen_work_order(workOrderId):
    actor = get_actor()
    require_role(actor, {"MaintenanceSupervisor"})
    require_supervisor_capable(actor)
    rec = _get_wo_or_404(workOrderId)
    if rec["status"] != "COMPLETED":
        raise ApiError(ERR_WORK_ORDER_INVALID_STATE, "Work order not COMPLETED", 409)
    rec["status"] = "REOPENED"
    touch(rec)
    return success_object(serialize_work_order(rec))


@bp.route("/v1/work-orders/<workOrderId>/cancel", methods=["POST"])
def cancel_work_order(workOrderId):
    actor = get_actor()
    require_role(actor, {"MaintenanceSupervisor", "PropertyAdmin"})
    require_supervisor_capable(actor)
    rec = _get_wo_or_404(workOrderId)
    if rec["status"] not in ("OPEN", "ASSIGNED", "ON_HOLD", "REOPENED"):
        raise ApiError(ERR_WORK_ORDER_INVALID_STATE, "Work order cannot be cancelled", 409)
    rec["status"] = "CANCELLED"
    touch(rec)
    return success_object(serialize_work_order(rec))
