"""SeedLot and GerminationTest endpoints (PRD 3.2)."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from db import db
from errors import (
    ApiError,
    ERR_GERMINATION_TEST_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_SEED_LOT_NOT_FOUND,
    ERR_VARIETY_NOT_FOUND,
)
from middleware import get_body, req_int, req_str, require_roles
from response import success, serialize
from services import cascade_block_lot, new_resource, touch
from routes.listing import list_response

bp = Blueprint("seed_lots", __name__)

RW = ("Grower", "OpsManager")
PASS_THRESHOLD = Decimal("0.85")


@bp.post("/seed-lots")
@require_roles("Grower")
def create_seed_lot():
    body = get_body()
    variety_id = req_str(body, "variety_id")
    supplier_name = req_str(body, "supplier_name")
    lot_code = req_str(body, "lot_code")
    received_date = req_str(body, "received_date")
    seeds_on_hand = req_int(body, "seeds_on_hand_grams")
    if variety_id not in db.varieties:
        raise ApiError(404, ERR_VARIETY_NOT_FOUND, "variety_id does not exist.")
    if seeds_on_hand < 0:
        raise ApiError(400, ERR_INVALID_REQUEST, "seeds_on_hand_grams must be >= 0.")
    # lot_code is unique per variety
    for lot in db.seed_lots.values():
        if lot["variety_id"] == variety_id and lot["lot_code"] == lot_code:
            raise ApiError(
                400, ERR_INVALID_REQUEST, "lot_code already exists for this variety."
            )
    rec = new_resource(
        {
            "variety_id": variety_id,
            "supplier_name": supplier_name,
            "lot_code": lot_code,
            "received_date": received_date,
            "seeds_on_hand_grams": seeds_on_hand,
            "status": "QUARANTINE",
        }
    )
    db.seed_lots[rec["id"]] = rec
    return success(serialize(rec), "object", 201)


@bp.get("/seed-lots")
@require_roles(*RW)
def list_seed_lots():
    variety_id = request.args.get("variety_id")
    status = request.args.get("status")
    records = list(db.seed_lots.values())
    if variety_id is not None:
        records = [r for r in records if r["variety_id"] == variety_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return list_response(records)


@bp.get("/seed-lots/<sid>")
@require_roles(*RW)
def get_seed_lot(sid):
    rec = db.seed_lots.get(sid)
    if rec is None:
        raise ApiError(404, ERR_SEED_LOT_NOT_FOUND, "seed_lot_id does not exist.")
    return success(serialize(rec), "object", 200)


@bp.post("/germination-tests")
@require_roles("Grower")
def create_germination_test():
    body = get_body()
    seed_lot_id = req_str(body, "seed_lot_id")
    seeds_sown_count = req_int(body, "seeds_sown_count")
    if seed_lot_id not in db.seed_lots:
        raise ApiError(404, ERR_SEED_LOT_NOT_FOUND, "seed_lot_id does not exist.")
    if seeds_sown_count <= 0:
        raise ApiError(400, ERR_INVALID_REQUEST, "seeds_sown_count must be positive.")
    rec = new_resource(
        {
            "seed_lot_id": seed_lot_id,
            "seeds_sown_count": seeds_sown_count,
            "germinated_count": None,
            "germination_rate": None,
            "result": "PENDING",
        }
    )
    db.germination_tests[rec["id"]] = rec
    return success(serialize(rec), "object", 201)


@bp.get("/germination-tests")
@require_roles(*RW)
def list_germination_tests():
    seed_lot_id = request.args.get("seed_lot_id")
    records = list(db.germination_tests.values())
    if seed_lot_id is not None:
        records = [r for r in records if r["seed_lot_id"] == seed_lot_id]
    return list_response(records)


@bp.get("/germination-tests/<tid>")
@require_roles(*RW)
def get_germination_test(tid):
    rec = db.germination_tests.get(tid)
    if rec is None:
        raise ApiError(
            404, ERR_GERMINATION_TEST_NOT_FOUND, "germination test id does not exist."
        )
    return success(serialize(rec), "object", 200)


@bp.post("/germination-tests/<tid>/record-result")
@require_roles("Grower")
def record_result(tid):
    test = db.germination_tests.get(tid)
    if test is None:
        raise ApiError(
            404, ERR_GERMINATION_TEST_NOT_FOUND, "germination test id does not exist."
        )
    body = get_body()
    germinated = req_int(body, "germinated_count")
    if test["result"] != "PENDING":
        raise ApiError(409, ERR_INVALID_STATE, "Test result already recorded.")
    if germinated < 0 or germinated > test["seeds_sown_count"]:
        raise ApiError(
            400,
            ERR_INVALID_REQUEST,
            "germinated_count must be between 0 and seeds_sown_count.",
        )
    rate = (Decimal(germinated) / Decimal(test["seeds_sown_count"])).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    # Inclusive boundary: rate >= 0.85 -> PASS, below -> FAIL.
    result = "PASS" if rate >= PASS_THRESHOLD else "FAIL"
    test["germinated_count"] = germinated
    test["germination_rate"] = float(rate)
    test["result"] = result
    touch(test)
    lot = db.seed_lots.get(test["seed_lot_id"])
    if lot is not None:
        if result == "PASS":
            if lot["status"] == "QUARANTINE":
                lot["status"] = "RELEASED"
                touch(lot)
            # PASS on an already-RELEASED lot leaves it RELEASED.
        else:
            if lot["status"] in ("QUARANTINE", "RELEASED"):
                lot["status"] = "BLOCKED"
                touch(lot)
                cascade_block_lot(lot["id"])
    return success(serialize(test), "object", 200)
