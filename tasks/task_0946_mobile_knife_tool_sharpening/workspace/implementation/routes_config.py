"""Logical clock and the PlatformAdmin configuration surface."""

from flask import Blueprint

import clock as clockmod
import envelope
import ladder
import serializers as ser
import services
from constants import (
    CADENCES,
    DEFAULT_BENCH_MINUTE_BUDGET,
    DEFAULT_RUN_SERVICE_MINUTE_BUDGET,
    DEFAULT_RUN_STOP_CAP,
    ITEM_CLASSES,
    LOCKER_SIZES,
    PRICE_TIERS,
    REQUIRED_CERTIFICATIONS,
)
from errors import ApiError
from store import db, stamp_new

bp = Blueprint("config", __name__)


# ---------------------------------------------------------------------------
# POST /_clock/set_current_utc
# ---------------------------------------------------------------------------
CLOCK_SPEC = ladder.Spec(
    required=[("to_iso8601", "string")],
    instants=["to_iso8601"],
)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    ctx = ladder.begin("PlatformAdmin")
    CLOCK_SPEC.validate(ctx.body)
    instant = clockmod.parse_instant(ctx.body["to_iso8601"])
    # Rung 39: the clock may only move forward.
    if instant < clockmod.clock.now:
        raise ApiError("ERR_VALUE_OUT_OF_RANGE", "The logical clock may only move forward.")
    clockmod.clock.set(instant, ctx.body["to_iso8601"])
    return envelope.ok({"current_utc": clockmod.clock.literal})


# ---------------------------------------------------------------------------
# POST /sharpening/plan-tiers
# ---------------------------------------------------------------------------
PLAN_TIER_SPEC = ladder.Spec(
    required=[
        ("code", "string"),
        ("monthly_fee_cents", "integer"),
        ("included_items_per_cycle", "integer"),
        ("overage_discount_pct", "number"),
        ("allowed_cadences", "array"),
    ],
    enum_arrays={"allowed_cadences": CADENCES},
    ranges={
        "monthly_fee_cents": (0, None),
        "included_items_per_cycle": (0, None),
        "overage_discount_pct": (0, None),
    },
)


@bp.route("/sharpening/plan-tiers", methods=["POST"])
def create_plan_tier():
    ctx = ladder.begin("PlatformAdmin")
    PLAN_TIER_SPEC.validate(ctx.body)
    if ctx.body["overage_discount_pct"] >= 1:
        raise ApiError("ERR_VALUE_OUT_OF_RANGE", "overage_discount_pct must be below 1.")
    row = stamp_new(
        {
            "code": ctx.body["code"],
            "monthly_fee_cents": ctx.body["monthly_fee_cents"],
            "included_items_per_cycle": ctx.body["included_items_per_cycle"],
            "overage_discount_pct": ctx.body["overage_discount_pct"],
            "allowed_cadences": list(ctx.body["allowed_cadences"]),
        }
    )
    db.plan_tiers[row["id"]] = row
    return envelope.created(ser.plan_tier(row))


# ---------------------------------------------------------------------------
# POST /sharpening/item-class-specs
# ---------------------------------------------------------------------------
SPEC_SPEC = ladder.Spec(
    required=[
        ("item_class", "string"),
        ("bevel_angle_degrees", "integer"),
        ("base_service_minutes", "integer"),
        ("list_price_cents", "integer"),
        ("required_certification", "string"),
        ("price_tier", "string"),
        ("min_locker_size", "string"),
    ],
    optional=[("loaner_eligible", "boolean")],
    enums={
        "item_class": ITEM_CLASSES,
        "required_certification": REQUIRED_CERTIFICATIONS,
        "price_tier": PRICE_TIERS,
        "min_locker_size": LOCKER_SIZES,
    },
    ranges={
        "bevel_angle_degrees": (10, 60),
        "base_service_minutes": (1, None),
        "list_price_cents": (0, None),
    },
)


@bp.route("/sharpening/item-class-specs", methods=["POST"])
def create_item_class_spec():
    ctx = ladder.begin("PlatformAdmin")
    SPEC_SPEC.validate(ctx.body)
    # Rung 45: one spec per edge-geometry class.
    for existing in db.item_class_specs.values():
        if existing["item_class"] == ctx.body["item_class"]:
            raise ApiError("ERR_DUPLICATE_ITEM_CLASS_SPEC")
    row = stamp_new(
        {
            "item_class": ctx.body["item_class"],
            "bevel_angle_degrees": ctx.body["bevel_angle_degrees"],
            "base_service_minutes": ctx.body["base_service_minutes"],
            "list_price_cents": ctx.body["list_price_cents"],
            "required_certification": ctx.body["required_certification"],
            "price_tier": ctx.body["price_tier"],
            "min_locker_size": ctx.body["min_locker_size"],
            "loaner_eligible": bool(ctx.body.get("loaner_eligible", False)),
        }
    )
    db.item_class_specs[row["id"]] = row
    return envelope.created(ser.item_class_spec(row))


