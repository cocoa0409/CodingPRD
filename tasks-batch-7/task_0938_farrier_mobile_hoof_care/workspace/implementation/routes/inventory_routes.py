"""Shoe SKUs, inventory buckets, stock transfers and reservations (PRD 3.2)."""

from flask import Blueprint

from core.auth import authenticate
from core.constants import MATERIALS, MAX_TRANSFER_PAIRS
from core.errors import ApiError
from core.store import db
from core.validate import bad, body, enum, in_range, out_of_range, req_int, req_str
from domain.inventory import move_bucket
from domain.lookup import must, must_ref

from ._common import listing, single

bp = Blueprint("inventory", __name__)

SKU_READ_ROLES = ("PlatformAdmin", "Dispatcher", "Farrier", "BillingClerk")
STOCK_READ_ROLES = ("PlatformAdmin", "Dispatcher", "Farrier")


# --------------------------------------------------------------------------
# Shoe SKUs
# --------------------------------------------------------------------------
@bp.post("/shoe-skus")
def create_sku():
    authenticate(("PlatformAdmin",))
    data = body()
    sku_code = req_str(data, "sku_code")
    size_code = req_str(data, "size_code")
    material = data.get("material")
    if not isinstance(material, str) or not material:
        bad("Field material is required.")
    price = req_int(data, "price_cents_per_pair")
    if any(row["sku_code"] == sku_code for row in db.shoe_skus.values()):
        bad("sku_code must be unique across all SKUs.")
    enum(material, MATERIALS, "material")
    if price < 0:
        out_of_range("price_cents_per_pair may not be negative.")
    sku = db.mint(
        "shoe_skus",
        {
            "sku_code": sku_code,
            "size_code": size_code,
            "material": material,
            "price_cents_per_pair": price,
        },
    )
    from domain.inventory import mint_buckets_for_sku

    mint_buckets_for_sku(sku)
    return single(sku, 201)


@bp.get("/shoe-skus")
def list_skus():
    return listing("shoe_skus", {"material": "material", "size_code": "size_code"}, SKU_READ_ROLES)


@bp.get("/shoe-skus/<sku_id>")
def read_sku(sku_id):
    authenticate(SKU_READ_ROLES)
    return single(must("shoe_skus", sku_id))


# --------------------------------------------------------------------------
# Inventory buckets
# --------------------------------------------------------------------------
@bp.get("/inventory-buckets")
def list_buckets():
    return listing(
        "inventory_buckets",
        {"farrier_id": "farrier_id", "sku_id": "sku_id", "location_kind": "location_kind"},
        STOCK_READ_ROLES,
    )


@bp.get("/inventory-buckets/<bucket_id>")
def read_bucket(bucket_id):
    authenticate(STOCK_READ_ROLES)
    return single(must("inventory_buckets", bucket_id))


@bp.post("/inventory-buckets/<bucket_id>/adjust")
def adjust_bucket(bucket_id):
    authenticate(("PlatformAdmin",))
    bucket = must("inventory_buckets", bucket_id)
    data = body()
    delta = req_int(data, "delta_pairs")
    # Adjudication of friction 4: an adjustment that would drive on_hand_pairs
    # or available_pairs below zero is REFUSED with ERR_VALUE_OUT_OF_RANGE
    # rather than written as-is.  Section 4.1 declares ERR_VALUE_OUT_OF_RANGE as
    # a reachable refusal of this endpoint and no other range applies to
    # delta_pairs, so the permissive reading would strand that declared code;
    # refusing strands nothing, since no declared behaviour needs a negative
    # bucket balance.
    if bucket["on_hand_pairs"] + delta < 0 or bucket["available_pairs"] + delta < 0:
        out_of_range("delta_pairs would drive the bucket below zero.")
    move_bucket(bucket, on_hand=delta, available=delta)
    return single(bucket)


