"""SurplusListing endpoints (PRD 3.8)."""
from flask import Blueprint, request

from db import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_SURPLUS_LISTING_NOT_FOUND,
    ERR_TRAY_BATCH_NOT_FOUND,
    ERR_VARIETY_NOT_FOUND,
)
from middleware import get_body, req_int, req_num, req_str, require_roles
from response import success, serialize
from services import new_resource, q3, touch
from routes.listing import list_response

bp = Blueprint("surplus", __name__)

RW = ("Grower", "OpsManager")


def _get_listing(sid):
    rec = db.surplus_listings.get(sid)
    if rec is None:
        raise ApiError(
            404, ERR_SURPLUS_LISTING_NOT_FOUND, "surplus listing id does not exist."
        )
    return rec


@bp.post("/surplus-listings")
@require_roles("Grower")
def create_listing():
    body = get_body()
    variety_id = req_str(body, "variety_id")
    tray_batch_id = req_str(body, "tray_batch_id")
    qty_kg = req_num(body, "qty_kg")
    market_price = req_int(body, "market_price_cents_per_kg")
    market_date = req_str(body, "market_date")
    if variety_id not in db.varieties:
        raise ApiError(404, ERR_VARIETY_NOT_FOUND, "variety_id does not exist.")
    if tray_batch_id not in db.tray_batches:
        raise ApiError(404, ERR_TRAY_BATCH_NOT_FOUND, "tray batch id does not exist.")
    if qty_kg <= 0:
        raise ApiError(400, ERR_INVALID_REQUEST, "qty_kg must be positive.")
    if market_price < 0:
        raise ApiError(400, ERR_INVALID_REQUEST, "market price must be >= 0.")
    rec = new_resource(
        {
            "variety_id": variety_id,
            "tray_batch_id": tray_batch_id,
            "qty_kg": q3(qty_kg),
            "market_price_cents_per_kg": market_price,
            "market_date": market_date,
            "status": "LISTED",
        }
    )
    db.surplus_listings[rec["id"]] = rec
    return success(serialize(rec), "object", 201)


@bp.get("/surplus-listings")
@require_roles(*RW)
def list_listings():
    variety_id = request.args.get("variety_id")
    tray_batch_id = request.args.get("tray_batch_id")
    status = request.args.get("status")
    records = list(db.surplus_listings.values())
    if variety_id is not None:
        records = [r for r in records if r["variety_id"] == variety_id]
    if tray_batch_id is not None:
        records = [r for r in records if r["tray_batch_id"] == tray_batch_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return list_response(records)


@bp.get("/surplus-listings/<sid>")
@require_roles(*RW)
def get_listing(sid):
    return success(serialize(_get_listing(sid)), "object", 200)


@bp.post("/surplus-listings/<sid>/sell")
@require_roles("Grower")
def sell_listing(sid):
    rec = _get_listing(sid)
    if rec["status"] != "LISTED":
        raise ApiError(409, ERR_INVALID_STATE, "Only a LISTED listing can be sold.")
    rec["status"] = "SOLD"
    touch(rec)
    return success(serialize(rec), "object", 200)


@bp.post("/surplus-listings/<sid>/withdraw")
@require_roles("Grower")
def withdraw_listing(sid):
    rec = _get_listing(sid)
    if rec["status"] != "LISTED":
        raise ApiError(
            409, ERR_INVALID_STATE, "Only a LISTED listing can be withdrawn."
        )
    rec["status"] = "WITHDRAWN"
    touch(rec)
    return success(serialize(rec), "object", 200)
