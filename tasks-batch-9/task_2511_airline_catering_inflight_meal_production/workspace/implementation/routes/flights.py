"""Flights: intake, retiming, locking, delays, cancellation, planning, reads."""

from flask import Blueprint

import clock
import db
import response
import serialize
import validate
from errors import fail
from middleware import (
    COMPLIANCE_OFFICER,
    LOAD_MASTER,
    PRODUCTION_SUPERVISOR,
    SCHEDULE_FEED_OPERATOR,
    authenticate,
)
from routes.helpers import created, guard_scope, one, resolve, simple_list
from services import calc, cascade
from timeutil import fmt_ms, fmt_sec, minutes

bp = Blueprint("flights", __name__)

FLIGHT_STATUSES = [
    "SCHEDULED", "COUNTS_LOCKED", "PLANNED", "LOADED", "DEPARTED",
    "RECONCILED", "CANCELLED",
]
DELAY_OK_STATES = ("SCHEDULED", "COUNTS_LOCKED", "PLANNED", "LOADED")


def flight_or_404(flight_id):
    return resolve("flights", flight_id, "ERR_FLIGHT_NOT_FOUND")


def refresh_provisional(flight):
    flight["units_planned_provisional"] = calc.provisional_requirement(flight)


# ---------------------------------------------------------------------------
# intake


@bp.route("/flights", methods=["POST"])
def create_flight():
    authenticate(SCHEDULE_FEED_OPERATOR)
    data = validate.body([
        ("airline_id", {"type": "id", "required": True}),
        ("flight_number", {"type": "string", "required": True, "non_empty": True}),
        ("service_date", {"type": "date", "required": True}),
        ("std_utc", {"type": "datetime", "required": True}),
        ("tail_number", {"type": "string", "required": True, "non_empty": True}),
        ("station_code", {"type": "string", "required": True, "non_empty": True}),
        ("pax_first", {"type": "int", "min": 0, "default": 0}),
        ("pax_business", {"type": "int", "min": 0, "default": 0}),
        ("pax_economy", {"type": "int", "min": 0, "default": 0}),
    ])
    resolve("airlines", data["airline_id"])
    for existing in db.where("flights", airline_id=data["airline_id"]):
        if (existing["flight_number"] == data["flight_number"]
                and existing["service_date"] == data["service_date"]):
            fail("ERR_INVALID_REQUEST",
                 "This airline already has that flight number on that service date.")

    std = data.pop("std_utc")
    row = dict(data)
    row["_std"] = std
    row["std_utc"] = fmt_ms(std)
    row["delay_minutes"] = 0
    row["counts_locked_at"] = None
    row["status"] = "SCHEDULED"
    row["production_hold"] = False
    row["units_planned"] = 0
    row["units_planned_provisional"] = 0
    row["_final_requirement"] = None
    flight = db.insert("flights", row)
    refresh_provisional(flight)
    return created("flights", flight)


@bp.route("/flights/<flight_id>/pax-counts", methods=["PATCH"])
def patch_pax_counts(flight_id):
    authenticate(SCHEDULE_FEED_OPERATOR)
    data = validate.body([
        ("pax_first", {"type": "int", "min": 0}),
        ("pax_business", {"type": "int", "min": 0}),
        ("pax_economy", {"type": "int", "min": 0}),
    ])
    flight = flight_or_404(flight_id)
    if flight["status"] != "SCHEDULED":
        fail("ERR_FLIGHT_COUNTS_LOCKED")
    flight.update(data)
    refresh_provisional(flight)
    db.touch(flight)
    return one("flights", flight)


@bp.route("/flights/<flight_id>/schedule", methods=["PATCH"])
def patch_schedule(flight_id):
    authenticate(SCHEDULE_FEED_OPERATOR)
    data = validate.body([("std_utc", {"type": "datetime", "required": True})])
    flight = flight_or_404(flight_id)
    if flight["status"] != "SCHEDULED":
        fail("ERR_INVALID_FLIGHT_STATE")
    flight["_std"] = data["std_utc"]
    flight["std_utc"] = fmt_ms(data["std_utc"])
    refresh_provisional(flight)
    db.touch(flight)
    return one("flights", flight)


# ---------------------------------------------------------------------------
# locking the counts


def _confirm_order(order, spec_required_active=True):
    spec = db.get("meal_specifications", calc.effective_spec_id(order))
    if spec_required_active and (spec is None or spec["status"] != "ACTIVE"):
        return False
    order["status"] = "CONFIRMED"
    db.touch(order)
    return True


