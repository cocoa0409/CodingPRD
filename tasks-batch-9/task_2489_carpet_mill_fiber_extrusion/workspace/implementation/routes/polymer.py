"""Polymer lots and the reclamation line (PRD 3.1)."""

from flask import Blueprint

import calc
from calc import dec, rhu
from db import insert, store, touch
from errors import ApiError
from routes.common import authenticate, created, fetch, listing, ok, unique
from services import ledgers
from validators import (
    json_body,
    opt_bool,
    opt_enum,
    opt_id,
    opt_num,
    req_enum,
    req_num,
    req_str,
)

bp = Blueprint("polymer", __name__)

POLYMER_TYPES = ("NYLON_6", "NYLON_66", "PET", "POLYPROPYLENE")
RECLAIM_SOURCES = ("VIRGIN", "POST_CONSUMER", "POST_INDUSTRIAL")
POLYMER_STATUSES = ("AVAILABLE", "DEPLETED")
RECLAMATION_STATUSES = ("RECEIVED", "DEPOLYMERIZED")

READ_ROLES = ("ExtrusionOperator", "MillPlanner", "CertificationOfficer", "PlantAdmin")
WRITE_ROLES = ("ExtrusionOperator", "PlantAdmin")


def new_polymer_lot(
    lot_code,
    polymer_type,
    received_kg,
    melt_flow_index,
    recycled_content_pct,
    segregated,
    reclaim_source,
):
    return insert(
        store.polymer_lots,
        {
            "lot_code": lot_code,
            "polymer_type": polymer_type,
            "received_kg": received_kg,
            "available_kg": received_kg,
            "reserved_kg": 0.0,
            "consumed_kg": 0.0,
            "scrapped_kg": 0.0,
            "recycled_content_pct": recycled_content_pct,
            "segregated": segregated,
            "reclaim_source": reclaim_source,
            "melt_flow_index": melt_flow_index,
            "status": "AVAILABLE",
        },
    )


@bp.post("/mill/polymer-lots")
def receive_polymer_lot():
    authenticate(WRITE_ROLES)
    body = json_body()
    lot_code = req_str(body, "lot_code")
    polymer_type = req_enum(body, "polymer_type", POLYMER_TYPES)
    received_kg = req_num(body, "received_kg", 3, gt=0)
    melt_flow_index = req_num(body, "melt_flow_index", 1, gt=0)
    recycled_content_pct = opt_num(body, "recycled_content_pct", 2, default=0.0, ge=0, le=100)
    segregated = opt_bool(body, "segregated", default=False)
    reclaim_source = opt_enum(body, "reclaim_source", RECLAIM_SOURCES, default="VIRGIN")

    unique("polymer_lots", "lot_code", lot_code)

    lot = new_polymer_lot(
        lot_code,
        polymer_type,
        received_kg,
        melt_flow_index,
        recycled_content_pct,
        segregated,
        reclaim_source,
    )
    return created("polymer_lot", lot)


@bp.get("/mill/polymer-lots/<polymer_lot_id>")
def read_polymer_lot(polymer_lot_id):
    authenticate(READ_ROLES)
    return ok("polymer_lot", fetch("polymer_lots", polymer_lot_id))


@bp.get("/mill/polymer-lots")
def list_polymer_lots():
    authenticate(READ_ROLES)
    return listing(
        "polymer_lot",
        "polymer_lots",
        enum_filters={
            "polymer_type": POLYMER_TYPES,
            "status": POLYMER_STATUSES,
            "reclaim_source": RECLAIM_SOURCES,
        },
    )


# ---- reclamation batches --------------------------------------------------

@bp.post("/mill/reclamation-batches")
def log_reclamation_batch():
    authenticate(WRITE_ROLES)
    body = json_body()
    batch_code = req_str(body, "batch_code")
    intake_lbs = req_num(body, "intake_lbs", 1, gt=0)
    face_fiber_type = req_enum(body, "face_fiber_type", POLYMER_TYPES)
    contamination_pct = req_num(body, "contamination_pct", 1, ge=0, le=100)
    source_roll_good_id = opt_id(body, "source_roll_good_id")

    if source_roll_good_id is not None:
        fetch("roll_goods", source_roll_good_id)

    unique("reclamation_batches", "batch_code", batch_code)

    batch = insert(
        store.reclamation_batches,
        {
            "batch_code": batch_code,
            "source_roll_good_id": source_roll_good_id,
            "intake_lbs": intake_lbs,
            "face_fiber_type": face_fiber_type,
            "contamination_pct": contamination_pct,
            "depolymerized_kg": 0.0,
            "output_polymer_lot_id": None,
            "status": "RECEIVED",
        },
    )
    return created("reclamation_batch", batch)


@bp.post("/mill/reclamation-batches/<reclamation_batch_id>/depolymerize")
def depolymerize(reclamation_batch_id):
    authenticate(WRITE_ROLES)
    batch = fetch("reclamation_batches", reclamation_batch_id)

    if batch["status"] != "RECEIVED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a RECEIVED reclamation batch may be depolymerized",
        )

    # Rung 21 — reclaim processability.
    if dec(batch["contamination_pct"]) > calc.dec(calc.MAX_RECLAIM_CONTAMINATION_PCT):
        raise ApiError(
            "ERR_RECLAIM_CONTAMINATION_EXCEEDED",
            "Contamination of %.1f percent exceeds the 12.0 percent gate"
            % batch["contamination_pct"],
        )
    if batch["source_roll_good_id"]:
        roll = store.roll_goods.get(batch["source_roll_good_id"])
        if roll is None or roll["inventory_status"] not in ("DEPLETED", "SCRAPPED"):
            raise ApiError(
                "ERR_ROLL_NOT_RECLAIMABLE",
                "The sourced roll is not DEPLETED or SCRAPPED",
            )

    yield_kg = calc.reclamation_yield_kg(batch["intake_lbs"], batch["face_fiber_type"])

    lot = new_polymer_lot(
        "RECLAIM-%s" % batch["batch_code"],
        batch["face_fiber_type"],
        yield_kg,
        float(calc.MIN_MELT_FLOW_INDEX),
        100.00,
        True,
        "POST_CONSUMER",
    )

    batch["depolymerized_kg"] = yield_kg
    batch["output_polymer_lot_id"] = lot["id"]
    batch["status"] = "DEPOLYMERIZED"
    touch(batch)
    return ok("reclamation_batch", batch)


@bp.get("/mill/reclamation-batches/<reclamation_batch_id>")
def read_reclamation_batch(reclamation_batch_id):
    authenticate(READ_ROLES)
    return ok("reclamation_batch", fetch("reclamation_batches", reclamation_batch_id))


@bp.get("/mill/reclamation-batches")
def list_reclamation_batches():
    authenticate(READ_ROLES)
    return listing(
        "reclamation_batch",
        "reclamation_batches",
        enum_filters={
            "status": RECLAMATION_STATUSES,
            "face_fiber_type": POLYMER_TYPES,
        },
        value_filters=("source_roll_good_id", "output_polymer_lot_id"),
    )
