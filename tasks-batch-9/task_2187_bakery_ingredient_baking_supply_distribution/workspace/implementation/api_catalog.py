"""Clock, customers, products, warehouse zones and the index board."""
from flask import Blueprint

import calc
import domain
import envelope
import serialize
import store
import validate as v
from auth import ROLES, authenticate, require_owner
from common import fk_lookup, path_lookup, unique_or_fail
from errors import fail

bp = Blueprint("catalog", __name__)

ALLERGEN_CLASSES = ("NONE", "GLUTEN", "TREE_NUT", "PEANUT", "DAIRY", "EGG", "SOY")
ALLERGEN_PROGRAMS = ("STANDARD", "GLUTEN_FREE_CERTIFIED", "NUT_FREE_CERTIFIED")
CATEGORIES = ("FLOUR", "LEAVENING", "FAT", "INCLUSION", "PACKAGING")
INDEX_CODES = ("HRW_WHEAT", "SRW_WHEAT", "SOFT_OIL", "CANE_SUGAR")
PRODUCT_INDEX_CODES = ("NONE",) + INDEX_CODES


# ------------------------------------------------------------- clock ------
@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(("PlatformAdmin",))
    body = v.body()
    instant = v.instant(body, "to_iso8601", required=True)
    domain.advance_clock(instant)
    return envelope.ok({})


# --------------------------------------------------------- customers ------
@bp.post("/customers")
def create_customer():
    authenticate(("AccountManager",))
    body = v.body()
    legal_name = v.string(body, "legal_name", min_len=1, max_len=120)
    allergen_program = v.enum(body, "allergen_program", ALLERGEN_PROGRAMS)
    credit_limit = v.integer(body, "credit_limit_cents", minimum=0)
    min_drop = v.integer(body, "min_drop_cents", required=False, minimum=0, default=25000)
    unique_or_fail("customers", "legal_name", legal_name, case_insensitive=True)
    rec = store.base_record()
    rec.update({
        "legal_name": legal_name,
        "status": "ACTIVE",
        "allergen_program": allergen_program,
        "credit_limit_cents": credit_limit,
        "open_exposure_cents": 0,
        "min_drop_cents": min_drop,
        "allergen_risk_score": store.D("0.00"),
        "risk_tier": "GREEN",
    })
    store.insert("customers", rec)
    return envelope.created(serialize.customer(rec))


@bp.get("/customers/<cid>")
def read_customer(cid):
    actor = authenticate(("AccountManager", "PricingController", "CustomerBuyer",
                          "QualityManager", "PlatformAdmin"))
    rec = path_lookup("customers", cid)
    require_owner(actor, rec["id"])
    return envelope.ok(serialize.customer(rec))


@bp.post("/customers/<cid>/credit-limit-adjustments")
def adjust_credit_limit(cid):
    authenticate(("AccountManager",))
    body = v.body()
    new_limit = v.integer(body, "new_credit_limit_cents", minimum=0)
    v.string(body, "reason", min_len=1)
    rec = path_lookup("customers", cid)
    rec["credit_limit_cents"] = new_limit
    calc.recompute_open_exposure(rec, bump_on_change=False)
    store.bump(rec)
    return envelope.ok(serialize.customer(rec))


# ---------------------------------------------------------- products ------
@bp.post("/products")
def create_product():
    authenticate(("PricingController",))
    body = v.body()
    sku = v.string(body, "sku", min_len=3, max_len=32)
    category = v.enum(body, "category", CATEGORIES)
    allergen_class = v.enum(body, "allergen_class", ALLERGEN_CLASSES)
    bulk_capable = v.boolean(body, "bulk_capable", default=False)
    shelf_life_days = v.integer(body, "shelf_life_days", minimum=1)
    index_code = v.enum(body, "index_code", PRODUCT_INDEX_CODES, required=False, default="NONE")
    list_price = v.integer(body, "list_price_cents_per_lb", minimum=1)
    min_rotation_days = v.integer(body, "min_rotation_days", required=False, minimum=0, default=0)
    unique_or_fail("products", "sku", sku)
    rec = store.base_record()
    rec.update({
        "sku": sku,
        "category": category,
        "allergen_class": allergen_class,
        "bulk_capable": bulk_capable,
        "shelf_life_days": shelf_life_days,
        "index_code": index_code,
        "list_price_cents_per_lb": list_price,
        "min_rotation_days": min_rotation_days,
    })
    store.insert("products", rec)
    return envelope.created(serialize.product(rec))


