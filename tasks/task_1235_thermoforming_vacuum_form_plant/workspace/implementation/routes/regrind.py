"""RegrindBatch endpoints (PRD §3.2)."""

from decimal import Decimal
from flask import request

from db import STORE, new_record, bump
from errors import ApiError
from middleware import endpoint, ANY_ROLE
from response import ok_object, list_response
from serializers import ser_batch
from services import get_batch, batch_recompute
from util import (
    BLEND_CAP,
    GRADE_RANK,
    GRADES,
    RESIN_TYPES,
    as_enum,
    as_positive_decimal,
    as_string,
    body_dict,
    opt_present,
    req_present,
)

from routes import bp


@bp.route("/regrind-batches", methods=["POST"])
@endpoint({"MaterialsPlanner"})
def create_batch(user_id, role):
    body = body_dict(request.get_json(silent=True))
    batch_code = as_string(req_present(body, "batch_code"), "batch_code")
    resin_type = as_enum(req_present(body, "resin_type"), "resin_type", RESIN_TYPES)
    source_grade = as_enum(req_present(body, "source_grade"), "source_grade", GRADES)
    target_kg = as_positive_decimal(req_present(body, "target_kg"), "target_kg")

    rec = new_record()
    rec.update({
        "batch_code": batch_code,
        "resin_type": resin_type,
        "source_grade": source_grade,
        "target_kg": target_kg,
        "accumulated_kg": Decimal("0"),
        "reserved_kg": Decimal("0"),
        "consumed_kg": Decimal("0"),
        "available_kg": Decimal("0"),
        "certified_grade": None,
        "max_blend_pct": None,
        "created_by_user_id": user_id,
        "decided_by_user_id": None,
        "status": "ACCEPTING",
    })
    STORE["regrind_batches"][rec["id"]] = rec
    return ok_object(ser_batch(rec), 201)


@bp.route("/regrind-batches", methods=["GET"])
@endpoint(ANY_ROLE)
def list_batches(user_id, role):
    items = list(STORE["regrind_batches"].values())
    status = request.args.get("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    return list_response(items, ser_batch)


@bp.route("/regrind-batches/<batchId>", methods=["GET"])
@endpoint(ANY_ROLE)
def get_one_batch(user_id, role, batchId):
    return ok_object(ser_batch(get_batch(batchId)))


@bp.route("/regrind-batches/<batchId>/decide", methods=["POST"])
@endpoint({"MaterialsPlanner"})
def decide_batch(user_id, role, batchId):
    body = body_dict(request.get_json(silent=True))
    decision = as_enum(req_present(body, "decision"), "decision", {"CERTIFIED", "DOWNGRADED", "REJECTED"})
    # Conditional field: certified_grade iff decision != REJECTED
    raw_grade = opt_present(body, "certified_grade")
    if decision == "REJECTED":
        if raw_grade is not None:
            raise ApiError("ERR_INVALID_REQUEST", "certified_grade must be null when decision is REJECTED")
        certified_grade = None
    else:
        if raw_grade is None:
            raise ApiError("ERR_INVALID_REQUEST", "certified_grade is required unless decision is REJECTED")
        certified_grade = as_enum(raw_grade, "certified_grade", GRADES)

    batch = get_batch(batchId)
    # p6 state
    if batch["status"] != "PENDING_CERT":
        raise ApiError("ERR_INVALID_BATCH_STATE", "Batch decide requires status PENDING_CERT")
    # Segregation of duties: decider must differ from creator
    if user_id == batch["created_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The batch decider must differ from the batch creator",
        )

    if decision == "DOWNGRADED":
        # certified_grade must rank strictly below source_grade
        if GRADE_RANK[certified_grade] >= GRADE_RANK[batch["source_grade"]]:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "DOWNGRADED decision requires certified_grade strictly below source_grade",
            )

    if decision == "REJECTED":
        # Permitted only while no material allocation references the batch
        for alloc in STORE["material_allocations"].values():
            if alloc["regrind_batch_id"] == batch["id"]:
                raise ApiError(
                    "ERR_INVALID_BATCH_STATE",
                    "Batch cannot be rejected while allocations reference it",
                )
        batch["status"] = "REJECTED"
    else:
        batch["certified_grade"] = certified_grade
        batch["max_blend_pct"] = BLEND_CAP[certified_grade]
        batch["status"] = decision  # CERTIFIED or DOWNGRADED

    batch["decided_by_user_id"] = user_id
    batch_recompute(batch)
    bump(batch)
    return ok_object(ser_batch(batch))