@bp.route("/flights/<flight_id>/lock-counts", methods=["POST"])
def lock_counts(flight_id):
    authenticate(SCHEDULE_FEED_OPERATOR)
    validate.body([])
    flight = flight_or_404(flight_id)
    if flight["status"] != "SCHEDULED":
        fail("ERR_INVALID_FLIGHT_STATE")
    if calc.total_pax(flight) < 1:
        fail("ERR_INVALID_FLIGHT_STATE", "The flight has no booked passengers.")

    now = clock.now()
    flight["status"] = "COUNTS_LOCKED"
    flight["counts_locked_at"] = fmt_ms(now)
    db.touch(flight)

    cutoff = calc.special_meal_cutoff(flight)
    for order in db.where("special_meal_orders", flight_id=flight["id"]):
        if order["status"] != "REQUESTED":
            continue
        if order["_requested_at"] <= cutoff:
            _confirm_order(order)
        else:
            order["status"] = "LATE_REJECTED"
            db.touch(order)
    return one("flights", flight)


# ---------------------------------------------------------------------------
# delays


def _reslot_runs(flight):
    """Shift every live run by the cumulative delay, cancelling collisions."""
    shift = minutes(flight["delay_minutes"])
    for run in calc.flight_runs(flight["id"]):
        if run["status"] not in ("RESERVED", "RESCHEDULED"):
            continue
        start = run["_window_start"] + shift
        end = run["_window_end"] + shift
        run["_window_start"] = start
        run["_window_end"] = end
        run["window_start_utc"] = fmt_ms(start)
        run["window_end_utc"] = fmt_ms(end)

        truck = db.get("trucks", run["truck_id"])
        stand = db.get("stands", run["stand_id"])
        buffer_minutes = truck["buffer_minutes"] if truck else 0
        max_concurrent = stand["max_concurrent_runs"] if stand else 1
        collides = calc.truck_conflict(
            run["truck_id"], start, end, buffer_minutes, exclude_ids=(run["id"],)
        ) or calc.stand_conflict(
            run["stand_id"], start, end, max_concurrent, exclude_ids=(run["id"],)
        )
        if collides:
            run["status"] = "CANCELLED"
            run["miss_reason"] = "SLOT_LOST"
        else:
            run["status"] = "RESCHEDULED"
        db.touch(run)
        cascade.amend_manifest(db.get("loading_manifests", run["loading_manifest_id"]))


@bp.route("/flights/<flight_id>/delays", methods=["POST"])
def record_delay(flight_id):
    authenticate(SCHEDULE_FEED_OPERATOR)
    data = validate.body([
        ("delay_minutes", {"type": "int", "required": True, "min": 1}),
        ("reason", {"type": "string", "nullable": True}),
    ])
    flight = flight_or_404(flight_id)
    if flight["status"] not in DELAY_OK_STATES:
        fail("ERR_INVALID_FLIGHT_STATE")

    flight["delay_minutes"] = flight["delay_minutes"] + data["delay_minutes"]
    db.touch(flight)

    cutoff = calc.special_meal_cutoff(flight)
    for order in db.where("special_meal_orders", flight_id=flight["id"]):
        if order["status"] != "LATE_REJECTED":
            continue
        if order["_requested_at"] > cutoff:
            continue
        order["status"] = "REQUESTED"
        db.touch(order)
        if flight["counts_locked_at"] is not None:
            _confirm_order(order)

    if flight["delay_minutes"] >= calc.DELAY_RESLOT_THRESHOLD_MINUTES:
        _reslot_runs(flight)
    return one("flights", flight)


# ---------------------------------------------------------------------------
# cancellation


@bp.route("/flights/<flight_id>/cancel", methods=["POST"])
def cancel_flight(flight_id):
    authenticate(SCHEDULE_FEED_OPERATOR)
    validate.body([("reason", {"type": "string", "nullable": True})])
    flight = flight_or_404(flight_id)
    if flight["status"] not in DELAY_OK_STATES:
        fail("ERR_INVALID_FLIGHT_STATE")

    flight["status"] = "CANCELLED"
    db.touch(flight)

    for order in db.where("special_meal_orders", flight_id=flight["id"]):
        if order["status"] in ("REQUESTED", "CONFIRMED"):
            order["status"] = "CANCELLED"
            db.touch(order)

    for batch in calc.flight_batches(flight["id"]):
        if batch["production_status"] in (
                "PLANNED", "IN_PRODUCTION", "HACCP_HOLD", "COMPLETED", "RELEASED"):
            cascade.reject_batch(batch)

    voided_at = fmt_ms(clock.now())
    for item in calc.flight_active_items(flight["id"]):
        item["status"] = "VOID"
        item["voided_at"] = voided_at
        db.touch(item)

    for manifest in calc.flight_manifests(flight["id"]):
        if manifest["status"] in ("DRAFT", "ISSUED", "AMENDED"):
            manifest["status"] = "VOID"
            db.touch(manifest)

    for run in calc.flight_runs(flight["id"]):
        if run["status"] in ("RESERVED", "RESCHEDULED", "EN_ROUTE", "AT_AIRCRAFT"):
            run["status"] = "CANCELLED"
            run["miss_reason"] = "SLOT_LOST"
            db.touch(run)

    return one("flights", flight)


