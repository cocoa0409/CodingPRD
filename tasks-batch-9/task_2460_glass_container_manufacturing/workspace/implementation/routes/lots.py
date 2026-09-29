from flask import Blueprint

import calc
from envelope import success
from errors import fail
from services import (
    add_ledger,
    compute_final_yield,
    lot_inspection_results,
    lot_tons,
    recompute_lot_inspection_totals,
    require,
)
from store import base_record, db, ordered, touch
from validation import (
    DEFECT_CLASSES,
    DEFECT_CODES,
    LOGISTICS_STATUSES,
    QUALITY_STATUSES,
    Enum,
    Int,
    Ts,
    authorize,
    paginate,
    pagination,
    query_enum,
    query_str,
    validate_body,
)

bp = Blueprint("lots", __name__)

READERS = (
    "PlantManager",
    "PlantScheduler",
    "QualityEngineer",
    "WarehouseOperator",
    "CustomerRep",
)


@bp.get("/glass-plant/pack-lots")
def list_lots():
    authorize(*READERS)
    quality_status = query_enum("quality_status", QUALITY_STATUSES)
    logistics_status = query_enum("logistics_status", LOGISTICS_STATUSES)
    filters = {}
    for name in ("production_job_id", "campaign_id", "bottle_design_id", "customer_id"):
        value = query_str(name)
        if value is not None:
            filters[name] = value
    limit, offset = pagination()
    records = ordered(list(db.pack_lots.values()))
    for name, value in filters.items():
        records = [r for r in records if r[name] == value]
    if quality_status is not None:
        records = [r for r in records if r["quality_status"] == quality_status]
    if logistics_status is not None:
        records = [r for r in records if r["logistics_status"] == logistics_status]
    page, meta = paginate(records, limit, offset)
    return success(page, 200, meta)


@bp.get("/glass-plant/pack-lots/<pack_lot_id>")
def read_lot(pack_lot_id):
    authorize(*READERS)
    lot = require(db.pack_lots, pack_lot_id, "ERR_PACK_LOT_NOT_FOUND")
    return success(lot)


# --------------------------------------------------------------------------- #
# inspection readings
# --------------------------------------------------------------------------- #
@bp.post("/glass-plant/pack-lots/<pack_lot_id>/inspection-results")
def create_inspection_result(pack_lot_id):
    user_id, _role = authorize("QualityEngineer")
    data = validate_body(
        [
            Enum("defect_class", DEFECT_CLASSES),
            Enum("defect_code", DEFECT_CODES),
            Int("rejected_units", ge=1),
            Ts("inspected_at"),
        ]
    )
    lot = require(db.pack_lots, pack_lot_id, "ERR_PACK_LOT_NOT_FOUND")

    already = sum(int(r["rejected_units"]) for r in lot_inspection_results(lot["id"]))
    if already + int(data["rejected_units"]) > int(lot["packed_units"]):
        fail("ERR_REJECTS_EXCEED_PACKED")

    # PRD 2.4: a reading carries only id and created_at -- never version/updated_at.
    record = base_record(versioned=False)
    record.update(
        {
            "pack_lot_id": lot["id"],
            "defect_class": data["defect_class"],
            "defect_code": data["defect_code"],
            "rejected_units": data["rejected_units"],
            "inspected_at": data["inspected_at"],
            "recorded_by_user_id": user_id,
        }
    )
    db.inspection_results[record["id"]] = record

    recompute_lot_inspection_totals(lot)
    touch(lot)
    return success(record, 201)


@bp.get("/glass-plant/pack-lots/<pack_lot_id>/inspection-results")
def list_inspection_results(pack_lot_id):
    authorize("PlantManager", "QualityEngineer", "CustomerRep")
    defect_class = query_enum("defect_class", DEFECT_CLASSES)
    limit, offset = pagination()
    require(db.pack_lots, pack_lot_id, "ERR_PACK_LOT_NOT_FOUND")
    records = lot_inspection_results(pack_lot_id)
    if defect_class is not None:
        records = [r for r in records if r["defect_class"] == defect_class]
    page, meta = paginate(records, limit, offset)
    return success(page, 200, meta)


