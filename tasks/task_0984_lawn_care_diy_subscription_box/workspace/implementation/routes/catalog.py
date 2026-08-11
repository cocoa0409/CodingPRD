from flask import Blueprint, request

from db import store, now, next_seq, new_id, Rec
from errors import raise_err, ERR_SKU_TAKEN, ERR_PRODUCT_NOT_FOUND, ERR_INVALID_REQUEST
from middleware import get_body, authenticate, paginate, sort_items
from response import ok, ok_list
from serializers import ser_product
from services import CATEGORIES, find_product_by_sku
from util import req_str, req_int, req_enum, opt_int, opt_bool, check_md

bp = Blueprint("catalog", __name__)

READ_ROLES = ["Customer", "Agronomist", "FulfillmentOps", "PlatformAdmin"]


@bp.route("/api/catalog/products", methods=["POST"])
def create_product():
    body = get_body()
    sku = req_str(body, "sku")
    name = req_str(body, "name")
    category = req_enum(body, "category", CATEGORIES)
    list_price_cents = req_int(body, "list_price_cents")
    tier_t1_cents = req_int(body, "tier_t1_cents")
    tier_t2_cents = req_int(body, "tier_t2_cents")
    tier_t3_cents = req_int(body, "tier_t3_cents")
    window_start_md = check_md(body.get("window_start_md"), "window_start_md")
    window_end_md = check_md(body.get("window_end_md"), "window_end_md")
    add_on_flat_price_cents = opt_int(body, "add_on_flat_price_cents")
    min_gap_days = opt_int(body, "min_gap_days")
    if min_gap_days is None:
        min_gap_days = 14
    active = opt_bool(body, "active")
    if active is None:
        active = True
    conflicting_categories = body.get("conflicting_categories")
    if conflicting_categories is None:
        conflicting_categories = []
    if not isinstance(conflicting_categories, list) or any(
        c not in CATEGORIES for c in conflicting_categories
    ):
        raise_err(ERR_INVALID_REQUEST, "Field 'conflicting_categories' must be an array of category names")

    authenticate(["PlatformAdmin"])

    if find_product_by_sku(sku) is not None:
        raise_err(ERR_SKU_TAKEN, "Catalog sku '%s' already exists" % sku)

    ts = now()
    rec = Rec(
        id=new_id(), created_at=ts, updated_at=ts, version=1, seq=next_seq(),
        sku=sku, name=name, category=category,
        list_price_cents=list_price_cents,
        tier_t1_cents=tier_t1_cents, tier_t2_cents=tier_t2_cents, tier_t3_cents=tier_t3_cents,
        add_on_flat_price_cents=add_on_flat_price_cents,
        window_start_md=window_start_md, window_end_md=window_end_md,
        conflicting_categories=conflicting_categories,
        min_gap_days=min_gap_days, active=active,
    )
    from util import fmt_dt3
    rec.raw["created_at"] = fmt_dt3(ts)
    rec.raw["updated_at"] = fmt_dt3(ts)
    store.products[rec.id] = rec
    return ok(ser_product(rec), 201)


@bp.route("/api/catalog/products/<pid>", methods=["GET"])
def get_product(pid):
    authenticate(READ_ROLES)
    rec = store.products.get(pid)
    if rec is None:
        raise_err(ERR_PRODUCT_NOT_FOUND, "Catalog product not found")
    return ok(ser_product(rec))


@bp.route("/api/catalog/products", methods=["GET"])
def list_products():
    authenticate(READ_ROLES)
    items = list(store.products.values())
    category = request.args.get("category")
    if category is not None:
        items = [p for p in items if p.category == category]
    active = request.args.get("active")
    if active is not None:
        want = active.strip().lower() == "true"
        items = [p for p in items if p.active == want]
    items = sort_items(items)
    page, total, limit, offset = paginate(items)
    return ok_list([ser_product(p) for p in page], total, limit, offset)
