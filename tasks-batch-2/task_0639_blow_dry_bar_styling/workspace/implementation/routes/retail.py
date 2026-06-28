"""Product, RetailSale, PackagePurchase routes (PRD §3.12, §3.13)."""

from flask import Blueprint, request

import errors
from common import (
    as_int, as_number, as_str, get_json_body, paginate, sort_by_created,
    stamp_new, touch,
)
from db import db
from errors import err
from lookup import (
    get_member, get_package_purchase, get_product, get_retail_sale, get_stylist,
)
from middleware import get_auth, require_role
from response import success_list, success_object
from serialize import public, public_list
from services.reconcile import (
    compute_retail_commission, reconcile_member, recompute_product_stock,
    recompute_stylist_earnings,
)

bp = Blueprint("retail", __name__)

ALL_ROLES = {"FrontDesk", "FinanceManager", "Stylist", "Member"}


# ===========================================================================
# Product
# ===========================================================================
@bp.post("/products")
def create_product():
    _, role = get_auth()
    require_role(role, {"FrontDesk", "FinanceManager"})
    body = get_json_body()
    sku = as_str(body, "sku")
    name = as_str(body, "name")
    unit_price = as_int(body, "unit_price_cents")
    initial_stock = as_int(body, "initial_stock")
    retail_commission_pct = as_number(body, "retail_commission_pct", required=False, default=0.10)
    if unit_price < 0:
        raise err(errors.ERR_INVALID_REQUEST, "unit_price_cents must be >= 0")
    if initial_stock < 0:
        raise err(errors.ERR_INVALID_REQUEST, "initial_stock must be >= 0")
    if retail_commission_pct < 0 or retail_commission_pct > 1:
        raise err(errors.ERR_INVALID_REQUEST, "retail_commission_pct must be between 0 and 1")
    for p in db.products.values():
        if p["sku"] == sku:
            raise err(errors.ERR_INVALID_REQUEST, "sku must be unique across products")
    product = stamp_new({
        "sku": sku,
        "name": name,
        "unit_price_cents": unit_price,
        "stock_qty": initial_stock,
        "retail_commission_pct": retail_commission_pct,
        "_initial_and_restock": initial_stock,
    })
    db.products[product["id"]] = product
    return success_object(public(product), 201)


@bp.get("/products")
def list_products():
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    items = sort_by_created(list(db.products.values()))
    page, limit, offset, total = paginate(items)
    return success_list(public_list(page), limit, offset, total, 200)


@bp.get("/products/<pid>")
def get_one_product(pid):
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    product = get_product(pid)
    return success_object(public(product), 200)


@bp.post("/products/<pid>/restock")
def restock(pid):
    _, role = get_auth()
    require_role(role, {"FrontDesk", "FinanceManager"})
    product = get_product(pid)
    body = get_json_body()
    quantity = as_int(body, "quantity")
    if quantity < 1:
        raise err(errors.ERR_INVALID_REQUEST, "quantity must be >= 1")
    product["_initial_and_restock"] += quantity
    recompute_product_stock(product)
    touch(product)
    return success_object(public(product), 200)


# ===========================================================================
# RetailSale
# ===========================================================================
@bp.post("/retail-sales")
def create_retail_sale():
    _, role = get_auth()
    require_role(role, {"FrontDesk"})
    body = get_json_body()
    product_id = body.get("product_id")
    member_id = body.get("member_id")
    if product_id is None:
        raise err(errors.ERR_INVALID_REQUEST, "Missing required field: product_id")
    if member_id is None:
        raise err(errors.ERR_INVALID_REQUEST, "Missing required field: member_id")
    # existence left-to-right: product, member, attributed_stylist
    product = get_product(product_id)
    member = get_member(member_id)
    attributed_stylist_id = body.get("attributed_stylist_id")
    stylist = None
    if attributed_stylist_id is not None:
        stylist = get_stylist(attributed_stylist_id)
    quantity = as_int(body, "quantity")
    if quantity < 1:
        raise err(errors.ERR_INVALID_REQUEST, "quantity must be >= 1")
    # stock sufficiency
    if quantity > product["stock_qty"]:
        raise err(errors.ERR_INSUFFICIENT_STOCK, "Insufficient stock")
    gross = product["unit_price_cents"] * quantity
    commission = compute_retail_commission(gross, attributed_stylist_id, product)
    sale = stamp_new({
        "product_id": product_id,
        "member_id": member_id,
        "attributed_stylist_id": attributed_stylist_id,
        "quantity": quantity,
        "gross_cents": gross,
        "retail_commission_cents": commission,
        "status": "SOLD",
    })
    db.retail_sales[sale["id"]] = sale
    recompute_product_stock(product)
    touch(product)
    if stylist is not None:
        recompute_stylist_earnings(stylist)
        touch(stylist)
    return success_object(public(sale), 201)


