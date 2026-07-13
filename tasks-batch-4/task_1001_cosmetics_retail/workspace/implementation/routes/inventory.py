"""Inventory lots and tester conversions."""
from flask import Blueprint, request

from db import base_record, db, find_lot, public, touch
from errors import ApiError, invalid
from middleware import (
    as_int,
    as_str,
    authenticate,
    body,
    get_lot,
    get_store,
    get_variant,
    page,
    pagination,
    required,
)
from response import created, ok, ok_list

bp = Blueprint("inventory", __name__)


@bp.post("/inventory-lots")
def create_lot():
    authenticate("MerchandisingAdmin")
    payload = body()

    store_id = as_str(required(payload, "store_id"), "store_id")
    variant_id = as_str(required(payload, "variant_id"), "variant_id")
    units_received = as_int(required(payload, "units_received"), "units_received", minimum=0)
    launch_reserved = payload.get("launch_reserved_units")
    launch_reserved = as_int(launch_reserved, "launch_reserved_units", minimum=0) if launch_reserved is not None else 0
    if launch_reserved > units_received:
        raise invalid("'launch_reserved_units' must be <= units_received")

    store = get_store(store_id)
    variant = get_variant(variant_id)

    if find_lot(store["id"], variant["id"]) is not None:
        raise ApiError("ERR_LOT_ALREADY_EXISTS", "a lot already exists for this (store, variant) pair")

    lot = base_record()
    lot.update({
        "store_id": store["id"],
        "variant_id": variant["id"],
        "units_received": units_received,
        "on_hand_units": units_received,
        "reserved_units": 0,
        "tester_units": 0,
        "sold_units": 0,
        "destroyed_units": 0,
        "launch_reserved_units": launch_reserved,
    })
    db.lots[lot["id"]] = lot
    return created(public(lot))


@bp.get("/inventory-lots/<lot_id>")
def read_lot(lot_id):
    authenticate("MerchandisingAdmin", "StoreAssociate")
    return ok(public(get_lot(lot_id)))


@bp.get("/inventory-lots")
def list_lots():
    authenticate("MerchandisingAdmin", "StoreAssociate")
    limit, offset = pagination()
    store_id = request.args.get("store_id")
    variant_id = request.args.get("variant_id")

    records = list(db.lots.values())
    if store_id:
        records = [l for l in records if l["store_id"] == store_id]
    if variant_id:
        records = [l for l in records if l["variant_id"] == variant_id]
    items, total = page(records, limit, offset, public)
    return ok_list(items, limit, offset, total)


@bp.post("/inventory-lots/<lot_id>/tester-conversions")
def tester_conversion(lot_id):
    authenticate("StoreAssociate")
    lot = get_lot(lot_id)
    payload = body()

    units = as_int(required(payload, "units"), "units", minimum=1)
    expected = as_int(required(payload, "expected_lot_version"), "expected_lot_version", minimum=0)

    # optimistic concurrency on the parent lot (PRD 2.8)
    if expected != lot["version"]:
        raise ApiError("ERR_STALE_LOT_VERSION", "the lot has moved since it was read")

    variant = db.variants[lot["variant_id"]]
    product = db.products[variant["product_id"]]
    if product["hygiene_class"] == "DIRECT_CONTACT":
        raise ApiError("ERR_TESTER_NOT_ALLOWED", "direct-contact products may not be put out as testers")

    if lot["on_hand_units"] < units:
        raise ApiError("ERR_INSUFFICIENT_STOCK", "the lot does not hold that many on-hand units")

    lot["on_hand_units"] -= units
    lot["tester_units"] += units
    touch(lot)
    return ok(public(lot))
