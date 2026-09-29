"""Processing campaigns, allocations and the production lifecycle (PRD 3.5-3.6)."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import calc
import domain
import response
import store
import validate
from constants import MIN_CHARGE_MT, YIELD_VARIANCE_TOLERANCE_PCT
from errors import (
    ERR_CATALYST_NOT_ACTIVE,
    ERR_INVALID_ALLOCATION_STATE,
    ERR_INVALID_RUN_STATE,
    ERR_INVALID_RUN_WINDOW,
    ERR_INVALID_UNIT_STATE,
    ERR_LOT_MASS_EXCEEDED,
    ERR_LOT_NOT_ACCEPTED,
    ERR_MASS_BALANCE_VIOLATION,
    ERR_MIN_CHARGE_NOT_MET,
    ERR_NO_FEEDSTOCK_ALLOCATED,
    ERR_HYDROGEN_COVERAGE_SHORTFALL,
    ERR_PRETREATMENT_REQUIRED,
    ERR_RUN_WINDOW_NOT_ELAPSED,
    ERR_SAF_SHARE_EXCEEDED,
    ERR_STALE_RUN_VERSION,
    ERR_SUPPLIER_DUE_DILIGENCE_EXPIRED,
    ERR_SUPPLIER_DUE_DILIGENCE_INCOMPLETE,
    ERR_UNIT_CAPACITY_EXCEEDED,
    ERR_UNIT_WINDOW_CONFLICT,
    fail,
)
from routes.helpers import body_ref, find, listing
from routes.units import overlaps
from store import bump, q

bp = Blueprint("runs", __name__)
ZERO = Decimal("0")
BLOCKING_RUN_STATES = ("PLANNED", "HYDROGEN_SECURED", "RUNNING")
BLOCKING_WINDOW_STATES = ("PLANNED", "APPROVED", "IN_PROGRESS")


def _midnight(dt):
    return (dt.hour == 0 and dt.minute == 0 and dt.second == 0 and dt.microsecond == 0)


@bp.post("/processing-runs")
def create_run():
    validate.auth("PlantOperator")
    data = validate.body()
    unit = body_ref("unit", data, "unit_id")
    charge = body_ref("charge", data, "catalyst_charge_id")
    window_start = validate.get_dt(data, "window_start")
    window_end = validate.get_dt(data, "window_end")
    target_saf = validate.get_num(data, "target_saf_share_pct", 0, 60, 2)

    if charge["status"] != "ACTIVE":
        fail(ERR_CATALYST_NOT_ACTIVE,
             "Catalyst charge is %s, not ACTIVE." % charge["status"])

    for other in domain.unit_runs(unit["id"]):
        if other["status"] not in BLOCKING_RUN_STATES:
            continue
        if overlaps(window_start, window_end, other["window_start"], other["window_end"]):
            fail(ERR_UNIT_WINDOW_CONFLICT,
                 "Another campaign on this unit intersects the requested interval.")
    for window in domain.unit_windows(unit["id"]):
        if window["status"] not in BLOCKING_WINDOW_STATES:
            continue
        if overlaps(window_start, window_end, window["start_at"], window["end_at"]):
            fail(ERR_UNIT_WINDOW_CONFLICT,
                 "A turnaround window on this unit intersects the requested interval.")

    if not _midnight(window_start) or not _midnight(window_end) or window_end <= window_start:
        fail(ERR_INVALID_RUN_WINDOW,
             "The campaign window must be midnight-aligned whole days with "
             "window_end strictly after window_start.")
    span = window_end - window_start
    if span.seconds or span.microseconds:
        fail(ERR_INVALID_RUN_WINDOW, "The campaign window must be a whole number of days.")

    if target_saf > unit["max_saf_share_pct"]:
        fail(ERR_SAF_SHARE_EXCEEDED,
             "target_saf_share_pct exceeds the unit's max_saf_share_pct.")

    row = store.new_row()
    row.update({
        "unit_id": unit["id"],
        "catalyst_charge_id": charge["id"],
        "window_start": window_start,
        "window_end": window_end,
        "target_saf_share_pct": q(target_saf, 2),
        "status": "PLANNED",
        "run_days": span.days,
        "reserved_mass_mt": q(ZERO, 3),
        "consumed_mass_mt": q(ZERO, 3),
        "blend_ci_gco2e_per_mj": None,
        "required_h2_kg_per_day": None,
        "provisional_yield_pct": None,
        "planned_total_product_mt": None,
        "planned_rd_mt": None,
        "planned_saf_mt": None,
        "measured_rd_mt": q(ZERO, 3),
        "measured_saf_mt": q(ZERO, 3),
        "final_yield_pct": None,
        "yield_variance_pct": None,
        "yield_variance_flag": False,
        "feedstock_cost_usd": None,
        "abort_reason": None,
    })
    store.runs[row["id"]] = row
    return response.ok(row, 201)


@bp.get("/processing-runs/<run_id>")
def read_run(run_id):
    validate.auth("PlantOperator", "ComplianceOfficer", "FeedstockTrader")
    return response.ok(find("run", run_id))


@bp.get("/processing-runs")
def list_runs():
    validate.auth("PlantOperator", "ComplianceOfficer", "FeedstockTrader")
    rows, limit, offset = listing(store.table_rows(store.runs), {
        "unit_id": "unit_id",
        "catalyst_charge_id": "catalyst_charge_id",
        "status": "status",
    })
    return response.page(rows, limit, offset)


@bp.post("/processing-runs/<run_id>/allocations")
def create_allocation(run_id):
    validate.auth("FeedstockTrader")
    run = find("run", run_id)
    data = validate.body()
    lot = body_ref("lot", data, "lot_id")
    mass_mt = validate.get_num(data, "mass_mt", 0, 20000, 3, exclusive_min=True)
    expected_version = validate.get_int(data, "expected_run_version")

    if expected_version != run["version"]:
        fail(ERR_STALE_RUN_VERSION,
             "Campaign version is %d, not %d." % (run["version"], expected_version))

    if run["status"] not in ("PLANNED", "HYDROGEN_SECURED"):
        fail(ERR_INVALID_RUN_STATE,
             "A campaign in %s cannot take new allocations." % run["status"])

    supplier = store.suppliers.get(lot["supplier_id"])
    if supplier is None or supplier["dd_status"] != "VERIFIED":
        fail(ERR_SUPPLIER_DUE_DILIGENCE_INCOMPLETE,
             "The lot's supplier has not completed due diligence.")
    if supplier["dd_expires_at"] is None or supplier["dd_expires_at"] <= store.now():
        fail(ERR_SUPPLIER_DUE_DILIGENCE_EXPIRED,
             "The lot's supplier due diligence has expired.")
    if lot["status"] == "PRETREAT_REQUIRED":
        fail(ERR_PRETREATMENT_REQUIRED,
             "Lot still owes %s pretreatment." % lot["pretreatment_tier"])
    if lot["status"] != "ACCEPTED":
        fail(ERR_LOT_NOT_ACCEPTED, "Lot is %s, not ACCEPTED." % lot["status"])

    mass_mt = q(mass_mt, 3)
    if mass_mt > lot["remaining_mass_mt"]:
        fail(ERR_LOT_MASS_EXCEEDED,
             "Requested %s exceeds the lot's remaining %s metric tonnes."
             % (mass_mt, lot["remaining_mass_mt"]))

    row = store.new_row()
    row.update({
        "run_id": run["id"],
        "lot_id": lot["id"],
        "mass_mt": mass_mt,
        "line_cost_usd": None,
        "status": "RESERVED",
        "release_reason": None,
    })
    store.allocations[row["id"]] = row

    domain.recompute_lot_masses(lot)
    bump(lot)
    domain.recompute_run_masses(run)
    domain.recompute_run_blend(run)
    bump(run)
    return response.ok(row, 201)


@bp.get("/processing-runs/<run_id>/allocations")
def list_run_allocations(run_id):
    validate.auth("FeedstockTrader", "PlantOperator", "ComplianceOfficer")
    run = find("run", run_id)
    rows, limit, offset = listing(domain.run_allocations(run["id"]), {"status": "status"})
    return response.page(rows, limit, offset)


@bp.post("/feedstock-allocations/<allocation_id>/releases")
def release_allocation(allocation_id):
    validate.auth("FeedstockTrader")
    alloc = find("allocation", allocation_id)
    if alloc["status"] != "RESERVED":
        fail(ERR_INVALID_ALLOCATION_STATE,
             "Only a RESERVED allocation may be released; this one is %s." % alloc["status"])
    run = store.runs.get(alloc["run_id"])
    if run is not None and run["status"] not in ("PLANNED", "HYDROGEN_SECURED"):
        fail(ERR_INVALID_RUN_STATE,
             "A campaign in %s cannot release allocations." % run["status"])

    was_secured = run is not None and run["status"] == "HYDROGEN_SECURED"
    domain.release_allocation(alloc, "MANUAL")
    if run is not None:
        domain.recompute_run_masses(run)
        domain.recompute_run_blend(run)
        bump(run)
        if was_secured and run["reserved_mass_mt"] < MIN_CHARGE_MT:
            run["status"] = "PLANNED"
            domain.reset_planned_figures(run)
            domain.cancel_run_nominations(run)
    return response.ok(alloc)


@bp.post("/processing-runs/<run_id>/hydrogen-securements")
def secure_hydrogen(run_id):
    validate.auth("PlantOperator")
    run = find("run", run_id)
    if run["status"] != "PLANNED":
        fail(ERR_INVALID_RUN_STATE, "Campaign is %s, not PLANNED." % run["status"])

    charge = store.charges.get(run["catalyst_charge_id"])
    if charge is None or charge["status"] != "ACTIVE":
        fail(ERR_CATALYST_NOT_ACTIVE, "The cited catalyst charge is no longer ACTIVE.")

    reserved_lines = [a for a in domain.run_allocations(run["id"])
                      if a["status"] == "RESERVED"]
    if not reserved_lines:
        fail(ERR_NO_FEEDSTOCK_ALLOCATED, "The campaign holds no RESERVED allocation.")

    domain.recompute_run_masses(run)
    domain.recompute_run_blend(run)

    if run["reserved_mass_mt"] < MIN_CHARGE_MT:
        fail(ERR_MIN_CHARGE_NOT_MET,
             "Reserved mass %s is below the %s metric tonne minimum charge."
             % (run["reserved_mass_mt"], MIN_CHARGE_MT))

    unit = store.units.get(run["unit_id"])
    daily_feed = q(run["reserved_mass_mt"] / Decimal(run["run_days"]), 3)
    if unit is not None and daily_feed > unit["nameplate_capacity_mt_per_day"]:
        fail(ERR_UNIT_CAPACITY_EXCEEDED,
             "Daily feed %s exceeds nameplate capacity %s."
             % (daily_feed, unit["nameplate_capacity_mt_per_day"]))
    if unit is not None and run["target_saf_share_pct"] > unit["max_saf_share_pct"]:
        fail(ERR_SAF_SHARE_EXCEEDED,
             "target_saf_share_pct exceeds the unit's max_saf_share_pct.")

    if not domain.hydrogen_coverage_ok(run):
        fail(ERR_HYDROGEN_COVERAGE_SHORTFALL,
             "Confirmed nominations do not cover every day of the window at %s kg/day."
             % run["required_h2_kg_per_day"])

    lines = [(a["mass_mt"], store.lots[a["lot_id"]]) for a in reserved_lines
             if a["lot_id"] in store.lots]
    split = calc.provisional_split(lines, charge["activity_index"],
                                   run["reserved_mass_mt"], run["target_saf_share_pct"])
    run["status"] = "HYDROGEN_SECURED"
    if split is not None:
        run.update(split)
    bump(run)
    return response.ok(run)


@bp.post("/processing-runs/<run_id>/starts")
def start_run(run_id):
    validate.auth("PlantOperator")
    run = find("run", run_id)
    if run["status"] != "HYDROGEN_SECURED":
        fail(ERR_INVALID_RUN_STATE,
             "Campaign is %s, not HYDROGEN_SECURED." % run["status"])

    unit = store.units.get(run["unit_id"])
    if unit is None or unit["status"] != "IDLE":
        fail(ERR_INVALID_UNIT_STATE,
             "The unit must be IDLE to start a campaign; it is %s."
             % (unit["status"] if unit else "missing"))

    charge = store.charges.get(run["catalyst_charge_id"])
    if charge is None or charge["status"] != "ACTIVE":
        fail(ERR_CATALYST_NOT_ACTIVE, "The cited catalyst charge is no longer ACTIVE.")

    if store.now() < run["window_start"]:
        fail(ERR_INVALID_RUN_STATE,
             "The logical clock has not reached the campaign's window_start.")

    for window in domain.unit_windows(unit["id"]):
        if window["status"] == "IN_PROGRESS":
            fail(ERR_INVALID_UNIT_STATE,
                 "A turnaround window on this unit is IN_PROGRESS.")

    lots_touched = []
    for alloc in domain.run_allocations(run["id"]):
        if alloc["status"] != "RESERVED":
            continue
        alloc["status"] = "CONSUMED"
        bump(alloc)
        lot = store.lots.get(alloc["lot_id"])
        if lot is not None and lot not in lots_touched:
            lots_touched.append(lot)

    domain.recompute_run_masses(run)
    run["reserved_mass_mt"] = q(ZERO, 3)
    for lot in lots_touched:
        domain.recompute_lot_masses(lot)
        if lot["remaining_mass_mt"] == ZERO and lot["status"] == "ACCEPTED":
            lot["status"] = "CHARGED"
        bump(lot)

    unit["status"] = "RUNNING"
    bump(unit)
    run["status"] = "RUNNING"
    bump(run)
    return response.ok(run)


def _create_batch(run, product_type, mass_mt):
    row = store.new_row()
    row.update({
        "run_id": run["id"],
        "product_type": product_type,
        "mass_mt": q(mass_mt, 3),
        "volume_gal": calc.product_volume(mass_mt, product_type),
        "cert_status": "UNCERTIFIED",
        "distribution_status": "IN_TANK",
        "astm_annex": None,
        "freeze_point_c": None,
        "cert_reject_reason": None,
        "offtaker_name": None,
    })
    store.batches[row["id"]] = row
    return row


@bp.post("/processing-runs/<run_id>/completions")
def complete_run(run_id):
    validate.auth("PlantOperator")
    run = find("run", run_id)
    data = validate.body()
    measured_rd = validate.get_num(data, "measured_rd_mt", 0, 1000000, 3)
    measured_saf = validate.get_num(data, "measured_saf_mt", 0, 1000000, 3)

    if run["status"] != "RUNNING":
        fail(ERR_INVALID_RUN_STATE, "Campaign is %s, not RUNNING." % run["status"])

    if store.now() < run["window_end"]:
        fail(ERR_RUN_WINDOW_NOT_ELAPSED,
             "The logical clock has not reached the campaign's window_end.")

    measured_rd = q(measured_rd, 3)
    measured_saf = q(measured_saf, 3)
    total = measured_rd + measured_saf
    unit = store.units.get(run["unit_id"])
    if total > ZERO and unit is not None:
        share = q(measured_saf / total * Decimal("100"), 2)
        if share > unit["max_saf_share_pct"]:
            fail(ERR_SAF_SHARE_EXCEEDED,
                 "Measured SAF share %s exceeds the unit's max_saf_share_pct %s."
                 % (share, unit["max_saf_share_pct"]))
    if q(total, 3) > run["consumed_mass_mt"]:
        fail(ERR_MASS_BALANCE_VIOLATION,
             "Measured product %s exceeds consumed feedstock %s."
             % (q(total, 3), run["consumed_mass_mt"]))

    run["status"] = "COMPLETED"
    run["measured_rd_mt"] = measured_rd
    run["measured_saf_mt"] = measured_saf
    final = calc.final_yield(measured_rd, measured_saf, run["consumed_mass_mt"])
    run["final_yield_pct"] = final
    provisional = run["provisional_yield_pct"] or q(ZERO, 3)
    if final is None:
        run["yield_variance_pct"] = None
        run["yield_variance_flag"] = False
    else:
        variance = q(final - provisional, 3)
        run["yield_variance_pct"] = variance
        run["yield_variance_flag"] = abs(variance) > YIELD_VARIANCE_TOLERANCE_PCT

    charge = store.charges.get(run["catalyst_charge_id"])
    if charge is not None:
        domain.recompute_charge(charge)
        charge_touched = True
        if charge["cumulative_throughput_mt"] >= charge["design_throughput_mt"] \
                and charge["status"] in ("ACTIVE", "DERATED"):
            charge["status"] = "SPENT"
            if unit is not None:
                unit["requires_turnaround"] = True
        elif run["yield_variance_flag"] and charge["status"] == "ACTIVE":
            charge["status"] = "DERATED"
            if unit is not None:
                unit["requires_turnaround"] = True
        if charge_touched:
            bump(charge)

    if measured_rd > ZERO:
        _create_batch(run, "RENEWABLE_DIESEL", measured_rd)
    if measured_saf > ZERO:
        _create_batch(run, "SAF", measured_saf)

    if unit is not None:
        unit["status"] = "IDLE"
        bump(unit)
    bump(run)
    return response.ok(run)


@bp.post("/processing-runs/<run_id>/reconciliations")
def reconcile_run(run_id):
    validate.auth("ComplianceOfficer")
    run = find("run", run_id)
    if run["status"] != "COMPLETED":
        fail(ERR_INVALID_RUN_STATE, "Campaign is %s, not COMPLETED." % run["status"])

    total = ZERO
    for alloc in domain.run_allocations(run["id"]):
        if alloc["status"] != "CONSUMED":
            continue
        lot = store.lots.get(alloc["lot_id"])
        price = lot["purchase_price_usd_per_mt"] if lot is not None else ZERO
        line = calc.settlement_line(alloc["mass_mt"], price)
        alloc["line_cost_usd"] = line
        bump(alloc)
        total += line

    run["feedstock_cost_usd"] = q(total, 2)
    run["status"] = "RECONCILED"
    bump(run)
    return response.ok(run)


@bp.post("/processing-runs/<run_id>/aborts")
def abort_run(run_id):
    validate.auth("PlantOperator")
    run = find("run", run_id)
    data = validate.body()
    reason = validate.get_str(data, "reason", 1, 500)

    if run["status"] not in ("PLANNED", "HYDROGEN_SECURED", "RUNNING"):
        fail(ERR_INVALID_RUN_STATE, "A campaign in %s cannot be aborted." % run["status"])

    was_running = run["status"] == "RUNNING"
    for alloc in domain.run_allocations(run["id"]):
        if alloc["status"] == "RESERVED":
            domain.release_allocation(alloc, "RUN_ABORTED")
    domain.cancel_run_nominations(run)

    if was_running:
        unit = store.units.get(run["unit_id"])
        if unit is not None and unit["status"] == "RUNNING":
            unit["status"] = "IDLE"
            bump(unit)

    domain.recompute_run_masses(run)
    run["status"] = "ABORTED"
    run["abort_reason"] = reason
    bump(run)
    return response.ok(run)
