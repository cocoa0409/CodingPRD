"""Kit ordering, barcode activation and lab receipt (PRD §3.3)."""
from flask import Blueprint, request

import calc
import db
import services as S
from auth import endpoint, require_owner
from errors import ApiError
from response import ok, paginate
from routes.common import body, require_string

bp = Blueprint("kits", __name__)

CHIP_VERSIONS = ("V4", "V5")


@bp.post("/dna/kits")
@endpoint(["Customer"])
def order_kit():
    payload = body()
    S.require_fields(payload, ["customer_id", "chip_version"])
    customer = S.get("customers", payload["customer_id"])
    require_owner(customer["id"])
    S.require_enum(payload["chip_version"], CHIP_VERSIONS, "chip_version")
    S.require_not_purged(customer)

    kit = db.new_record(
        {
            "customer_id": customer["id"],
            "barcode": db.mint_barcode(),
            "chip_version": payload["chip_version"],
            "price_cents": calc.KIT_PRICE_CENTS,
            "status": "ORDERED",
            "activated_at": None,
        }
    )
    db.db.kits[kit["id"]] = kit
    return ok(S.kit_json(kit), 201)


@bp.get("/dna/kits/<kit_id>")
@endpoint(["Customer", "PlatformAdmin", "LabTechnician"])
def read_kit(kit_id):
    kit = S.get("kits", kit_id)
    require_owner(kit["customer_id"])
    return ok(S.kit_json(kit))


@bp.get("/dna/kits")
@endpoint(["Customer", "PlatformAdmin", "LabTechnician"])
def list_kits():
    records = S.all_of("kits")
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    if customer_id:
        records = [r for r in records if r["customer_id"] == customer_id]
    if status:
        records = [r for r in records if r["status"] == status]
    return paginate(records, S.kit_json)


@bp.post("/dna/kits/<kit_id>/activate")
@endpoint(["Customer"])
def activate_kit(kit_id):
    kit = S.get("kits", kit_id)
    require_owner(kit["customer_id"])

    payload = body()
    S.require_fields(payload, ["barcode"])
    barcode = require_string(payload["barcode"], "barcode")

    customer = db.db.customers[kit["customer_id"]]
    S.require_not_purged(customer)

    if kit["status"] != "ORDERED":
        raise ApiError("ERR_BARCODE_ALREADY_ACTIVATED")
    if barcode != kit["barcode"]:
        raise ApiError("ERR_BARCODE_MISMATCH")
    if S.access_status_of(kit["customer_id"]) not in ("ACTIVE", "GRACE"):
        raise ApiError("ERR_SUBSCRIPTION_LOCKED")

    kit["status"] = "ACTIVATED"
    kit["activated_at"] = db.now()
    db.touch(kit)
    return ok(S.kit_json(kit))


@bp.post("/dna/kits/<kit_id>/receive")
@endpoint(["LabTechnician"])
def receive_kit(kit_id):
    kit = S.get("kits", kit_id)

    if kit["status"] != "ACTIVATED":
        raise ApiError("ERR_INVALID_STATE")

    kit["status"] = "RECEIVED"
    db.touch(kit)

    sample = db.new_record(
        {
            "kit_id": kit["id"],
            "batch_id": None,
            "status": "RECEIVED",
            "extraction_attempts": 0,
            "dna_yield_ng": None,
            "call_rate": None,
            "population_scores": [],
            "genotype_markers": [],
        }
    )
    db.db.samples[sample["id"]] = sample

    customer = db.db.customers.get(kit["customer_id"])
    if customer and customer["dna_status"] == "NO_SAMPLE":
        customer["dna_status"] = "PROCESSING"
        db.touch(customer)

    return ok(S.sample_json(sample), 201)
