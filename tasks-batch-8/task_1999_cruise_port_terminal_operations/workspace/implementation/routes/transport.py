"""Transport slots: enqueue, dispatch (FIFO + window capacity), complete,
no-show, requeue (PRD 3.9)."""

from flask import Blueprint, request

import db
import services
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_POSTURE_EMERGENCY,
    ERR_QUEUE_WINDOW_FULL, ERR_QUEUE_ORDER, ERR_REQUEUE_LIMIT, ERR_VESSEL_SCOPE,
)
from middleware import authenticate, ANY
from response import success_obj, success_list
from util import body_json, check_shape, pagination_params, paginate, apply_filters

bp = Blueprint("transport", __name__, url_prefix="/port-ops")

_ENQUEUEABLE_CALL_STATES = ("SCHEDULED", "DELAYED", "ARRIVED", "TURNAROUND")


def _get_slot_or_404(slot_id):
    slot = db.get("transport_slots", slot_id)
    if slot is None:
        raise ApiError(ERR_NOT_FOUND, 404, "transport slot not found")
    return slot


@bp.route("/transport-slots", methods=["POST"])
def create_slot():
    authenticate({"TerminalOperator"})
    body = body_json()
    # Priority 3: body FK existence, left to right (terminal then port call).
    term = None
    if body.get("terminal_id") is not None:
        term = db.get("terminals", body["terminal_id"])
        if term is None:
            raise ApiError(ERR_NOT_FOUND, 404, "terminal not found")
    call = None
    if body.get("port_call_id") is not None:
        call = db.get("port_calls", body["port_call_id"])
        if call is None:
            raise ApiError(ERR_NOT_FOUND, 404, "port call not found")
    check_shape(body, {
        "terminal_id": {"type": "string", "required": True},
        "port_call_id": {"type": "string", "required": True},
        "vehicle_class": {"type": "enum", "required": True, "values": {"TAXI", "SHUTTLE", "PRIVATE"}},
        "party_size": {"type": "integer", "required": True, "min": 1},
    })
    if call["status"] not in _ENQUEUEABLE_CALL_STATES:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "the call must be SCHEDULED, DELAYED, ARRIVED, or TURNAROUND")
    slot = db.new_entity("transport_slots", {
        "terminal_id": body["terminal_id"],
        "port_call_id": body["port_call_id"],
        "vehicle_class": body["vehicle_class"],
        "party_size": body["party_size"],
        "queue_seq": db.next_queue_seq(body["terminal_id"], body["vehicle_class"]),
        "requeue_count": 0,
        "dispatch_window_start": None,
        "status": "QUEUED",
    })
    return success_obj(db.public(slot), code=201)


@bp.route("/transport-slots", methods=["GET"])
def list_slots():
    user_id, role = authenticate(ANY)
    limit, offset = pagination_params()
    items = db.all_of("transport_slots")
    if role == "VesselAgent":
        port_call_id = request.args.get("port_call_id")
        if port_call_id is not None:
            call = db.get("port_calls", port_call_id)
            if call is not None and call["vessel_id"] != user_id:
                raise ApiError(ERR_VESSEL_SCOPE, 403,
                               "vessel agent may only read its own vessel's calls")
        items = [
            s for s in items
            if (db.get("port_calls", s["port_call_id"]) or {}).get("vessel_id") == user_id
        ]
    items = apply_filters(items, ["terminal_id", "port_call_id", "status", "vehicle_class"])
    page, total, has_more = paginate([db.public(s) for s in items], limit, offset)
    return success_list(page, limit, offset, total, has_more)


@bp.route("/transport-slots/<slot_id>", methods=["GET"])
def get_slot(slot_id):
    user_id, role = authenticate(ANY)
    slot = _get_slot_or_404(slot_id)
    if role == "VesselAgent":
        call = db.get("port_calls", slot["port_call_id"])
        if call is None or call["vessel_id"] != user_id:
            raise ApiError(ERR_VESSEL_SCOPE, 403,
                           "vessel agent may only read its own vessel's calls")
    return success_obj(db.public(slot))


