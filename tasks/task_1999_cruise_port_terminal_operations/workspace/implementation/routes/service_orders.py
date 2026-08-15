"""Service orders: request, approve (SoD + posture), reject, start, complete,
cancel (PRD 3.7)."""

from flask import Blueprint, request

import db
import services
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_POSTURE_EMERGENCY,
    ERR_SERVICE_WINDOW_OUTSIDE_BERTH, ERR_SEGREGATION_OF_DUTIES,
    ERR_CONSTRAINED_REQUIRES_HARBORMASTER, ERR_WASTE_BEFORE_PROVISIONING,
    ERR_APRON_CAPACITY, ERR_VESSEL_SCOPE,
)
from middleware import authenticate, ANY, scope_call
from response import success_obj, success_list
from util import body_json, check_shape, pagination_params, paginate, apply_filters

bp = Blueprint("service_orders", __name__, url_prefix="/port-ops")

_REQUESTABLE_CALL_STATES = ("SCHEDULED", "DELAYED", "ARRIVED", "TURNAROUND")


def _get_order_or_404(order_id):
    order = db.get("service_orders", order_id)
    if order is None:
        raise ApiError(ERR_NOT_FOUND, 404, "service order not found")
    return order


@bp.route("/port-calls/<call_id>/service-orders", methods=["POST"])
def create_order(call_id):
    user_id, role = authenticate({"VesselAgent"})
    call = db.get("port_calls", call_id)
    if call is None:
        raise ApiError(ERR_NOT_FOUND, 404, "port call not found")
    scope_call(user_id, role, call)
    body = body_json()
    check_shape(body, {
        "kind": {"type": "enum", "required": True, "values": {"PROVISIONING", "WASTE_OFFLOAD"}},
        "units": {"type": "integer", "required": True, "min": 1},
        "window_start": {"type": "datetime", "required": True},
        "window_end": {"type": "datetime", "required": True},
    })
    if call["status"] not in _REQUESTABLE_CALL_STATES:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "service orders may only be requested in a pre-departure call state")
    order = db.new_entity("service_orders", {
        "port_call_id": call["id"],
        "kind": body["kind"],
        "units": body["units"],
        "window_start": body["window_start"],
        "window_end": body["window_end"],
        "requested_by_user_id": user_id,
        "approved_by_user_id": None,
        "surcharge_applied": False,
        "actual_units": None,
        "reject_reason": None,
        "status": "REQUESTED",
    })
    return success_obj(db.public(order), code=201)


@bp.route("/service-orders", methods=["GET"])
def list_orders():
    user_id, role = authenticate(ANY)
    limit, offset = pagination_params()
    items = db.all_of("service_orders")
    if role == "VesselAgent":
        port_call_id = request.args.get("port_call_id")
        if port_call_id is not None:
            call = db.get("port_calls", port_call_id)
            if call is not None and call["vessel_id"] != user_id:
                raise ApiError(ERR_VESSEL_SCOPE, 403,
                               "vessel agent may only read its own vessel's calls")
        items = [
            o for o in items
            if (db.get("port_calls", o["port_call_id"]) or {}).get("vessel_id") == user_id
        ]
    items = apply_filters(items, ["port_call_id", "status", "kind"])
    page, total, has_more = paginate([db.public(o) for o in items], limit, offset)
    return success_list(page, limit, offset, total, has_more)


@bp.route("/service-orders/<order_id>", methods=["GET"])
def get_order(order_id):
    user_id, role = authenticate(ANY)
    order = _get_order_or_404(order_id)
    if role == "VesselAgent":
        call = db.get("port_calls", order["port_call_id"])
        if call is None or call["vessel_id"] != user_id:
            raise ApiError(ERR_VESSEL_SCOPE, 403,
                           "vessel agent may only read its own vessel's calls")
    return success_obj(db.public(order))


