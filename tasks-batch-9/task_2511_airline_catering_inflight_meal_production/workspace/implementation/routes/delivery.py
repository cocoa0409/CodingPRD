"""Delivery runs: slot reservation, events, recovery runs, reads."""

from flask import Blueprint

import clock
import db
import validate
from errors import fail
from middleware import LOAD_MASTER, authenticate
from routes.helpers import created, guard_scope, one, resolve, simple_list
from services import calc, cascade
from timeutil import fmt_ms, minutes

bp = Blueprint("delivery", __name__)

RUN_STATUSES = [
    "RESERVED", "RESCHEDULED", "EN_ROUTE", "AT_AIRCRAFT", "DELIVERED",
    "MISSED", "RECOVERED", "CANCELLED",
]
MISS_REASONS = ["SLOT_LOST", "AIRCRAFT_NOT_READY", "TRAFFIC", "EQUIPMENT_FAILURE"]
EVENT_TYPES = ["DISPATCH", "ARRIVE", "DELIVER", "MISS"]

WINDOW_FIELDS = [
    ("window_start_utc", {"type": "datetime", "required": True}),
    ("window_end_utc", {"type": "datetime", "required": True}),
]


def _check_window(flight, truck, stand, start, end, exclude_ids=()):
    """The four window rules of PRD 3.7, in their pinned order."""
    if not start < end:
        fail("ERR_SLOT_WINDOW_INVALID")

    revised = calc.revised_std(flight)
    earliest = revised - minutes(calc.SLOT_EARLIEST_LEAD_MINUTES)
    latest = revised - minutes(calc.SLOT_LATEST_LEAD_MINUTES)
    if start < earliest or end > latest:
        fail("ERR_SLOT_OUTSIDE_FLIGHT_WINDOW")

    if truck["status"] != "ACTIVE" or stand["status"] != "ACTIVE":
        fail("ERR_SLOT_RESOURCE_UNAVAILABLE")

    if calc.truck_conflict(truck["id"], start, end, truck["buffer_minutes"], exclude_ids):
        fail("ERR_TRUCK_SLOT_CONFLICT")
    if calc.stand_conflict(stand["id"], start, end, stand["max_concurrent_runs"], exclude_ids):
        fail("ERR_STAND_CAPACITY_CONFLICT")


def _new_run(manifest, truck, stand, start, end, recovery_of=None):
    return db.insert("delivery_runs", {
        "loading_manifest_id": manifest["id"],
        "truck_id": truck["id"],
        "stand_id": stand["id"],
        "recovery_of_run_id": recovery_of,
        "window_start_utc": fmt_ms(start),
        "window_end_utc": fmt_ms(end),
        "_window_start": start,
        "_window_end": end,
        "status": "RESERVED",
        "dispatched_at_utc": None,
        "arrived_at_utc": None,
        "delivered_at_utc": None,
        "lateness_minutes": 0,
        "penalty_cents": 0,
        "miss_reason": None,
    })


# ---------------------------------------------------------------------------
# reservation


@bp.route("/delivery-runs", methods=["POST"])
def reserve_run():
    authenticate(LOAD_MASTER)
    data = validate.body([
        ("loading_manifest_id", {"type": "id", "required": True}),
        ("truck_id", {"type": "id", "required": True}),
        ("stand_id", {"type": "id", "required": True}),
    ] + WINDOW_FIELDS)

    manifest = resolve("loading_manifests", data["loading_manifest_id"])
    truck = resolve("trucks", data["truck_id"])
    stand = resolve("stands", data["stand_id"])

    if manifest["status"] != "ISSUED":
        fail("ERR_MANIFEST_NOT_ISSUED")
    flight = db.get("flights", manifest["flight_id"])

    _check_window(flight, truck, stand, data["window_start_utc"], data["window_end_utc"])
    run = _new_run(manifest, truck, stand, data["window_start_utc"], data["window_end_utc"])
    return created("delivery_runs", run)


# ---------------------------------------------------------------------------
# events


@bp.route("/delivery-runs/<run_id>/events", methods=["POST"])
def record_event(run_id):
    authenticate(LOAD_MASTER)
    data = validate.body([
        ("event_type", {"type": "enum", "required": True, "values": EVENT_TYPES}),
        ("miss_reason", {"type": "enum", "values": MISS_REASONS, "nullable": True}),
        ("note", {"type": "string", "nullable": True}),
    ])
    event = data["event_type"]
    reason = data.get("miss_reason")
    if event == "MISS" and (reason is None or reason == "SLOT_LOST"):
        fail("ERR_INVALID_REQUEST",
             "A missed run requires a miss_reason other than SLOT_LOST.")

    run = resolve("delivery_runs", run_id)
    manifest = db.get("loading_manifests", run["loading_manifest_id"])

    if event == "DISPATCH":
        return _dispatch(run, manifest)
    if event == "ARRIVE":
        return _arrive(run)
    if event == "DELIVER":
        return _deliver(run, manifest)
    return _miss(run, manifest, reason)


