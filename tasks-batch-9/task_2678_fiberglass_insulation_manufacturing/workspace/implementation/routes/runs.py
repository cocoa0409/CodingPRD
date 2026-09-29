"""Production runs: schedule, charge, cure, package, close, abort, release-hold."""

from decimal import Decimal

from flask import Blueprint

import calc
import ledger
from calc import D0_2, D0_4, q2
from db import clock_iso, clock_now, new_row, ordered, store, touch
from errors import fail
from middleware import authenticate, require_plant_owned
from refs import apply_filters, get_batch, get_plant, get_product_line, get_run
from response import created_response, list_response, object_response
from validate import (body, dec_field, instant_field, int_field, list_field, present,
                     str_field, to_decimal)

bp = Blueprint("runs", __name__)

READ_ROLES = ("CorporateOps", "PlantOperator", "QualityEngineer", "EnvironmentalCompliance")
OCCUPYING_STATUSES = ("SCHEDULED", "HELD", "MELTING", "CURING")


def _overlaps_half_open(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


@bp.post("/production-runs")
def schedule_run():
    authenticate(("PlantOperator",))
    payload = body()
    # rung 4 — ownership is decided on the payload's plant_id before shape checks.
    if present(payload, "plant_id"):
        require_plant_owned(payload["plant_id"])

    line_index = int_field(payload, "line_index")
    start_raw, start_dt = instant_field(payload, "scheduled_start")
    end_raw, end_dt = instant_field(payload, "scheduled_end")
    if not end_dt > start_dt:
        fail("ERR_INVALID_REQUEST", "scheduled_end must be strictly later than scheduled_start")
    target_pull = dec_field(payload, "target_pull_kg", gt=0)
    setpoints_raw = list_field(payload, "zone_setpoints_f")
    if not setpoints_raw:
        fail("ERR_INVALID_REQUEST", "zone_setpoints_f must be a non-empty array")
    setpoints = [to_decimal(value, "zone_setpoints_f") for value in setpoints_raw]

    if not present(payload, "plant_id"):
        fail("ERR_INVALID_REQUEST", "plant_id is required")
    plant = get_plant(payload["plant_id"])
    if not present(payload, "product_line_id"):
        fail("ERR_INVALID_REQUEST", "product_line_id is required")
    product_line = get_product_line(payload["product_line_id"])

    # rung 9
    if plant["melt_posture"] == "FROZEN":
        fail("ERR_MELT_POSTURE_FROZEN", "the plant's melt shop is frozen")
    # rung 10
    binder = store.binders.get(product_line["binder_formulation_id"])
    if binder is None or binder["status"] != "CERTIFIED":
        fail("ERR_BINDER_NOT_CERTIFIED", "the SKU's binder formulation is not CERTIFIED")
    # rung 11 — occupancy first, then the line index range
    for other in ledger.plant_runs(plant["id"]):
        if other["line_index"] != line_index:
            continue
        if other["run_status"] not in OCCUPYING_STATUSES:
            continue
        if _overlaps_half_open(start_dt, end_dt,
                               other["_scheduled_start_dt"], other["_scheduled_end_dt"]):
            fail("ERR_LINE_OCCUPANCY_CONFLICT",
                 "the window overlaps run %s on line %s" % (other["id"], line_index))
    if line_index < 1 or line_index > plant["production_line_count"]:
        fail("ERR_LINE_INDEX_OUT_OF_RANGE", "line_index is outside the plant's line count")
    # rung 12
    if len(setpoints) != plant["oven_zone_count"] or any(v <= 0 for v in setpoints):
        fail("ERR_OVEN_ZONE_MISMATCH",
             "zone_setpoints_f must carry one positive setpoint per oven zone")

    row = new_row()
    row.update({
        "plant_id": plant["id"],
        "product_line_id": product_line["id"],
        "line_index": line_index,
        "scheduled_start": start_raw,
        "scheduled_end": end_raw,
        "_scheduled_start_dt": start_dt,
        "_scheduled_end_dt": end_dt,
        "target_pull_kg": target_pull,
        "zone_setpoints_f": setpoints,
        "run_status": "SCHEDULED",
        "qc_status": "UNSAMPLED",
        "hold_reason": None,
        "total_charge_kg": None,
        "allowed_cullet_kg": None,
        "cullet_charged_kg": D0_2,
        "virgin_batch_kg": None,
        "cullet_fraction": None,
        "changeover_scrap_kg": D0_2,
        "avg_zone_temp_f": None,
        "line_speed_fpm": None,
        "binder_applied_kg": None,
        "dwell_s": None,
        "cure_index": None,
        "formaldehyde_kg": None,
        "voc_kg": None,
        "bags_produced": None,
        "produced_sqft": None,
        "closed_at": None,
    })
    store.runs[row["id"]] = row
    return created_response(row)


@bp.get("/production-runs/<run_id>")
def read_run(run_id):
    authenticate(READ_ROLES)
    return object_response(get_run(run_id))


@bp.get("/production-runs")
def list_runs():
    authenticate(READ_ROLES)
    rows = apply_filters(store.runs.values(), {
        "plant_id": ("plant_id", "str"),
        "product_line_id": ("product_line_id", "str"),
        "line_index": ("line_index", "int"),
        "run_status": ("run_status", "str"),
        "qc_status": ("qc_status", "str"),
    })
    return list_response(rows)


@bp.post("/production-runs/<run_id>/start-melt")
def start_melt(run_id):
    authenticate(("PlantOperator",))
    run = get_run(run_id)
    require_plant_owned(run["plant_id"])
    payload = body()
    ids = payload.get("cullet_batch_ids")
    if ids is None:
        ids = []
    if not isinstance(ids, list):
        fail("ERR_INVALID_REQUEST", "cullet_batch_ids must be an array")
    batches = [get_batch(batch_id) for batch_id in ids]

    plant = store.plants[run["plant_id"]]
    if run["run_status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE", "only a SCHEDULED run may be charged")
    if clock_now() < run["_scheduled_start_dt"]:
        fail("ERR_INVALID_STATE", "the run's scheduled window has not opened yet")
    if plant["melt_posture"] == "RESTRICTED" and batches:
        fail("ERR_INVALID_STATE", "a RESTRICTED plant may not charge cullet")
    if plant["melt_posture"] == "FROZEN":
        fail("ERR_MELT_POSTURE_FROZEN", "the plant's melt shop is frozen")
    for batch in batches:
        if batch["plant_id"] != run["plant_id"] or batch["status"] != "STAGED":
            fail("ERR_CULLET_BATCH_NOT_STAGED",
                 "cullet batch %s is not staged at this plant" % batch["id"])

    total_charge = calc.total_charge_kg(run["target_pull_kg"])
    allowed = calc.allowed_cullet_kg(total_charge, plant["max_cullet_fraction"])
    accepted, charged = calc.select_cullet(ordered(batches), allowed)

    run["run_status"] = "MELTING"
    run["total_charge_kg"] = total_charge
    run["allowed_cullet_kg"] = allowed
    run["cullet_charged_kg"] = charged
    run["virgin_batch_kg"] = q2(Decimal(total_charge) - Decimal(charged))
    run["cullet_fraction"] = calc.cullet_fraction(charged, total_charge)
    touch(run)

    for batch in accepted:
        batch["status"] = "CHARGED"
        batch["charged_run_id"] = run["id"]
        touch(batch)

    ledger.recompute_plant_ledger(plant, bump=False)
    ledger.tighten_posture_if_needed(plant)
    touch(plant)
    return object_response(run)


@bp.post("/production-runs/<run_id>/start-cure")
def start_cure(run_id):
    authenticate(("PlantOperator",))
    run = get_run(run_id)
    require_plant_owned(run["plant_id"])
    payload = body()
    avg_temp = dec_field(payload, "avg_zone_temp_f", gt=0)
    line_speed = dec_field(payload, "line_speed_fpm", gt=0)
    binder_applied = dec_field(payload, "binder_applied_kg", gt=0)

    if run["run_status"] != "MELTING":
        fail("ERR_INVALID_STATE", "only a MELTING run may start curing")
    plant = store.plants[run["plant_id"]]
    product_line = store.product_lines[run["product_line_id"]]
    binder = store.binders[product_line["binder_formulation_id"]]

    dwell = calc.dwell_seconds(plant["oven_length_ft"], line_speed)
    index = calc.cure_index(dwell, binder["min_dwell_s"], avg_temp, binder["min_cure_temp_f"])
    if index < calc.MIN_CURE_INDEX:
        fail("ERR_CURE_INDEX_BELOW_MINIMUM", "the cure index is below the 100.00 floor")

    run["avg_zone_temp_f"] = avg_temp
    run["line_speed_fpm"] = line_speed
    run["binder_applied_kg"] = binder_applied
    run["dwell_s"] = dwell
    run["cure_index"] = index
    run["formaldehyde_kg"] = calc.formaldehyde_kg(binder_applied, binder["formaldehyde_ppm"])
    run["voc_kg"] = calc.voc_kg(binder_applied, binder["voc_g_per_kg"])
    run["run_status"] = "CURING"
    touch(run)
    return object_response(run)


@bp.post("/production-runs/<run_id>/package")
def package_run(run_id):
    authenticate(("PlantOperator",))
    run = get_run(run_id)
    require_plant_owned(run["plant_id"])
    payload = body()
    bags = int_field(payload, "bags_produced", minimum=1)

    if run["run_status"] != "CURING":
        fail("ERR_INVALID_STATE", "only a CURING run may be packaged")
    if run.get("cure_index") is None or Decimal(run["cure_index"]) < calc.MIN_CURE_INDEX:
        fail("ERR_INVALID_STATE", "the run's cure index no longer clears the floor")

    product_line = store.product_lines[run["product_line_id"]]
    produced = q2(Decimal(bags) * Decimal(product_line["bag_sqft"]))
    if not produced > 0 or run.get("binder_applied_kg") is None or \
            Decimal(run["binder_applied_kg"]) == 0:
        fail("ERR_INVALID_REQUEST", "packaged coverage and applied binder must both be non-zero")

    run["bags_produced"] = bags
    run["produced_sqft"] = produced
    run["run_status"] = "PACKAGED"
    touch(run)

    lot = new_row()
    lot.update({
        "plant_id": run["plant_id"],
        "product_line_id": run["product_line_id"],
        "production_run_id": run["id"],
        "parent_lot_id": None,
        "form": product_line["form"],
        "bags": bags,
        "produced_sqft": produced,
        "allocated_sqft": D0_2,
        "available_sqft": produced,
        "status": "AVAILABLE",
        "quarantine_reason": None,
    })
    store.lots[lot["id"]] = lot
    return object_response(run)


@bp.post("/production-runs/<run_id>/close")
def close_run(run_id):
    authenticate(("PlantOperator",))
    run = get_run(run_id)
    require_plant_owned(run["plant_id"])
    if run["run_status"] != "PACKAGED":
        fail("ERR_INVALID_STATE", "only a PACKAGED run may be closed")
    if run["qc_status"] not in ("SAMPLED", "CONFORMING", "NONCONFORMING", "RETEST_PENDING"):
        fail("ERR_INVALID_STATE", "an unsampled run cannot be closed")
    run["run_status"] = "CLOSED"
    run["closed_at"] = clock_iso()
    touch(run)
    plant = store.plants[run["plant_id"]]
    ledger.recompute_plant_ledger(plant)
    return object_response(run)


@bp.post("/production-runs/<run_id>/abort")
def abort_run(run_id):
    authenticate(("PlantOperator",))
    run = get_run(run_id)
    require_plant_owned(run["plant_id"])
    payload = body()
    reason = str_field(payload, "abort_reason")
    if run["run_status"] not in ("SCHEDULED", "MELTING", "CURING"):
        fail("ERR_INVALID_STATE", "only a SCHEDULED, MELTING or CURING run may be aborted")

    unwind = run["run_status"] in ("MELTING", "CURING")
    run["run_status"] = "ABORTED"
    run["_abort_reason"] = reason
    if unwind:
        run["cullet_charged_kg"] = D0_2
        if run.get("total_charge_kg") is not None:
            run["virgin_batch_kg"] = q2(Decimal(run["total_charge_kg"]))
        run["cullet_fraction"] = D0_4
    touch(run)

    if unwind:
        for batch in ledger.plant_batches(run["plant_id"]):
            if batch.get("charged_run_id") == run["id"] and batch["status"] == "CHARGED":
                batch["status"] = "STAGED"
                batch["charged_run_id"] = None
                touch(batch)
    plant = store.plants[run["plant_id"]]
    ledger.recompute_plant_ledger(plant)
    return object_response(run)


@bp.post("/production-runs/<run_id>/release-hold")
def release_hold(run_id):
    authenticate(("PlantOperator",))
    run = get_run(run_id)
    require_plant_owned(run["plant_id"])
    if run["run_status"] != "HELD":
        fail("ERR_INVALID_STATE", "only a HELD run may be released")
    plant = store.plants[run["plant_id"]]
    if plant["melt_posture"] != "OPEN":
        fail("ERR_INVALID_STATE", "the plant's melt posture is not OPEN")
    product_line = store.product_lines[run["product_line_id"]]
    if product_line["certification_status"] in ("SUSPENDED", "WITHDRAWN"):
        fail("ERR_INVALID_STATE", "the SKU is not sellable")
    run["run_status"] = "SCHEDULED"
    run["hold_reason"] = None
    touch(run)
    return object_response(run)
