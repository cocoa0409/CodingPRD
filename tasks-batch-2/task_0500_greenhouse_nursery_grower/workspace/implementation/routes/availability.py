from flask import Blueprint, request

from core import (store, require, get_body, get_or_404, ok, ok_list, paginate, common_create, touch,
                  req_str, req_int, ApiError, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_BATCH_NOT_SALEABLE)
import services as svc

bp = Blueprint("availability", __name__)


@bp.post("/nursery/availability")
def publish_availability():
    require(["SalesCoordinator"])
    body = get_body()
    raw_bid = body.get("batch_id")
    if isinstance(raw_bid, str) and raw_bid not in store.batches:
        raise ApiError(ERR_NOT_FOUND, "Batch not found")
    batch_id = req_str(body, "batch_id")
    unit_price_cents = req_int(body, "unit_price_cents", minimum=1)
    if batch_id not in store.batches:
        raise ApiError(ERR_NOT_FOUND, "Batch not found")
    batch = store.batches[batch_id]
    if batch["status"] != "SALEABLE":
        raise ApiError(ERR_BATCH_NOT_SALEABLE, "Batch is not SALEABLE")
    entry = common_create({
        "batch_id": batch_id,
        "variety_id": batch["variety_id"],
        "unit_price_cents": unit_price_cents,
        "published_quantity": batch["saleable_count"],
        "committed_quantity": 0,
        "available_quantity": batch["saleable_count"],
        "status": "OPEN",
    })
    store.availability[entry["id"]] = entry
    return ok(entry, 201)


@bp.get("/nursery/availability/<aid>")
def get_availability(aid):
    require(["SalesCoordinator", "Broker"])
    entry = get_or_404(store.availability, aid)
    return ok(entry)


@bp.get("/nursery/availability")
def list_availability():
    require(["SalesCoordinator", "Broker"])
    rows = list(store.availability.values())
    for key in ("status", "variety_id", "batch_id"):
        val = request.args.get(key)
        if val is not None:
            rows = [r for r in rows if r[key] == val]
    page, limit, offset, total = paginate(rows)
    return ok_list(page, limit, offset, total)


@bp.post("/nursery/availability/<aid>/close")
def close_availability(aid):
    require(["SalesCoordinator"])
    entry = get_or_404(store.availability, aid)
    if entry["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, "Availability entry is not OPEN")
    entry["status"] = "CLOSED"
    touch(entry)
    return ok(entry)
