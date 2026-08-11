"""SupplyOrder endpoints (PRD §3.8)."""
from flask import Blueprint, request

from db import new_id, now, serialize, stamp_new, store, touch
from errors import fail
from middleware import ALL_ROLES, authenticate, body, require_owner, require_role
from response import list_response, ok
from services.pricing import CREDIT_LIMIT_CENTS, supply_order_totals
from util import is_int, req_str

bp = Blueprint("orders", __name__)

CUSTOMER_OR_ADMIN = {"Customer", "PlatformAdmin"}


def get_order(oid):
    o = store.orders.get(oid)
    if o is None:
        fail("ERR_ORDER_NOT_FOUND", f"Supply order {oid} does not exist")
    return o


@bp.route("/coopcare/supply-orders", methods=["POST"])
def create_order():
    uid, role = authenticate()
    require_role(role, CUSTOMER_OR_ADMIN)
    data = body()
    household_id = data.get("household_id")
    require_owner(uid, role, household_id if isinstance(household_id, str) else None)
    if not isinstance(household_id, str) or not household_id.strip():
        fail("ERR_INVALID_REQUEST", "household_id is required")
    if household_id not in store.households:
        fail("ERR_HOUSEHOLD_NOT_FOUND", f"Household {household_id} does not exist")
    fulfillment_visit_id = data.get("fulfillment_visit_id")
    if fulfillment_visit_id is not None:
        if not isinstance(fulfillment_visit_id, str) or not fulfillment_visit_id.strip():
            fail("ERR_INVALID_REQUEST", "fulfillment_visit_id must be a string")
        if fulfillment_visit_id not in store.visits:
            fail("ERR_VISIT_NOT_FOUND", f"Service visit {fulfillment_visit_id} does not exist")
    rec = stamp_new({
        "id": new_id(),
        "household_id": household_id,
        "fulfillment_visit_id": fulfillment_visit_id,
        "status": "DRAFT",
        "lines": [],
        "subtotal_cents": 0,
        "discount_cents": 0,
        "total_cents": 0,
        "placed_at": None,
        "billed_invoice_id": None,
    })
    store.orders[rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.route("/coopcare/supply-orders", methods=["GET"])
def list_orders():
    uid, role = authenticate()
    require_role(role, set(ALL_ROLES))
    filters = []
    for key in ("household_id", "fulfillment_visit_id", "status"):
        v = request.args.get(key)
        if v is not None:
            filters.append((key, v))
    return list_response(store.orders.values(), filters)


@bp.route("/coopcare/supply-orders/<oid>", methods=["GET"])
def read_order(oid):
    uid, role = authenticate()
    require_role(role, set(ALL_ROLES))
    return ok(serialize(get_order(oid)), 200)


@bp.route("/coopcare/supply-orders/<oid>/lines", methods=["POST"])
def add_line(oid):
    uid, role = authenticate()
    require_role(role, CUSTOMER_OR_ADMIN)
    o = get_order(oid)
    require_owner(uid, role, o["household_id"])
    data = body()
    product_sku = data.get("product_sku")
    if not isinstance(product_sku, str) or not product_sku.strip():
        fail("ERR_INVALID_REQUEST", "product_sku is required")
    product = None
    for p in store.products.values():
        if p["sku"] == product_sku:
            product = p
            break
    if product is None:
        fail("ERR_PRODUCT_NOT_FOUND", f"Product {product_sku} does not exist")
    quantity = data.get("quantity")
    if not is_int(quantity):
        fail("ERR_INVALID_REQUEST", "quantity is required and must be an integer")
    if quantity <= 0:
        fail("ERR_INVALID_TIME_RANGE", "quantity must be positive")
    if o["status"] != "DRAFT":
        fail("ERR_ORDER_NOT_DRAFT", "lines can only be added to a DRAFT order")
    if not product["active"]:
        fail("ERR_INVALID_REQUEST", "inactive products cannot be added to orders")
    line = {
        "product_sku": product_sku,
        "quantity": quantity,
        "unit_price_cents": product["unit_price_cents"],  # snapshot at add time
        "line_total_cents": product["unit_price_cents"] * quantity,  # integer cents, no rounding
    }
    o["lines"].append(line)
    o["subtotal_cents"] = sum(l["line_total_cents"] for l in o["lines"])
    touch(o)
    return ok(serialize(o), 200)


@bp.route("/coopcare/supply-orders/<oid>/place", methods=["POST"])
def place_order(oid):
    uid, role = authenticate()
    require_role(role, CUSTOMER_OR_ADMIN)
    o = get_order(oid)
    require_owner(uid, role, o["household_id"])
    if o["status"] != "DRAFT":
        fail("ERR_ORDER_NOT_DRAFT", "place requires order status DRAFT")
    h = store.households[o["household_id"]]
    if h["status"] != "ACTIVE":
        fail("ERR_ACCOUNT_SUSPENDED", "order placement requires household status ACTIVE")
    # Referential fit (priority 8) precedes the empty-order constraint (priority 11).
    if o["fulfillment_visit_id"] is not None:
        v = store.visits.get(o["fulfillment_visit_id"])
        if v is None or v["household_id"] != o["household_id"] or v["status"] != "SCHEDULED":
            fail("ERR_FULFILLMENT_VISIT_INVALID", "fulfillment visit must belong to the household and be SCHEDULED")
    if not o["lines"]:
        fail("ERR_ORDER_EMPTY", "cannot place an order with zero lines")
    subtotal, discount, total = supply_order_totals(o, h)
    # Money gate runs last of all.
    if total > h["wallet_credit_cents"] + CREDIT_LIMIT_CENTS:
        fail("ERR_CREDIT_LIMIT_EXCEEDED", "order total exceeds wallet credit plus the credit limit")
    o["subtotal_cents"] = subtotal
    o["discount_cents"] = discount
    o["total_cents"] = total
    o["placed_at"] = now()
    o["status"] = "PLACED"
    touch(o)
    return ok(serialize(o), 200)