# ---------------------------------------------------------------------------
# production planning


@bp.route("/flights/<flight_id>/production-plan", methods=["POST"])
def production_plan(flight_id):
    authenticate(PRODUCTION_SUPERVISOR)
    validate.body([])
    flight = flight_or_404(flight_id)
    if flight["status"] != "COUNTS_LOCKED":
        fail("ERR_INVALID_FLIGHT_STATE")
    airline = calc.airline_of_flight(flight)
    if airline is None or airline["status"] != "ACTIVE" or flight["production_hold"]:
        fail("ERR_AIRLINE_SUSPENDED")

    units, rows = calc.final_requirement(flight)
    allocations = calc.allocate_zones(rows)

    plan_instant = clock.now()
    revised = calc.revised_std(flight)
    created_batches = []
    total = 0
    requirement = {}
    for spec, qty in rows:
        requirement[spec["id"]] = requirement.get(spec["id"], 0) + qty
    for spec, zone, qty in allocations:
        deadline = calc.release_deadline(plan_instant, spec, zone, revised)
        batch = db.insert("production_batches", {
            "flight_id": flight["id"],
            "meal_specification_id": spec["id"],
            "store_zone": zone,
            "planned_qty": qty,
            "produced_qty": 0,
            "scrapped_qty": 0,
            "production_status": "PLANNED",
            "haccp_rework_rounds": 0,
            "release_deadline_utc": fmt_sec(deadline),
            "_deadline": deadline,
            "released_at": None,
            "released_by_user_id": None,
            "is_overflow": zone != spec["storage_class"],
        })
        created_batches.append(batch)
        total += qty

    flight["status"] = "PLANNED"
    flight["units_planned"] = total
    flight["_final_requirement"] = requirement
    db.touch(flight)
    return response.array(serialize.many("production_batches", created_batches), 201)


# ---------------------------------------------------------------------------
# loading manifest creation


@bp.route("/flights/<flight_id>/loading-manifests", methods=["POST"])
def create_manifest(flight_id):
    authenticate(LOAD_MASTER)
    data = validate.body([
        ("expected_flight_version", {"type": "int", "required": True, "min": 0}),
    ])
    flight = flight_or_404(flight_id)
    if data["expected_flight_version"] != flight["version"]:
        fail("ERR_STALE_FLIGHT_VERSION")
    if flight["status"] in ("DEPARTED", "RECONCILED", "CANCELLED"):
        fail("ERR_INVALID_FLIGHT_STATE")

    existing = calc.flight_manifests(flight["id"])
    ordinal = len(existing) + 1
    manifest = db.insert("loading_manifests", {
        "flight_id": flight["id"],
        "manifest_number": "MFST-%s-%d" % (flight["flight_number"], ordinal),
        "status": "DRAFT",
        "cart_seal_snapshot": [],
        "total_units": 0,
        "issued_at": None,
        "issued_by_user_id": None,
        "amendment_count": 0,
    })
    for earlier in existing:
        if earlier["status"] == "DRAFT":
            earlier["status"] = "VOID"
            db.touch(earlier)
    db.touch(flight)
    return created("loading_manifests", manifest)


# ---------------------------------------------------------------------------
# uplift reconciliation


def _latest_pinned_manifest(flight_id):
    live = [m for m in calc.flight_manifests(flight_id)
            if m["status"] in ("ISSUED", "AMENDED")]
    return live[-1] if live else None


