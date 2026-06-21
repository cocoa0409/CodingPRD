from flask import Blueprint, request

from db import store
from errors import err
from middleware import require
from response import success, paginated
from services.common import base_record, touch, require_body, parse_pagination, page
from services import serialize

bp = Blueprint("batches", __name__)


@bp.post("/intake-batches")
@require("IntakeGrader", "StoreAdmin")
def create_batch():
    body = require_body()
    if "agreement_id" not in body or not isinstance(body["agreement_id"], str):
        raise err("ERR_INVALID_REQUEST", "agreement_id required")
    agreement = store.agreements.get(body["agreement_id"])
    if agreement is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "Agreement not found")
    if agreement["status"] != "ACTIVE":
        raise err("ERR_AGREEMENT_TERMINATED", "Agreement is not ACTIVE")

    rec = base_record()
    rec.update({
        "agreement_id": agreement["id"],
        "received_at": rec["created_at"],
        "status": "OPEN",
        "item_count": 0,
    })
    store.intake_batches[rec["id"]] = rec
    return success(serialize.batch_out(rec), 201)


@bp.get("/intake-batches/<bid>")
@require("IntakeGrader", "StoreAdmin", "SettlementManager")
def get_batch(bid):
    b = store.intake_batches.get(bid)
    if b is None:
        raise err("ERR_NOT_FOUND", "Batch not found")
    return success(serialize.batch_out(b), 200)


@bp.post("/intake-batches/<bid>/close")
@require("IntakeGrader", "StoreAdmin")
def close_batch(bid):
    b = store.intake_batches.get(bid)
    if b is None:
        raise err("ERR_NOT_FOUND", "Batch not found")
    if b["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Batch is not OPEN")
    b["status"] = "CLOSED"
    touch(b)
    return success(serialize.batch_out(b), 200)


@bp.get("/intake-batches/<bid>/items")
@require("IntakeGrader", "StoreAdmin", "SettlementManager")
def batch_items(bid):
    if bid not in store.intake_batches:
        raise err("ERR_NOT_FOUND", "Batch not found")
    limit, offset = parse_pagination()
    recs = [it for it in store.items.values() if it["batch_id"] == bid]
    grading_status = request.args.get("grading_status")
    listing_status = request.args.get("listing_status")
    if grading_status is not None:
        recs = [it for it in recs if it["grading_status"] == grading_status]
    if listing_status is not None:
        recs = [it for it in recs if it["listing_status"] == listing_status]
    window, total = page(recs, limit, offset)
    return paginated([serialize.item_out(it) for it in window], limit, offset, total)