def _dispatch(run, manifest):
    if run["status"] not in ("RESERVED", "RESCHEDULED"):
        fail("ERR_INVALID_RUN_STATE")
    if manifest is None or manifest["status"] != "ISSUED":
        fail("ERR_MANIFEST_NOT_ISSUED")
    now = clock.now()
    if now < run["_window_start"] - minutes(calc.DISPATCH_LEAD_MINUTES):
        fail("ERR_INVALID_RUN_STATE")
    run["status"] = "EN_ROUTE"
    run["dispatched_at_utc"] = fmt_ms(now)
    db.touch(run)
    return one("delivery_runs", run)


def _arrive(run):
    if run["status"] != "EN_ROUTE":
        fail("ERR_INVALID_RUN_STATE")
    run["status"] = "AT_AIRCRAFT"
    run["arrived_at_utc"] = fmt_ms(clock.now())
    db.touch(run)
    return one("delivery_runs", run)


def _deliver(run, manifest):
    if run["status"] != "AT_AIRCRAFT":
        fail("ERR_INVALID_RUN_STATE")
    now = clock.now()
    flight = calc.flight_of_run(run)
    airline = calc.airline_of_flight(flight) if flight else None
    grace = airline["late_delivery_grace_minutes"] if airline else 0

    lateness = calc.lateness_minutes(now, run["_window_end"])
    billable = max(0, lateness - grace)
    penalty = calc.banded_penalty_cents(billable)

    run["status"] = "DELIVERED"
    run["delivered_at_utc"] = fmt_ms(now)
    run["lateness_minutes"] = lateness
    run["penalty_cents"] = penalty
    db.touch(run)

    if penalty >= 1 and flight is not None:
        cascade.raise_finding(
            flight["airline_id"], flight["id"], "LATE_DELIVERY", "MINOR", "SYSTEM"
        )
    cascade.check_departure(manifest)
    return one("delivery_runs", run)


def _miss(run, manifest, reason):
    if run["status"] not in ("EN_ROUTE", "AT_AIRCRAFT"):
        fail("ERR_INVALID_RUN_STATE")
    run["status"] = "MISSED"
    run["miss_reason"] = reason
    run["lateness_minutes"] = 0
    run["penalty_cents"] = calc.MISSED_FLAT_PENALTY_CENTS
    db.touch(run)

    flight = calc.flight_of_run(run)
    if flight is not None:
        cascade.raise_finding(
            flight["airline_id"], flight["id"], "LATE_DELIVERY", "MAJOR", "SYSTEM"
        )
    return one("delivery_runs", run)


# ---------------------------------------------------------------------------
# recovery


@bp.route("/delivery-runs/<run_id>/recovery-runs", methods=["POST"])
def create_recovery(run_id):
    authenticate(LOAD_MASTER)
    data = validate.body([
        ("truck_id", {"type": "id", "required": True}),
        ("stand_id", {"type": "id", "required": True}),
    ] + WINDOW_FIELDS)
    run = resolve("delivery_runs", run_id)
    truck = resolve("trucks", data["truck_id"])
    stand = resolve("stands", data["stand_id"])

    if run["status"] != "MISSED":
        fail("ERR_INVALID_RUN_STATE")
    for other in db.rows("delivery_runs"):
        if other["recovery_of_run_id"] == run["id"]:
            fail("ERR_INVALID_RUN_STATE")

    manifest = db.get("loading_manifests", run["loading_manifest_id"])
    flight = calc.flight_of_run(run)
    _check_window(flight, truck, stand, data["window_start_utc"], data["window_end_utc"])

    run["status"] = "RECOVERED"
    db.touch(run)
    recovery = _new_run(
        manifest, truck, stand,
        data["window_start_utc"], data["window_end_utc"], recovery_of=run["id"],
    )
    return created("delivery_runs", recovery)


# ---------------------------------------------------------------------------
# reads


@bp.route("/delivery-runs", methods=["GET"])
def list_runs():
    authenticate()
    return simple_list("delivery_runs", {
        "loading_manifest_id": {"type": "string"},
        "truck_id": {"type": "string"},
        "stand_id": {"type": "string"},
        "recovery_of_run_id": {"type": "string"},
        "status": {"type": "enum", "values": RUN_STATUSES},
    })


@bp.route("/delivery-runs/<run_id>", methods=["GET"])
def read_run(run_id):
    authenticate()
    run = resolve("delivery_runs", run_id)
    guard_scope("delivery_runs", run)
    return one("delivery_runs", run)
