"""MaterialAllocation endpoints (PRD §3.5)."""

from flask import request

from db import STORE, new_record, bump
from errors import ApiError
from middleware import endpoint, ANY_ROLE
from response import ok_object, list_response
from serializers import ser_allocation
from services import (
    get_allocation,
    get_batch,
    get_lot,
    get_order,
    allocations_of,
    cert_exists_at_grade,
    valid_cert_at_grade,
    release_allocation,
    reserve_balance,
)
from util import (
    BLEND_CAP,
    GRADE_RANK,
    as_enum,
    as_positive_decimal,
    as_string,
    body_dict,
    opt_present,
    q3,
    req_present,
)

from routes import bp

SOURCE_TYPES = {"VIRGIN_LOT", "REGRIND"}


@bp.route("/material-allocations", methods=["POST"])
@endpoint({"ProductionScheduler"})
def create_allocation(user_id, role):
    body = body_dict(request.get_json(silent=True))
    order_id = as_string(req_present(body, "production_order_id"), "production_order_id")
    source_type = as_enum(req_present(body, "source_type"), "source_type", SOURCE_TYPES)
    # Conditional fields: lot_id iff VIRGIN_LOT; regrind_batch_id iff REGRIND
    lot_id = opt_present(body, "lot_id")
    regrind_batch_id = opt_present(body, "regrind_batch_id")
    if source_type == "VIRGIN_LOT":
        if lot_id is None:
            raise ApiError("ERR_INVALID_REQUEST", "lot_id is required when source_type is VIRGIN_LOT")
        if regrind_batch_id is not None:
            raise ApiError("ERR_INVALID_REQUEST", "regrind_batch_id must be null when source_type is VIRGIN_LOT")
        lot_id = as_string(lot_id, "lot_id")
    else:
        if regrind_batch_id is None:
            raise ApiError("ERR_INVALID_REQUEST", "regrind_batch_id is required when source_type is REGRIND")
        if lot_id is not None:
            raise ApiError("ERR_INVALID_REQUEST", "lot_id must be null when source_type is REGRIND")
        regrind_batch_id = as_string(regrind_batch_id, "regrind_batch_id")
    qty_kg = as_positive_decimal(req_present(body, "qty_kg"), "qty_kg")

    # p4 existence (body order: order, then source)
    order = get_order(order_id)
    # p6 state: order allocatable
    if order["schedule_status"] not in ("QUEUED", "STAGED", "ON_HOLD"):
        raise ApiError(
            "ERR_ORDER_NOT_ALLOCATABLE",
            "Allocation create requires order schedule_status in QUEUED, STAGED, or ON_HOLD",
        )

    if source_type == "VIRGIN_LOT":
        lot = get_lot(lot_id)
        batch = None
        # p6 state: source lot must be CERTIFIED
        if lot["status"] != "CERTIFIED":
            raise ApiError("ERR_INVALID_LOT_STATE", "Allocation source lot must be CERTIFIED")
        # p7: a lot certificate at grade >= order grade must exist (rank check, expiry aside)
        if not cert_exists_at_grade("MATERIAL_LOT", lot["id"], order["cleanliness_grade"]):
            raise ApiError(
                "ERR_GRADE_INCOMPATIBLE",
                "No lot certificate at a grade sufficient for the order",
            )
        # p8: that grade-satisfying certificate must be currently valid
        if not valid_cert_at_grade("MATERIAL_LOT", lot["id"], order["cleanliness_grade"]):
            raise ApiError(
                "ERR_CERTIFICATE_INVALID",
                "The grade-satisfying lot certificate is not currently valid",
            )
        # p9 domain: resin match, exact gauge match
        if lot["resin_type"] != order["resin_type"]:
            raise ApiError("ERR_RESIN_MISMATCH", "Lot resin_type differs from the order's")
        if lot["gauge_mm"] != order["required_gauge_mm"]:
            raise ApiError("ERR_GAUGE_MISMATCH", "Lot gauge_mm differs from the order's required_gauge_mm")
        # p10 sufficiency
        if lot["available_kg"] < qty_kg:
            raise ApiError("ERR_INSUFFICIENT_MATERIAL", "Lot available_kg is below the requested qty_kg")
    else:
        batch = get_batch(regrind_batch_id)
        lot = None
        # p6 state: batch must be CERTIFIED or DOWNGRADED
        if batch["status"] not in ("CERTIFIED", "DOWNGRADED"):
            raise ApiError(
                "ERR_INVALID_BATCH_STATE", "Allocation source batch must be CERTIFIED or DOWNGRADED"
            )
        # p7: certified_grade rank >= order grade
        if GRADE_RANK[batch["certified_grade"]] < GRADE_RANK[order["cleanliness_grade"]]:
            raise ApiError(
                "ERR_GRADE_INCOMPATIBLE", "Batch certified_grade is below the order grade"
            )
        # p7: a batch certificate at grade >= order grade must exist (rank check, expiry aside)
        if not cert_exists_at_grade("REGRIND_BATCH", batch["id"], order["cleanliness_grade"]):
            raise ApiError(
                "ERR_GRADE_INCOMPATIBLE",
                "No batch certificate at a grade sufficient for the order",
            )
        # p8: that grade-satisfying certificate must be currently valid
        if not valid_cert_at_grade("REGRIND_BATCH", batch["id"], order["cleanliness_grade"]):
            raise ApiError(
                "ERR_CERTIFICATE_INVALID",
                "The grade-satisfying batch certificate is not currently valid",
            )
        # p9 domain: resin match, cumulative blend cap
        if batch["resin_type"] != order["resin_type"]:
            raise ApiError("ERR_RESIN_MISMATCH", "Batch resin_type differs from the order's")
        cap = q3(order["required_material_kg"] * BLEND_CAP[order["cleanliness_grade"]])
        cumulative = qty_kg
        for a in allocations_of(order["id"]):
            if a["source_type"] == "REGRIND" and a["status"] == "RESERVED":
                cumulative += a["qty_kg"]
        if cumulative > cap:
            raise ApiError(
                "ERR_BLEND_CAP_EXCEEDED",
                "Cumulative RESERVED regrind would exceed the blend cap",
            )
        # p10 sufficiency: eligible mass
        eligible = batch["accumulated_kg"] - batch["reserved_kg"] - batch["consumed_kg"]
        if eligible < qty_kg:
            raise ApiError("ERR_INSUFFICIENT_MATERIAL", "Batch eligible mass is below the requested qty_kg")

    rec = new_record()
    rec.update({
        "production_order_id": order["id"],
        "source_type": source_type,
        "lot_id": lot["id"] if lot else None,
        "regrind_batch_id": batch["id"] if batch else None,
        "qty_kg": qty_kg,
        "status": "RESERVED",
    })
    STORE["material_allocations"][rec["id"]] = rec
    reserve_balance(rec)
    bump(order)  # allocation creation advances ProductionOrder.version
    return ok_object(ser_allocation(rec), 201)