@bp.get("/retail-sales")
def list_retail_sales():
    _, role = get_auth()
    require_role(role, {"FrontDesk", "FinanceManager", "Stylist"})
    items = list(db.retail_sales.values())
    for key in ("product_id", "member_id", "attributed_stylist_id"):
        val = request.args.get(key)
        if val is not None:
            items = [s for s in items if s.get(key) == val]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return success_list(public_list(page), limit, offset, total, 200)


@bp.get("/retail-sales/<sid>")
def get_one_retail_sale(sid):
    _, role = get_auth()
    require_role(role, {"FrontDesk", "FinanceManager", "Stylist"})
    sale = get_retail_sale(sid)
    return success_object(public(sale), 200)


@bp.post("/retail-sales/<sid>/void")
def void_sale(sid):
    _, role = get_auth()
    require_role(role, {"FrontDesk"})
    sale = get_retail_sale(sid)
    if sale["status"] != "SOLD":
        raise err(errors.ERR_SALE_NOT_VOIDABLE, "Sale is not voidable")
    sale["status"] = "VOIDED"
    touch(sale)
    product = db.products[sale["product_id"]]
    recompute_product_stock(product)
    touch(product)
    if sale.get("attributed_stylist_id") is not None:
        stylist = db.stylists.get(sale["attributed_stylist_id"])
        if stylist is not None:
            recompute_stylist_earnings(stylist)
            touch(stylist)
    return success_object(public(sale), 200)


# ===========================================================================
# PackagePurchase
# ===========================================================================
@bp.post("/package-purchases")
def create_package_purchase():
    _, role = get_auth()
    require_role(role, {"FrontDesk", "FinanceManager"})
    body = get_json_body()
    member_id = body.get("member_id")
    if member_id is None:
        raise err(errors.ERR_INVALID_REQUEST, "Missing required field: member_id")
    member = get_member(member_id)
    credits_purchased = as_int(body, "credits_purchased")
    price_cents = as_int(body, "price_cents")
    expected_version = as_int(body, "expected_member_version")
    if credits_purchased < 1:
        raise err(errors.ERR_INVALID_REQUEST, "credits_purchased must be >= 1")
    if price_cents < 0:
        raise err(errors.ERR_INVALID_REQUEST, "price_cents must be >= 0")
    # OCC on member version
    if expected_version != member["version"]:
        raise err(errors.ERR_STALE_VERSION, "expected_member_version does not match current version")
    pkg = stamp_new({
        "member_id": member_id,
        "credits_purchased": credits_purchased,
        "price_cents": price_cents,
        "status": "ACTIVE",
    })
    db.package_purchases[pkg["id"]] = pkg
    reconcile_member(member)  # raises blowout_credit_balance by credits_purchased
    touch(member)
    return success_object(public(pkg), 201)


@bp.get("/package-purchases")
def list_package_purchases():
    user_id, role = get_auth()
    require_role(role, {"FrontDesk", "FinanceManager", "Member"})
    items = list(db.package_purchases.values())
    member_id = request.args.get("member_id")
    if member_id is not None:
        items = [p for p in items if p["member_id"] == member_id]
    if role == "Member":
        items = [p for p in items if p["member_id"] == user_id]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return success_list(public_list(page), limit, offset, total, 200)


@bp.get("/package-purchases/<pid>")
def get_one_package_purchase(pid):
    user_id, role = get_auth()
    require_role(role, {"FrontDesk", "FinanceManager", "Member"})
    pkg = get_package_purchase(pid)
    if role == "Member" and user_id != pkg["member_id"]:
        raise err(errors.ERR_NOT_OWNER, "Member may only read their own package purchases")
    return success_object(public(pkg), 200)


@bp.post("/package-purchases/<pid>/refund")
def refund_package(pid):
    _, role = get_auth()
    require_role(role, {"FinanceManager"})
    pkg = get_package_purchase(pid)
    body = get_json_body()
    expected_version = as_int(body, "expected_member_version")
    member = db.members[pkg["member_id"]]
    if pkg["status"] != "ACTIVE":
        raise err(errors.ERR_PACKAGE_NOT_REFUNDABLE, "Package is not refundable")
    if member["blowout_credit_balance"] < pkg["credits_purchased"]:
        raise err(errors.ERR_CREDITS_ALREADY_USED, "Purchased credits already used")
    if expected_version != member["version"]:
        raise err(errors.ERR_STALE_VERSION, "expected_member_version does not match current version")
    pkg["status"] = "REFUNDED"
    touch(pkg)
    reconcile_member(member)  # drops package credits, credits prepay by price_cents
    touch(member)
    return success_object(public(pkg), 200)