# --------------------------------------------------------------------------- #
# disposition
# --------------------------------------------------------------------------- #
@bp.post("/glass-plant/pack-lots/<pack_lot_id>/release")
def release_lot(pack_lot_id):
    authorize("QualityEngineer")
    lot = require(db.pack_lots, pack_lot_id, "ERR_PACK_LOT_NOT_FOUND")
    if lot["quality_status"] != "PENDING_INSPECTION":
        fail("ERR_LOT_STATE_INVALID")
    results = lot_inspection_results(lot["id"])
    if not results:
        fail("ERR_NO_INSPECTION_RECORDS")

    campaign = db.campaigns[lot["campaign_id"]]
    has_critical = any(r["defect_class"] == "CRITICAL" for r in results)
    disposition = calc.lot_disposition(has_critical, lot["major_ppm"], lot["minor_ppm"])
    lot["quality_status"] = disposition

    if disposition == "SCRAPPED":
        add_ledger(campaign, "reject_loss_tons", lot_tons(lot, "packed_units"))
    else:
        final_yield, transition = compute_final_yield(lot)
        lot["final_yield_pct"] = final_yield
        add_ledger(campaign, "reject_loss_tons", lot_tons(lot, "reject_units"))
        if disposition == "RELEASED":
            add_ledger(campaign, "packed_tons", lot_tons(lot, "net_packed_units"))
            add_ledger(campaign, "transition_loss_tons", transition)
    touch(lot)
    return success(lot)


@bp.post("/glass-plant/pack-lots/<pack_lot_id>/rework-release")
def rework_release_lot(pack_lot_id):
    user_id, _role = authorize("QualityEngineer")
    lot = require(db.pack_lots, pack_lot_id, "ERR_PACK_LOT_NOT_FOUND")
    if lot["quality_status"] != "QUARANTINED":
        fail("ERR_LOT_STATE_INVALID")
    # The releaser must differ from *every* inspector on this lot.
    for result in lot_inspection_results(lot["id"]):
        if result["recorded_by_user_id"] == user_id:
            fail("ERR_SEGREGATION_OF_DUTIES")

    campaign = db.campaigns[lot["campaign_id"]]
    lot["quality_status"] = "RELEASED"
    final_yield, _transition = compute_final_yield(lot)
    lot["final_yield_pct"] = final_yield
    add_ledger(campaign, "packed_tons", lot_tons(lot, "net_packed_units"))
    touch(lot)
    return success(lot)


# --------------------------------------------------------------------------- #
# warehouse
# --------------------------------------------------------------------------- #
@bp.post("/glass-plant/pack-lots/<pack_lot_id>/palletize")
def palletize_lot(pack_lot_id):
    authorize("WarehouseOperator")
    lot = require(db.pack_lots, pack_lot_id, "ERR_PACK_LOT_NOT_FOUND")
    if lot["logistics_status"] != "IN_AGING":
        fail("ERR_LOT_STATE_INVALID")
    if db.clock < lot["aged_until_at"]:
        fail("ERR_WINDOW_NOT_ELAPSED")
    lot["pallet_count"] = calc.ceil_div(
        lot["net_packed_units"], calc.UNITS_PER_PALLET[lot["palletization_standard"]]
    )
    lot["logistics_status"] = "PALLETIZED"
    touch(lot)
    return success(lot)


@bp.post("/glass-plant/pack-lots/<pack_lot_id>/ship")
def ship_lot(pack_lot_id):
    authorize("WarehouseOperator")
    lot = require(db.pack_lots, pack_lot_id, "ERR_PACK_LOT_NOT_FOUND")
    if lot["logistics_status"] != "PALLETIZED" or lot["quality_status"] != "RELEASED":
        fail("ERR_LOT_STATE_INVALID")
    customer = db.customers[lot["customer_id"]]
    if lot["palletization_standard"] != customer["palletization_standard"]:
        fail("ERR_PALLET_STANDARD_MISMATCH")
    lot["logistics_status"] = "SHIPPED"
    lot["shipped_at"] = db.clock
    touch(lot)
    return success(lot)