@bp.route("/service-orders/<order_id>/approve", methods=["POST"])
def approve(order_id):
    user_id, role = authenticate({"TerminalOperator", "Harbormaster"})
    order = _get_order_or_404(order_id)
    if order["status"] != "REQUESTED":
        raise ApiError(ERR_INVALID_STATE, 409, "approve requires status REQUESTED")
    call = db.get("port_calls", order["port_call_id"])
    term = services.terminal_of_call(call)
    posture, _a, _o, _f = services.posture_of(term)
    # Priority 9: posture gate.
    if posture == "EMERGENCY":
        raise ApiError(ERR_POSTURE_EMERGENCY, 409,
                       "terminal posture is EMERGENCY; approval is gated")
    # Priority 13: requested window contained in a live assignment window.
    if not services.order_window_contained(order, call["id"]):
        raise ApiError(ERR_SERVICE_WINDOW_OUTSIDE_BERTH, 422,
                       "service window is not contained in any live assignment window")
    # Priority 17: segregation of duties.
    if order["requested_by_user_id"] == user_id:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 409,
                       "the requester may never approve its own order")
    # Priority 18: conditional role under CONSTRAINED posture.
    if posture == "CONSTRAINED" and role != "Harbormaster":
        raise ApiError(ERR_CONSTRAINED_REQUIRES_HARBORMASTER, 403,
                       "under CONSTRAINED posture only the Harbormaster may approve")
    order["status"] = "APPROVED"
    order["approved_by_user_id"] = user_id
    order["surcharge_applied"] = posture == "CONSTRAINED"
    db.touch(order)
    services.recompute_draft_provisional(order["port_call_id"])
    return success_obj(db.public(order))


@bp.route("/service-orders/<order_id>/reject", methods=["POST"])
def reject(order_id):
    authenticate({"TerminalOperator", "Harbormaster"})
    order = _get_order_or_404(order_id)
    body = body_json()
    check_shape(body, {"reason": {"type": "string", "required": False}})
    if order["status"] != "REQUESTED":
        raise ApiError(ERR_INVALID_STATE, 409, "reject requires status REQUESTED")
    order["status"] = "REJECTED"
    order["reject_reason"] = body.get("reason")
    db.touch(order)
    return success_obj(db.public(order))


@bp.route("/service-orders/<order_id>/start", methods=["POST"])
def start(order_id):
    authenticate({"TerminalOperator"})
    order = _get_order_or_404(order_id)
    if order["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, 409, "start requires status APPROVED")
    call = db.get("port_calls", order["port_call_id"])
    # An ACTIVE berth assignment must exist for the call.
    if not any(a["status"] == "ACTIVE" for a in services.assignments_of_call(call["id"])):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "no ACTIVE berth assignment exists for this call")
    # Priority 11: contamination sequencing.
    if order["kind"] == "PROVISIONING":
        for other in services.orders_of_call(call["id"]):
            if other["kind"] == "WASTE_OFFLOAD" and other["status"] == "IN_PROGRESS":
                raise ApiError(ERR_WASTE_BEFORE_PROVISIONING, 409,
                               "PROVISIONING may not start while a WASTE_OFFLOAD is IN_PROGRESS")
    # Priority 19: aggregate apron capacity across the whole terminal.
    term = services.terminal_of_call(call)
    in_progress = 0
    for other in db.all_of("service_orders"):
        if other["status"] != "IN_PROGRESS":
            continue
        other_call = db.get("port_calls", other["port_call_id"])
        if other_call is not None and other_call["terminal_id"] == term["id"]:
            in_progress += 1
    if in_progress >= term["max_apron_slots"]:
        raise ApiError(ERR_APRON_CAPACITY, 409,
                       "terminal apron is at capacity")
    order["status"] = "IN_PROGRESS"
    db.touch(order)
    return success_obj(db.public(order))


@bp.route("/service-orders/<order_id>/complete", methods=["POST"])
def complete(order_id):
    authenticate({"TerminalOperator"})
    order = _get_order_or_404(order_id)
    body = body_json()
    check_shape(body, {"actual_units": {"type": "integer", "required": True, "min": 0}})
    if order["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, 409, "complete requires status IN_PROGRESS")
    order["status"] = "COMPLETED"
    order["actual_units"] = body["actual_units"]
    db.touch(order)
    services.recompute_draft_provisional(order["port_call_id"])
    return success_obj(db.public(order))


@bp.route("/service-orders/<order_id>/cancel", methods=["POST"])
def cancel(order_id):
    user_id, role = authenticate({"VesselAgent"})
    order = _get_order_or_404(order_id)
    call = db.get("port_calls", order["port_call_id"])
    scope_call(user_id, role, call)
    if order["status"] not in ("REQUESTED", "APPROVED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "cancel requires status REQUESTED or APPROVED")
    was_approved = order["status"] == "APPROVED"
    order["status"] = "CANCELLED"
    db.touch(order)
    # A REQUESTED order never contributed to any fee; cancelling an APPROVED
    # order recomputes the DRAFT PROVISIONAL invoice.
    if was_approved:
        services.recompute_draft_provisional(order["port_call_id"])
    return success_obj(db.public(order))
