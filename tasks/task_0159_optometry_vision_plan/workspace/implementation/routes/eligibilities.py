"""Eligibility (benefit period) + BenefitPool lifecycle."""
from flask import Blueprint, request

import clock
import errors
import helpers
import response
import serialize
from db import db, new_id, stamp_create, touch
from middleware import require_roles
from services import benefit

bp = Blueprint("eligibilities", __name__)

ELIG_CARRIERS = {"VSP", "EYEMED"}
POOL_TYPES = {"MATERIALS", "EXAM"}
EXAM_POOL_ALLOTTED = 1  # single exam-benefit slot


@bp.post("/eligibilities")
@require_roles("FrontDesk")
def create_eligibility():
    body = helpers.get_json_body()
    patient_id = helpers.require_str(body, "patient_id")

    # body FK existence (priority 4)
    patient = db.patients.get(patient_id)
    if patient is None:
        raise errors.reference_not_found("patient_id references no Patient")

    carrier = helpers.require_enum(body, "carrier", ELIG_CARRIERS)
    start = helpers.require_str(body, "benefit_period_start")
    start_date = clock.parse_date(start)
    if start_date is None:
        raise errors.invalid_request("benefit_period_start must be a valid ISO date")
    exam_copay = helpers.require_int(body, "exam_copay_cents", minimum=0)
    materials_allowance = helpers.require_int(body, "materials_allowance_cents",
                                              minimum=0)

    # business referential (priority 10): carrier must equal patient's plan_carrier
    if carrier != patient["plan_carrier"]:
        raise errors.carrier_mismatch(
            "Eligibility carrier must equal the patient's plan_carrier")

    end_date = clock.add_months(start_date, 12)

    record = {
        "id": new_id(),
        "patient_id": patient_id,
        "carrier": carrier,
        "benefit_period_start": start,
        "benefit_period_end": end_date.isoformat(),
        "exam_copay_cents": exam_copay,
        "materials_allowance_cents": materials_allowance,
        "exam_benefit_available": True,
        "status": "ACTIVE",
    }
    stamp_create(record)
    db.eligibilities[record["id"]] = record

    # Auto-provision MATERIALS + EXAM pools.
    materials_pool = {
        "id": new_id(),
        "eligibility_id": record["id"],
        "pool_type": "MATERIALS",
        "allotted_cents": materials_allowance,
        "consumed_cents": 0,
        "remaining_cents": materials_allowance,
    }
    stamp_create(materials_pool)
    db.benefit_pools[materials_pool["id"]] = materials_pool

    exam_pool = {
        "id": new_id(),
        "eligibility_id": record["id"],
        "pool_type": "EXAM",
        "allotted_cents": EXAM_POOL_ALLOTTED,
        "consumed_cents": 0,
        "remaining_cents": EXAM_POOL_ALLOTTED,
    }
    stamp_create(exam_pool)
    db.benefit_pools[exam_pool["id"]] = exam_pool

    return response.object_response(serialize.eligibility(record), 201)


@bp.get("/eligibilities/<eligibility_id>")
@require_roles("FrontDesk", "Optician", "Biller")
def get_eligibility(eligibility_id):
    record = db.eligibilities.get(eligibility_id)
    if record is None:
        raise errors.not_found("Eligibility not found")
    return response.object_response(serialize.eligibility(record), 200)


@bp.get("/eligibilities")
@require_roles("FrontDesk", "Optician", "Biller")
def list_eligibilities():
    limit, offset = helpers.parse_pagination()
    patient_id = request.args.get("patient_id")
    status = request.args.get("status")
    records = list(db.eligibilities.values())
    if patient_id is not None:
        records = [r for r in records if r["patient_id"] == patient_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = helpers.paginate(records, limit, offset)
    return response.array_response(
        [serialize.eligibility(r) for r in page], limit, offset, total, 200)


@bp.get("/eligibilities/<eligibility_id>/benefit-pools")
@require_roles("FrontDesk", "Optician", "Biller")
def list_eligibility_pools(eligibility_id):
    elig = db.eligibilities.get(eligibility_id)
    if elig is None:
        raise errors.not_found("Eligibility not found")
    pool_type = request.args.get("pool_type")
    records = benefit.pools_for(eligibility_id)
    if pool_type is not None:
        records = [r for r in records if r["pool_type"] == pool_type]
    records.sort(key=lambda r: r.get("_seq", 0))
    # not a paginated endpoint per scaffold (no limit/offset inputs)
    return response.array_response(
        [serialize.benefit_pool(r) for r in records], len(records), 0, len(records), 200)


@bp.get("/benefit-pools/<pool_id>")
@require_roles("FrontDesk", "Optician", "Biller")
def get_benefit_pool(pool_id):
    record = db.benefit_pools.get(pool_id)
    if record is None:
        raise errors.not_found("BenefitPool not found")
    return response.object_response(serialize.benefit_pool(record), 200)


@bp.get("/benefit-pools")
@require_roles("FrontDesk", "Optician", "Biller")
def list_benefit_pools():
    limit, offset = helpers.parse_pagination()
    eligibility_id = request.args.get("eligibility_id")
    pool_type = request.args.get("pool_type")
    records = list(db.benefit_pools.values())
    if eligibility_id is not None:
        records = [r for r in records if r["eligibility_id"] == eligibility_id]
    if pool_type is not None:
        records = [r for r in records if r["pool_type"] == pool_type]
    page, total = helpers.paginate(records, limit, offset)
    return response.array_response(
        [serialize.benefit_pool(r) for r in page], limit, offset, total, 200)


@bp.post("/eligibilities/<eligibility_id>/terminate")
@require_roles("FrontDesk")
def terminate_eligibility(eligibility_id):
    record = db.eligibilities.get(eligibility_id)
    if record is None:
        raise errors.not_found("Eligibility not found")
    if record["status"] not in ("ACTIVE", "EXHAUSTED"):
        raise errors.invalid_state(
            "Eligibility must be ACTIVE or EXHAUSTED to terminate")
    for lo in db.lab_orders.values():
        if (lo.get("eligibility_id") == eligibility_id
                and lo["status"] in ("PLACED", "IN_LAB", "REMAKE_REQUESTED")):
            raise errors.invalid_state(
                "Eligibility is referenced by an active lab order")

    record["status"] = "TERMINATED"
    touch(record)
    return response.object_response(serialize.eligibility(record), 200)