@bp.route("/flights/<flight_id>/uplift-records", methods=["POST"])
def create_uplift(flight_id):
    authenticate(COMPLIANCE_OFFICER)
    data = validate.body([
        ("expected_flight_version", {"type": "int", "required": True, "min": 0}),
        ("lines", {
            "type": "array", "required": True, "min_items": 1,
            "item": {"type": "object", "fields": [
                ("meal_specification_id", {"type": "id", "required": True}),
                ("consumed_units", {"type": "int", "required": True, "min": 0}),
                ("returned_units", {"type": "int", "required": True, "min": 0}),
            ]},
        }),
        ("observed_seals", {
            "type": "array", "nullable": True,
            "item": {"type": "string"},
        }),
    ])
    flight = flight_or_404(flight_id)

    specs = []
    for line in data["lines"]:
        specs.append(resolve("meal_specifications", line["meal_specification_id"]))

    if data["expected_flight_version"] != flight["version"]:
        fail("ERR_STALE_FLIGHT_VERSION")
    if flight["status"] != "DEPARTED":
        fail("ERR_INVALID_FLIGHT_STATE")

    uplifted = calc.units_loaded(flight["id"])
    consumed = sum(line["consumed_units"] for line in data["lines"])
    returned = sum(line["returned_units"] for line in data["lines"])
    if consumed + returned != uplifted:
        fail("ERR_UPLIFT_UNITS_MISMATCH")

    # per-specification uplifted units and gross, from ACTIVE cart items only
    per_spec_units = {}
    per_spec_gross = {}
    for item in calc.flight_active_items(flight["id"]):
        spec = calc.spec_of_item(item)
        if spec is None:
            continue
        per_spec_units[spec["id"]] = per_spec_units.get(spec["id"], 0) + item["qty_units"]
        per_spec_gross[spec["id"]] = per_spec_gross.get(spec["id"], 0) + calc.item_gross_cents(
            item["qty_units"], spec["unit_cost_cents"]
        )

    lines = []
    for line, spec in zip(data["lines"], specs):
        lines.append({
            "meal_specification_id": spec["id"],
            "consumed_units": line["consumed_units"],
            "returned_units": line["returned_units"],
            "uplifted_units": per_spec_units.get(spec["id"], 0),
            "line_gross_cents": per_spec_gross.get(spec["id"], 0),
            "reuse_units": 0,
            "donate_units": 0,
            "destroy_units": 0,
        })
    order = {spec["id"]: spec["spec_code"] for spec in specs}
    lines.sort(key=lambda line: order.get(line["meal_specification_id"], ""))

    gross = calc.gross_cost_cents(flight["id"])
    net = gross
    handling = calc.handling_fee_cents(net)
    late = calc.late_penalty_cents(flight["id"])
    deviation = calc.spec_deviation_pct(flight)

    mismatch = 0
    manifest = _latest_pinned_manifest(flight["id"])
    if data.get("observed_seals") is not None and manifest is not None:
        observed = set(data["observed_seals"])
        for entry in manifest.get("cart_seal_snapshot") or []:
            if entry.get("seal_number") not in observed:
                mismatch += 1

    # A new reconciliation supersedes any earlier DRAFT record of the flight.
    for earlier in db.where("uplift_records", flight_id=flight["id"]):
        if earlier["status"] == "DRAFT":
            earlier["status"] = "VOID"
            db.touch(earlier)

    record = db.insert("uplift_records", {
        "flight_id": flight["id"],
        "lines": lines,
        "uplifted_units": uplifted,
        "consumed_units": consumed,
        "returned_units": returned,
        "unused_units": uplifted - consumed,
        "gross_cost_cents": gross,
        "net_cost_cents": net,
        "handling_fee_cents": handling,
        "late_penalty_cents": late,
        "billing_total_cents": net + handling + late,
        "cost_per_pax_cents": 0 if uplifted == 0 else calc.cost_per_pax_cents(flight),
        "spec_deviation_pct": deviation,
        "seal_mismatch_count": mismatch,
        "status": "DRAFT",
    })

    flight["status"] = "RECONCILED"
    db.touch(flight)

    airline = calc.airline_of_flight(flight)
    tolerance = airline["spec_deviation_tolerance_pct"] if airline else None
    if tolerance is not None and deviation >= tolerance:
        severity = calc.deviation_severity(deviation) or "MINOR"
        cascade.raise_finding(
            flight["airline_id"], flight["id"], "SPEC_DEVIATION", severity, "SYSTEM"
        )
    if mismatch >= 1:
        cascade.raise_finding(
            flight["airline_id"], flight["id"], "SEAL_MISMATCH", "MAJOR", "SYSTEM"
        )
    return created("uplift_records", record)


# ---------------------------------------------------------------------------
# reads


@bp.route("/flights", methods=["GET"])
def list_flights():
    authenticate()
    return simple_list("flights", {
        "airline_id": {"type": "string"},
        "station_code": {"type": "string"},
        "service_date": {"type": "string"},
        "status": {"type": "enum", "values": FLIGHT_STATUSES},
        "production_hold": {"type": "bool"},
    })


@bp.route("/flights/<flight_id>", methods=["GET"])
def read_flight(flight_id):
    authenticate()
    flight = flight_or_404(flight_id)
    guard_scope("flights", flight)
    return one("flights", flight)


@bp.route("/flights/<flight_id>/cost-report", methods=["GET"])
def read_cost_report(flight_id):
    authenticate()
    flight = flight_or_404(flight_id)
    guard_scope("flights", flight)
    return response.ok(calc.cost_report(flight))
