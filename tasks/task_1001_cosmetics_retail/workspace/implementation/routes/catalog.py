"""Clock, stores, products, variants and the shade finder."""
from flask import Blueprint, request

from db import base_record, db, find_lot, public, touch
from errors import ApiError, invalid
from middleware import (
    as_bool,
    as_dt,
    as_enum,
    as_int,
    as_str,
    authenticate,
    body,
    get_product,
    get_store,
    get_variant,
    pagination,
    page,
    required,
)
from response import created, ok, ok_list
from util import iso, parse_dt

bp = Blueprint("catalog", __name__)

ALL_ROLES = ("MerchandisingAdmin", "StoreAssociate", "BeautyArtist", "Customer")
STORE_STATUS = ("ACTIVE", "PAUSED")
CATEGORY = ("SKINCARE", "MAKEUP", "FRAGRANCE", "HAIR")
HYGIENE = ("SEALED", "TESTER_APPLIED", "DIRECT_CONTACT")
FINISH = ("MATTE", "DEWY", "SATIN")
UNDERTONE = ("WARM", "COOL", "NEUTRAL")
VARIANT_STATUS = ("ACTIVE", "DISCONTINUED")
LAUNCH_STATUS = ("NOT_LIMITED", "SCHEDULED", "TIER_ROUGE_ONLY", "TIER_VIB_PLUS", "PUBLIC", "CLOSED")


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------

def advance_launches():
    """Step every limited variant through rouge -> vib -> public in that order."""
    advanced = []
    now = db.clock
    for variant in db.variants.values():
        if not variant["is_limited_launch"]:
            continue
        moved = False
        while True:
            status = variant["launch_status"]
            if status == "SCHEDULED":
                target = parse_dt(variant["launch_open_rouge_at"])
                if target is not None and now >= target:
                    variant["launch_status"] = "TIER_ROUGE_ONLY"
                    touch(variant)
                    moved = True
                    continue
            elif status == "TIER_ROUGE_ONLY":
                target = parse_dt(variant["launch_open_vib_at"])
                if target is not None and now >= target:
                    variant["launch_status"] = "TIER_VIB_PLUS"
                    touch(variant)
                    moved = True
                    continue
            elif status == "TIER_VIB_PLUS":
                target = parse_dt(variant["launch_open_public_at"])
                if target is not None and now >= target:
                    variant["launch_status"] = "PUBLIC"
                    touch(variant)
                    moved = True
                    continue
            break
        if moved:
            advanced.append(variant)
    advanced.sort(key=lambda v: v["_seq"])
    return [v["id"] for v in advanced]


@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate("MerchandisingAdmin")
    payload = body()
    target = as_dt(required(payload, "to_iso8601"), "to_iso8601")
    db.clock = target
    advanced = advance_launches()
    return ok({"current_utc": iso(db.clock), "advanced_variant_ids": advanced})


# --------------------------------------------------------------------------
# stores
# --------------------------------------------------------------------------

@bp.post("/stores")
def create_store():
    authenticate("MerchandisingAdmin")
    payload = body()
    name = as_str(required(payload, "name"), "name")
    region_code = as_str(required(payload, "region_code"), "region_code")
    status = as_enum(payload["status"], "status", STORE_STATUS) if payload.get("status") is not None else "ACTIVE"
    capacity = payload.get("bopis_slot_capacity")
    capacity = as_int(capacity, "bopis_slot_capacity", minimum=1) if capacity is not None else 2

    store = base_record()
    store.update({
        "name": name,
        "region_code": region_code,
        "status": status,
        "bopis_slot_capacity": capacity,
    })
    db.stores[store["id"]] = store
    return created(public(store))


@bp.get("/stores/<store_id>")
def read_store(store_id):
    authenticate(*ALL_ROLES)
    return ok(public(get_store(store_id)))


@bp.patch("/stores/<store_id>")
def update_store(store_id):
    authenticate("MerchandisingAdmin")
    store = get_store(store_id)
    payload = body()
    if payload.get("status") is not None:
        store["status"] = as_enum(payload["status"], "status", STORE_STATUS)
    if payload.get("bopis_slot_capacity") is not None:
        store["bopis_slot_capacity"] = as_int(payload["bopis_slot_capacity"], "bopis_slot_capacity", minimum=1)
    touch(store)
    return ok(public(store))


# --------------------------------------------------------------------------
# products
# --------------------------------------------------------------------------

@bp.post("/products")
def create_product():
    authenticate("MerchandisingAdmin")
    payload = body()
    product = base_record()
    product.update({
        "name": as_str(required(payload, "name"), "name"),
        "brand": as_str(required(payload, "brand"), "brand"),
        "category": as_enum(required(payload, "category"), "category", CATEGORY),
        "hygiene_class": as_enum(required(payload, "hygiene_class"), "hygiene_class", HYGIENE),
        "base_price_cents": as_int(required(payload, "base_price_cents"), "base_price_cents", minimum=0),
    })
    db.products[product["id"]] = product
    return created(public(product))


@bp.get("/products/<product_id>")
def read_product(product_id):
    authenticate(*ALL_ROLES)
    return ok(public(get_product(product_id)))


