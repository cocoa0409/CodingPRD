"""Chocolate & Confectionery Shop API — Flask implementation.

Every endpoint / field / side effect traces to a PRD sentence. Storage is
in-memory only and starts empty on every boot (no seeding).
"""
import os
from datetime import datetime
from decimal import Decimal
from functools import wraps

from flask import Flask, request, jsonify, g

from db import (
    db, now_real, fmt_dt, parse_dt, add_days, add_minutes,
    round_half_up, D, make_common, make_common_immutable, touch, request_id,
)
from errors import ApiError

app = Flask(__name__)

ROLES = {"Customer", "SalesManager", "ProductionManager", "Admin"}
READ_ROLES = ["Customer", "SalesManager", "ProductionManager", "Admin"]

TAX_RATE = D("0.0725")
GIFT_WRAP_FEE_CENTS = 500
MOLD_SURCHARGE_PER_UNIT_CENTS = 300
MOLD_SETUP_FEE_CENTS = 25000

PAGE_DEFAULT = 10
PAGE_MIN = 1
PAGE_MAX = 100


# ==========================================================================
# Serialization + response envelope (PRD §2.2)
# ==========================================================================
def serialize(entity):
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = fmt_dt(v)
        elif isinstance(v, Decimal):
            out[k] = float(v)
        else:
            out[k] = v
    return out


def meta_base():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_dt(now_real()),
    }


def ok_object(data, status=200):
    body = {"meta": meta_base(), "response_type": "object", "data": data or {}}
    return jsonify(body), status


def ok_entity(entity, status=200):
    return ok_object(serialize(entity), status)


def ok_list(items, limit, offset, total_count):
    meta = meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serialize(e) for e in items],
    }
    return jsonify(body), 200


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"},
    }
    return jsonify(body), 404


# ==========================================================================
# Auth (PRD §2.1) — validations priority 1 (auth) & 2 (authz)
# ==========================================================================
def require_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or invalid auth headers")
    return uid, role


