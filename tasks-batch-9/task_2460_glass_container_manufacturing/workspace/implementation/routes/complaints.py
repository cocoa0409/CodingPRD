from flask import Blueprint

import calc
from calc import D
from envelope import success
from errors import fail
from services import (
    check_unique,
    recompute_customer_standing,
    require,
    suspend_customer_programs,
)
from store import base_record, db, ordered, touch
from validation import (
    ATTRIBUTIONS,
    COMPLAINT_STATUSES,
    Enum,
    Id,
    Int,
    Num,
    Str,
    Text,
    Ts,
    authorize,
    paginate,
    pagination,
    query_enum,
    query_str,
    validate_body,
)

bp = Blueprint("complaints", __name__)

READERS = ("PlantManager", "QualityEngineer", "CustomerRep")


@bp.post("/glass-plant/complaints")
def create_complaint():
    user_id, _role = authorize("CustomerRep")
    data = validate_body(
        [
            Id("customer_id"),
            Id("pack_lot_id"),
            Str("code", min_len=1, max_len=32),
            Ts("reported_at"),
            Int("affected_units", ge=1),
            Num("filling_line_speed_bpm", gt=0, le=900, decimals=2),
        ]
    )
    customer = require(db.customers, data["customer_id"], "ERR_CUSTOMER_NOT_FOUND")
    lot = require(db.pack_lots, data["pack_lot_id"], "ERR_PACK_LOT_NOT_FOUND")
    # 7 ownership scope -> 15 lot state -> 32 traceability -> 39 uniqueness -> 43
    if user_id != customer["id"]:
        fail("ERR_CUSTOMER_SCOPE_VIOLATION")
    if lot["logistics_status"] != "SHIPPED":
        fail("ERR_LOT_STATE_INVALID")
    design = db.bottle_designs[lot["bottle_design_id"]]
    if lot["customer_id"] != customer["id"] or design["customer_id"] != customer["id"]:
        fail("ERR_LOT_CUSTOMER_MISMATCH")
    check_unique(db.complaints, "code", data["code"])
    if int(data["affected_units"]) > int(lot["net_packed_units"]):
        fail("ERR_AFFECTED_UNITS_EXCEED_LOT")

    record = base_record()
    record.update(
        {
            "customer_id": customer["id"],
            "pack_lot_id": lot["id"],
            "code": data["code"],
            "reported_at": data["reported_at"],
            "affected_units": data["affected_units"],
            "filling_line_speed_bpm": data["filling_line_speed_bpm"],
            "status": "OPEN",
            "attribution": "UNDETERMINED",
            "breakage_ppm": calc.breakage_ppm(
                data["affected_units"], lot["net_packed_units"]
            ),
            "credit_usd": D("0.00"),
            "affected_pallets": 0,
            "investigated_by_user_id": None,
        }
    )
    db.complaints[record["id"]] = record
    return success(record, 201)


@bp.get("/glass-plant/complaints")
def list_complaints():
    authorize(*READERS)
    status = query_enum("status", COMPLAINT_STATUSES)
    attribution = query_enum("attribution", ATTRIBUTIONS)
    customer_id = query_str("customer_id")
    pack_lot_id = query_str("pack_lot_id")
    limit, offset = pagination()
    records = ordered(list(db.complaints.values()))
    if customer_id is not None:
        records = [r for r in records if r["customer_id"] == customer_id]
    if pack_lot_id is not None:
        records = [r for r in records if r["pack_lot_id"] == pack_lot_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if attribution is not None:
        records = [r for r in records if r["attribution"] == attribution]
    page, meta = paginate(records, limit, offset)
    return success(page, 200, meta)


@bp.get("/glass-plant/complaints/<complaint_id>")
def read_complaint(complaint_id):
    authorize(*READERS)
    complaint = require(db.complaints, complaint_id, "ERR_COMPLAINT_NOT_FOUND")
    return success(complaint)


@bp.post("/glass-plant/complaints/<complaint_id>/investigate")
def investigate_complaint(complaint_id):
    user_id, _role = authorize("QualityEngineer")
    data = validate_body(
        [Enum("attribution", ATTRIBUTIONS), Text("findings", required=False)]
    )
    complaint = require(db.complaints, complaint_id, "ERR_COMPLAINT_NOT_FOUND")
    if complaint["status"] != "OPEN":
        fail("ERR_COMPLAINT_STATE_INVALID")
    lot = db.pack_lots[complaint["pack_lot_id"]]
    if lot["logistics_status"] != "SHIPPED":
        fail("ERR_LOT_STATE_INVALID")

    complaint["status"] = "INVESTIGATING"
    complaint["attribution"] = data["attribution"]
    complaint["investigated_by_user_id"] = user_id
    touch(complaint)

    if data["attribution"] in ("PLANT", "SHARED"):
        # Traceability cascade: pull the lot back out of the shipped population.
        lot["logistics_status"] = "RETURNED"
        if lot["quality_status"] == "RELEASED":
            lot["quality_status"] = "QUARANTINED"
        touch(lot)
    return success(complaint)


@bp.post("/glass-plant/complaints/<complaint_id>/settle")
def settle_complaint(complaint_id):
    user_id, _role = authorize("CustomerRep")
    data = validate_body([Enum("settlement", ("CREDIT", "REJECT"))])
    complaint = require(db.complaints, complaint_id, "ERR_COMPLAINT_NOT_FOUND")
    if user_id != complaint["customer_id"]:
        fail("ERR_CUSTOMER_SCOPE_VIOLATION")
    if complaint["status"] != "INVESTIGATING":
        fail("ERR_COMPLAINT_STATE_INVALID")

    if data["settlement"] == "REJECT":
        complaint["status"] = "REJECTED"
        touch(complaint)
        return success(complaint)

    if complaint["attribution"] not in ("PLANT", "SHARED"):
        fail(
            "ERR_COMPLAINT_STATE_INVALID",
            "Only a complaint attributed to PLANT or SHARED may be credited.",
        )
    if user_id == complaint["investigated_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")

    lot = db.pack_lots[complaint["pack_lot_id"]]
    design = db.bottle_designs[lot["bottle_design_id"]]
    customer = db.customers[complaint["customer_id"]]
    affected_pallets, credit = calc.complaint_credit(
        lot["palletization_standard"],
        complaint["affected_units"],
        design["container_price_usd"],
        complaint["breakage_ppm"],
        customer["complaint_ppm_threshold"],
    )
    complaint["status"] = "CREDIT_ISSUED"
    complaint["affected_pallets"] = affected_pallets
    complaint["credit_usd"] = credit
    touch(complaint)

    customer["credit_issued_usd"] = calc.rhu(D(customer["credit_issued_usd"]) + credit, 2)
    standing = recompute_customer_standing(customer)
    touch(customer)
    if standing == "CRITICAL":
        suspend_customer_programs(customer["id"])
    return success(complaint)
