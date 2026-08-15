"""Spot order endpoints: create (OCC-guarded, supersedes the car's prior open
order), get, list, schedule (full gate set), execute (places the car), cancel
(releases the reservation, voids the switch charge)."""

from flask import Blueprint, request

import domain
from db import STORE, new_entity, touch, public, now, iso
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_STALE_VERSION, ERR_FACILITY_SUSPENDED, ERR_DERAIL_ENGAGED,
    ERR_TRACK_OUT_OF_SERVICE, ERR_TRACK_FULL, ERR_SPOT_NUMBER_INVALID,
    ERR_SPOT_WINDOW_OVERLAP, ERR_SWITCH_WINDOW_CONFLICT, ERR_CAR_NOT_ARRIVED,
    ERR_WINDOW_NOT_ACTIVE, ERR_CREDIT_HOLD, ERR_ALLOCATION_EXCEEDED,
)
from middleware import auth_context, require_role, require_ownership, ALL_ROLES
from response import ok, paginated
from util import parse_datetime, half_open_overlap, within_buffer
from validate import body, req_str, req_int, req_datetime

bp = Blueprint("spot_orders", __name__)

CREATABLE_PLACEMENTS = ("REGISTERED", "ARRIVED", "SPOTTED")


def _get_order_or_404(spot_order_id):
    order = STORE.spot_orders.get(spot_order_id)
    if order is None:
        raise_err(ERR_NOT_FOUND, "spot order id does not exist")
    return order


def _order_customer_id(order):
    return STORE.railcars[order["railcar_id"]]["customer_id"]


@bp.route("/transload/railcars/<rid>/spot-orders", methods=["POST"])
def create_spot_order(rid):
    user_id, role = auth_context()
    require_role(role, ["YardMaster", "CustomerRep"])
    # Priority 3: path ids left-to-right, then body FK ids.
    car = STORE.railcars.get(rid)
    if car is None:
        raise_err(ERR_NOT_FOUND, "railcar id does not exist")
    data = body()
    raw_track = data.get("track_id")
    if isinstance(raw_track, str) and raw_track not in STORE.tracks:
        raise_err(ERR_NOT_FOUND, "track id does not exist")
    # Priority 4: envelope/shape.
    expected_version = req_int(data, "expected_railcar_version")
    track_id = req_str(data, "track_id")
    spot_number = req_int(data, "spot_number")
    if spot_number < 1:
        raise_err(ERR_INVALID_REQUEST, "spot_number must be at least 1")
    window_start = req_datetime(data, "window_start")
    window_end = req_datetime(data, "window_end")
    if window_end <= window_start:
        raise_err(ERR_INVALID_REQUEST, "window_end must be strictly after window_start")
    # Priority 5: state.
    if car["placement_status"] not in CREATABLE_PLACEMENTS:
        raise_err(ERR_INVALID_STATE, "railcar placement does not accept new spot orders")
    # Priority 6: ownership.
    require_ownership(user_id, role, car["customer_id"])
    # Priority 16: optimistic concurrency, evaluated with the mutation.
    if expected_version != car["version"]:
        raise_err(ERR_STALE_VERSION, "expected_railcar_version does not match the current version")
    track = STORE.tracks[track_id]
    # Supersede the car's prior REQUESTED/SCHEDULED order.
    for prior in STORE.spot_orders.values():
        if prior["railcar_id"] == car["id"] and prior["status"] in ("REQUESTED", "SCHEDULED"):
            was = prior["status"]
            prior["status"] = "SUPERSEDED"
            touch(prior)
            if was == "SCHEDULED":
                old_track = STORE.tracks[prior["track_id"]]
                old_track["reserved_spots"] -= 1
                touch(old_track)
            if prior["switch_order_id"]:
                sw = STORE.switch_orders.get(prior["switch_order_id"])
                if sw is not None and sw["status"] == "SCHEDULED":
                    sw["status"] = "CANCELLED"
                    domain.void_switch_charge(sw["id"])
    order = new_entity(STORE.spot_orders, {
        "railcar_id": car["id"],
        "track_id": track_id,
        "spot_number": spot_number,
        "window_start": iso(window_start),
        "window_end": iso(window_end),
        "status": "REQUESTED",
        "switch_order_id": None,
    })
    track["reserved_spots"] += 1
    touch(track)
    touch(car)
    return ok(public(order), status=201)


