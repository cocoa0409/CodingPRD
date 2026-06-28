"""Product and RetailOrder endpoints (PRD §3.10).

retail_order_total (scaffold):
  subtotal = quantity * unit_price_cents
  discount_pct by quantity tier (whole-order, average-rate)
  discounted = subtotal - round_half_up(subtotal * discount_pct)
  wallet split if pay_from_wallet.
"""
from decimal import Decimal

from flask import Blueprint, request

from constants import (
    ROLE_STUDIO_MANAGER, ROLE_MEMBER, ROLE_INSTRUCTOR,
    TIER1_MIN_QTY, TIER1_PCT, TIER2_MIN_QTY, TIER2_PCT,
)
from db import db, stamp_new, touch
from errors import (
    err, ERR_VALIDATION, ERR_INVALID_STATE, ERR_OWNERSHIP_VIOLATION,
    ERR_PRODUCT_DISCONTINUED, ERR_INSUFFICIENT_STOCK,
)
from middleware import require_auth, require_role
from response import success_object, success_array
from serializers import product_out, retail_order_out
from services import lookup, validate, paging
from util import round_half_up

bp = Blueprint("retail", __name__)

READ_ROLES_PI = {ROLE_STUDIO_MANAGER, ROLE_MEMBER, ROLE_INSTRUCTOR}
READ_ROLES_ORDER = {ROLE_STUDIO_MANAGER, ROLE_MEMBER}


# ---- Product ----
@bp.route("/studios/<studio_id>/products", methods=["POST"])
def create_product(studio_id):
    _, role = require_auth()
    require_role(role, {ROLE_STUDIO_MANAGER})
    lookup.get_studio(studio_id)
    body = validate.get_body()
    sku = validate.require_str(body, "sku")
    name = validate.require_str(body, "name")
    unit_price_cents = validate.require_int(body, "unit_price_cents", minimum=0)
    stock_qty = validate.require_int(body, "stock_qty", minimum=0)
    rec = {
        "studio_id": studio_id,
        "sku": sku,
        "name": name,
        "unit_price_cents": unit_price_cents,
        "stock_qty": stock_qty,
        "status": "AVAILABLE",
    }
    stamp_new(rec)
    db.products[rec["id"]] = rec
    return success_object(product_out(rec), 201)


@bp.route("/products/<product_id>", methods=["GET"])
def get_product(product_id):
    _, role = require_auth()
    require_role(role, READ_ROLES_PI)
    rec = lookup.get_product(product_id)
    return success_object(product_out(rec), 200)


@bp.route("/products", methods=["GET"])
def list_products():
    _, role = require_auth()
    require_role(role, READ_ROLES_PI)
    limit, offset = paging.get_pagination()
    studio_id = request.args.get("studio_id")
    records = [
        p for p in db.products.values()
        if studio_id is None or p["studio_id"] == studio_id
    ]
    records = paging.sort_default(records)
    page, total = paging.apply_page(records, limit, offset)
    return success_array([product_out(p) for p in page], limit, offset, total)


@bp.route("/studios/<studio_id>/products/<product_id>/discontinue", methods=["POST"])
def discontinue_product(studio_id, product_id):
    _, role = require_auth()
    require_role(role, {ROLE_STUDIO_MANAGER})
    rec = lookup.get_product_in_studio(studio_id, product_id)
    if rec["status"] != "AVAILABLE":
        raise err(ERR_INVALID_STATE, "Product is not AVAILABLE")
    rec["status"] = "DISCONTINUED"
    touch(rec)
    return success_object(product_out(rec), 200)


# ---- RetailOrder ----
def _discount_pct(quantity):
    if quantity >= TIER2_MIN_QTY:
        return Decimal(str(TIER2_PCT))
    if quantity >= TIER1_MIN_QTY:
        return Decimal(str(TIER1_PCT))
    return Decimal("0")


@bp.route("/retail-orders", methods=["POST"])
def create_order():
    user_id, role = require_auth()
    require_role(role, {ROLE_MEMBER})
    body = validate.get_body()
    member_id = validate.require_str(body, "member_id")
    studio_id = validate.require_str(body, "studio_id")
    product_id = validate.require_str(body, "product_id")
    quantity = validate.require_int(body, "quantity", minimum=1)
    pay_from_wallet = validate.opt_bool(body, "pay_from_wallet", False)

    member = lookup.get_member(member_id)
    if user_id != member_id:
        raise err(ERR_OWNERSHIP_VIOLATION, "Members may only order for themselves")
    # product must belong to the named studio (existence + scope)
    product = lookup.get_product_in_studio(studio_id, product_id)

    # product available
    if product["status"] != "AVAILABLE":
        raise err(ERR_PRODUCT_DISCONTINUED, "Product is discontinued")
    # stock
    if quantity > product["stock_qty"]:
        raise err(ERR_INSUFFICIENT_STOCK, "Requested quantity exceeds stock")

    subtotal_cents = quantity * product["unit_price_cents"]
    discount_pct = _discount_pct(quantity)
    discount = round_half_up(Decimal(subtotal_cents) * discount_pct)
    discounted_cents = subtotal_cents - discount

    wallet_applied = 0
    if pay_from_wallet:
        wallet_applied = min(member["wallet_credit_cents"], discounted_cents)
    card_charged = discounted_cents - wallet_applied

    # commit: decrement stock, draw wallet
    product["stock_qty"] -= quantity
    touch(product)
    if wallet_applied:
        member["wallet_credit_cents"] -= wallet_applied
        touch(member)

    rec = {
        "member_id": member_id,
        "studio_id": studio_id,
        "product_id": product_id,
        "quantity": quantity,
        "pay_from_wallet": pay_from_wallet,
        "subtotal_cents": subtotal_cents,
        "wallet_applied_cents": wallet_applied,
        "card_charged_cents": card_charged,
        "status": "PLACED",
    }
    stamp_new(rec)
    db.retail_orders[rec["id"]] = rec
    return success_object(retail_order_out(rec), 201)


@bp.route("/retail-orders/<order_id>", methods=["GET"])
def get_order(order_id):
    user_id, role = require_auth()
    require_role(role, READ_ROLES_ORDER)
    rec = lookup.get_retail_order(order_id)
    if role == ROLE_MEMBER and user_id != rec["member_id"]:
        raise err(ERR_OWNERSHIP_VIOLATION, "Members may only read their own orders")
    return success_object(retail_order_out(rec), 200)


@bp.route("/retail-orders", methods=["GET"])
def list_orders():
    user_id, role = require_auth()
    require_role(role, READ_ROLES_ORDER)
    limit, offset = paging.get_pagination()
    f_member = request.args.get("member_id")
    f_studio = request.args.get("studio_id")
    f_product = request.args.get("product_id")
    records = []
    for o in db.retail_orders.values():
        if f_member is not None and o["member_id"] != f_member:
            continue
        if f_studio is not None and o["studio_id"] != f_studio:
            continue
        if f_product is not None and o["product_id"] != f_product:
            continue
        if role == ROLE_MEMBER and o["member_id"] != user_id:
            continue
        records.append(o)
    records = paging.sort_default(records)
    page, total = paging.apply_page(records, limit, offset)
    return success_array([retail_order_out(o) for o in page], limit, offset, total)
