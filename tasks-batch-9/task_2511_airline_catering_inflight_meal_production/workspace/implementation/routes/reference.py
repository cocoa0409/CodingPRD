"""Logical clock, airlines, meal specifications, trucks and stands."""

from decimal import Decimal

from flask import Blueprint

import clock
import db
import response
import validate
from errors import fail
from middleware import PLATFORM_ADMIN, authenticate
from routes.helpers import created, guard_scope, one, resolve, simple_list
from services import calc
from timeutil import fmt_ms

bp = Blueprint("reference", __name__)

CABINS = ["FIRST", "BUSINESS", "ECONOMY"]
MEAL_CODES = ["STANDARD", "VGML", "AVML", "CHML", "GFML"]
STORAGE_CLASSES = ["CHILL", "HOT", "DRY"]
HACCP_STEPS = ["COOK_TEMP", "CHILL_DOWN", "HOLD_TEMP", "BLAST_CHILL"]


# ---------------------------------------------------------------------------
# logical clock — the one operation that skips authentication entirely


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    data = validate.body([("current_utc", {"type": "datetime", "required": True})])
    clock.set_now(data["current_utc"])
    return response.ok({"current_utc": fmt_ms(clock.now())})


# ---------------------------------------------------------------------------
# airlines

AIRLINE_CREATE = [
    ("name", {"type": "string", "required": True, "non_empty": True}),
    ("iata_code", {"type": "string", "required": True, "pattern": r"[A-Z]{2}"}),
    ("waste_regime", {"type": "enum", "required": True, "values": ["BONDED", "DOMESTIC"]}),
    ("cost_cap_per_pax_cents", {"type": "int", "required": True, "min": 1}),
    ("special_meal_cutoff_minutes", {"type": "int", "min": 0, "max": 4320, "default": 720}),
    ("late_delivery_grace_minutes", {"type": "int", "min": 0, "max": 120, "default": 10}),
    ("unused_recovery_rate_pct",
     {"type": "number", "min": 0, "max": 100, "decimals": 2, "default": Decimal("30.00")}),
    ("spec_deviation_tolerance_pct",
     {"type": "number", "min": 0, "max": 100, "decimals": 2, "default": Decimal("5.00")}),
]


@bp.route("/airlines", methods=["POST"])
def create_airline():
    authenticate(PLATFORM_ADMIN)
    data = validate.body(AIRLINE_CREATE)
    for existing in db.rows("airlines"):
        if existing["iata_code"] == data["iata_code"]:
            fail("ERR_INVALID_REQUEST", "iata_code is already registered.")
    row = dict(data)
    row["status"] = "ACTIVE"
    return created("airlines", db.insert("airlines", row))


@bp.route("/airlines", methods=["GET"])
def list_airlines():
    authenticate()
    return simple_list("airlines", {
        "status": {"type": "enum", "values": ["ACTIVE", "SUSPENDED"]},
        "waste_regime": {"type": "enum", "values": ["BONDED", "DOMESTIC"]},
    })


@bp.route("/airlines/<airline_id>", methods=["GET"])
def read_airline(airline_id):
    authenticate()
    row = resolve("airlines", airline_id)
    guard_scope("airlines", row)
    return one("airlines", row)


# ---------------------------------------------------------------------------
# meal specifications

SPEC_CREATE = [
    ("airline_id", {"type": "id", "required": True}),
    ("spec_code", {"type": "string", "required": True, "non_empty": True}),
    ("cabin", {"type": "enum", "required": True, "values": CABINS}),
    ("meal_code", {"type": "enum", "required": True, "values": MEAL_CODES}),
    ("storage_class", {"type": "enum", "required": True, "values": STORAGE_CLASSES}),
    ("portion_grams", {"type": "int", "required": True, "min": 1}),
    ("gross_weight_grams", {"type": "int", "required": True, "min": 1}),
    ("unit_cost_cents", {"type": "int", "required": True, "min": 1}),
    ("shelf_life_hours", {"type": "int", "required": True, "min": 1}),
    ("required_haccp_steps", {
        "type": "array", "required": True, "min_items": 1, "unique": True,
        "item": {"type": "enum", "values": HACCP_STEPS},
    }),
    ("load_factor_pct",
     {"type": "number", "min": 0, "max": 25, "decimals": 2, "default": Decimal("0.00")}),
    ("status", {"type": "enum", "values": ["ACTIVE", "RETIRED"], "default": "ACTIVE"}),
]


@bp.route("/meal-specifications", methods=["POST"])
def create_spec():
    authenticate(PLATFORM_ADMIN)
    data = validate.body(SPEC_CREATE)
    resolve("airlines", data["airline_id"])
    for existing in db.where("meal_specifications", airline_id=data["airline_id"]):
        if existing["spec_code"] == data["spec_code"]:
            fail("ERR_INVALID_REQUEST", "spec_code is already registered for this airline.")
    return created("meal_specifications", db.insert("meal_specifications", dict(data)))


