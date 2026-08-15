"""FinishingBatch endpoints (PRD §3.5): booth load discipline and sheen conformance."""

from decimal import Decimal

from flask import Blueprint, request

import db
from errors import err
from middleware import (get_context, require_role, raw_body, validate_fields,
                        req_string, req_int, req_number, require_existence)
from response import success, list_response, parse_pagination

bp = Blueprint("batches", __name__)

BATCH_STATUSES = ("MIXED", "SPRAYED", "CURED", "PASSED", "FAILED")
ACTIVE_BATCH_STATUSES = ("MIXED", "SPRAYED", "CURED")

SHEEN_TARGET_GU = {"MATTE": 15, "SATIN": 35, "SEMI_GLOSS": 60, "HIGH_GLOSS": 85}
SHEEN_TOLERANCE_GU = Decimal("2.0")


def finish_family(finish_system):
    return "PAINT" if finish_system == "PAINT" else "CLEAR_STAIN"


def serialize(b):
    return {
        "id": b["id"],
        "order_id": b["order_id"],
        "booth_id": b["booth_id"],
        "finish_family": b["finish_family"],
        "cure_start_hour": b["cure_start_hour"],
        "cure_end_hour": b["cure_end_hour"],
        "sheen_target_gu": b["sheen_target_gu"],
        "sheen_measured_gu": b["sheen_measured_gu"],
        "delta_gu": b["delta_gu"],
        "is_rework_batch": b["is_rework_batch"],
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


@bp.post("/finishing-batches")
def create_batch():
    _, role = get_context()
    require_role(role, "ProductionLead")
    body = raw_body()
    # Rung 3: body FK existence in declared input order.
    if body.get("order_id") is not None:
        order = require_existence(db.orders, body["order_id"], "ERR_ORDER_NOT_FOUND", "MillworkOrder")
    else:
        order = None
    if body.get("booth_id") is not None:
        booth = require_existence(db.spray_booths, body["booth_id"], "ERR_BOOTH_NOT_FOUND", "SprayBooth")
    else:
        booth = None
    # Rung 4: payload, including the >= 4 shop-hour cure window rule.
    validate_fields(body,
                    required=("order_id", "booth_id", "cure_start_hour", "cure_end_hour"),
                    optional=("is_rework_batch",))
    cure_start = req_int(body, "cure_start_hour")
    cure_end = req_int(body, "cure_end_hour")
    if cure_end - cure_start < 4:
        raise err("ERR_INVALID_CURE_WINDOW", "Cure window must span at least 4 shop-hours")
    is_rework = body.get("is_rework_batch", False)
    if not isinstance(is_rework, bool):
        raise err("ERR_INVALID_REQUEST", "is_rework_batch must be a boolean")
    # Rung 6: order-state gates differ for rework vs non-rework batches.
    if is_rework:
        has_rework = any(o for o in db.openings.values()
                         if o["order_id"] == order["id"] and o["fab_status"] == "REWORK")
        if not has_rework:
            raise err("ERR_NO_REWORK_OPENINGS",
                      "Rework batch requires at least one opening of the order in REWORK")
    else:
        if order["status"] != "FINISHING":
            raise err("ERR_ORDER_NOT_FINISHING",
                      "Non-rework batch creation requires order FINISHING")
    family = finish_family(order["finish_system"])
    # Rung 7 (safety): cross-family purge on overlapping windows, regardless of headroom.
    overlapping = [b for b in db.finishing_batches.values()
                   if b["booth_id"] == booth["id"] and b["status"] in ACTIVE_BATCH_STATUSES
                   and cure_start < b["cure_end_hour"] and b["cure_start_hour"] < cure_end]
    for existing in overlapping:
        if existing["finish_family"] != family:
            raise err("ERR_BOOTH_PURGE_VIOLATION",
                      "Overlapping batches of different finish families share a booth")
    # Rung 11 (fiscal): aggregate capacity — count + 1 must not exceed capacity.
    if len(overlapping) + 1 > booth["capacity"]:
        raise err("ERR_BOOTH_CAPACITY_EXCEEDED", "Booth capacity would be exceeded")
    rec = db.new_record()
    rec.update({
        "order_id": order["id"],
        "booth_id": booth["id"],
        "finish_family": family,
        "cure_start_hour": cure_start,
        "cure_end_hour": cure_end,
        "sheen_target_gu": SHEEN_TARGET_GU[order["sheen_target"]],
        "sheen_measured_gu": None,
        "delta_gu": None,
        "is_rework_batch": is_rework,
        "status": "MIXED",
    })
    db.finishing_batches[rec["id"]] = rec
    return success(serialize(rec), status=201)


@bp.get("/finishing-batches")
def list_batches():
    get_context()
    limit, offset = parse_pagination(request.args)
    order_id = request.args.get("order_id")
    booth_id = request.args.get("booth_id")
    status = request.args.get("status")
    items = [b for b in db.finishing_batches.values()
             if (order_id is None or b["order_id"] == order_id)
             and (booth_id is None or b["booth_id"] == booth_id)
             and (status is None or b["status"] == status)]
    return list_response(items, limit, offset, serialize)


@bp.get("/finishing-batches/<bid>")
def get_batch(bid):
    get_context()
    batch = require_existence(db.finishing_batches, bid, "ERR_BATCH_NOT_FOUND", "FinishingBatch")
    return success(serialize(batch))


@bp.put("/finishing-batches/<bid>/status")
def transition_batch(bid):
    _, role = get_context()
    require_role(role, "ProductionLead")
    batch = require_existence(db.finishing_batches, bid, "ERR_BATCH_NOT_FOUND", "FinishingBatch")
    body = raw_body()
    validate_fields(body, required=("target_status",))
    target = req_string(body, "target_status")
    current = batch["status"]
    declared = (current, target) in (("MIXED", "SPRAYED"), ("SPRAYED", "CURED"))
    if not declared:
        if target in BATCH_STATUSES:
            raise err("ERR_INVALID_BATCH_STATUS_TRANSITION",
                      "Batch cannot transition from %s to %s" % (current, target))
        raise err("ERR_INVALID_BATCH_STATUS_TRANSITION",
                  "Unknown batch status: %s" % target)
    batch["status"] = target
    db.touch(batch)
    return success(serialize(batch))


@bp.post("/finishing-batches/<bid>/measure")
def measure_batch(bid):
    _, role = get_context()
    require_role(role, "QAInspector")
    batch = require_existence(db.finishing_batches, bid, "ERR_BATCH_NOT_FOUND", "FinishingBatch")
    body = raw_body()
    validate_fields(body, required=("sheen_measured_gu",))
    measured = req_number(body, "sheen_measured_gu")
    if batch["status"] != "CURED":
        raise err("ERR_BATCH_NOT_CURED", "Sheen measurement requires batch CURED")
    delta = abs(Decimal(str(measured)) - Decimal(batch["sheen_target_gu"]))
    batch["sheen_measured_gu"] = measured
    batch["delta_gu"] = float(delta)
    if delta <= SHEEN_TOLERANCE_GU:
        batch["status"] = "PASSED"
        # Consolidator: every opening of the order in MACHINED or REWORK -> FINISHED.
        for opening in db.openings.values():
            if opening["order_id"] == batch["order_id"] and opening["fab_status"] in ("MACHINED", "REWORK"):
                opening["fab_status"] = "FINISHED"
                db.touch(opening)
        # Batch-linked IN_REWORK punch items -> RESOLVED.
        for punch in db.punch_items.values():
            if punch["rework_batch_id"] == bid and punch["status"] == "IN_REWORK":
                punch["status"] = "RESOLVED"
                db.touch(punch)
    else:
        batch["status"] = "FAILED"
    db.touch(batch)
    return success(serialize(batch))
