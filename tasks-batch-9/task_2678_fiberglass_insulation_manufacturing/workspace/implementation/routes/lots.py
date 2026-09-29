"""Finished-goods lots: the allocation ledger, quarantine, scrap, release and repack."""

from decimal import Decimal

from flask import Blueprint

import calc
import ledger
from calc import D0_2, q2
from db import new_row, store, touch
from errors import fail
from middleware import authenticate
from refs import apply_filters, get_lot
from response import list_response, object_response
from validate import body, dec_field, str_field

bp = Blueprint("lots", __name__)

READ_ROLES = ("CorporateOps", "PlantOperator", "QualityEngineer", "ChannelManager")


@bp.get("/inventory-lots/<lot_id>")
def read_lot(lot_id):
    authenticate(READ_ROLES)
    return object_response(get_lot(lot_id))


@bp.get("/inventory-lots")
def list_lots():
    authenticate(READ_ROLES)
    rows = apply_filters(store.lots.values(), {
        "plant_id": ("plant_id", "str"),
        "product_line_id": ("product_line_id", "str"),
        "production_run_id": ("production_run_id", "str"),
        "parent_lot_id": ("parent_lot_id", "str"),
        "form": ("form", "str"),
        "status": ("status", "str"),
    })
    return list_response(rows)


@bp.post("/inventory-lots/<lot_id>/repack")
def repack_lot(lot_id):
    authenticate(("PlantOperator",))
    lot = get_lot(lot_id)
    payload = body()
    raw = payload.get("child_bags")
    if raw is None or not isinstance(raw, list):
        fail("ERR_INVALID_REQUEST", "child_bags must be an array of positive whole numbers")
    counts = []
    for value in raw:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            fail("ERR_INVALID_REQUEST", "child_bags must contain numbers only")
        counts.append(value)

    if lot["status"] != "AVAILABLE":
        fail("ERR_INVALID_STATE", "only an AVAILABLE lot may be repacked")
    if Decimal(lot["allocated_sqft"]) != 0 or ledger.live_lines_of_lot(lot):
        fail("ERR_LOT_HAS_ALLOCATIONS", "the lot still carries a proposed or booked allocation")

    valid = len(counts) >= 2
    if valid:
        for value in counts:
            if int(value) != value or int(value) <= 0:
                valid = False
                break
    if valid and sum(int(v) for v in counts) != lot["bags"]:
        valid = False
    if not valid:
        fail("ERR_BAG_MULTIPLE_MISMATCH",
             "child_bags must hold at least two positive whole numbers summing to lot.bags")

    product_line = store.product_lines[lot["product_line_id"]]
    bag_sqft = Decimal(product_line["bag_sqft"])

    lot["status"] = "REPACKED"
    lot["available_sqft"] = D0_2
    touch(lot)

    for value in counts:
        bags = int(value)
        child = new_row()
        child.update({
            "plant_id": lot["plant_id"],
            "product_line_id": lot["product_line_id"],
            "production_run_id": lot["production_run_id"],
            "parent_lot_id": lot["id"],
            "form": product_line["form"],
            "bags": bags,
            "produced_sqft": q2(Decimal(bags) * bag_sqft),
            "allocated_sqft": D0_2,
            "available_sqft": q2(Decimal(bags) * bag_sqft),
            "status": "AVAILABLE",
            "quarantine_reason": None,
        })
        store.lots[child["id"]] = child
    return object_response(lot)


@bp.post("/inventory-lots/<lot_id>/quarantine")
def quarantine(lot_id):
    authenticate(("QualityEngineer",))
    lot = get_lot(lot_id)
    payload = body()
    disposition = str_field(payload, "disposition", allowed=("HOLD", "SCRAP"))
    weighed = dec_field(payload, "weighed_scrap_lb", required=False, ge=0, default=None)
    note = str_field(payload, "quarantine_note", required=False, default=None)

    if disposition == "HOLD":
        if lot["status"] not in ("AVAILABLE", "ALLOCATED"):
            fail("ERR_INVALID_STATE", "only an AVAILABLE or ALLOCATED lot may be held")
        ledger.quarantine_lot(lot, "MANUAL_HOLD", bump=False)
        if note is not None:
            lot["_quarantine_note"] = note
        touch(lot)
        return object_response(lot)

    if lot["status"] != "QUARANTINED":
        fail("ERR_INVALID_STATE", "only a QUARANTINED lot may be scrapped")
    product_line = store.product_lines[lot["product_line_id"]]
    mass = calc.scrap_cullet_mass(weighed, lot["bags"], product_line["bale_mass_kg"],
                                  product_line["facing_type"])
    lot["status"] = "SCRAPPED"
    lot["available_sqft"] = D0_2
    if note is not None:
        lot["_quarantine_note"] = note
    touch(lot)

    batch = new_row()
    batch.update({
        "plant_id": lot["plant_id"],
        "source_run_id": lot["production_run_id"],
        "charged_run_id": None,
        "source_type": "QUARANTINE_SCRAP",
        "mass_kg": mass,
        "status": "STAGED",
        "reject_reason": None,
    })
    store.cullet[batch["id"]] = batch
    plant = store.plants[lot["plant_id"]]
    ledger.recompute_plant_ledger(plant)
    return object_response(lot)


@bp.post("/inventory-lots/<lot_id>/release")
def release_lot(lot_id):
    authenticate(("QualityEngineer",))
    lot = get_lot(lot_id)
    if lot["status"] != "QUARANTINED":
        fail("ERR_INVALID_STATE", "only a QUARANTINED lot may be released")
    run = store.runs.get(lot["production_run_id"])
    if run is None or run["qc_status"] != "CONFORMING":
        fail("ERR_RUN_NOT_CONFORMING", "the originating run's QC verdict is not CONFORMING")
    lot["status"] = "AVAILABLE"
    lot["quarantine_reason"] = None
    ledger.recompute_lot(lot, bump=False)
    touch(lot)
    return object_response(lot)