@bp.route("/material-allocations", methods=["GET"])
@endpoint(ANY_ROLE)
def list_allocations(user_id, role):
    items = list(STORE["material_allocations"].values())
    order_id = request.args.get("production_order_id")
    if order_id is not None:
        items = [a for a in items if a["production_order_id"] == order_id]
    lot_id = request.args.get("lot_id")
    if lot_id is not None:
        items = [a for a in items if a["lot_id"] == lot_id]
    batch_id = request.args.get("regrind_batch_id")
    if batch_id is not None:
        items = [a for a in items if a["regrind_batch_id"] == batch_id]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return list_response(items, ser_allocation)


@bp.route("/material-allocations/<allocationId>", methods=["GET"])
@endpoint(ANY_ROLE)
def get_one_allocation(user_id, role, allocationId):
    return ok_object(ser_allocation(get_allocation(allocationId)))


@bp.route("/material-allocations/<allocationId>/release", methods=["POST"])
@endpoint({"ProductionScheduler"})
def release_allocation_endpoint(user_id, role, allocationId):
    alloc = get_allocation(allocationId)
    if alloc["status"] not in ("RESERVED", "REVIEW"):
        raise ApiError(
            "ERR_ALLOCATION_NOT_RELEASABLE", "Release requires status RESERVED or REVIEW"
        )
    release_allocation(alloc)
    order = get_order(alloc["production_order_id"])
    bump(order)  # release advances ProductionOrder.version
    return ok_object(ser_allocation(alloc))
