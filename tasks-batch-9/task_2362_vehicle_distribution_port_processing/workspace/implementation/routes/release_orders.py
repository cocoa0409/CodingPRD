"""Release orders: dispatch, gate-out, cancellation and delivery (PRD §3.8, §3.9)."""
from flask import Blueprint

import db
import validation as v
from errors import fail, invalid_state
from middleware import ALL_ROLES, ROLE_DEALER, ROLE_MANAGER, authenticate
from response import list_response, object_response
from services import calculations as calc
from services import serializers as ser
from services import state

bp = Blueprint("release_orders", __name__)


@bp.route("/vpc/release-orders/<release_order_id>", methods=["GET"])
def read_release_order(release_order_id):
    authenticate(ALL_ROLES)
    order = db.must_get("release_orders", release_order_id)
    return object_response(ser.release_order(order))


@bp.route("/vpc/release-orders", methods=["GET"])
def list_release_orders():
    authenticate(ALL_ROLES)
    vehicle_id = v.query_filter("vehicle_id")
    dealer_id = v.query_filter("dealer_id")
    carrier_id = v.query_filter("truck_carrier_id")
    route_zone = v.query_filter("route_zone")
    superseded = v.query_filter("superseded_release_order_id")
    cancelled_by = v.query_filter("cancelled_by_hold_order_id")
    status = v.query_filter("status")
    records = db.ordered(db.release_orders)
    if vehicle_id is not None:
        records = [r for r in records if r["vehicle_id"] == vehicle_id]
    if dealer_id is not None:
        records = [r for r in records if r["dealer_id"] == dealer_id]
    if carrier_id is not None:
        records = [r for r in records if r["truck_carrier_id"] == carrier_id]
    if route_zone is not None:
        records = [r for r in records if r["route_zone"] == route_zone]
    if superseded is not None:
        records = [r for r in records if r["superseded_release_order_id"] == superseded]
    if cancelled_by is not None:
        records = [r for r in records if r["cancelled_by_hold_order_id"] == cancelled_by]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    items, limit, offset, total = v.paginate(records, ser.release_order)
    return list_response(items, limit, offset, total)


@bp.route("/vpc/release-orders/<release_order_id>/dispatch", methods=["POST"])
def dispatch(release_order_id):
    authenticate([ROLE_MANAGER])
    order = db.must_get("release_orders", release_order_id)

    if order["status"] != "ALLOCATED":
        invalid_state("only an ALLOCATED release order can be dispatched")

    carrier = db.carriers.get(order["truck_carrier_id"])
    if carrier is not None and not state.carrier_window_capacity_ok(order, carrier):
        fail(
            "ERR_CARRIER_WINDOW_CAPACITY",
            "the carrier's concurrent load capacity is exhausted in this pickup window",
        )

    vehicle = db.vehicles.get(order["vehicle_id"])
    dealer = db.dealers.get(order["dealer_id"])
    center = state.center_of_vehicle(vehicle) if vehicle is not None else None
    freight = calc.freight_settlement(
        dealer["distance_miles"] if dealer is not None else 0,
        carrier["linehaul_rate_cents_per_mile"] if carrier is not None else 0,
        center["fuel_surcharge_pct"] if center is not None else 0,
        order["route_zone"],
    )
    order.update(freight)
    order["status"] = "RELEASED"
    order["dispatched_at"] = db.clock_now()
    db.touch(order)

    if vehicle is not None and vehicle["processing_status"] == "ALLOCATED":
        vehicle["processing_status"] = "RELEASED"
        db.touch(vehicle)
    if carrier is not None:
        state.recompute_carrier(carrier)
    return object_response(ser.release_order(order))


@bp.route("/vpc/release-orders/<release_order_id>/gate-out", methods=["POST"])
def gate_out(release_order_id):
    authenticate([ROLE_MANAGER])
    order = db.must_get("release_orders", release_order_id)

    if order["status"] != "RELEASED":
        invalid_state("only a RELEASED release order can be gated out")

    vehicle = db.vehicles.get(order["vehicle_id"])
    if vehicle is not None and (
        vehicle["stop_ship_blocked"] or state.open_holds_covering(vehicle)
    ):
        fail("ERR_VEHICLE_STOP_SHIP_BLOCKED", "an open hold covers this unit")

    gated_out_at = db.clock_now()
    order["status"] = "GATED_OUT"
    order["gated_out_at"] = gated_out_at
    db.touch(order)

    if vehicle is not None:
        center = state.center_of_vehicle(vehicle)
        vehicle["yard_presence"] = "DEPARTED"
        vehicle["gate_out_at"] = gated_out_at
        vehicle["processing_status"] = "GATED_OUT"
        if center is not None:
            vehicle["storage_charge_final_cents"] = state.stamp_final_storage(
                vehicle, center, gated_out_at
            )
        vehicle["storage_charge_provisional_cents"] = 0
        db.touch(vehicle)
        if center is not None:
            state.recompute_center(center)

    carrier = db.carriers.get(order["truck_carrier_id"])
    if carrier is not None:
        state.recompute_carrier(carrier)
    return object_response(ser.release_order(order))


@bp.route("/vpc/release-orders/<release_order_id>/cancel", methods=["POST"])
def cancel(release_order_id):
    authenticate([ROLE_MANAGER])
    order = db.must_get("release_orders", release_order_id)

    if order["status"] not in ("ALLOCATED", "RELEASED"):
        invalid_state("only an ALLOCATED or RELEASED release order can be cancelled")

    state.unwind_release_order(order, "CANCELLED")
    return object_response(ser.release_order(order))


@bp.route("/vpc/release-orders/<release_order_id>/delivery-confirmation", methods=["POST"])
def confirm_delivery(release_order_id):
    user_id, _role = authenticate([ROLE_DEALER])
    order = db.must_get("release_orders", release_order_id)

    if order["status"] != "GATED_OUT":
        invalid_state("only a GATED_OUT release order can be confirmed as delivered")
    if order["dealer_id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "only the consignee dealer may confirm delivery")

    order["status"] = "DELIVERED"
    db.touch(order)
    return object_response(ser.release_order(order))
