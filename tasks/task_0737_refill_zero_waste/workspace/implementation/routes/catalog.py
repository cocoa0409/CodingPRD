from flask import Blueprint, request

import store
import response
import serialize
import calc
from errors import ApiError
from helpers import endpoint, get_body, field, lookup, require_fk, stamp_new, touch, paginate

bp = Blueprint("catalog", __name__)


# ---------------------------------------------------------------------------
# Logical clock (test-driving)
# ---------------------------------------------------------------------------
@bp.post("/v1/_clock/set_current_utc")
@endpoint(["InventoryManager"])
def set_clock():
    body = get_body()
    dt = field(body, "to_iso8601", required=True, kind="datetime")
    store.set_clock(dt)
    return response.ok({})


# ---------------------------------------------------------------------------
# Product
# ---------------------------------------------------------------------------
@bp.post("/v1/products")
@endpoint(["InventoryManager"])
def create_product():
    body = get_body()
    rec = {
        "name": field(body, "name", required=True, kind="str"),
        "category": field(body, "category", required=True, kind="str",
                          enum={"GRAINS", "LIQUIDS", "SPICES", "CLEANING"}),
        "unit_price_cents_per_100g": field(body, "unit_price_cents_per_100g", required=True, kind="int"),
        "bulk_tier_threshold_g": field(body, "bulk_tier_threshold_g", required=True, kind="int"),
        "bulk_tier_price_cents_per_100g": field(body, "bulk_tier_price_cents_per_100g", required=True, kind="int"),
        "allergen_tags": field(body, "allergen_tags", kind="array", default=[]),
        "taxable": field(body, "taxable", kind="bool", default=False),
    }
    stamp_new(rec)
    store.DB["products"][rec["id"]] = rec
    return response.created(serialize.product_out(rec))


@bp.get("/v1/products/<product_id>")
@endpoint(["Member", "StoreClerk", "InventoryManager"])
def get_product(product_id):
    return response.ok(serialize.product_out(lookup("products", product_id)))


# ---------------------------------------------------------------------------
# RefillStation
# ---------------------------------------------------------------------------
@bp.post("/v1/stations")
@endpoint(["InventoryManager"])
def create_station():
    body = get_body()
    rec = {
        "name": field(body, "name", required=True, kind="str"),
        "station_status": field(body, "station_status", kind="str",
                               enum={"OPEN", "MAINTENANCE"}, default="OPEN"),
    }
    stamp_new(rec)
    store.DB["stations"][rec["id"]] = rec
    return response.created(serialize.station_out(rec))


@bp.get("/v1/stations/<station_id>")
@endpoint(["Member", "StoreClerk", "InventoryManager"])
def get_station(station_id):
    return response.ok(serialize.station_out(lookup("stations", station_id)))


# ---------------------------------------------------------------------------
# BulkBin
# ---------------------------------------------------------------------------
@bp.post("/v1/bins")
@endpoint(["InventoryManager"])
def create_bin():
    body = get_body()
    product_id = field(body, "product_id", required=True, kind="str")
    station_id = field(body, "station_id", required=True, kind="str")
    capacity_g = field(body, "capacity_g", required=True, kind="int")
    reorder_threshold_g = field(body, "reorder_threshold_g", required=True, kind="int")
    last_recount_g = field(body, "last_recount_g", required=True, kind="int")
    # Existence of body FKs (product before station, per input order)
    require_fk("products", product_id)
    require_fk("stations", station_id)
    status = "LOW" if last_recount_g <= reorder_threshold_g else "OPEN"
    rec = {
        "product_id": product_id,
        "station_id": station_id,
        "capacity_g": capacity_g,
        "reorder_threshold_g": reorder_threshold_g,
        "on_hand_g": last_recount_g,
        "last_recount_g": last_recount_g,
        "last_recount_at": store.now(),
        "last_shrink_g": 0,
        "status": status,
    }
    stamp_new(rec)
    store.DB["bins"][rec["id"]] = rec
    return response.created(serialize.bin_out(rec))


@bp.get("/v1/bins/<bin_id>")
@endpoint(["Member", "StoreClerk", "InventoryManager"])
def get_bin(bin_id):
    return response.ok(serialize.bin_out(lookup("bins", bin_id)))


@bp.get("/v1/bins")
@endpoint(["Member", "StoreClerk", "InventoryManager"])
def list_bins():
    product_id = request.args.get("product_id")
    station_id = request.args.get("station_id")
    status = request.args.get("status")
    recs = list(store.DB["bins"].values())
    if product_id is not None:
        recs = [b for b in recs if b["product_id"] == product_id]
    if station_id is not None:
        recs = [b for b in recs if b["station_id"] == station_id]
    if status is not None:
        recs = [b for b in recs if b["status"] == status]
    page, limit, offset, total = paginate(recs)
    return response.listing([serialize.bin_out(b) for b in page], limit, offset, total)


@bp.post("/v1/bins/<bin_id>/recount")
@endpoint(["InventoryManager"])
def recount_bin(bin_id):
    b = lookup("bins", bin_id)
    body = get_body()
    physical_g = field(body, "physical_g", required=True, kind="int")

    baseline = b["last_recount_at"]
    dispensed = 0
    for l in store.DB["lines"].values():
        if l["pricing_stage"] == "FINAL" and l["bin_id"] == b["id"] and l["created_at"] >= baseline:
            dispensed += l["net_weight_g"]
    restocked = 0
    for t in store.DB["restock_tasks"].values():
        if (t["status"] == "COMPLETED" and t["bin_id"] == b["id"]
                and t.get("_completed_at") is not None and t["_completed_at"] >= baseline):
            restocked += t["restocked_g"]

    shrink_g = calc.shrink(b["last_recount_g"], dispensed, restocked, physical_g)
    b["last_shrink_g"] = shrink_g
    b["on_hand_g"] = physical_g
    b["last_recount_g"] = physical_g
    b["last_recount_at"] = store.now()
    if shrink_g > calc.SHRINK_QUARANTINE_G:
        b["status"] = "QUARANTINED"
    elif b["status"] == "QUARANTINED" and shrink_g <= calc.SHRINK_QUARANTINE_G:
        b["status"] = "OPEN"
    touch(b)
    return response.ok(serialize.bin_out(b))
