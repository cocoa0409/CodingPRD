"""Cullet batches: staging under plant OCC, reversal out of a live melt, rejection."""

from decimal import Decimal

from flask import Blueprint

import calc
import ledger
from calc import q2
from db import new_row, store, touch
from errors import fail
from middleware import authenticate, require_plant_owned
from refs import apply_filters, get_batch, get_plant, get_run
from response import created_response, list_response, object_response
from validate import body, dec_field, int_field, present, str_field

bp = Blueprint("cullet", __name__)

READ_ROLES = ("CorporateOps", "PlantOperator", "EnvironmentalCompliance")
SOURCE_TYPES = ("TRIM", "CHANGEOVER_SCRAP", "QUARANTINE_SCRAP", "EXTERNAL")


@bp.post("/cullet-batches")
def stage_batch():
    authenticate(("PlantOperator",))
    payload = body()
    if present(payload, "plant_id"):
        require_plant_owned(payload["plant_id"])

    source_type = str_field(payload, "source_type", allowed=SOURCE_TYPES)
    mass = dec_field(payload, "mass_kg", gt=0)
    expected_version = int_field(payload, "expected_plant_version")

    if not present(payload, "plant_id"):
        fail("ERR_INVALID_REQUEST", "plant_id is required")
    plant = get_plant(payload["plant_id"])
    source_run = None
    if present(payload, "source_run_id"):
        source_run = get_run(payload["source_run_id"])

    if expected_version != plant["version"]:
        fail("ERR_STALE_PLANT_VERSION", "expected_plant_version does not match the plant")
    if plant["melt_posture"] == "FROZEN":
        fail("ERR_MELT_POSTURE_FROZEN", "the plant's melt shop is frozen")
    if plant["melt_posture"] == "RESTRICTED":
        fail("ERR_MELT_POSTURE_RESTRICTED", "no further cullet may enter a restricted yard")

    row = new_row()
    row.update({
        "plant_id": plant["id"],
        "source_run_id": source_run["id"] if source_run is not None else None,
        "charged_run_id": None,
        "source_type": source_type,
        "mass_kg": q2(mass),
        "status": "STAGED",
        "reject_reason": None,
    })
    store.cullet[row["id"]] = row
    ledger.recompute_plant_ledger(plant, bump=False)
    touch(plant)
    return created_response(row)


@bp.get("/cullet-batches/<batch_id>")
def read_batch(batch_id):
    authenticate(READ_ROLES)
    return object_response(get_batch(batch_id))


@bp.get("/cullet-batches")
def list_batches():
    authenticate(READ_ROLES)
    rows = apply_filters(store.cullet.values(), {
        "plant_id": ("plant_id", "str"),
        "source_run_id": ("source_run_id", "str"),
        "charged_run_id": ("charged_run_id", "str"),
        "source_type": ("source_type", "str"),
        "status": ("status", "str"),
    })
    return list_response(rows)


@bp.post("/cullet-batches/<batch_id>/reverse")
def reverse_batch(batch_id):
    authenticate(("PlantOperator",))
    batch = get_batch(batch_id)
    require_plant_owned(batch["plant_id"])
    payload = body()
    note = str_field(payload, "reversal_note", required=False, default=None)

    if batch["status"] != "CHARGED":
        fail("ERR_INVALID_STATE", "only a CHARGED batch may be reversed")
    run = store.runs.get(batch["charged_run_id"])
    if run is None or run["run_status"] != "MELTING":
        fail("ERR_CULLET_REVERSAL_WINDOW_CLOSED", "the reversal window shut when curing started")

    mass = Decimal(batch["mass_kg"])
    batch["status"] = "STAGED"
    batch["charged_run_id"] = None
    if note is not None:
        batch["_reversal_note"] = note
    touch(batch)

    run["cullet_charged_kg"] = q2(Decimal(run["cullet_charged_kg"]) - mass)
    run["virgin_batch_kg"] = q2(Decimal(run["virgin_batch_kg"]) + mass)
    run["cullet_fraction"] = calc.cullet_fraction(run["cullet_charged_kg"],
                                                  run["total_charge_kg"])
    touch(run)

    plant = store.plants[batch["plant_id"]]
    ledger.recompute_plant_ledger(plant)
    return object_response(batch)


@bp.post("/cullet-batches/<batch_id>/reject")
def reject_batch(batch_id):
    authenticate(("PlantOperator",))
    batch = get_batch(batch_id)
    require_plant_owned(batch["plant_id"])
    payload = body()
    reason = str_field(payload, "reject_reason")

    if batch["status"] != "STAGED":
        fail("ERR_INVALID_STATE", "only a STAGED batch may be rejected")
    batch["status"] = "REJECTED"
    batch["reject_reason"] = reason
    touch(batch)

    plant = store.plants[batch["plant_id"]]
    ledger.recompute_plant_ledger(plant)
    return object_response(batch)