# --------------------------------------------------------------------------
# Stock transfers
# --------------------------------------------------------------------------
@bp.post("/stock-transfers")
def create_transfer():
    authenticate(("PlatformAdmin", "Dispatcher"))
    data = body()
    must_ref("shoe_skus", data.get("sku_id"))
    must_ref("inventory_buckets", data.get("from_bucket_id"))
    must_ref("inventory_buckets", data.get("to_bucket_id"))
    sku_id = req_str(data, "sku_id")
    from_bucket_id = req_str(data, "from_bucket_id")
    to_bucket_id = req_str(data, "to_bucket_id")
    quantity = req_int(data, "quantity_pairs")
    source = db.get("inventory_buckets", from_bucket_id)
    target = db.get("inventory_buckets", to_bucket_id)
    if source["location_kind"] != "SHOP" or source["sku_id"] != sku_id:
        bad("from_bucket_id must be the SHOP bucket for this SKU.")
    if target["location_kind"] != "VAN" or target["sku_id"] != sku_id:
        bad("to_bucket_id must be a VAN bucket for the same SKU.")
    in_range(quantity, 1, MAX_TRANSFER_PAIRS, "quantity_pairs")
    transfer = db.mint(
        "stock_transfers",
        {
            "sku_id": sku_id,
            "from_bucket_id": from_bucket_id,
            "to_bucket_id": to_bucket_id,
            "quantity_pairs": quantity,
            "status": "REQUESTED",
        },
    )
    return single(transfer, 201)


@bp.get("/stock-transfers")
def list_transfers():
    return listing(
        "stock_transfers",
        {
            "sku_id": "sku_id",
            "from_bucket_id": "from_bucket_id",
            "to_bucket_id": "to_bucket_id",
            "status": "status",
        },
        STOCK_READ_ROLES,
    )


@bp.get("/stock-transfers/<transfer_id>")
def read_transfer(transfer_id):
    authenticate(STOCK_READ_ROLES)
    return single(must("stock_transfers", transfer_id))


@bp.post("/stock-transfers/<transfer_id>/dispatch")
def dispatch_transfer(transfer_id):
    authenticate(("PlatformAdmin",))
    transfer = must("stock_transfers", transfer_id)
    if transfer["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE")
    shop = db.get("inventory_buckets", transfer["from_bucket_id"])
    if shop is None or shop["available_pairs"] < transfer["quantity_pairs"]:
        raise ApiError("ERR_SHOP_STOCK_INSUFFICIENT")
    move_bucket(shop, on_hand=-transfer["quantity_pairs"], available=-transfer["quantity_pairs"])
    transfer["status"] = "IN_TRANSIT"
    db.touch(transfer)
    return single(transfer)


@bp.post("/stock-transfers/<transfer_id>/receive")
def receive_transfer(transfer_id):
    authenticate(("Farrier", "PlatformAdmin"))
    transfer = must("stock_transfers", transfer_id)
    if transfer["status"] != "IN_TRANSIT":
        raise ApiError("ERR_INVALID_STATE")
    van = db.get("inventory_buckets", transfer["to_bucket_id"])
    if van is not None:
        move_bucket(van, on_hand=transfer["quantity_pairs"], available=transfer["quantity_pairs"])
    transfer["status"] = "RECEIVED"
    db.touch(transfer)
    return single(transfer)


@bp.post("/stock-transfers/<transfer_id>/abort")
def abort_transfer(transfer_id):
    authenticate(("PlatformAdmin",))
    transfer = must("stock_transfers", transfer_id)
    if transfer["status"] != "IN_TRANSIT":
        raise ApiError("ERR_INVALID_STATE")
    shop = db.get("inventory_buckets", transfer["from_bucket_id"])
    if shop is not None:
        move_bucket(shop, on_hand=transfer["quantity_pairs"], available=transfer["quantity_pairs"])
    transfer["status"] = "ABORTED"
    db.touch(transfer)
    return single(transfer)


# --------------------------------------------------------------------------
# Shoe reservations
# --------------------------------------------------------------------------
@bp.get("/shoe-reservations")
def list_reservations():
    return listing(
        "shoe_reservations",
        {
            "appointment_id": "appointment_id",
            "sku_id": "sku_id",
            "bucket_id": "bucket_id",
            "status": "status",
        },
        STOCK_READ_ROLES,
    )


@bp.get("/shoe-reservations/<reservation_id>")
def read_reservation(reservation_id):
    authenticate(STOCK_READ_ROLES)
    return single(must("shoe_reservations", reservation_id))
