"""Order intake, quoting, dispatch and cancellation (PRD 3.3, 3.4)."""
from decimal import Decimal

from flask import Blueprint, g

import calc
import serializers
import validation as v
from auth import require
from db import db, get_or_404, new_record, sorted_rows, touch
from errors import err
from response import ok
from routes import filtered, list_response
from services import flight_service
from timeutil import plus_minutes

bp = Blueprint("orders", __name__)

ORDER_READERS = ("PlatformAdmin", "DispatchOperator", "FlightDirector", "Customer")
ORDER_STATUSES = ("QUOTED", "ASSIGNED", "IN_TRANSIT", "DELIVERED", "CANCELLED")


@bp.post("/orders")
@require("Customer", "DispatchOperator")
def create_order():
    body = v.body()
    customer_id = v.as_string(body, "customer_id")
    service_area_id = v.as_string(body, "service_area_id")
    payload_weight_g = v.as_integer(body, "payload_weight_g", gt=0)
    priority = v.as_enum(
        body, "priority", ("STANDARD", "URGENT", "MEDICAL"), required=False, default="STANDARD"
    )

    customer = get_or_404("Customer", customer_id)
    area = get_or_404("ServiceArea", service_area_id)

    if g.role == "Customer" and g.user_id != customer_id:
        raise err("ERR_NOT_ORDER_OWNER")

    if area["status"] != "ACTIVE":
        raise err("ERR_SERVICE_AREA_SUSPENDED")

    # Geometry first: the dropoff point is copied from the customer and frozen.
    dropoff_lat = customer["dropoff_lat"]
    dropoff_lon = customer["dropoff_lon"]
    distance_km = calc.planar_distance_km(
        area["center_lat"], area["center_lon"], dropoff_lat, dropoff_lon
    )

    if payload_weight_g > area["max_payload_g"]:
        raise err("ERR_PAYLOAD_EXCEEDS_LIMIT")
    if distance_km > Decimal(area["max_range_km"]):
        raise err("ERR_OUT_OF_SERVICE_RANGE")

    fee = calc.delivery_fee(distance_km, payload_weight_g, priority)
    surcharge, total = calc.billing_total(fee)

    rec = new_record(
        "Order",
        {
            "customer_id": customer_id,
            "service_area_id": service_area_id,
            "payload_weight_g": payload_weight_g,
            "priority": priority,
            "dropoff_lat": dropoff_lat,
            "dropoff_lon": dropoff_lon,
            "distance_km": distance_km,
            "delivery_fee": fee,
            "airspace_surcharge": surcharge,
            "order_total": total,
            "status": "QUOTED",
        },
    )
    return ok(serializers.order(rec), 201)


@bp.get("/orders")
@require(*ORDER_READERS)
def list_orders():
    limit, offset = v.pagination()
    rows = filtered(
        db.orders.values(),
        customer_id=v.query_str("customer_id"),
        service_area_id=v.query_str("service_area_id"),
        status=v.query_enum("status", ORDER_STATUSES),
    )
    return list_response(rows, serializers.order, limit, offset)


@bp.get("/orders/<order_id>")
@require(*ORDER_READERS)
def read_order(order_id):
    return ok(serializers.order(get_or_404("Order", order_id)))


@bp.post("/orders/<order_id>/cancel")
@require("Customer", "DispatchOperator")
def cancel_order(order_id):
    order = get_or_404("Order", order_id)
    if g.role == "Customer" and g.user_id != order["customer_id"]:
        raise err("ERR_NOT_ORDER_OWNER")
    if order["status"] != "QUOTED":
        raise err("ERR_ORDER_NOT_CANCELLABLE")
    order["status"] = "CANCELLED"
    touch(order)
    return ok(serializers.order(order))


# --- dispatch -------------------------------------------------------------


def _pad_hold(eta):
    return plus_minutes(eta, -calc.PAD_BUFFER_MIN), plus_minutes(eta, calc.PAD_HOLD_MIN)


def _eta_for(planned_route_km, drone, now):
    minutes = calc.cruise_minutes(planned_route_km, drone["cruise_speed_kmh"])
    return plus_minutes(now, minutes + calc.HOVER_MIN)


def _maintenance_blocks(drone_id, window_start, window_end):
    """Half-open [scheduled_start, scheduled_end) vs the half-open flight window."""
    for log in db.maintenance_logs.values():
        if log["drone_id"] != drone_id or log["status"] != "SCHEDULED":
            continue
        if log["scheduled_start"] < window_end and window_start < log["scheduled_end"]:
            return True
    return False


