"""ProductionRun endpoints: quote, confirm, schedule, start, complete, invoice, cancel."""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from domain import (CHANGEOVER_ALLERGEN_WASHOUT_MIN, CHANGEOVER_DIFF_CONTAINER_MIN,
                    CHANGEOVER_SAME_CONTAINER_MIN, CONTAINER_TYPES,
                    GIVEAWAY_RATE_CENTS_PER_LITER, UNITS_PER_CASE, UNITS_PER_PALLET,
                    ceil_div, reserve_units, ser_fg_lot, ser_run, zone_pallets_stored)
from errors import err
from routes_batches import get_batch_or_404
from routes_customers import get_customer_or_404
from routes_formulas import get_formula_or_404
from routes_lines import get_line_or_404
from services import release_run_reservations
from store import db, iso_ms, stamp, touch, trunc_minute
from util import body, ok, paginate, req_enum, req_field, require_any, require_roles

bp = Blueprint("runs", __name__)


def get_run_or_404(run_id):
    run = db.runs.get(run_id)
    if run is None:
        raise err("ERR_PRODUCTION_RUN_NOT_FOUND", f"ProductionRun {run_id} not found")
    return run


def get_zone_or_404(zone_id):
    zone = db.zones.get(zone_id)
    if zone is None:
        raise err("ERR_ZONE_NOT_FOUND", f"WarehouseZone {zone_id} not found")
    return zone


def _dec(v):
    return Decimal(str(v))


def _changeover_minutes(outgoing_run, incoming_run):
    """Directional changeover buffer from run E to run N."""
    base = (CHANGEOVER_SAME_CONTAINER_MIN
            if outgoing_run["container_type"] == incoming_run["container_type"]
            else CHANGEOVER_DIFF_CONTAINER_MIN)
    outgoing_formula = db.formulas.get(outgoing_run["formula_id"])
    incoming_formula = db.formulas.get(incoming_run["formula_id"])
    outgoing_allergen = outgoing_formula["allergen_group"] if outgoing_formula else "NONE"
    incoming_allergen = incoming_formula["allergen_group"] if incoming_formula else "NONE"
    if outgoing_allergen != "NONE" and outgoing_allergen != incoming_allergen:
        base += CHANGEOVER_ALLERGEN_WASHOUT_MIN
    return base


@bp.post("/v1/production-runs")
def create_run():
    require_roles("ProductionPlanner")
    data = body()
    customer_id = req_field(data, "customer_id", "str")
    formula_id = req_field(data, "formula_id", "str")
    container_type = req_enum(data, "container_type", CONTAINER_TYPES)
    planned_units = req_field(data, "planned_units", "int")
    unit_price_cents = req_field(data, "unit_price_cents", "int")
    get_customer_or_404(customer_id)
    formula = get_formula_or_404(formula_id)
    if formula["customer_id"] != customer_id:
        raise err("ERR_FORMULA_CUSTOMER_MISMATCH",
                  "The formula does not belong to this customer")
    run = {
        "customer_id": customer_id,
        "formula_id": formula_id,
        "container_type": container_type,
        "planned_units": planned_units,
        "unit_price_cents": unit_price_cents,
        "batch_id": None,
        "line_id": None,
        "scheduled_start_at": None,
        "scheduled_end_at": None,
        "label_version_pinned": None,
        "theoretical_units": None,
        "actual_units_filled": None,
        "avg_fill_ml": None,
        "giveaway_liters": None,
        "billable_units": None,
        "pallet_count": None,
        "provisional_invoice_cents": None,
        "final_invoice_cents": None,
        "production_status": "QUOTED",
        "invoice_status": "NOT_INVOICED",
        "_reservations": [],
        "_scheduled_start_dt": None,
        "_scheduled_end_dt": None,
    }
    stamp(run)
    db.runs[run["id"]] = run
    return ok(ser_run(run), 201)


@bp.get("/v1/production-runs")
def list_runs():
    require_any()
    customer_id = request.args.get("customer_id")
    formula_id = request.args.get("formula_id")
    production_status = request.args.get("production_status")
    items = list(db.runs.values())
    if customer_id is not None:
        items = [r for r in items if r["customer_id"] == customer_id]
    if formula_id is not None:
        items = [r for r in items if r["formula_id"] == formula_id]
    if production_status is not None:
        items = [r for r in items if r["production_status"] == production_status]
    return paginate(items, ser_run)


@bp.get("/v1/production-runs/<run_id>")
def get_run(run_id):
    require_any()
    return ok(ser_run(get_run_or_404(run_id)))


