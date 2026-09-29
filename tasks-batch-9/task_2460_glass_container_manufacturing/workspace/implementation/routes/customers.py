from flask import Blueprint

from calc import D
from envelope import success
from services import check_unique, require
from store import base_record, db, touch
from validation import (
    PALLET_STANDARDS,
    Enum,
    Num,
    Str,
    authorize,
    validate_body,
)

bp = Blueprint("customers", __name__)


@bp.post("/glass-plant/customers")
def create_customer():
    authorize("PlantManager")
    data = validate_body(
        [
            Str("name", min_len=1, max_len=120),
            Str("account_code", min_len=1, max_len=32),
            Enum("palletization_standard", PALLET_STANDARDS),
            Num("complaint_ppm_threshold", gt=0, le=20000, decimals=2),
        ]
    )
    check_unique(db.customers, "account_code", data["account_code"])

    record = base_record()
    record.update(
        {
            "name": data["name"],
            "account_code": data["account_code"],
            "palletization_standard": data["palletization_standard"],
            "complaint_ppm_threshold": data["complaint_ppm_threshold"],
            "quality_standing": "GOOD",
            "weighted_breakage_ppm": D("0.00"),
            "credit_issued_usd": D("0.00"),
        }
    )
    db.customers[record["id"]] = record
    return success(record, 201)


@bp.get("/glass-plant/customers/<customer_id>")
def read_customer(customer_id):
    authorize(
        "PlantManager", "PlantScheduler", "QualityEngineer", "WarehouseOperator", "CustomerRep"
    )
    customer = require(db.customers, customer_id, "ERR_CUSTOMER_NOT_FOUND")
    return success(customer)


@bp.patch("/glass-plant/customers/<customer_id>/palletization-standard")
def update_palletization_standard(customer_id):
    authorize("PlantManager")
    data = validate_body([Enum("palletization_standard", PALLET_STANDARDS)])
    customer = require(db.customers, customer_id, "ERR_CUSTOMER_NOT_FOUND")
    # PRD 3.1: forward-looking only; already-packed lots keep their snapshot.
    customer["palletization_standard"] = data["palletization_standard"]
    touch(customer)
    return success(customer)