@bp.route("/meal-specifications/<spec_id>", methods=["PATCH"])
def patch_spec(spec_id):
    authenticate(PLATFORM_ADMIN)
    data = validate.body([
        ("status", {"type": "enum", "values": ["ACTIVE", "RETIRED"]}),
        ("unit_cost_cents", {"type": "int", "min": 1}),
        ("load_factor_pct", {"type": "number", "min": 0, "max": 25, "decimals": 2}),
    ])
    row = resolve("meal_specifications", spec_id)
    row.update(data)
    db.touch(row)
    return one("meal_specifications", row)


@bp.route("/meal-specifications", methods=["GET"])
def list_specs():
    authenticate()
    return simple_list("meal_specifications", {
        "airline_id": {"type": "string"},
        "cabin": {"type": "enum", "values": CABINS},
        "meal_code": {"type": "enum", "values": MEAL_CODES},
        "storage_class": {"type": "enum", "values": STORAGE_CLASSES},
        "status": {"type": "enum", "values": ["ACTIVE", "RETIRED"]},
    })


@bp.route("/meal-specifications/<spec_id>", methods=["GET"])
def read_spec(spec_id):
    authenticate()
    row = resolve("meal_specifications", spec_id)
    guard_scope("meal_specifications", row)
    return one("meal_specifications", row)


# ---------------------------------------------------------------------------
# trucks


@bp.route("/trucks", methods=["POST"])
def create_truck():
    authenticate(PLATFORM_ADMIN)
    data = validate.body([
        ("station_code", {"type": "string", "required": True, "non_empty": True}),
        ("registration", {"type": "string", "required": True, "non_empty": True}),
        ("buffer_minutes", {"type": "int", "min": 0, "max": 120, "default": 20}),
        ("status", {"type": "enum", "values": ["ACTIVE", "MAINTENANCE"], "default": "ACTIVE"}),
    ])
    for existing in db.where("trucks", station_code=data["station_code"]):
        if existing["registration"] == data["registration"]:
            fail("ERR_INVALID_REQUEST", "registration is already registered at this station.")
    return created("trucks", db.insert("trucks", dict(data)))


@bp.route("/trucks/<truck_id>", methods=["PATCH"])
def patch_truck(truck_id):
    authenticate(PLATFORM_ADMIN)
    data = validate.body([
        ("status", {"type": "enum", "values": ["ACTIVE", "MAINTENANCE"]}),
        ("buffer_minutes", {"type": "int", "min": 0, "max": 120}),
    ])
    row = resolve("trucks", truck_id)
    row.update(data)
    db.touch(row)
    return one("trucks", row)


@bp.route("/trucks", methods=["GET"])
def list_trucks():
    authenticate()
    return simple_list("trucks", {
        "station_code": {"type": "string"},
        "status": {"type": "enum", "values": ["ACTIVE", "MAINTENANCE"]},
    })


@bp.route("/trucks/<truck_id>", methods=["GET"])
def read_truck(truck_id):
    authenticate()
    return one("trucks", resolve("trucks", truck_id))


# ---------------------------------------------------------------------------
# stands


@bp.route("/stands", methods=["POST"])
def create_stand():
    authenticate(PLATFORM_ADMIN)
    data = validate.body([
        ("station_code", {"type": "string", "required": True, "non_empty": True}),
        ("stand_code", {"type": "string", "required": True, "non_empty": True}),
        ("max_concurrent_runs", {"type": "int", "min": 1, "max": 6, "default": 2}),
        ("status", {"type": "enum", "values": ["ACTIVE", "CLOSED"], "default": "ACTIVE"}),
    ])
    for existing in db.where("stands", station_code=data["station_code"]):
        if existing["stand_code"] == data["stand_code"]:
            fail("ERR_INVALID_REQUEST", "stand_code is already registered at this station.")
    return created("stands", db.insert("stands", dict(data)))


@bp.route("/stands/<stand_id>", methods=["PATCH"])
def patch_stand(stand_id):
    authenticate(PLATFORM_ADMIN)
    data = validate.body([
        ("status", {"type": "enum", "values": ["ACTIVE", "CLOSED"]}),
        ("max_concurrent_runs", {"type": "int", "min": 1, "max": 6}),
    ])
    row = resolve("stands", stand_id)
    row.update(data)
    db.touch(row)
    return one("stands", row)


@bp.route("/stands", methods=["GET"])
def list_stands():
    authenticate()
    return simple_list("stands", {
        "station_code": {"type": "string"},
        "status": {"type": "enum", "values": ["ACTIVE", "CLOSED"]},
    })


@bp.route("/stands/<stand_id>", methods=["GET"])
def read_stand(stand_id):
    authenticate()
    return one("stands", resolve("stands", stand_id))


__all__ = ["bp", "calc"]