@bp.post("/v1/production-runs/<run_id>/confirm")
def confirm_run(run_id):
    require_roles("ProductionPlanner")
    run = get_run_or_404(run_id)
    if run["production_status"] != "QUOTED":
        raise err("ERR_RUN_STATE_INVALID", "confirm requires status QUOTED")
    customer = get_customer_or_404(run["customer_id"])
    if customer["status"] != "ACTIVE":
        raise err("ERR_CUSTOMER_NOT_ACTIVE", "Customer must be ACTIVE to confirm a run")
    formula = get_formula_or_404(run["formula_id"])
    if formula["status"] != "APPROVED":
        raise err("ERR_LABEL_NOT_APPROVED", "Formula must stand in APPROVED")
    if run["planned_units"] < customer["minimum_run_units"]:
        raise err("ERR_MINIMUM_RUN_NOT_MET",
                  "planned_units is below the customer's minimum run size")
    run["production_status"] = "CONFIRMED"
    touch(run)
    return ok(ser_run(run))


@bp.post("/v1/production-runs/<run_id>/schedule")
def schedule_run(run_id):
    require_roles("ProductionPlanner")
    run = get_run_or_404(run_id)
    data = body()
    batch_id = req_field(data, "batch_id", "str")
    line_id = req_field(data, "line_id", "str")
    scheduled_start = req_field(data, "scheduled_start_at", "datetime")
    scheduled_end = req_field(data, "scheduled_end_at", "datetime")
    expected = req_field(data, "expected_production_run_version", "int")
    batch = get_batch_or_404(batch_id)
    line = get_line_or_404(line_id)
    # category 4: OCC
    if expected != run["version"]:
        raise err("ERR_STALE_VERSION",
                  "expected_production_run_version does not match the run's current version")
    # category 5: state admissibility (target + cross-entity)
    if run["production_status"] not in ("CONFIRMED", "BLOCKED_SUPPLY"):
        raise err("ERR_RUN_STATE_INVALID",
                  "schedule requires status CONFIRMED or BLOCKED_SUPPLY")
    if line["status"] != "ACTIVE":
        raise err("ERR_LINE_STATE_INVALID", "Line must stand in ACTIVE")
    # category 6: label safety gate
    formula = get_formula_or_404(run["formula_id"])
    if formula["status"] != "APPROVED":
        raise err("ERR_LABEL_NOT_APPROVED", "Formula must stand in APPROVED")
    # category 7: referential linkability
    if batch["status"] != "RELEASED" or batch["formula_id"] != run["formula_id"]:
        raise err("ERR_BATCH_NOT_RELEASED",
                  "Batch must be RELEASED and belong to the run's formula")
    if batch.get("linked_run_id") is not None:
        raise err("ERR_BATCH_ALREADY_LINKED", "Batch is already linked to a run")
    # category 8: structural constraints
    if run["container_type"] not in line["supported_container_types"]:
        raise err("ERR_LINE_UNSUPPORTED_CONTAINER",
                  "Line does not support the run's container type")
    if scheduled_end <= scheduled_start:
        raise err("ERR_INVALID_WINDOW", "scheduled_end_at must be strictly after scheduled_start_at")
    new_start = trunc_minute(scheduled_start)
    new_end = trunc_minute(scheduled_end)
    for other in db.runs.values():
        if other.get("line_id") != line_id or other["id"] == run_id:
            continue
        if other["production_status"] not in ("SCHEDULED", "IN_PRODUCTION"):
            continue
        old_start = trunc_minute(other["_scheduled_start_dt"])
        old_end = trunc_minute(other["_scheduled_end_dt"])
        n_to_e = timedelta(minutes=_changeover_minutes(run, other))
        e_to_n = timedelta(minutes=_changeover_minutes(other, run))
        if new_end + n_to_e <= old_start or old_end + e_to_n <= new_start:
            continue
        raise err("ERR_LINE_WINDOW_CONFLICT",
                  "Line window conflicts with an existing booking (changeover buffer)")
    needed = reserve_units(run["planned_units"])
    pool = [l for l in db.container_lots.values()
            if l["container_type"] == run["container_type"] and l["status"] == "QC_PASSED"]
    available_total = sum(l["quantity_received"] - l["quantity_reserved"] - l["quantity_consumed"]
                          for l in pool)
    if available_total < needed:
        raise err("ERR_CONTAINER_SUPPLY_INSUFFICIENT",
                  "QC_PASSED container supply is below the required reserve")
    # side effects
    pool.sort(key=lambda l: (l["created_at"], l["_seq"]))
    remaining = needed
    reservations = []
    for lot in pool:
        if remaining <= 0:
            break
        available = lot["quantity_received"] - lot["quantity_reserved"] - lot["quantity_consumed"]
        take = min(available, remaining)
        if take <= 0:
            continue
        lot["quantity_reserved"] += take
        touch(lot)
        reservations.append({"lot_id": lot["id"], "units": take})
        remaining -= take
    run["_reservations"] = reservations
    run["label_version_pinned"] = formula["label_version"]
    processed = _dec(batch["processed_liters"])
    theoretical = int((processed * 1000) // _dec(formula["container_fill_ml"]))
    run["theoretical_units"] = theoretical
    run["batch_id"] = batch_id
    run["line_id"] = line_id
    run["scheduled_start_at"] = iso_ms(scheduled_start)
    run["scheduled_end_at"] = iso_ms(scheduled_end)
    run["_scheduled_start_dt"] = scheduled_start
    run["_scheduled_end_dt"] = scheduled_end
    run["production_status"] = "SCHEDULED"
    touch(run)
    batch["linked_run_id"] = run["id"]
    touch(batch)
    return ok(ser_run(run))


@bp.post("/v1/production-runs/<run_id>/start")
def start_run(run_id):
    require_roles("ProductionPlanner")
    run = get_run_or_404(run_id)
    if run["production_status"] != "SCHEDULED":
        raise err("ERR_RUN_STATE_INVALID", "start requires status SCHEDULED")
    line = get_line_or_404(run["line_id"])
    if line["status"] != "ACTIVE":
        raise err("ERR_LINE_STATE_INVALID", "Line must stand in ACTIVE")
    formula = get_formula_or_404(run["formula_id"])
    if run["label_version_pinned"] != formula["label_version"]:
        raise err("ERR_LABEL_VERSION_STALE",
                  "The pinned label version is no longer current")
    now = trunc_minute(db.clock)
    if not (trunc_minute(run["_scheduled_start_dt"]) <= now < trunc_minute(run["_scheduled_end_dt"])):
        raise err("ERR_RUN_WINDOW_NOT_ACTIVE",
                  "The logical clock is outside the run's scheduled window")
    run["production_status"] = "IN_PRODUCTION"
    touch(run)
    return ok(ser_run(run))


@bp.post("/v1/production-runs/<run_id>/complete")
def complete_run(run_id):
    require_roles("ProductionPlanner")
    run = get_run_or_404(run_id)
    data = body()
    actual_units = req_field(data, "actual_units_filled", "int")
    avg_fill = req_field(data, "avg_fill_ml", "num")
    zone_id = req_field(data, "warehouse_zone_id", "str")
    zone = get_zone_or_404(zone_id)
    if run["production_status"] != "IN_PRODUCTION":
        raise err("ERR_RUN_STATE_INVALID", "complete requires status IN_PRODUCTION")
    formula = get_formula_or_404(run["formula_id"])
    ceiling = min(run["theoretical_units"], reserve_units(run["planned_units"]))
    if actual_units < 1 or actual_units > ceiling:
        raise err("ERR_FILL_COUNT_EXCEEDS_THEORETICAL",
                  "actual_units_filled is outside the permitted bounds")
    if formula["process_type"] == "HPP":
        temp_ok = zone["temperature_class"] == "CHILLED"
    else:
        temp_ok = zone["temperature_class"] in ("AMBIENT", "CHILLED")
    if not temp_ok:
        raise err("ERR_ZONE_TEMPERATURE_MISMATCH",
                  "The zone's temperature class cannot hold this product")
    pallet_count = ceil_div(actual_units, UNITS_PER_PALLET[run["container_type"]])
    if zone_pallets_stored(zone) + pallet_count > zone["pallet_capacity"]:
        raise err("ERR_ZONE_CAPACITY_EXCEEDED", "The zone cannot hold these pallets")
    # yield + invoice accounting (pinned order)
    excess = max(Decimal("0"), _dec(avg_fill) - _dec(formula["container_fill_ml"]))
    giveaway = (excess * actual_units / 1000).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    billable = (actual_units // UNITS_PER_CASE) * UNITS_PER_CASE
    provisional = billable * run["unit_price_cents"]
    run["actual_units_filled"] = actual_units
    run["avg_fill_ml"] = avg_fill
    run["giveaway_liters"] = float(giveaway)
    run["billable_units"] = billable
    run["pallet_count"] = pallet_count
    run["provisional_invoice_cents"] = provisional
    run["production_status"] = "COMPLETED"
    run["invoice_status"] = "PROVISIONAL"
    touch(run)
    # finished-goods lot
    production_date = db.clock.date()
    shelf = formula["shelf_life_days"]
    expiry_label = production_date + timedelta(days=shelf)
    if formula["process_type"] == "HPP":
        expiry_stability = production_date + timedelta(days=(shelf * 3) // 2)
    else:
        expiry_stability = production_date + timedelta(days=shelf - 7)
    lot = {
        "production_run_id": run["id"],
        "formula_id": run["formula_id"],
        "customer_id": run["customer_id"],
        "warehouse_zone_id": zone_id,
        "lot_code": "FG-" + run["id"],
        "units_total": actual_units,
        "units_allocated": 0,
        "units_shipped": 0,
        "production_date": production_date.isoformat(),
        "expiry_label_date": expiry_label.isoformat(),
        "expiry_stability_date": expiry_stability.isoformat(),
        "status": "AVAILABLE",
        "_container_type": run["container_type"],
        "_expiry_label_date": expiry_label,
        "_expiry_stability_date": expiry_stability,
    }
    stamp(lot)
    db.fg_lots[lot["id"]] = lot
    # container consumption FIFO over the run's reserved lots, then release remainder
    to_consume = actual_units
    for entry in run["_reservations"]:
        cl = db.container_lots.get(entry["lot_id"])
        if cl is None:
            continue
        consume = min(entry["units"], to_consume)
        to_consume -= consume
        released = entry["units"] - consume
        cl["quantity_consumed"] += consume
        cl["quantity_reserved"] -= entry["units"]
        if cl["status"] == "QC_PASSED" and cl["quantity_reserved"] == 0 and \
                (cl["quantity_received"] - cl["quantity_consumed"]) == 0:
            cl["status"] = "DEPLETED"
        touch(cl)
    run["_reservations"] = []
    # batch consumption
    batch = db.batches.get(run["batch_id"])
    if batch is not None:
        if batch["status"] == "RELEASED":
            batch["status"] = "CONSUMED"
        if batch.get("linked_run_id") == run["id"]:
            batch["linked_run_id"] = None
        touch(batch)
    # provisional ledger posting
    customer = get_customer_or_404(run["customer_id"])
    customer["outstanding_balance_cents"] += provisional
    touch(customer)
    return ok(ser_run(run))


@bp.post("/v1/production-runs/<run_id>/finalize-invoice")
def finalize_invoice(run_id):
    require_roles("FinanceClerk")
    run = get_run_or_404(run_id)
    if run["production_status"] != "COMPLETED" or run["invoice_status"] != "PROVISIONAL":
        raise err("ERR_RUN_STATE_INVALID",
                  "finalize-invoice requires COMPLETED production with PROVISIONAL invoice")
    deduction = int((_dec(run["giveaway_liters"]) * GIVEAWAY_RATE_CENTS_PER_LITER)
                    .quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    final = run["provisional_invoice_cents"] - deduction
    run["final_invoice_cents"] = final
    run["invoice_status"] = "FINAL"
    touch(run)
    customer = get_customer_or_404(run["customer_id"])
    customer["outstanding_balance_cents"] += (final - run["provisional_invoice_cents"])
    touch(customer)
    return ok(ser_run(run))


@bp.post("/v1/production-runs/<run_id>/cancel")
def cancel_run(run_id):
    require_roles("ProductionPlanner")
    run = get_run_or_404(run_id)
    if run["production_status"] not in ("QUOTED", "CONFIRMED", "SCHEDULED",
                                        "BLOCKED_SUPPLY", "BLOCKED_LABEL"):
        raise err("ERR_RUN_STATE_INVALID",
                  "cancel requires a non-terminal production status")
    if run["_reservations"]:
        release_run_reservations(run)
    if run.get("batch_id"):
        batch = db.batches.get(run["batch_id"])
        if batch is not None and batch.get("linked_run_id") == run["id"]:
            batch["linked_run_id"] = None
            touch(batch)
    run["production_status"] = "CANCELLED"
    touch(run)
    return ok(ser_run(run))


@bp.get("/v1/production-runs/<run_id>/finished-good-lots")
def run_fg_lots(run_id):
    require_any()
    get_run_or_404(run_id)
    items = [l for l in db.fg_lots.values() if l["production_run_id"] == run_id]
    return paginate(items, ser_fg_lot)
