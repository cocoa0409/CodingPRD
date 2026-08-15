"""Linehaul leg endpoints: planning, relay sequencing, depart/arrive/cancel
(PRD section 3.6)."""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (err_invalid_request, err_invalid_state,
                    err_leg_window_invalid, err_relay_connect_infeasible,
                    err_relay_sequence)
from middleware import require_roles
from response import success, success_list
from routes.common import (active_entries_for_trailer, as_datetime, body_json,
                           find_prior_leg, get_path, new_record, paginate,
                           resolve_fk, ser_leg, touch)
from services.calculations import MIN_CONNECT_MINUTES

bp = Blueprint("legs", __name__)

_READ_ROLES = ("TerminalAdmin", "Dispatcher", "DockSupervisor")


@bp.route("/ltl/linehaul-legs", methods=["POST"])
@require_roles("Dispatcher")
def create_leg():
    body = body_json()
    origin = resolve_fk("terminals", body.get("origin_terminal_id"), "origin_terminal_id")
    dest = resolve_fk("terminals", body.get("destination_terminal_id"), "destination_terminal_id")
    trailer = resolve_fk("trailers", body.get("trailer_id"), "trailer_id")
    # Field types needed for the temporal checks below.
    departure = as_datetime(body, "planned_departure_utc")
    arrival = as_datetime(body, "planned_arrival_utc")
    seq = body.get("relay_sequence")
    if seq is None or not isinstance(seq, int) or isinstance(seq, bool):
        raise err_invalid_request("relay_sequence must be an integer")
    # Priority 12: relay connect feasibility against the previous leg's
    # planned arrival plus the 45-minute connect buffer; exactly at the buffer
    # is feasible. CANCELLED legs are excluded from chain reasoning.
    if seq > 1:
        prior = None
        candidates = [
            l for l in db.store["linehaul_legs"].values()
            if l["trailer_id"] == trailer["id"]
            and l["relay_sequence"] == seq - 1
            and l["status"] != "CANCELLED"
        ]
        if candidates:
            prior = max(candidates, key=lambda l: (l["created_at"], l["_seq"]))
        if prior is not None and departure < prior["planned_arrival_utc"] + timedelta(minutes=MIN_CONNECT_MINUTES):
            raise err_relay_connect_infeasible()
    # Priority 13: arrival strictly after departure.
    if not arrival > departure:
        raise err_leg_window_invalid()
    # Priority 20: remaining ranges.
    if seq < 1:
        raise err_invalid_request("relay_sequence must be >= 1")
    rec = new_record({
        "origin_terminal_id": origin["id"],
        "destination_terminal_id": dest["id"],
        "trailer_id": trailer["id"],
        "planned_departure_utc": departure,
        "planned_arrival_utc": arrival,
        "actual_departure_utc": None,
        "actual_arrival_utc": None,
        "relay_sequence": seq,
        "status": "PLANNED",
    })
    db.store["linehaul_legs"][rec["id"]] = rec
    return success(ser_leg(rec), 201)


@bp.route("/ltl/linehaul-legs", methods=["GET"])
@require_roles(*_READ_ROLES)
def list_legs():
    items = list(db.store["linehaul_legs"].values())
    for param in ("trailer_id", "origin_terminal_id", "destination_terminal_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [l for l in items if l.get(param) == value]
    page, total, limit, offset = paginate(items)
    return success_list([ser_leg(l) for l in page], total, limit, offset)


@bp.route("/ltl/linehaul-legs/<legId>", methods=["GET"])
@require_roles(*_READ_ROLES)
def get_leg(legId):
    return success(ser_leg(get_path("linehaul_legs", legId)))


@bp.route("/ltl/linehaul-legs/<legId>/depart", methods=["POST"])
@require_roles("Dispatcher")
def depart_leg(legId):
    leg = get_path("linehaul_legs", legId)
    if leg["status"] != "PLANNED":
        raise err_invalid_state("Only a PLANNED leg can depart")
    trailer = db.store["trailers"][leg["trailer_id"]]
    if leg["relay_sequence"] == 1:
        # First leg of the chain: the trailer must be SEALED.
        if trailer["posture"] != "SEALED":
            raise err_invalid_state("First-leg departure requires trailer posture SEALED")
    else:
        # Priority 18: the prior same-trailer leg must be ARRIVED.
        prior = find_prior_leg(leg)
        if prior is None or prior["status"] != "ARRIVED":
            raise err_relay_sequence()
    leg["actual_departure_utc"] = db.now()
    leg["status"] = "EN_ROUTE"
    touch(leg)
    if leg["relay_sequence"] == 1:
        trailer["posture"] = "DISPATCHED"
        touch(trailer)
        for entry in active_entries_for_trailer(trailer["id"]):
            shipment = db.store["shipments"][entry["shipment_id"]]
            if shipment["handling_status"] == "MANIFESTED":
                shipment["handling_status"] = "IN_LINEHAUL"
                touch(shipment)
    return success(ser_leg(leg))


@bp.route("/ltl/linehaul-legs/<legId>/arrive", methods=["POST"])
@require_roles("Dispatcher")
def arrive_leg(legId):
    leg = get_path("linehaul_legs", legId)
    if leg["status"] != "EN_ROUTE":
        raise err_invalid_state("Only an EN_ROUTE leg can arrive")
    now = db.now()
    leg["actual_arrival_utc"] = now
    leg["status"] = "ARRIVED"
    touch(leg)
    trailer = db.store["trailers"][leg["trailer_id"]]
    # Final relay leg: destination equals the trailer's linehaul destination.
    if leg["destination_terminal_id"] == trailer["destination_terminal_id"]:
        trailer["posture"] = "ARRIVED"
        touch(trailer)
        for entry in active_entries_for_trailer(trailer["id"]):
            shipment = db.store["shipments"][entry["shipment_id"]]
            if shipment["handling_status"] == "IN_LINEHAUL":
                shipment["handling_status"] = "DELIVERED"
                shipment["delivered_at_utc"] = now
                touch(shipment)
    return success(ser_leg(leg))


@bp.route("/ltl/linehaul-legs/<legId>/cancel", methods=["POST"])
@require_roles("Dispatcher")
def cancel_leg(legId):
    leg = get_path("linehaul_legs", legId)
    if leg["status"] != "PLANNED":
        raise err_invalid_state("Only a PLANNED leg can be cancelled")
    leg["status"] = "CANCELLED"
    touch(leg)
    return success(ser_leg(leg))