@bp.get("/products/<pid>")
def read_product(pid):
    authenticate(ROLES)
    return envelope.ok(serialize.product(path_lookup("products", pid)))


# ---------------------------------------------------- warehouse zones -----
@bp.post("/warehouse-zones")
def create_zone():
    authenticate(("WarehouseOperator",))
    body = v.body()
    zone_code = v.string(body, "zone_code", min_len=2, max_len=16)
    allergen_class = v.enum(body, "allergen_class", ALLERGEN_CLASSES)
    unique_or_fail("zones", "zone_code", zone_code)
    rec = store.base_record()
    rec.update({
        "zone_code": zone_code,
        "allergen_class": allergen_class,
        "status": "OPEN",
        "lockout_start_at": None,
        "lockout_end_at": None,
        "on_hand_lb": store.D("0.00"),
    })
    store.insert("zones", rec)
    return envelope.created(serialize.zone(rec))


@bp.get("/warehouse-zones/<zid>")
def read_zone(zid):
    authenticate(("WarehouseOperator", "QualityManager", "LogisticsPlanner", "PlatformAdmin"))
    return envelope.ok(serialize.zone(path_lookup("zones", zid)))


@bp.post("/warehouse-zones/<zid>/lockout")
def zone_lockout(zid):
    authenticate(("QualityManager",))
    body = v.body()
    clear = v.boolean(body, "clear", default=False)
    if clear:
        start = v.instant(body, "lockout_start_at", required=False)
        end = v.instant(body, "lockout_end_at", required=False)
    else:
        start = v.instant(body, "lockout_start_at", required=True)
        end = v.instant(body, "lockout_end_at", required=True)
    rec = path_lookup("zones", zid)
    if clear:
        rec["lockout_start_at"] = None
        rec["lockout_end_at"] = None
    else:
        rec["lockout_start_at"] = start
        rec["lockout_end_at"] = end
    domain.refresh_zone_status(rec)
    store.bump(rec)
    return envelope.ok(serialize.zone(rec))


# ------------------------------------------------------ index quotes ------
@bp.post("/index-quotes")
def create_quote():
    authenticate(("PricingController",))
    body = v.body()
    index_code = v.enum(body, "index_code", INDEX_CODES)
    effective_on = v.date(body, "effective_on")
    price = v.integer(body, "price_cents_per_lb", minimum=1)
    for q in store.all_of("quotes"):
        if q["index_code"] == index_code and q["effective_on"] == effective_on:
            fail("ERR_DUPLICATE_RESOURCE",
                 "A quote for %s effective %s already exists" % (index_code, store.iso(effective_on)))
    rec = store.base_record(with_version=False)
    rec.update({
        "index_code": index_code,
        "effective_on": effective_on,
        "price_cents_per_lb": price,
    })
    store.insert("quotes", rec)
    return envelope.created(serialize.quote(rec))


@bp.get("/index-quotes")
def list_quotes():
    authenticate(("PricingController", "AccountManager", "CustomerBuyer", "PlatformAdmin"))
    limit, offset = v.pagination()
    index_code = v.q_enum("index_code", INDEX_CODES)
    rows = [q for q in store.all_of("quotes")
            if index_code is None or q["index_code"] == index_code]
    rows.sort(key=lambda q: (q["created_at"], q["_seq"]))
    rows.sort(key=lambda q: q["effective_on"], reverse=True)
    data, total = v.page(rows, limit, offset, serialize.quote)
    return envelope.listing(data, limit, offset, total)