def _overlapping_holds(nest_id, start, end):
    """Closed [pad_hold_start, pad_hold_end] intersection; touching endpoints collide."""
    count = 0
    for f in db.flights.values():
        if f["recovery_nest_id"] != nest_id:
            continue
        if f["ops_state"] not in flight_service.NON_TERMINAL_OPS:
            continue
        if f["pad_hold_start"] <= end and start <= f["pad_hold_end"]:
            count += 1
    return count


@bp.post("/orders/<order_id>/dispatch")
@require("DispatchOperator")
def dispatch_order(order_id):
    body = v.body()
    nest_id = v.as_string(body, "nest_id")
    expected_version = v.as_integer(body, "expected_order_version")

    order = get_or_404("Order", order_id)
    nest = get_or_404("Nest", nest_id)

    if expected_version != order["version"]:
        raise err("ERR_STALE_ORDER_VERSION")
    if order["status"] != "QUOTED":
        raise err("ERR_ORDER_NOT_QUOTED")

    area = db.service_areas[order["service_area_id"]]
    if area["status"] != "ACTIVE":
        raise err("ERR_SERVICE_AREA_SUSPENDED")

    if nest["status"] != "OPEN" or nest["service_area_id"] != order["service_area_id"]:
        raise err("ERR_NEST_UNAVAILABLE")

    now = db.now()

    # Route geometry and the frozen wind. Both are drone-independent.
    planned_route_km = Decimal(2) * calc.planar_distance_km(
        nest["lat"], nest["lon"], order["dropoff_lat"], order["dropoff_lon"]
    )
    observation = calc.latest_observation(order["service_area_id"])
    wind = Decimal(observation["wind_kph"]) if observation else Decimal("0")
    required = calc.required_energy_pct(planned_route_km, order["payload_weight_g"], wind)

    # --- the selector (PRD 3.4) ---
    candidates = []
    at_nest = sorted_rows([d for d in db.drones.values() if d["home_nest_id"] == nest_id])
    for drone in at_nest:
        if drone["status"] != "IDLE":
            continue
        if drone["max_payload_g"] < order["payload_weight_g"]:
            continue
        battery_id = drone["installed_battery_id"]
        if not battery_id:
            continue
        battery = db.batteries.get(battery_id)
        if battery is None or battery["state"] != "READY":
            continue
        if Decimal(battery["charge_pct"]) < required:
            continue
        if calc.blocking_risk_score(drone) >= calc.RISK_BLOCK_THRESHOLD:
            continue
        eta = _eta_for(planned_route_km, drone, now)
        if _maintenance_blocks(drone["id"], now, eta):
            continue
        candidates.append((drone, battery, eta))

    candidates.sort(
        key=lambda c: (
            -Decimal(c[1]["charge_pct"]),
            Decimal(c[0]["hours_since_service"]),
            c[0]["created_at"],
            c[0]["_seq"],
        )
    )

    # --- the pad-capacity gate (PRD 3.4; it precedes the selector in PRD 2.11) ---
    # The candidate hold interval is derived from the recovery ETA, which is
    # airframe-specific. The winner's ETA defines the hold that will be stored.
    # When no airframe survives the filter there is still a nest to gate on, so
    # the interval is taken from the longest-registered airframe based there.
    reference = candidates[0][0] if candidates else (at_nest[0] if at_nest else None)
    if reference is not None:
        ref_eta = candidates[0][2] if candidates else _eta_for(planned_route_km, reference, now)
        hold_start, hold_end = _pad_hold(ref_eta)
        if _overlapping_holds(nest_id, hold_start, hold_end) >= nest["pad_count"]:
            raise err("ERR_NEST_PADS_FULL")

    if not candidates:
        raise err("ERR_NO_ELIGIBLE_DRONE")

    drone, battery, eta = candidates[0]
    hold_start, hold_end = _pad_hold(eta)

    flight = new_record(
        "Flight",
        {
            "order_id": order["id"],
            "drone_id": drone["id"],
            "launch_nest_id": nest["id"],
            "recovery_nest_id": nest["id"],
            "battery_id": battery["id"],
            "ops_state": "PLANNED",
            "clearance_state": "UNFILED",
            "planned_route_km": planned_route_km,
            "required_energy_pct": required,
            "actual_energy_pct": None,
            "actual_route_km": None,
            "wind_kph_at_dispatch": wind,
            "eta_recovery_at": eta,
            "pad_hold_start": hold_start,
            "pad_hold_end": hold_end,
            "filed_by_user_id": None,
            "released_by_user_id": None,
            "abort_reason": None,
        },
    )

    drone["status"] = "RESERVED"
    touch(drone)

    # The pad slot and the funds hold are both derived from this flight/order pair.
    order["status"] = "ASSIGNED"
    touch(order)

    return ok(serializers.flight(flight), 201)