def endpoint(allowed_roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid, role = require_auth()
            if role not in allowed_roles:
                raise ApiError("ERR_UNAUTHORIZED", "Role not permitted for this operation")
            g.uid = uid
            g.role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco


# ==========================================================================
# Body / validation helpers
# ==========================================================================
def get_body():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return {}
    return body


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_number(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def require_fields(body, keys):
    """priority 3 — ERR_VALIDATION for missing required fields."""
    for k in keys:
        if body.get(k) is None:
            raise ApiError("ERR_VALIDATION", f"Missing required field: {k}")


def require_enum(value, allowed, field):
    if value not in allowed:
        raise ApiError("ERR_VALIDATION", f"Invalid value for {field}")


def parse_dt_field(value, field):
    try:
        return parse_dt(value)
    except Exception:
        raise ApiError("ERR_VALIDATION", f"Invalid datetime for {field}")


def positive_qty(value):
    """priority 15 — ERR_INVALID_QUANTITY: must be a positive integer > 0."""
    if not is_int(value) or value <= 0:
        raise ApiError("ERR_INVALID_QUANTITY", "Quantity/units must be a positive integer")


# ---- existence helpers (priority 4) ----
def find_customer(cid):
    e = db.customers.get(cid)
    if e is None:
        raise ApiError("ERR_CUSTOMER_NOT_FOUND", "Customer not found")
    return e


def find_product(pid):
    e = db.products.get(pid)
    if e is None:
        raise ApiError("ERR_PRODUCT_NOT_FOUND", "Product not found")
    return e


def find_batch(bid):
    e = db.batches.get(bid)
    if e is None:
        raise ApiError("ERR_BATCH_NOT_FOUND", "Batch not found")
    return e


def find_order(oid):
    e = db.orders.get(oid)
    if e is None:
        raise ApiError("ERR_ORDER_NOT_FOUND", "Order not found")
    return e


def find_order_line(lid):
    e = db.order_lines.get(lid)
    if e is None:
        raise ApiError("ERR_ORDER_LINE_NOT_FOUND", "Order line not found")
    return e


def find_mold(mid):
    e = db.molds.get(mid)
    if e is None:
        raise ApiError("ERR_MOLD_NOT_FOUND", "Mold not found")
    return e


def find_custom_order(coid):
    e = db.custom_orders.get(coid)
    if e is None:
        raise ApiError("ERR_CUSTOM_ORDER_NOT_FOUND", "Custom order not found")
    return e


def find_subscription(sid):
    e = db.subscriptions.get(sid)
    if e is None:
        raise ApiError("ERR_SUBSCRIPTION_NOT_FOUND", "Subscription not found")
    return e


def find_shipment(shid):
    e = db.subscription_shipments.get(shid)
    if e is None:
        raise ApiError("ERR_SHIPMENT_NOT_FOUND", "Shipment not found")
    return e


def find_tempering_line(tid):
    e = db.tempering_lines.get(tid)
    if e is None:
        raise ApiError("ERR_TEMPERING_LINE_NOT_FOUND", "Tempering line not found")
    return e


def find_reservation(rid):
    e = db.reservations.get(rid)
    if e is None:
        raise ApiError("ERR_RESERVATION_NOT_FOUND", "Reservation not found")
    return e


def find_bundle_component(bcid):
    e = db.bundle_components.get(bcid)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", "Bundle component not found")
    return e


def check_ownership(resource):
    """priority 5 — Customer may only act on their own resource."""
    if g.role == "Customer" and resource.get("customer_id") != g.uid:
        raise ApiError("ERR_OWNERSHIP_FORBIDDEN", "Customer does not own this resource")


# ---- pagination + listing (PRD §2.3) ----
def pagination():
    args = request.args
    limit = args.get("limit")
    offset = args.get("offset")
    try:
        limit = int(limit) if limit is not None else PAGE_DEFAULT
    except (TypeError, ValueError):
        limit = PAGE_DEFAULT
    try:
        offset = int(offset) if offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    if limit < PAGE_MIN:
        limit = PAGE_MIN
    if limit > PAGE_MAX:
        limit = PAGE_MAX
    if offset < 0:
        offset = 0
    return limit, offset


def list_response(collection, filters=None):
    """Sort by created_at ASC (insertion _seq), filter, paginate."""
    items = list(collection.values())
    if filters:
        for key, val in filters.items():
            if val is None:
                continue
            items = [e for e in items if _match(e, key, val)]
    items.sort(key=lambda e: e["_seq"])
    total = len(items)
    limit, offset = pagination()
    page = items[offset:offset + limit]
    return ok_list(page, limit, offset, total)


def _match(entity, key, val):
    ev = entity.get(key)
    if isinstance(ev, datetime):
        # date-bucket match for usage_date style fields
        try:
            return ev.date() == parse_dt(val).date()
        except Exception:
            return False
    return str(ev) == str(val)


# ==========================================================================
# Allergen / expiry / inventory helpers
# ==========================================================================
def clock():
    return db.clock


def batch_expired(batch):
    return clock() >= batch["lot_expiry"]


def order_lines_of(order_id):
    lines = [l for l in db.order_lines.values() if l["order_id"] == order_id]
    lines.sort(key=lambda l: l["_seq"])
    return lines


def active_reservations_for_batch(batch_id):
    return [r for r in db.reservations.values()
            if r["batch_id"] == batch_id and r["status"] == "ACTIVE"]


def recompute_released_available(batch):
    used = sum(r["units"] for r in active_reservations_for_batch(batch["id"]))
    batch["available_units"] = batch["initial_units"] - used


def allergen_conflict(customer, product):
    restricted = set(customer.get("allergen_restrictions") or [])
    return bool(restricted.intersection(set(product.get("allergens") or [])))


def order_has_allergen_conflict(order):
    customer = db.customers.get(order["customer_id"])
    if customer is None:
        return False
    for line in order_lines_of(order["id"]):
        product = db.products.get(line["product_id"])
        if product and allergen_conflict(customer, product):
            return True
    return False


# ==========================================================================
# Products & bundles (PRD §3.1)
# ==========================================================================
@app.route("/products", methods=["POST"])
@endpoint(["Admin"])
def create_product():
    body = get_body()
    require_fields(body, ["sku", "name", "product_type", "base_price_cents",
                          "shelf_life_days", "unit_weight_g"])
    require_enum(body["product_type"], {"SINGLE", "BUNDLE"}, "product_type")
    if "status" in body and body["status"] is not None:
        require_enum(body["status"], {"ACTIVE", "DISCONTINUED"}, "status")
    if not is_int(body["base_price_cents"]) or body["base_price_cents"] <= 0:
        raise ApiError("ERR_VALIDATION", "base_price_cents must be > 0")
    if not is_int(body["shelf_life_days"]) or body["shelf_life_days"] <= 0:
        raise ApiError("ERR_VALIDATION", "shelf_life_days must be > 0")
    if not is_number(body["unit_weight_g"]):
        raise ApiError("ERR_VALIDATION", "unit_weight_g must be a number")
    requires_tempering = bool(body.get("requires_tempering", False))
    tempering_minutes = body.get("tempering_minutes", 0) or 0
    if not is_int(tempering_minutes) or tempering_minutes < 0:
        raise ApiError("ERR_VALIDATION", "tempering_minutes invalid")
    if requires_tempering and tempering_minutes <= 0:
        raise ApiError("ERR_VALIDATION", "tempering_minutes must be > 0 when requires_tempering")

    e = make_common()
    e.update({
        "sku": body["sku"],
        "name": body["name"],
        "product_type": body["product_type"],
        "base_price_cents": body["base_price_cents"],
        "shelf_life_days": body["shelf_life_days"],
        "requires_tempering": requires_tempering,
        "tempering_minutes": tempering_minutes,
        "unit_weight_g": body["unit_weight_g"],
        "allergens": list(body.get("allergens") or []),
        "status": body.get("status") or "ACTIVE",
    })
    db.products[e["id"]] = e
    return ok_entity(e, 201)


@app.route("/products/<pid>", methods=["GET"])
@endpoint(READ_ROLES)
def get_product(pid):
    return ok_entity(find_product(pid))


@app.route("/products", methods=["GET"])
@endpoint(READ_ROLES)
def list_products():
    return list_response(db.products, {
        "product_type": request.args.get("product_type"),
        "status": request.args.get("status"),
    })


@app.route("/products/<pid>", methods=["PATCH"])
@endpoint(["Admin"])
def update_product(pid):
    e = find_product(pid)
    body = get_body()
    if "base_price_cents" in body and body["base_price_cents"] is not None:
        if not is_int(body["base_price_cents"]) or body["base_price_cents"] <= 0:
            raise ApiError("ERR_VALIDATION", "base_price_cents must be > 0")
        e["base_price_cents"] = body["base_price_cents"]
    if "status" in body and body["status"] is not None:
        require_enum(body["status"], {"ACTIVE", "DISCONTINUED"}, "status")
        e["status"] = body["status"]
    touch(e)
    return ok_entity(e)


@app.route("/products/<pid>/bundle-components", methods=["POST"])
@endpoint(["Admin"])
def add_bundle_component(pid):
    body = get_body()
    require_fields(body, ["component_product_id", "quantity"])
    bundle = find_product(pid)
    component = find_product(body["component_product_id"])
    # priority 16 — ERR_BUNDLE_COMPONENT_INVALID
    q = body["quantity"]
    if (bundle["product_type"] != "BUNDLE"
            or component["product_type"] != "SINGLE"
            or component["id"] == bundle["id"]
            or not is_int(q) or q <= 0):
        raise ApiError("ERR_BUNDLE_COMPONENT_INVALID", "Invalid bundle component")
    e = make_common_immutable()
    e.update({
        "bundle_product_id": bundle["id"],
        "component_product_id": component["id"],
        "quantity": q,
    })
    db.bundle_components[e["id"]] = e
    return ok_entity(e, 201)


@app.route("/bundle-components/<bcid>", methods=["GET"])
@endpoint(READ_ROLES)
def get_bundle_component(bcid):
    return ok_entity(find_bundle_component(bcid))


@app.route("/bundle-components", methods=["GET"])
@endpoint(READ_ROLES)
def list_bundle_components():
    return list_response(db.bundle_components, {
        "bundle_product_id": request.args.get("bundle_product_id"),
        "component_product_id": request.args.get("component_product_id"),
    })


# ==========================================================================
# Customers, accounts, wallet (PRD §3.2)
# ==========================================================================
@app.route("/customers", methods=["POST"])
@endpoint(["Admin"])
def create_customer():
    body = get_body()
    require_fields(body, ["name", "email", "account_type"])
    require_enum(body["account_type"], {"RETAIL", "WHOLESALE", "CORPORATE"}, "account_type")
    credit = body.get("credit_limit_cents", 0)
    if credit is None:
        credit = 0
    if not is_int(credit):
        raise ApiError("ERR_VALIDATION", "credit_limit_cents must be an integer")
    loyalty = body.get("loyalty_discount_pct", 0)
    if loyalty is None:
        loyalty = 0
    if not is_number(loyalty) or loyalty < 0 or loyalty > 0.5:
        raise ApiError("ERR_VALIDATION", "loyalty_discount_pct must be in 0..0.5")
    e = make_common()
    e.update({
        "name": body["name"],
        "email": body["email"],
        "account_type": body["account_type"],
        "credit_limit_cents": credit,
        "loyalty_discount_pct": loyalty,
        "allergen_restrictions": list(body.get("allergen_restrictions") or []),
        "wallet_credit_cents": 0,
    })
    db.customers[e["id"]] = e
    return ok_entity(e, 201)


@app.route("/customers/<cid>", methods=["GET"])
@endpoint(["Customer", "SalesManager", "Admin"])
def get_customer(cid):
    return ok_entity(find_customer(cid))


@app.route("/customers", methods=["GET"])
@endpoint(["Admin"])
def list_customers():
    return list_response(db.customers, {"account_type": request.args.get("account_type")})


@app.route("/customers/<cid>", methods=["PATCH"])
@endpoint(["Admin"])
def update_customer(cid):
    e = find_customer(cid)
    body = get_body()
    if "credit_limit_cents" in body and body["credit_limit_cents"] is not None:
        if not is_int(body["credit_limit_cents"]):
            raise ApiError("ERR_VALIDATION", "credit_limit_cents must be an integer")
        e["credit_limit_cents"] = body["credit_limit_cents"]
    if "loyalty_discount_pct" in body and body["loyalty_discount_pct"] is not None:
        lv = body["loyalty_discount_pct"]
        if not is_number(lv) or lv < 0 or lv > 0.5:
            raise ApiError("ERR_VALIDATION", "loyalty_discount_pct must be in 0..0.5")
        e["loyalty_discount_pct"] = lv
    if "allergen_restrictions" in body and body["allergen_restrictions"] is not None:
        e["allergen_restrictions"] = list(body["allergen_restrictions"])
    touch(e)
    return ok_entity(e)


@app.route("/customers/<cid>/wallet/adjust", methods=["POST"])
@endpoint(["Admin"])
def wallet_adjust(cid):
    e = find_customer(cid)
    body = get_body()
    require_fields(body, ["amount_cents"])
    if not is_int(body["amount_cents"]):
        raise ApiError("ERR_VALIDATION", "amount_cents must be an integer")
    e["wallet_credit_cents"] += body["amount_cents"]
    touch(e)
    return ok_entity(e)


# ==========================================================================
# Molds & tempering lines (PRD §3.1)
# ==========================================================================
@app.route("/molds", methods=["POST"])
@endpoint(["ProductionManager"])
def create_mold():
    body = get_body()
    require_fields(body, ["name", "cavity_count", "daily_capacity_units"])
    if not is_int(body["cavity_count"]) or body["cavity_count"] <= 0:
        raise ApiError("ERR_VALIDATION", "cavity_count must be > 0")
    if not is_int(body["daily_capacity_units"]) or body["daily_capacity_units"] <= 0:
        raise ApiError("ERR_VALIDATION", "daily_capacity_units must be > 0")
    e = make_common()
    e.update({
        "name": body["name"],
        "cavity_count": body["cavity_count"],
        "daily_capacity_units": body["daily_capacity_units"],
        "allergens": list(body.get("allergens") or []),
        "status": "ACTIVE",
    })
    db.molds[e["id"]] = e
    return ok_entity(e, 201)


@app.route("/molds/<mid>", methods=["GET"])
@endpoint(READ_ROLES)
def get_mold(mid):
    return ok_entity(find_mold(mid))


@app.route("/molds", methods=["GET"])
@endpoint(READ_ROLES)
def list_molds():
    return list_response(db.molds, {"status": request.args.get("status")})


@app.route("/molds/<mid>/set-status", methods=["POST"])
@endpoint(["ProductionManager"])
def set_mold_status(mid):
    e = find_mold(mid)
    body = get_body()
    require_fields(body, ["status"])
    require_enum(body["status"], {"ACTIVE", "MAINTENANCE", "RETIRED"}, "status")
    e["status"] = body["status"]
    touch(e)
    return ok_entity(e)


@app.route("/tempering-lines", methods=["POST"])
@endpoint(["ProductionManager"])
def create_tempering_line():
    body = get_body()
    require_fields(body, ["name"])
    e = make_common()
    e["name"] = body["name"]
    db.tempering_lines[e["id"]] = e
    return ok_entity(e, 201)


@app.route("/tempering-lines/<tid>", methods=["GET"])
@endpoint(READ_ROLES)
def get_tempering_line(tid):
    return ok_entity(find_tempering_line(tid))


@app.route("/tempering-lines", methods=["GET"])
@endpoint(READ_ROLES)
def list_tempering_lines():
    return list_response(db.tempering_lines, {})


@app.route("/mold-bookings/<mbid>", methods=["GET"])
@endpoint(READ_ROLES)
def get_mold_booking(mbid):
    e = db.mold_bookings.get(mbid)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", "Mold booking not found")
    return ok_entity(e)


@app.route("/mold-bookings", methods=["GET"])
@endpoint(READ_ROLES)
def list_mold_bookings():
    return list_response(db.mold_bookings, {
        "mold_id": request.args.get("mold_id"),
        "custom_order_id": request.args.get("custom_order_id"),
        "usage_date": request.args.get("usage_date"),
        "status": request.args.get("status"),
    })


# ==========================================================================
# Batches — production lots (PRD §3.3, §3.4)
# ==========================================================================
@app.route("/batches", methods=["POST"])
@endpoint(["ProductionManager"])
def create_batch():
    body = get_body()
    require_fields(body, ["product_id", "initial_units"])
    product = find_product(body["product_id"])
    mold = None
    if body.get("mold_id") is not None:
        mold = find_mold(body["mold_id"])
    positive_qty(body["initial_units"])  # ERR_INVALID_QUANTITY
    if body.get("produced_at") is not None:
        produced_at = parse_dt_field(body["produced_at"], "produced_at")
    else:
        produced_at = clock()
    lot_expiry = add_days(produced_at, product["shelf_life_days"])
    e = make_common()
    e.update({
        "product_id": product["id"],
        "mold_id": mold["id"] if mold else None,
        "tempering_line_id": None,
        "initial_units": body["initial_units"],
        "available_units": 0,
        "produced_at": produced_at,
        "lot_expiry": lot_expiry,
        "temper_start": None,
        "temper_end": None,
        "reseed_count": 0,
        "status": "RAW",
    })
    db.batches[e["id"]] = e
    return ok_entity(e, 201)


@app.route("/batches/<bid>", methods=["GET"])
@endpoint(READ_ROLES)
def get_batch(bid):
    return ok_entity(find_batch(bid))


@app.route("/batches", methods=["GET"])
@endpoint(READ_ROLES)
def list_batches():
    return list_response(db.batches, {
        "product_id": request.args.get("product_id"),
        "mold_id": request.args.get("mold_id"),
        "tempering_line_id": request.args.get("tempering_line_id"),
        "status": request.args.get("status"),
    })


@app.route("/batches/<bid>/start-tempering", methods=["POST"])
@endpoint(["ProductionManager"])
def start_tempering(bid):
    body = get_body()
    require_fields(body, ["tempering_line_id", "temper_start"])
    batch = find_batch(bid)
    line = find_tempering_line(body["tempering_line_id"])
    product = db.products[batch["product_id"]]
    temper_start = parse_dt_field(body["temper_start"], "temper_start")
    # state (priority 7)
    if batch["status"] != "RAW":
        raise ApiError("ERR_INVALID_STATE", "Batch not in RAW state")
    if not product.get("requires_tempering"):
        raise ApiError("ERR_VALIDATION", "Product does not require tempering")
    temper_end = add_minutes(temper_start, product["tempering_minutes"])
    # tempering-line conflict (priority 9) — half-open [start, end)
    for other in db.batches.values():
        if other["id"] == batch["id"]:
            continue
        if other["status"] == "TEMPERING" and other["tempering_line_id"] == line["id"]:
            if temper_start < other["temper_end"] and other["temper_start"] < temper_end:
                raise ApiError("ERR_TEMPERING_LINE_CONFLICT", "Tempering line interval conflict")
    # batch expired (priority 13)
    if batch_expired(batch):
        raise ApiError("ERR_BATCH_EXPIRED", "Batch expired")
    batch["tempering_line_id"] = line["id"]
    batch["temper_start"] = temper_start
    batch["temper_end"] = temper_end
    batch["status"] = "TEMPERING"
    touch(batch)
    return ok_entity(batch)


@app.route("/batches/<bid>/complete-tempering", methods=["POST"])
@endpoint(["ProductionManager"])
def complete_tempering(bid):
    batch = find_batch(bid)
    if batch["status"] != "TEMPERING":
        raise ApiError("ERR_INVALID_STATE", "Batch not in TEMPERING state")
    if clock() < batch["temper_end"]:
        raise ApiError("ERR_INVALID_STATE", "Tempering not yet complete")
    batch["tempering_line_id"] = None
    batch["status"] = "TEMPERED"
    touch(batch)
    return ok_entity(batch)


@app.route("/batches/<bid>/reseed", methods=["POST"])
@endpoint(["ProductionManager"])
def reseed_batch(bid):
    batch = find_batch(bid)
    if batch["status"] != "TEMPERING":
        raise ApiError("ERR_INVALID_STATE", "Batch not in TEMPERING state")
    batch["reseed_count"] += 1
    batch["tempering_line_id"] = None
    batch["temper_start"] = None
    batch["temper_end"] = None
    batch["status"] = "RAW"
    touch(batch)
    return ok_entity(batch)


@app.route("/batches/<bid>/release", methods=["POST"])
@endpoint(["ProductionManager"])
def release_batch(bid):
    batch = find_batch(bid)
    product = db.products[batch["product_id"]]
    status = batch["status"]
    if status == "RAW":
        if product.get("requires_tempering"):
            raise ApiError("ERR_INVALID_STATE", "Product requires tempering before release")
    elif status == "TEMPERED":
        pass
    else:
        raise ApiError("ERR_INVALID_STATE", "Batch cannot be released from its current state")
    if batch_expired(batch):
        raise ApiError("ERR_BATCH_EXPIRED", "Batch expired")
    batch["status"] = "RELEASED"
    batch["available_units"] = batch["initial_units"]
    touch(batch)
    return ok_entity(batch)


@app.route("/batches/<bid>/quarantine", methods=["POST"])
@endpoint(["ProductionManager"])
def quarantine_batch(bid):
    batch = find_batch(bid)
    if batch["status"] != "RELEASED":
        raise ApiError("ERR_INVALID_STATE", "Only RELEASED batches can be quarantined")
    # Cascade — applied atomically (PRD §3.4)
    affected_orders = set()
    for r in active_reservations_for_batch(batch["id"]):
        r["status"] = "VOIDED"
        touch(r)
        line = db.order_lines.get(r["order_line_id"])
        if line is not None:
            line["allocated_units"] -= r["units"]
            touch(line)
            affected_orders.add(line["order_id"])
    for oid in affected_orders:
        order = db.orders.get(oid)
        if order is None or order["status"] != "ALLOCATED":
            continue
        if any(l["allocated_units"] < l["quantity"] for l in order_lines_of(oid)):
            order["status"] = "BACKORDERED"
            touch(order)
    batch["available_units"] = 0
    batch["status"] = "QUARANTINED"
    touch(batch)
    return ok_entity(batch)


@app.route("/batches/<bid>/clear-quarantine", methods=["POST"])
@endpoint(["ProductionManager"])
def clear_quarantine(bid):
    batch = find_batch(bid)
    if batch["status"] != "QUARANTINED":
        raise ApiError("ERR_INVALID_STATE", "Batch not in QUARANTINED state")
    if batch_expired(batch):
        raise ApiError("ERR_BATCH_EXPIRED", "Batch expired")
    batch["status"] = "RELEASED"
    recompute_released_available(batch)
    touch(batch)
    return ok_entity(batch)


@app.route("/batches/<bid>/discard", methods=["POST"])
@endpoint(["ProductionManager"])
def discard_batch(bid):
    batch = find_batch(bid)
    if batch["status"] != "QUARANTINED":
        raise ApiError("ERR_INVALID_STATE", "Batch not in QUARANTINED state")
    batch["available_units"] = 0
    batch["status"] = "DISCARDED"
    touch(batch)
    return ok_entity(batch)


@app.route("/batches/<bid>/reservations", methods=["POST"])
@endpoint(["SalesManager"])
def create_reservation(bid):
    body = get_body()
    require_fields(body, ["order_line_id", "units", "expected_batch_version"])
    batch = find_batch(bid)
    line = find_order_line(body["order_line_id"])
    units = body["units"]
    expected = body["expected_batch_version"]
    # batch expired (priority 13)
    if batch_expired(batch):
        raise ApiError("ERR_BATCH_EXPIRED", "Batch expired")
    # insufficient inventory (priority 14)
    avail = batch["available_units"] if batch["status"] == "RELEASED" else 0
    need = units if is_int(units) else 0
    if avail < need:
        raise ApiError("ERR_INSUFFICIENT_INVENTORY", "Not enough available units in lot")
    # invalid quantity (priority 15)
    positive_qty(units)
    # stale version / OCC (priority 19)
    if expected != batch["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_batch_version does not match current version")
    e = make_common()
    e.update({
        "order_line_id": line["id"],
        "batch_id": batch["id"],
        "units": units,
        "status": "ACTIVE",
    })
    db.reservations[e["id"]] = e
    batch["available_units"] -= units
    touch(batch)  # version advances by 1
    line["allocated_units"] += units
    touch(line)
    return ok_entity(e, 201)


@app.route("/reservations/<rid>", methods=["GET"])
@endpoint(READ_ROLES)
def get_reservation(rid):
    return ok_entity(find_reservation(rid))


@app.route("/reservations", methods=["GET"])
@endpoint(READ_ROLES)
def list_reservations():
    return list_response(db.reservations, {
        "order_line_id": request.args.get("order_line_id"),
        "batch_id": request.args.get("batch_id"),
        "status": request.args.get("status"),
    })


# ==========================================================================
# Orders (PRD §3.5, §3.6)
# ==========================================================================
def wholesale_tier(total_units):
    if total_units >= 500:
        return D("0.25")
    if total_units >= 200:
        return D("0.18")
    if total_units >= 50:
        return D("0.10")
    return D("0")


def fefo_candidates(product_id):
    cands = [b for b in db.batches.values()
             if b["product_id"] == product_id
             and b["status"] == "RELEASED"
             and b["lot_expiry"] > clock()
             and b["available_units"] > 0]
    cands.sort(key=lambda b: (b["lot_expiry"], b["_seq"]))
    return cands


@app.route("/orders", methods=["POST"])
@endpoint(["Customer"])
def create_order():
    body = get_body()
    require_fields(body, ["customer_id", "order_type"])
    require_enum(body["order_type"], {"RETAIL", "WHOLESALE", "PREORDER"}, "order_type")
    customer = find_customer(body["customer_id"])
    if g.role == "Customer" and customer["id"] != g.uid:
        raise ApiError("ERR_OWNERSHIP_FORBIDDEN", "Customer may only create their own orders")
    ws = None
    we = None
    if body.get("fulfillment_window_start") is not None:
        ws = parse_dt_field(body["fulfillment_window_start"], "fulfillment_window_start")
    if body.get("fulfillment_window_end") is not None:
        we = parse_dt_field(body["fulfillment_window_end"], "fulfillment_window_end")
    e = make_common()
    e.update({
        "customer_id": customer["id"],
        "order_type": body["order_type"],
        "is_gift": bool(body.get("is_gift", False)),
        "fulfillment_window_start": ws,
        "fulfillment_window_end": we,
        "wallet_applied_cents": 0,
        "subtotal_cents": 0,
        "tax_cents": 0,
        "gift_fee_cents": 0,
        "total_cents": 0,
        "status": "DRAFT",
    })
    db.orders[e["id"]] = e
    return ok_entity(e, 201)


@app.route("/orders/<oid>", methods=["GET"])
@endpoint(READ_ROLES)
def get_order(oid):
    return ok_entity(find_order(oid))


@app.route("/orders", methods=["GET"])
@endpoint(READ_ROLES)
def list_orders():
    return list_response(db.orders, {
        "customer_id": request.args.get("customer_id"),
        "order_type": request.args.get("order_type"),
        "status": request.args.get("status"),
    })


@app.route("/orders/<oid>/lines", methods=["POST"])
@endpoint(["Customer"])
def add_order_line(oid):
    body = get_body()
    require_fields(body, ["product_id", "quantity"])
    order = find_order(oid)
    product = find_product(body["product_id"])
    check_ownership(order)
    if order["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Lines can only be added to DRAFT orders")
    customer = db.customers[order["customer_id"]]
    if allergen_conflict(customer, product):
        raise ApiError("ERR_ALLERGEN_RESTRICTED", "Product contains a restricted allergen")
    positive_qty(body["quantity"])
    for l in order_lines_of(order["id"]):
        if l["product_id"] == product["id"]:
            raise ApiError("ERR_DUPLICATE_LINE", "Order already has a line for this product")
    e = make_common()
    e.update({
        "order_id": order["id"],
        "product_id": product["id"],
        "quantity": body["quantity"],
        "unit_price_cents": None,
        "line_total_cents": None,
        "allocated_units": 0,
    })
    db.order_lines[e["id"]] = e
    return ok_entity(e, 201)


@app.route("/order-lines/<lid>", methods=["GET"])
@endpoint(READ_ROLES)
def get_order_line(lid):
    return ok_entity(find_order_line(lid))


@app.route("/order-lines", methods=["GET"])
@endpoint(READ_ROLES)
def list_order_lines():
    return list_response(db.order_lines, {
        "order_id": request.args.get("order_id"),
        "product_id": request.args.get("product_id"),
    })


@app.route("/orders/<oid>/confirm", methods=["POST"])
@endpoint(["Customer"])
def confirm_order(oid):
    order = find_order(oid)
    body = get_body()
    check_ownership(order)
    customer = db.customers[order["customer_id"]]
    # account-type compatibility (priority 6)
    ot = order["order_type"]
    at = customer["account_type"]
    if ot == "WHOLESALE":
        if at != "WHOLESALE":
            raise ApiError("ERR_ACCOUNT_TYPE_MISMATCH", "Wholesale order requires wholesale account")
    else:  # RETAIL / PREORDER
        if at not in ("RETAIL", "CORPORATE"):
            raise ApiError("ERR_ACCOUNT_TYPE_MISMATCH", "Retail/preorder order requires retail or corporate account")
    # state (priority 7)
    if order["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only DRAFT orders can be confirmed")
    lines = order_lines_of(order["id"])
    if len(lines) < 1:
        raise ApiError("ERR_VALIDATION", "Order must have at least one line")
    # allergen re-check (priority 8)
    for line in lines:
        product = db.products[line["product_id"]]
        if allergen_conflict(customer, product):
            raise ApiError("ERR_ALLERGEN_RESTRICTED", "Product contains a restricted allergen")
    # pricing (calculations.line_unit_price + order_total)
    total_units = sum(l["quantity"] for l in lines)
    disc = wholesale_tier(total_units) if ot == "WHOLESALE" else None
    priced = []
    subtotal = 0
    for line in lines:
        product = db.products[line["product_id"]]
        base = D(product["base_price_cents"])
        if ot in ("RETAIL", "PREORDER"):
            unit = base * (D(1) - D(customer["loyalty_discount_pct"]))
        else:
            unit = base * (D(1) - disc)
        line_total = round_half_up(unit * D(line["quantity"]))
        priced.append((line, unit, line_total))
        subtotal += line_total
    tax = round_half_up(D(subtotal) * TAX_RATE)
    gift = GIFT_WRAP_FEE_CENTS if order["is_gift"] else 0
    wallet_apply = body.get("wallet_apply_cents", 0)
    if not is_int(wallet_apply):
        wallet_apply = 0
    applied = min(wallet_apply, customer["wallet_credit_cents"], subtotal + tax + gift)
    if applied < 0:
        applied = 0
    total = subtotal + tax + gift - applied
    # credit limit (priority 18) — checked before committing
    if ot == "WHOLESALE" and total > customer["credit_limit_cents"]:
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED", "Order total exceeds credit limit")
    # commit
    for line, unit, line_total in priced:
        line["unit_price_cents"] = unit
        line["line_total_cents"] = line_total
        touch(line)
    order["subtotal_cents"] = subtotal
    order["tax_cents"] = tax
    order["gift_fee_cents"] = gift
    order["wallet_applied_cents"] = applied
    order["total_cents"] = total
    order["status"] = "CONFIRMED"
    touch(order)
    if applied > 0:
        customer["wallet_credit_cents"] -= applied
        touch(customer)
    return ok_entity(order)


@app.route("/orders/<oid>/allocate", methods=["POST"])
@endpoint(["SalesManager"])
def allocate_order(oid):
    order = find_order(oid)
    if order["status"] not in ("CONFIRMED", "BACKORDERED"):
        raise ApiError("ERR_INVALID_STATE", "Order not in an allocatable state")
    customer = db.customers[order["customer_id"]]
    lines = order_lines_of(order["id"])
    # allergen re-check (priority 8)
    for line in lines:
        product = db.products[line["product_id"]]
        if allergen_conflict(customer, product):
            raise ApiError("ERR_ALLERGEN_RESTRICTED", "Product contains a restricted allergen")
    # inventory sufficiency precheck (priority 14) — all-or-nothing
    for line in lines:
        need = line["quantity"] - line["allocated_units"]
        if need <= 0:
            continue
        available = sum(b["available_units"] for b in fefo_candidates(line["product_id"]))
        if available < need:
            raise ApiError("ERR_INSUFFICIENT_INVENTORY", "Not enough released inventory to allocate")
    # commit FEFO draw
    for line in lines:
        need = line["quantity"] - line["allocated_units"]
        for cand in fefo_candidates(line["product_id"]):
            if need <= 0:
                break
            take = min(need, cand["available_units"])
            if take <= 0:
                continue
            res = make_common()
            res.update({
                "order_line_id": line["id"],
                "batch_id": cand["id"],
                "units": take,
                "status": "ACTIVE",
            })
            db.reservations[res["id"]] = res
            cand["available_units"] -= take
            touch(cand)
            line["allocated_units"] += take
            need -= take
        touch(line)
    order["status"] = "ALLOCATED"
    touch(order)
    return ok_entity(order)


@app.route("/orders/<oid>/fulfill", methods=["POST"])
@endpoint(["ProductionManager"])
def fulfill_order(oid):
    order = find_order(oid)
    if order["status"] != "ALLOCATED":
        raise ApiError("ERR_INVALID_STATE", "Only ALLOCATED orders can be fulfilled")
    # PREORDER fulfillment window (priority 11)
    if order["order_type"] == "PREORDER":
        ws = order["fulfillment_window_start"]
        we = order["fulfillment_window_end"]
        if ws is not None and we is not None:
            if not (ws <= clock() <= we):
                raise ApiError("ERR_FULFILLMENT_WINDOW_CLOSED", "Fulfillment window closed")
    lines = order_lines_of(order["id"])
    if any(l["allocated_units"] != l["quantity"] for l in lines):
        raise ApiError("ERR_INVALID_STATE", "All lines must be fully allocated")
    line_ids = {l["id"] for l in lines}
    for r in db.reservations.values():
        if r["order_line_id"] in line_ids and r["status"] == "ACTIVE":
            r["status"] = "CONSUMED"
            touch(r)
    order["status"] = "FULFILLED"
    touch(order)
    return ok_entity(order)


@app.route("/orders/<oid>/cancel", methods=["POST"])
@endpoint(["Customer", "SalesManager"])
def cancel_order(oid):
    order = find_order(oid)
    check_ownership(order)
    status = order["status"]
    if status not in ("DRAFT", "CONFIRMED", "ALLOCATED", "BACKORDERED"):
        raise ApiError("ERR_INVALID_STATE", "Order cannot be cancelled from its current state")
    if status in ("ALLOCATED", "BACKORDERED"):
        line_ids = {l["id"] for l in order_lines_of(order["id"])}
        for r in db.reservations.values():
            if r["order_line_id"] in line_ids and r["status"] == "ACTIVE":
                r["status"] = "RELEASED"
                touch(r)
                batch = db.batches.get(r["batch_id"])
                if batch is not None:
                    batch["available_units"] += r["units"]
                    touch(batch)
    if status in ("CONFIRMED", "ALLOCATED", "BACKORDERED") and order["wallet_applied_cents"] > 0:
        customer = db.customers.get(order["customer_id"])
        if customer is not None:
            customer["wallet_credit_cents"] += order["wallet_applied_cents"]
            touch(customer)
        order["wallet_applied_cents"] = 0
    order["status"] = "CANCELLED"
    touch(order)
    return ok_entity(order)


# ==========================================================================
# Custom / corporate orders (PRD §3.7)
# ==========================================================================
def custom_amount(units, base_price):
    return units * (base_price + MOLD_SURCHARGE_PER_UNIT_CENTS) + MOLD_SETUP_FEE_CENTS


def active_booking_for_custom(custom_order_id):
    for mb in db.mold_bookings.values():
        if mb["custom_order_id"] == custom_order_id and mb["status"] == "ACTIVE":
            return mb
    return None


@app.route("/custom-orders", methods=["POST"])
@endpoint(["Customer"])
def create_custom_order():
    body = get_body()
    require_fields(body, ["customer_id", "product_id", "mold_id", "units_estimated"])
    customer = find_customer(body["customer_id"])
    product = find_product(body["product_id"])
    mold = find_mold(body["mold_id"])
    if g.role == "Customer" and customer["id"] != g.uid:
        raise ApiError("ERR_OWNERSHIP_FORBIDDEN", "Customer may only create their own custom orders")
    positive_qty(body["units_estimated"])
    e = make_common()
    e.update({
        "customer_id": customer["id"],
        "product_id": product["id"],
        "mold_id": mold["id"],
        "units_estimated": body["units_estimated"],
        "units_produced": None,
        "quote_round": 0,
        "usage_date": None,
        "quoted_amount_cents": None,
        "invoiced_amount_cents": None,
        "status": "DRAFT",
    })
    db.custom_orders[e["id"]] = e
    return ok_entity(e, 201)


@app.route("/custom-orders/<coid>", methods=["GET"])
@endpoint(READ_ROLES)
def get_custom_order(coid):
    return ok_entity(find_custom_order(coid))


@app.route("/custom-orders", methods=["GET"])
@endpoint(READ_ROLES)
def list_custom_orders():
    return list_response(db.custom_orders, {
        "customer_id": request.args.get("customer_id"),
        "mold_id": request.args.get("mold_id"),
        "product_id": request.args.get("product_id"),
        "status": request.args.get("status"),
    })


@app.route("/custom-orders/<coid>/quote", methods=["POST"])
@endpoint(["SalesManager"])
def quote_custom_order(coid):
    co = find_custom_order(coid)
    if co["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError("ERR_INVALID_STATE", "Custom order cannot be quoted from its current state")
    product = db.products[co["product_id"]]
    co["quoted_amount_cents"] = custom_amount(co["units_estimated"], product["base_price_cents"])
    co["quote_round"] += 1
    co["status"] = "QUOTED"
    touch(co)
    return ok_entity(co)


@app.route("/custom-orders/<coid>/request-revision", methods=["POST"])
@endpoint(["Customer"])
def request_revision(coid):
    co = find_custom_order(coid)
    check_ownership(co)
    if co["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE", "Only QUOTED custom orders can be revised")
    co["status"] = "REVISION_REQUESTED"
    touch(co)
    return ok_entity(co)


@app.route("/custom-orders/<coid>/accept", methods=["POST"])
@endpoint(["Customer"])
def accept_custom_order(coid):
    body = get_body()
    require_fields(body, ["usage_date"])
    co = find_custom_order(coid)
    check_ownership(co)
    if co["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE", "Only QUOTED custom orders can be accepted")
    usage_date = parse_dt_field(body["usage_date"], "usage_date")
    mold = db.molds[co["mold_id"]]
    # mold day-capacity (priority 10)
    booked = sum(mb["units"] for mb in db.mold_bookings.values()
                 if mb["mold_id"] == mold["id"] and mb["status"] == "ACTIVE"
                 and mb["usage_date"].date() == usage_date.date())
    if co["units_estimated"] + booked > mold["daily_capacity_units"]:
        raise ApiError("ERR_MOLD_CAPACITY_EXCEEDED", "Mold day-capacity exceeded")
    # mold activity (priority 12)
    if mold["status"] != "ACTIVE":
        raise ApiError("ERR_MOLD_INACTIVE", "Mold is not ACTIVE")
    co["usage_date"] = usage_date
    co["status"] = "ACCEPTED"
    touch(co)
    mb = make_common()
    mb.update({
        "mold_id": mold["id"],
        "custom_order_id": co["id"],
        "usage_date": usage_date,
        "units": co["units_estimated"],
        "status": "ACTIVE",
    })
    db.mold_bookings[mb["id"]] = mb
    return ok_entity(co)


@app.route("/custom-orders/<coid>/reject", methods=["POST"])
@endpoint(["Customer"])
def reject_custom_order(coid):
    co = find_custom_order(coid)
    check_ownership(co)
    if co["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE", "Only QUOTED custom orders can be rejected")
    co["status"] = "REJECTED"
    touch(co)
    return ok_entity(co)


@app.route("/custom-orders/<coid>/start-production", methods=["POST"])
@endpoint(["ProductionManager"])
def start_production(coid):
    co = find_custom_order(coid)
    if co["status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_STATE", "Only ACCEPTED custom orders can start production")
    mold = db.molds[co["mold_id"]]
    if mold["status"] != "ACTIVE":
        raise ApiError("ERR_MOLD_INACTIVE", "Mold is not ACTIVE")
    product = db.products[co["product_id"]]
    produced_at = clock()
    batch = make_common()
    batch.update({
        "product_id": product["id"],
        "mold_id": mold["id"],
        "tempering_line_id": None,
        "initial_units": co["units_estimated"],
        "available_units": 0,
        "produced_at": produced_at,
        "lot_expiry": add_days(produced_at, product["shelf_life_days"]),
        "temper_start": None,
        "temper_end": None,
        "reseed_count": 0,
        "status": "RAW",
    })
    db.batches[batch["id"]] = batch
    co["status"] = "IN_PRODUCTION"
    touch(co)
    return ok_entity(co)


@app.route("/custom-orders/<coid>/fulfill", methods=["POST"])
@endpoint(["ProductionManager"])
def fulfill_custom_order(coid):
    body = get_body()
    require_fields(body, ["units_produced"])
    co = find_custom_order(coid)
    if co["status"] != "IN_PRODUCTION":
        raise ApiError("ERR_INVALID_STATE", "Only IN_PRODUCTION custom orders can be fulfilled")
    up = body["units_produced"]
    if not is_int(up) or up <= 0:
        raise ApiError("ERR_VALIDATION", "units_produced must be a positive integer")
    product = db.products[co["product_id"]]
    co["units_produced"] = up
    co["invoiced_amount_cents"] = custom_amount(up, product["base_price_cents"])
    co["status"] = "FULFILLED"
    touch(co)
    mb = active_booking_for_custom(co["id"])
    if mb is not None:
        mb["status"] = "RELEASED"
        touch(mb)
    return ok_entity(co)


@app.route("/custom-orders/<coid>/cancel", methods=["POST"])
@endpoint(["Customer"])
def cancel_custom_order(coid):
    co = find_custom_order(coid)
    check_ownership(co)
    if co["status"] not in ("DRAFT", "QUOTED", "ACCEPTED"):
        raise ApiError("ERR_INVALID_STATE", "Custom order cannot be cancelled from its current state")
    if co["status"] == "ACCEPTED":
        mb = active_booking_for_custom(co["id"])
        if mb is not None:
            mb["status"] = "CANCELLED"
            touch(mb)
    co["status"] = "CANCELLED"
    touch(co)
    return ok_entity(co)


# ==========================================================================
# Subscriptions & shipments (PRD §3.8)
# ==========================================================================
@app.route("/subscriptions", methods=["POST"])
@endpoint(["Customer"])
def create_subscription():
    body = get_body()
    require_fields(body, ["customer_id", "box_product_id", "cadence_days", "next_ship_date"])
    customer = find_customer(body["customer_id"])
    product = find_product(body["box_product_id"])
    if g.role == "Customer" and customer["id"] != g.uid:
        raise ApiError("ERR_OWNERSHIP_FORBIDDEN", "Customer may only create their own subscriptions")
    if not is_int(body["cadence_days"]) or body["cadence_days"] <= 0:
        raise ApiError("ERR_VALIDATION", "cadence_days must be a positive integer")
    next_ship = parse_dt_field(body["next_ship_date"], "next_ship_date")
    e = make_common()
    e.update({
        "customer_id": customer["id"],
        "box_product_id": product["id"],
        "cadence_days": body["cadence_days"],
        "next_ship_date": next_ship,
        "status": "ACTIVE",
    })
    db.subscriptions[e["id"]] = e
    return ok_entity(e, 201)


@app.route("/subscriptions/<sid>", methods=["GET"])
@endpoint(READ_ROLES)
def get_subscription(sid):
    return ok_entity(find_subscription(sid))


@app.route("/subscriptions", methods=["GET"])
@endpoint(READ_ROLES)
def list_subscriptions():
    return list_response(db.subscriptions, {
        "customer_id": request.args.get("customer_id"),
        "box_product_id": request.args.get("box_product_id"),
        "status": request.args.get("status"),
    })


@app.route("/subscriptions/<sid>/pause", methods=["POST"])
@endpoint(["Customer"])
def pause_subscription(sid):
    sub = find_subscription(sid)
    check_ownership(sub)
    if sub["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only ACTIVE subscriptions can be paused")
    sub["status"] = "PAUSED"
    touch(sub)
    return ok_entity(sub)


@app.route("/subscriptions/<sid>/resume", methods=["POST"])
@endpoint(["Customer"])
def resume_subscription(sid):
    sub = find_subscription(sid)
    check_ownership(sub)
    if sub["status"] != "PAUSED":
        raise ApiError("ERR_INVALID_STATE", "Only PAUSED subscriptions can be resumed")
    sub["status"] = "ACTIVE"
    touch(sub)
    return ok_entity(sub)


@app.route("/subscriptions/<sid>/cancel", methods=["POST"])
@endpoint(["Customer"])
def cancel_subscription(sid):
    sub = find_subscription(sid)
    check_ownership(sub)
    if sub["status"] not in ("ACTIVE", "PAUSED"):
        raise ApiError("ERR_INVALID_STATE", "Subscription cannot be cancelled from its current state")
    for sh in db.subscription_shipments.values():
        if sh["subscription_id"] == sub["id"] and sh["status"] == "SCHEDULED":
            sh["status"] = "CANCELLED"
            touch(sh)
    sub["status"] = "CANCELLED"
    touch(sub)
    return ok_entity(sub)


@app.route("/subscriptions/<sid>/advance", methods=["POST"])
@endpoint(["Admin"])
def advance_subscription(sid):
    sub = find_subscription(sid)
    if sub["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only ACTIVE subscriptions can be advanced")
    if clock() < sub["next_ship_date"]:
        raise ApiError("ERR_INVALID_STATE", "Subscription not yet due for advance")
    product = db.products[sub["box_product_id"]]
    existing = [sh for sh in db.subscription_shipments.values()
                if sh["subscription_id"] == sub["id"]]
    period_index = len(existing) + 1
    sh = make_common()
    sh.update({
        "subscription_id": sub["id"],
        "period_index": period_index,
        "scheduled_date": sub["next_ship_date"],
        "estimated_charge_cents": product["base_price_cents"],
        "settled_charge_cents": None,
        "status": "SCHEDULED",
    })
    db.subscription_shipments[sh["id"]] = sh
    sub["next_ship_date"] = add_days(sub["next_ship_date"], sub["cadence_days"])
    touch(sub)
    return ok_entity(sh, 201)


@app.route("/subscription-shipments/<shid>", methods=["GET"])
@endpoint(READ_ROLES)
def get_shipment(shid):
    return ok_entity(find_shipment(shid))


@app.route("/subscription-shipments", methods=["GET"])
@endpoint(READ_ROLES)
def list_shipments():
    return list_response(db.subscription_shipments, {
        "subscription_id": request.args.get("subscription_id"),
        "status": request.args.get("status"),
    })


@app.route("/subscription-shipments/<shid>/ship", methods=["POST"])
@endpoint(["Admin"])
def ship_shipment(shid):
    sh = find_shipment(shid)
    if sh["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Only SCHEDULED shipments can be shipped")
    sub = db.subscriptions[sh["subscription_id"]]
    if sub["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Parent subscription is not ACTIVE")
    product = db.products[sub["box_product_id"]]
    sh["settled_charge_cents"] = product["base_price_cents"]
    sh["status"] = "SHIPPED"
    touch(sh)
    return ok_entity(sh)


# ==========================================================================
# System / test-driving endpoints (PRD §4)
# ==========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
@endpoint(["Admin"])
def set_clock():
    body = get_body()
    require_fields(body, ["to_iso8601"])
    db.clock = parse_dt_field(body["to_iso8601"], "to_iso8601")
    return ok_object({})


@app.route("/_inventory/sweep-expired", methods=["POST"])
@endpoint(["Admin"])
def sweep_expired():
    for batch in db.batches.values():
        if batch["status"] == "RELEASED" and clock() >= batch["lot_expiry"]:
            batch["status"] = "EXPIRED"
            batch["available_units"] = 0
            touch(batch)
    return ok_object({})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