@bp.route("/transport-slots/<slot_id>/dispatch", methods=["POST"])
def dispatch(slot_id):
    authenticate({"TerminalOperator"})
    slot = _get_slot_or_404(slot_id)
    if slot["status"] != "QUEUED":
        raise ApiError(ERR_INVALID_STATE, 409, "dispatch requires status QUEUED")
    call = db.get("port_calls", slot["port_call_id"])
    if call is None or call["status"] not in ("ARRIVED", "TURNAROUND"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "the slot's port call must be ARRIVED or TURNAROUND")
    # Priority 9: posture gate.
    term = db.get("terminals", slot["terminal_id"])
    posture, _a, _o, _f = services.posture_of(term)
    if posture == "EMERGENCY":
        raise ApiError(ERR_POSTURE_EMERGENCY, 409,
                       "terminal posture is EMERGENCY; dispatch is gated")
    # Priority 19: current 15-minute dispatch window capacity.
    window_start_iso = db.fmt_ts(services.current_dispatch_window_start())
    if services.dispatched_in_window(slot["terminal_id"], window_start_iso) >= term["taxi_dispatch_capacity_per_window"]:
        raise ApiError(ERR_QUEUE_WINDOW_FULL, 409,
                       "the current dispatch window is at capacity")
    # Priority 20: strict FIFO per (terminal, vehicle_class).
    for other in db.all_of("transport_slots"):
        if (other["terminal_id"] == slot["terminal_id"]
                and other["vehicle_class"] == slot["vehicle_class"]
                and other["status"] == "QUEUED"
                and other["id"] != slot["id"]
                and other["queue_seq"] < slot["queue_seq"]):
            raise ApiError(ERR_QUEUE_ORDER, 409,
                           "a QUEUED slot with a lower queue_seq exists for this class")
    slot["status"] = "DISPATCHED"
    slot["dispatch_window_start"] = window_start_iso
    db.touch(slot)
    return success_obj(db.public(slot))


@bp.route("/transport-slots/<slot_id>/complete", methods=["POST"])
def complete(slot_id):
    authenticate({"TerminalOperator"})
    slot = _get_slot_or_404(slot_id)
    if slot["status"] != "DISPATCHED":
        raise ApiError(ERR_INVALID_STATE, 409, "complete requires status DISPATCHED")
    slot["status"] = "COMPLETED"
    db.touch(slot)
    return success_obj(db.public(slot))


@bp.route("/transport-slots/<slot_id>/no-show", methods=["POST"])
def no_show(slot_id):
    authenticate({"TerminalOperator"})
    slot = _get_slot_or_404(slot_id)
    if slot["status"] != "DISPATCHED":
        raise ApiError(ERR_INVALID_STATE, 409, "no-show requires status DISPATCHED")
    slot["status"] = "NO_SHOW"
    db.touch(slot)
    return success_obj(db.public(slot))


@bp.route("/transport-slots/<slot_id>/requeue", methods=["POST"])
def requeue(slot_id):
    authenticate({"TerminalOperator"})
    slot = _get_slot_or_404(slot_id)
    if slot["status"] != "NO_SHOW":
        raise ApiError(ERR_INVALID_STATE, 409, "requeue requires status NO_SHOW")
    # Priority 20: a slot may be requeued exactly once.
    if slot["requeue_count"] >= 1:
        raise ApiError(ERR_REQUEUE_LIMIT, 409, "requeue_count has reached the limit of 1")
    slot["requeue_count"] += 1
    slot["queue_seq"] = db.next_queue_seq(slot["terminal_id"], slot["vehicle_class"])
    slot["status"] = "QUEUED"
    db.touch(slot)
    return success_obj(db.public(slot))
