"""SwitchingOrder endpoints: create, get, list, issue, approve, execute, abort.
Segregation of duties: approver must differ from issuer; issuance restricted to
the issuer."""
from flask import Blueprint, request

from db import db
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE_TRANSITION,
    ERR_OWNERSHIP_MISMATCH, ERR_SEGREGATION_OF_DUTIES, ERR_EVENT_NOT_ACTIVE,
)
from services.core import (
    get_body, req_string, paginate, new_common, bump,
    get_work_order, get_switching_order, get_outage, get_event,
    serialize_switching_order, sort_created_asc, check_event_not_closed,
)

bp = Blueprint("switching_orders", __name__)


@bp.route("/om/switching-orders", methods=["POST"])
def create_switching_order():
    user_id, _ = require_roles(["SystemOperator"])
    body = get_body()
    wo_id = req_string(body, "work_order_id")
    steps = body.get("switching_steps")
    if not isinstance(steps, list) or len(steps) < 1:
        raise_err(ERR_INVALID_REQUEST, "switching_steps must contain at least one step")
    for s in steps:
        if not isinstance(s, str):
            raise_err(ERR_INVALID_REQUEST, "switching_steps entries must be strings")
    wo = get_work_order(wo_id)
    if wo["execution_status"] in ("COMPLETED", "CANCELLED"):
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Cannot create a switching order against a terminal work order")
    outage = get_outage(wo["outage_id"])
    event = get_event(outage["storm_event_id"])
    check_event_not_closed(event)

    so = new_common()
    so.update({
        "work_order_id": wo_id,
        "switching_steps": steps,
        "so_status": "DRAFT",
        "issuer_user_id": user_id,
        "approver_user_id": None,
    })
    db.switching_orders[so["id"]] = so
    wo["switching_order_id"] = so["id"]
    bump(wo)
    return success_object(serialize_switching_order(so), status=201)


@bp.route("/om/switching-orders/<sid>", methods=["GET"])
def get_one(sid):
    require_roles(ALL_ROLES)
    so = get_switching_order(sid)
    return success_object(serialize_switching_order(so))


@bp.route("/om/switching-orders", methods=["GET"])
def list_switching_orders():
    require_roles(ALL_ROLES)
    items = list(db.switching_orders.values())
    wo_id = request.args.get("work_order_id")
    status = request.args.get("so_status")
    if wo_id is not None:
        items = [s for s in items if s["work_order_id"] == wo_id]
    if status is not None:
        items = [s for s in items if s["so_status"] == status]
    items = sort_created_asc(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_switching_order(s) for s in page], limit, offset, total)


@bp.route("/om/switching-orders/<sid>/issue", methods=["POST"])
def issue(sid):
    user_id, _ = require_roles(["SystemOperator"])
    so = get_switching_order(sid)
    if so["so_status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"SwitchingOrder in {so['so_status']} cannot be issued")
    if user_id != so["issuer_user_id"]:
        raise_err(ERR_OWNERSHIP_MISMATCH, "Only the issuer may issue the order")
    so["so_status"] = "ISSUED"
    bump(so)
    return success_object(serialize_switching_order(so))


@bp.route("/om/switching-orders/<sid>/approve", methods=["POST"])
def approve(sid):
    user_id, _ = require_roles(["SystemOperator"])
    so = get_switching_order(sid)
    if so["so_status"] != "ISSUED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"SwitchingOrder in {so['so_status']} cannot be approved")
    if user_id == so["issuer_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES,
                  "Approver must differ from the issuer")
    so["so_status"] = "APPROVED"
    so["approver_user_id"] = user_id
    bump(so)
    return success_object(serialize_switching_order(so))


@bp.route("/om/switching-orders/<sid>/execute", methods=["POST"])
def execute(sid):
    user_id, _ = require_roles(["SystemOperator"])
    so = get_switching_order(sid)
    if so["so_status"] != "APPROVED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"SwitchingOrder in {so['so_status']} cannot be executed")
    wo = get_work_order(so["work_order_id"])
    if wo["execution_status"] in ("COMPLETED", "CANCELLED"):
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Linked work order is terminal")
    outage = get_outage(wo["outage_id"])
    event = get_event(outage["storm_event_id"])
    check_event_not_closed(event)
    if event["event_status"] != "ACTIVE":
        raise_err(ERR_EVENT_NOT_ACTIVE,
                  "Switching execution requires the event ACTIVE")
    so["so_status"] = "EXECUTED"
    bump(so)
    return success_object(serialize_switching_order(so))


@bp.route("/om/switching-orders/<sid>/abort", methods=["POST"])
def abort(sid):
    user_id, _ = require_roles(["SystemOperator"])
    so = get_switching_order(sid)
    if so["so_status"] not in ("DRAFT", "ISSUED", "APPROVED"):
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"SwitchingOrder in {so['so_status']} cannot be aborted")
    so["so_status"] = "ABORTED"
    bump(so)
    wo = db.work_orders.get(so["work_order_id"])
    if wo is not None and wo.get("switching_order_id") == sid:
        wo["switching_order_id"] = None
        bump(wo)
    return success_object(serialize_switching_order(so))