# ---------------------------------------------------------------------------
# POST /sharpening/technicians
# ---------------------------------------------------------------------------
TECHNICIAN_SPEC = ladder.Spec(
    required=[("full_name", "string")],
    optional=[("certifications", "array")],
)


@bp.route("/sharpening/technicians", methods=["POST"])
def create_technician():
    ctx = ladder.begin("PlatformAdmin")
    TECHNICIAN_SPEC.validate(ctx.body)
    row = stamp_new(
        {
            "full_name": ctx.body["full_name"],
            "certifications": list(ctx.body.get("certifications") or []),
        }
    )
    db.technicians[row["id"]] = row
    return envelope.created(ser.technician(row))


# ---------------------------------------------------------------------------
# POST /sharpening/vans
# ---------------------------------------------------------------------------
VAN_SPEC = ladder.Spec(
    required=[("code", "string")],
    optional=[
        ("default_service_minute_budget", "integer"),
        ("default_stop_cap", "integer"),
    ],
    ranges={"default_service_minute_budget": (1, None), "default_stop_cap": (1, None)},
)


@bp.route("/sharpening/vans", methods=["POST"])
def create_van():
    ctx = ladder.begin("PlatformAdmin")
    VAN_SPEC.validate(ctx.body)
    row = stamp_new(
        {
            "code": ctx.body["code"],
            "default_service_minute_budget": ctx.body.get(
                "default_service_minute_budget", DEFAULT_RUN_SERVICE_MINUTE_BUDGET
            ),
            "default_stop_cap": ctx.body.get("default_stop_cap", DEFAULT_RUN_STOP_CAP),
        }
    )
    db.vans[row["id"]] = row
    return envelope.created(ser.van(row))


# ---------------------------------------------------------------------------
# POST /sharpening/bench-days , GET /sharpening/bench-days/{id}
# ---------------------------------------------------------------------------
BENCH_DAY_SPEC = ladder.Spec(
    required=[("bench_date", "string")],
    optional=[("bench_minute_budget", "integer")],
    ranges={"bench_minute_budget": (1, None)},
    dates=["bench_date"],
)


@bp.route("/sharpening/bench-days", methods=["POST"])
def create_bench_day():
    ctx = ladder.begin("PlatformAdmin")
    BENCH_DAY_SPEC.validate(ctx.body)
    bench_date = clockmod.parse_date(ctx.body["bench_date"])
    # Rung 46: one bench day per date.
    for existing in db.bench_days.values():
        if existing["bench_date"] == bench_date:
            raise ApiError("ERR_DUPLICATE_BENCH_DAY")
    row = stamp_new(
        {
            "bench_date": bench_date,
            "bench_minute_budget": ctx.body.get(
                "bench_minute_budget", DEFAULT_BENCH_MINUTE_BUDGET
            ),
        }
    )
    db.bench_days[row["id"]] = row
    return envelope.created(ser.bench_day(row))


@bp.route("/sharpening/bench-days/<id>", methods=["GET"])
def get_bench_day(id):
    ctx = ladder.begin("PlatformAdmin", "Technician")
    row = ladder.must_exist(db.bench_days, id, "BenchDay")
    services.acting_technician(ctx)
    return envelope.ok(ser.bench_day(row))


# ---------------------------------------------------------------------------
# POST /sharpening/locker-compartments
# ---------------------------------------------------------------------------
COMPARTMENT_SPEC = ladder.Spec(
    required=[("site_code", "string"), ("size", "string")],
    enums={"size": LOCKER_SIZES},
)


@bp.route("/sharpening/locker-compartments", methods=["POST"])
def create_locker_compartment():
    ctx = ladder.begin("PlatformAdmin")
    COMPARTMENT_SPEC.validate(ctx.body)
    row = stamp_new(
        {
            "site_code": ctx.body["site_code"],
            "size": ctx.body["size"],
            "current_service_request_id": None,
            "status": "AVAILABLE",
            "access_code": None,
            "hold_expires_at": None,
            "last_released_at": None,
        }
    )
    db.locker_compartments[row["id"]] = row
    return envelope.created(ser.locker_compartment(row))