# --------------------------------------------------------------------------
# variants
# --------------------------------------------------------------------------

@bp.post("/products/<product_id>/variants")
def create_variant(product_id):
    authenticate("MerchandisingAdmin")
    product = get_product(product_id)
    payload = body()

    shade_name = as_str(required(payload, "shade_name"), "shade_name")
    shade_code = as_str(required(payload, "shade_code"), "shade_code")
    finish = as_enum(required(payload, "finish"), "finish", FINISH)
    undertone = as_enum(required(payload, "undertone"), "undertone", UNDERTONE)
    depth_index = as_int(required(payload, "depth_index"), "depth_index", minimum=1, maximum=12)

    price = payload.get("price_cents")
    price = as_int(price, "price_cents", minimum=0) if price is not None else product["base_price_cents"]

    is_limited = payload.get("is_limited_launch")
    is_limited = as_bool(is_limited, "is_limited_launch") if is_limited is not None else False

    cap = payload.get("per_customer_cap")
    cap = as_int(cap, "per_customer_cap", minimum=1) if cap is not None else 2

    windows = {}
    for key in ("launch_open_rouge_at", "launch_open_vib_at", "launch_open_public_at"):
        raw = payload.get(key)
        windows[key] = iso(as_dt(raw, key)) if raw is not None else None

    variant = base_record()
    variant.update({
        "product_id": product["id"],
        "shade_name": shade_name,
        "shade_code": shade_code,
        "finish": finish,
        "undertone": undertone,
        "depth_index": depth_index,
        "price_cents": price,
        "status": "ACTIVE",
        "is_limited_launch": is_limited,
        "launch_status": "SCHEDULED" if is_limited else "NOT_LIMITED",
        "launch_open_rouge_at": windows["launch_open_rouge_at"],
        "launch_open_vib_at": windows["launch_open_vib_at"],
        "launch_open_public_at": windows["launch_open_public_at"],
        "per_customer_cap": cap,
    })
    db.variants[variant["id"]] = variant
    return created(public(variant))


@bp.get("/variants/<variant_id>")
def read_variant(variant_id):
    authenticate(*ALL_ROLES)
    return ok(public(get_variant(variant_id)))


@bp.get("/variants")
def list_variants():
    authenticate(*ALL_ROLES)
    limit, offset = pagination()
    product_id = request.args.get("product_id")
    launch_status = request.args.get("launch_status")

    records = list(db.variants.values())
    if product_id:
        records = [v for v in records if v["product_id"] == product_id]
    if launch_status:
        records = [v for v in records if v["launch_status"] == launch_status]
    items, total = page(records, limit, offset, public)
    return ok_list(items, limit, offset, total)


@bp.patch("/variants/<variant_id>")
def update_variant(variant_id):
    authenticate("MerchandisingAdmin")
    variant = get_variant(variant_id)
    payload = body()
    if payload.get("status") is not None:
        variant["status"] = as_enum(payload["status"], "status", VARIANT_STATUS)
    if payload.get("launch_status") is not None:
        variant["launch_status"] = as_enum(payload["launch_status"], "launch_status", LAUNCH_STATUS)
    if payload.get("price_cents") is not None:
        variant["price_cents"] = as_int(payload["price_cents"], "price_cents", minimum=0)
    touch(variant)
    return ok(public(variant))


# --------------------------------------------------------------------------
# shade finder
# --------------------------------------------------------------------------

DEPTH_TOLERANCE = 2
UNDERTONE_MATCH_POINTS = 25
FINISH_MATCH_POINTS = 15
DEPTH_PENALTY_PER_STEP = 10


@bp.post("/shade-recommendations")
def shade_recommendations():
    authenticate("Customer", "StoreAssociate")
    payload = body()
    undertone = as_enum(required(payload, "undertone"), "undertone", UNDERTONE)
    depth_index = as_int(required(payload, "depth_index"), "depth_index", minimum=1, maximum=12)
    finish_pref = as_enum(required(payload, "finish_pref"), "finish_pref", FINISH)

    store_id = payload.get("store_id")
    if store_id is not None:
        get_store(store_id)

    candidates = []
    for variant in db.variants.values():
        if variant["status"] != "ACTIVE":
            continue
        if variant["launch_status"] not in ("NOT_LIMITED", "PUBLIC"):
            continue
        distance = abs(variant["depth_index"] - depth_index)
        if distance > DEPTH_TOLERANCE:
            continue
        if store_id is not None:
            lot = find_lot(store_id, variant["id"])
            if lot is None:
                continue
            if lot["on_hand_units"] - lot["launch_reserved_units"] < 1:
                continue
        score = 100 - DEPTH_PENALTY_PER_STEP * distance
        if variant["undertone"] == undertone:
            score += UNDERTONE_MATCH_POINTS
        if variant["finish"] == finish_pref:
            score += FINISH_MATCH_POINTS
        candidates.append((score, distance, variant))

    if not candidates:
        raise ApiError("ERR_NO_SHADE_MATCH", "no shade matches the request")

    candidates.sort(key=lambda c: (-c[0], c[1], c[2]["_seq"]))
    return ok(public(candidates[0][2]))
