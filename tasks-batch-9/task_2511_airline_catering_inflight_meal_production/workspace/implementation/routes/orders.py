"""Special meal orders: capture, last-minute changes, reads."""

from flask import Blueprint

import clock
import db
import validate
from errors import fail
from middleware import AIRLINE_REP, PRODUCTION_SUPERVISOR, actor, authenticate, require_scope
from routes.helpers import created, guard_scope, one, resolve, simple_list
from services import calc
from timeutil import fmt_ms

bp = Blueprint("orders", __name__)

ORDER_STATUSES = ["REQUESTED", "CONFIRMED", "SUBSTITUTED", "CANCELLED", "LATE_REJECTED"]
SEAT_BLOCKING = ("REQUESTED", "CONFIRMED", "LATE_REJECTED")


@bp.route("/special-meal-orders", methods=["POST"])
def capture_order():
    authenticate(AIRLINE_REP)
    data = validate.body([
        ("flight_id", {"type": "id", "required": True}),
        ("meal_specification_id", {"type": "id", "required": True}),
        ("passenger_ref", {"type": "string", "required": True, "non_empty": True}),
        ("seat_number", {"type": "string", "required": True, "non_empty": True}),
    ])
    flight = resolve("flights", data["flight_id"])
    require_scope(flight["airline_id"])
    spec = resolve("meal_specifications", data["meal_specification_id"])
    if spec["meal_code"] == "STANDARD":
        fail("ERR_INVALID_REQUEST", "A special meal order may not name a STANDARD specification.")

    if flight["status"] != "SCHEDULED":
        fail("ERR_FLIGHT_COUNTS_LOCKED")
    if spec["status"] != "ACTIVE":
        fail("ERR_SPEC_RETIRED")
    if spec["airline_id"] != flight["airline_id"]:
        fail("ERR_SPEC_AIRLINE_MISMATCH")

    for other in db.where("special_meal_orders", flight_id=flight["id"]):
        if other["seat_number"] == data["seat_number"] and other["status"] in SEAT_BLOCKING:
            fail("ERR_DUPLICATE_SEAT_ORDER")

    now = clock.now()
    if now >= calc.special_meal_cutoff(flight):
        fail("ERR_SPECIAL_MEAL_CUTOFF_PASSED")

    order = db.insert("special_meal_orders", {
        "flight_id": flight["id"],
        "meal_specification_id": spec["id"],
        "substitute_meal_specification_id": None,
        "passenger_ref": data["passenger_ref"],
        "seat_number": data["seat_number"],
        "cabin": spec["cabin"],
        "requested_at": fmt_ms(now),
        "_requested_at": now,
        "status": "REQUESTED",
    })
    return created("special_meal_orders", order)


@bp.route("/special-meal-orders/<order_id>/changes", methods=["POST"])
def change_order(order_id):
    authenticate(AIRLINE_REP, PRODUCTION_SUPERVISOR)
    data = validate.body([
        ("action", {"type": "enum", "required": True, "values": ["CANCEL", "SUBSTITUTE"]}),
        ("substitute_meal_specification_id", {"type": "id"}),
        ("reason", {"type": "string", "nullable": True}),
    ])
    order = resolve("special_meal_orders", order_id)
    flight = db.get("flights", order["flight_id"])
    guard_scope("special_meal_orders", order)

    action = data["action"]
    act = actor()
    if action == "CANCEL":
        if act.role != AIRLINE_REP:
            fail("ERR_FORBIDDEN_ROLE")
        return _cancel(order, flight)
    if act.role != PRODUCTION_SUPERVISOR:
        fail("ERR_FORBIDDEN_ROLE")
    return _substitute(order, flight, data.get("substitute_meal_specification_id"))


def _cancel(order, flight):
    if order["status"] not in ("REQUESTED", "CONFIRMED"):
        fail("ERR_INVALID_RESOURCE_STATE")
    if flight is None or flight["status"] not in ("SCHEDULED", "COUNTS_LOCKED"):
        fail("ERR_INVALID_RESOURCE_STATE")
    if clock.now() >= calc.special_meal_cutoff(flight):
        fail("ERR_SPECIAL_MEAL_CUTOFF_PASSED")
    order["status"] = "CANCELLED"
    db.touch(order)
    return one("special_meal_orders", order)


def _substitute(order, flight, substitute_id):
    if substitute_id is None:
        fail("ERR_INVALID_REQUEST", "substitute_meal_specification_id is required for SUBSTITUTE.")
    substitute = resolve("meal_specifications", substitute_id)
    if order["status"] != "CONFIRMED":
        fail("ERR_INVALID_RESOURCE_STATE")
    if flight is None or flight["status"] not in ("COUNTS_LOCKED", "PLANNED"):
        fail("ERR_INVALID_RESOURCE_STATE")
    if substitute["status"] != "ACTIVE":
        fail("ERR_SPEC_RETIRED")
    if substitute["airline_id"] != flight["airline_id"]:
        fail("ERR_SPEC_AIRLINE_MISMATCH")
    original = db.get("meal_specifications", order["meal_specification_id"])
    if original is not None and substitute["cabin"] != original["cabin"]:
        fail("ERR_SPEC_AIRLINE_MISMATCH")
    order["substitute_meal_specification_id"] = substitute["id"]
    order["status"] = "SUBSTITUTED"
    db.touch(order)
    return one("special_meal_orders", order)


@bp.route("/special-meal-orders", methods=["GET"])
def list_orders():
    authenticate()
    return simple_list("special_meal_orders", {
        "flight_id": {"type": "string"},
        "meal_specification_id": {"type": "string"},
        "substitute_meal_specification_id": {"type": "string"},
        "status": {"type": "enum", "values": ORDER_STATUSES},
        "seat_number": {"type": "string"},
    })


@bp.route("/special-meal-orders/<order_id>", methods=["GET"])
def read_order(order_id):
    authenticate()
    order = resolve("special_meal_orders", order_id)
    guard_scope("special_meal_orders", order)
    return one("special_meal_orders", order)