@bp.route("/transload/spot-orders/<sid>", methods=["GET"])
def get_spot_order(sid):
    user_id, role = auth_context()
    require_role(role, ALL_ROLES)
    order = _get_order_or_404(sid)
    require_ownership(user_id, role, _order_customer_id(order))
    return ok(public(order))


@bp.route("/transload/spot-orders", methods=["GET"])
def list_spot_orders():
    user_id, role = auth_context()
    require_role(role, ALL_ROLES)
    railcar_id = request.args.get("railcar_id")
    track_id = request.args.get("track_id")
    switch_order_id = request.args.get("switch_order_id")
    status = request.args.get("status")
    items = sorted(STORE.spot_orders.values(), key=lambda o: (o["created_at"], o["_seq"]))
    if role == "CustomerRep":
        items = [o for o in items if _order_customer_id(o) == user_id]
    if railcar_id is not None:
        items = [o for o in items if o["railcar_id"] == railcar_id]
    if track_id is not None:
        items = [o for o in items if o["track_id"] == track_id]
    if switch_order_id is not None:
        items = [o for o in items if o["switch_order_id"] == switch_order_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    page, meta = paginated(items)
    return ok([public(o) for o in page], pagination=meta)


@bp.route("/transload/spot-orders/<sid>/schedule", methods=["POST"])
def schedule_spot_order(sid):
    _, role = auth_context()
    require_role(role, ["YardMaster"])
    order = _get_order_or_404(sid)
    # Priority 5: state.
    if order["status"] != "REQUESTED":
        raise_err(ERR_INVALID_STATE, "spot order is not REQUESTED")
    car = STORE.railcars[order["railcar_id"]]
    track = STORE.tracks[order["track_id"]]
    # Priority 7: facility posture and derail gates.
    if track["derail_protection"] != "DISENGAGED":
        raise_err(ERR_DERAIL_ENGAGED, "track derail protection is ENGAGED")
    if STORE.posture == "SUSPENDED":
        raise_err(ERR_FACILITY_SUSPENDED, "facility safety posture is SUSPENDED")
    # Priority 10: track/window constraints.
    if car["placement_status"] != "ARRIVED":
        raise_err(ERR_CAR_NOT_ARRIVED, "railcar is not ARRIVED")
    if track["status"] != "ACTIVE":
        raise_err(ERR_TRACK_OUT_OF_SERVICE, "track is OUT_OF_SERVICE")
    if not (1 <= order["spot_number"] <= track["spot_capacity"]):
        raise_err(ERR_SPOT_NUMBER_INVALID, "spot_number is outside the track's capacity")
    ws = parse_datetime(order["window_start"])
    we = parse_datetime(order["window_end"])
    for other in STORE.spot_orders.values():
        if other["id"] == order["id"]:
            continue
        if other["track_id"] != track["id"] or other["spot_number"] != order["spot_number"]:
            continue
        if other["status"] not in ("REQUESTED", "SCHEDULED", "EXECUTED"):
            continue
        if half_open_overlap(
            ws, we,
            parse_datetime(other["window_start"]), parse_datetime(other["window_end"]),
        ):
            raise_err(ERR_SPOT_WINDOW_OVERLAP, "spot window overlaps an existing order")
    for other_car in STORE.railcars.values():
        if (other_car["placement_status"] == "SPOTTED"
                and other_car["track_id"] == track["id"]
                and other_car["spot_number"] == order["spot_number"]):
            raise_err(ERR_SPOT_WINDOW_OVERLAP, "spot is physically occupied")
    if track["occupied_spots"] + domain.scheduled_count_on_track(track["id"]) + 1 > track["spot_capacity"]:
        raise_err(ERR_TRACK_FULL, "track has no free spot capacity")
    buffer_minutes = domain.facility_config()["switch_buffer_minutes"]
    for sw in STORE.switch_orders.values():
        if sw["track_id"] != track["id"] or sw["status"] != "SCHEDULED":
            continue
        if within_buffer(
            ws, we,
            parse_datetime(sw["window_start"]), parse_datetime(sw["window_end"]),
            buffer_minutes,
        ):
            raise_err(ERR_SWITCH_WINDOW_CONFLICT, "crew window conflicts with a scheduled move")
    # Priority 12: credit hold.
    cust = STORE.customers[car["customer_id"]]
    if cust["credit_standing"] == "CREDIT_HOLD":
        raise_err(ERR_CREDIT_HOLD, "customer is on CREDIT_HOLD")
    # Priority 15: track-space allocation.
    occupied, reserved = domain.customer_spot_usage(cust["id"])
    if occupied + reserved > cust["allocated_car_spots"]:
        raise_err(ERR_ALLOCATION_EXCEEDED, "customer track-space allocation exceeded")
    sw = domain.create_switch_move(
        cust["id"], track["id"], car["id"], "SPOT", ws, we,
    )
    order["switch_order_id"] = sw["id"]
    order["status"] = "SCHEDULED"
    touch(order)
    return ok(public(order))


@bp.route("/transload/spot-orders/<sid>/execute", methods=["POST"])
def execute_spot_order(sid):
    _, role = auth_context()
    require_role(role, ["YardMaster"])
    order = _get_order_or_404(sid)
    # Priority 5: state.
    if order["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "spot order is not SCHEDULED")
    car = STORE.railcars[order["railcar_id"]]
    track = STORE.tracks[order["track_id"]]
    # Priority 7: facility posture and derail gates.
    if track["derail_protection"] != "DISENGAGED":
        raise_err(ERR_DERAIL_ENGAGED, "track derail protection is ENGAGED")
    if STORE.posture == "SUSPENDED":
        raise_err(ERR_FACILITY_SUSPENDED, "facility safety posture is SUSPENDED")
    # Priority 10: car arrived, track active, window active.
    if car["placement_status"] != "ARRIVED":
        raise_err(ERR_CAR_NOT_ARRIVED, "railcar is not ARRIVED")
    if track["status"] != "ACTIVE":
        raise_err(ERR_TRACK_OUT_OF_SERVICE, "track is OUT_OF_SERVICE")
    now_dt = now()
    if not (parse_datetime(order["window_start"]) <= now_dt < parse_datetime(order["window_end"])):
        raise_err(ERR_WINDOW_NOT_ACTIVE, "current time is outside the reservation window")
    car["track_id"] = track["id"]
    car["spot_number"] = order["spot_number"]
    car["placed_timestamp"] = iso(now_dt)
    car["placement_status"] = "SPOTTED"
    track["occupied_spots"] += 1
    track["reserved_spots"] -= 1
    touch(track)
    sw = STORE.switch_orders.get(order["switch_order_id"])
    if sw is not None and sw["status"] == "SCHEDULED":
        sw["status"] = "COMPLETED"
    touch(car)
    order["status"] = "EXECUTED"
    touch(order)
    return ok(public(order))


@bp.route("/transload/spot-orders/<sid>/cancel", methods=["POST"])
def cancel_spot_order(sid):
    user_id, role = auth_context()
    require_role(role, ["YardMaster", "CustomerRep"])
    order = _get_order_or_404(sid)
    # Priority 5: state.
    if order["status"] not in ("REQUESTED", "SCHEDULED"):
        raise_err(ERR_INVALID_STATE, "spot order is not REQUESTED or SCHEDULED")
    # Priority 6: ownership.
    require_ownership(user_id, role, _order_customer_id(order))
    was = order["status"]
    track = STORE.tracks[order["track_id"]]
    track["reserved_spots"] -= 1
    touch(track)
    if was == "SCHEDULED" and order["switch_order_id"]:
        sw = STORE.switch_orders.get(order["switch_order_id"])
        if sw is not None and sw["status"] == "SCHEDULED":
            sw["status"] = "CANCELLED"
            domain.void_switch_charge(sw["id"])
    order["status"] = "CANCELLED"
    touch(order)
    return ok(public(order))
