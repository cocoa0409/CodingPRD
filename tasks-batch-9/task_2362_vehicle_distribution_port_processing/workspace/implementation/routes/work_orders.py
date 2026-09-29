"""Accessory work orders: kit, install and the compensating void (PRD §3.5)."""
from flask import Blueprint

import db
import validation as v
from errors import fail, invalid_state
from middleware import OPS_ROLES, ROLE_TECH, authenticate
from response import list_response, object_response
from services import calculations as calc
from services import serializers as ser
from services import state

bp = Blueprint("work_orders", __name__)

KITTABLE_VEHICLE_STATES = ("SURVEYED", "ACCESSORY_IN_PROGRESS")
VOIDABLE_FROM_INSTALLED_VEHICLE_STATES = ("ACCESSORY_IN_PROGRESS", "INSPECTION_PASSED")


@bp.route("/vpc/accessory-work-orders/<work_order_id>", methods=["GET"])
def read_work_order(work_order_id):
    authenticate(OPS_ROLES)
    order = db.must_get("work_orders", work_order_id)
    return object_response(ser.work_order(order))


@bp.route("/vpc/accessory-work-orders", methods=["GET"])
def list_work_orders():
    authenticate(OPS_ROLES)
    vehicle_id = v.query_filter("vehicle_id")
    kit_id = v.query_filter("accessory_kit_id")
    status = v.query_filter("status")
    records = db.ordered(db.work_orders)
    if vehicle_id is not None:
        records = [r for r in records if r["vehicle_id"] == vehicle_id]
    if kit_id is not None:
        records = [r for r in records if r["accessory_kit_id"] == kit_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    items, limit, offset, total = v.paginate(records, ser.work_order)
    return list_response(items, limit, offset, total)


@bp.route("/vpc/accessory-work-orders/<work_order_id>/kit", methods=["POST"])
def kit_work_order(work_order_id):
    authenticate([ROLE_TECH])
    order = db.must_get("work_orders", work_order_id)
    kit = db.kits.get(order["accessory_kit_id"])
    vehicle = db.vehicles.get(order["vehicle_id"])

    if order["status"] != "PLANNED":
        invalid_state("only a PLANNED work order can be kitted")
    if vehicle is None or vehicle["processing_status"] not in KITTABLE_VEHICLE_STATES:
        invalid_state("the unit must be in SURVEYED or ACCESSORY_IN_PROGRESS to kit accessories")

    state.recompute_kit(kit)
    if kit["available_qty"] < order["qty"]:
        fail("ERR_KIT_INSUFFICIENT", "the kit does not hold enough available units")

    order["status"] = "KITTED"
    db.touch(order)
    state.recompute_kit(kit)

    if vehicle["processing_status"] == "SURVEYED":
        vehicle["processing_status"] = "ACCESSORY_IN_PROGRESS"
        db.touch(vehicle)
    return object_response(ser.work_order(order))


@bp.route("/vpc/accessory-work-orders/<work_order_id>/install", methods=["POST"])
def install_work_order(work_order_id):
    user_id, _role = authenticate([ROLE_TECH])
    order = db.must_get("work_orders", work_order_id)
    kit = db.kits.get(order["accessory_kit_id"])
    vehicle = db.vehicles.get(order["vehicle_id"])

    if order["status"] != "KITTED":
        invalid_state("only a KITTED work order can be installed")
    if vehicle is None or vehicle["processing_status"] != "ACCESSORY_IN_PROGRESS":
        invalid_state("the unit must be in ACCESSORY_IN_PROGRESS to record an install")

    center = db.centers.get(kit["processing_center_id"])
    labor_rate = center["labor_rate_cents_per_hour"] if center is not None else 0
    billed = calc.accessory_billing(
        kit["unit_cost_cents"], kit["install_minutes_per_unit"], labor_rate, order["qty"]
    )

    order["status"] = "INSTALLED"
    order["installed_by_user_id"] = user_id
    order["billed_cents"] = billed
    db.touch(order)

    kit["on_hand_qty"] = kit["on_hand_qty"] - order["qty"]
    state.recompute_kit(kit)

    billed_total = state.vehicle_accessory_billed(vehicle["id"])
    if vehicle["accessory_billed_cents"] != billed_total:
        vehicle["accessory_billed_cents"] = billed_total
        db.touch(vehicle)
    return object_response(ser.work_order(order))


@bp.route("/vpc/accessory-work-orders/<work_order_id>/void", methods=["POST"])
def void_work_order(work_order_id):
    authenticate([ROLE_TECH])
    order = db.must_get("work_orders", work_order_id)
    kit = db.kits.get(order["accessory_kit_id"])
    vehicle = db.vehicles.get(order["vehicle_id"])

    if order["status"] not in ("PLANNED", "KITTED", "INSTALLED"):
        invalid_state("a work order can only be voided from PLANNED, KITTED or INSTALLED")
    was_installed = order["status"] == "INSTALLED"
    if was_installed:
        if (
            vehicle is None
            or vehicle["processing_status"] not in VOIDABLE_FROM_INSTALLED_VEHICLE_STATES
        ):
            invalid_state(
                "voiding an installed work order needs the unit in ACCESSORY_IN_PROGRESS "
                "or INSPECTION_PASSED"
            )

    order["status"] = "VOIDED"
    if was_installed:
        order["billed_cents"] = 0
    db.touch(order)

    if kit is not None:
        if was_installed:
            kit["on_hand_qty"] = kit["on_hand_qty"] + order["qty"]
        state.recompute_kit(kit)

    if was_installed and vehicle is not None:
        billed_total = state.vehicle_accessory_billed(vehicle["id"])
        if vehicle["accessory_billed_cents"] != billed_total:
            vehicle["accessory_billed_cents"] = billed_total
            db.touch(vehicle)
    return object_response(ser.work_order(order))
