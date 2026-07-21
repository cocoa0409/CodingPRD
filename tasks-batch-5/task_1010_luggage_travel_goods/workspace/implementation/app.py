"""Luggage & Travel-Goods Store API — Flask implementation.

All behavior traces to workspace/PRD.md. Storage is in-memory only (core.py).
"""

import os
from decimal import Decimal

from flask import Flask, request, jsonify

import core
from core import (
    serialize, create_record, touch, now, set_clock, parse_iso, fmt_dt,
    add_months, round_half_up, floor_div_100, floor_dec, sort_by_created,
    gen_request_id,
)
from errors import ApiError, err

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants (PRD 3).
# ---------------------------------------------------------------------------
ROLES = {"Customer", "Associate", "Manager"}

PRODUCT_CATEGORIES = {"HARD_SHELL", "SOFT_SIDE", "BACKPACK", "DUFFEL", "ACCESSORY"}
DEFECT_TYPES = {"WHEEL", "HANDLE", "ZIPPER", "SHELL", "LINING", "OTHER"}
RESOLUTIONS = {"REPAIR", "REPLACE", "REJECT"}
REPAIR_TYPES = {"WHEEL", "HANDLE", "ZIPPER", "OTHER"}
COMPLEXITIES = {"STANDARD", "COMPLEX"}
CONDITIONS = {"LIKE_NEW", "GOOD", "FAIR", "POOR"}
REMEDIES = {"REPAIR", "REPLACE", "REFUND"}
BENCH_SKILLS = {"WHEEL", "HANDLE", "ZIPPER", "GENERAL"}
STATION_METHODS = {"EMBOSS", "HEATSTAMP", "ENGRAVE"}

TIER_THRESHOLDS = [("PLATINUM", 500000), ("GOLD", 150000), ("SILVER", 50000), ("BRONZE", 0)]
TIER_DISCOUNT = {"BRONZE": Decimal("0.00"), "SILVER": Decimal("0.05"),
                 "GOLD": Decimal("0.10"), "PLATINUM": Decimal("0.15")}
TIER_MULT = {"BRONZE": Decimal("1.00"), "SILVER": Decimal("1.25"),
             "GOLD": Decimal("1.50"), "PLATINUM": Decimal("2.00")}

MONOGRAM_FEE_CENTS = 1200
GIFT_WRAP_FEE_CENTS = 800
TAX_RATE = Decimal("0.08")

LABOR_RATE = {"WHEEL": 3500, "HANDLE": 4000, "ZIPPER": 3000, "OTHER": 4500}
COMPLEXITY_MULT = {"STANDARD": Decimal("1.0"), "COMPLEX": Decimal("1.5")}
MIN_LABOR_CENTS = 1500
MAX_LABOR_CENTS = 20000
DIAGNOSTIC_FEE_CENTS = 2500

CONDITION_FACTOR = {"LIKE_NEW": Decimal("0.40"), "GOOD": Decimal("0.30"),
                    "FAIR": Decimal("0.20"), "POOR": Decimal("0.10")}
MIN_TRADE_CENTS = 500
TRADE_IN_OFFER_DAYS = 14

STATION_BUFFER_MIN = 15


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2).
# ---------------------------------------------------------------------------
def envelope(data, response_type, status, extra_meta=None):
    meta = {"api_request_id": gen_request_id(),
            "api_request_timestamp": fmt_dt(now())}
    if extra_meta:
        meta.update(extra_meta)
    return jsonify({"meta": meta, "response_type": response_type, "data": data}), status


def obj_response(rec, status=200):
    data = serialize(rec) if isinstance(rec, dict) else rec
    return envelope(data, "object", status)


def list_response(items, limit, offset, total):
    meta = {"limit": limit, "offset": offset, "total_count": total,
            "has_more": offset + limit < total}
    return envelope([serialize(r) for r in items], "array", 200, meta)


# ---------------------------------------------------------------------------
# Auth / RBAC (PRD 2.1, 2.8).
# ---------------------------------------------------------------------------
def identity():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "missing or unknown auth headers")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise err("ERR_FORBIDDEN", "role not permitted")


# ---------------------------------------------------------------------------
# Body / query parsing helpers.
# ---------------------------------------------------------------------------
def body():
    return request.get_json(silent=True) or {}


def require_present(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise err("ERR_INVALID_REQUEST", "missing field: %s" % f)


def check_enum(value, valid, field):
    if value not in valid:
        raise err("ERR_INVALID_REQUEST", "invalid enum for %s" % field)


def require_int(data, field):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "%s must be an integer" % field)
    return v


def require_nonneg_int(data, field):
    v = require_int(data, field)
    if v < 0:
        raise err("ERR_VALIDATION_RANGE", "%s must be non-negative" % field)
    return v


def require_number(data, field):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", "%s must be a number" % field)
    return v


def get_existing(collection, ident):
    rec = collection.get(ident)
    if rec is None:
        raise err("ERR_NOT_FOUND", "resource not found")
    return rec


def get_pagination():
    args = request.args
    limit = 10
    offset = 0
    if args.get("limit") is not None:
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            limit = 10
        limit = max(1, min(100, limit))
    if args.get("offset") is not None:
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            offset = 0
        offset = max(0, offset)
    return limit, offset


def paginate(items):
    items = sort_by_created(items)
    total = len(items)
    limit, offset = get_pagination()
    return items[offset:offset + limit], limit, offset, total


# ---------------------------------------------------------------------------
# Domain helpers.
# ---------------------------------------------------------------------------
def compute_tier(spend):
    for name, threshold in TIER_THRESHOLDS:
        if spend >= threshold:
            return name
    return "BRONZE"


def recompute_customer_tier(customer):
    customer["tier"] = compute_tier(customer["lifetime_spend_cents"])


def points_for(net_merch_cents, tier):
    units = floor_div_100(net_merch_cents)
    return floor_dec(Decimal(units) * TIER_MULT[tier])


def lines_of_order(order_id):
    return [l for l in core.sales_order_lines.values() if l["sales_order_id"] == order_id]


def recompute_sales_order(order):
    lines = sort_by_created(lines_of_order(order["id"]))
    subtotal = sum(l["line_subtotal_cents"] for l in lines)
    tier = order["_tier_at_creation"]
    loyalty_discount = round_half_up(Decimal(subtotal) * TIER_DISCOUNT[tier])
    taxable = subtotal - loyalty_discount
    tax = round_half_up(Decimal(taxable) * TAX_RATE)
    gift = GIFT_WRAP_FEE_CENTS if order["is_gift"] else 0
    total = taxable + tax + gift
    order["subtotal_cents"] = subtotal
    order["loyalty_discount_cents"] = loyalty_discount
    order["tax_cents"] = tax
    order["gift_wrap_fee_cents"] = gift
    order["total_cents"] = total
    order["provisional_points"] = points_for(subtotal - loyalty_discount, tier)
    touch(order)


def repair_pay_mode(order):
    claim_id = order.get("claim_id")
    if claim_id:
        claim = core.claims.get(claim_id)
        if claim and claim.get("resolution") == "REPAIR":
            return "WARRANTY_COVERED"
    return "CUSTOMER_PAY"


def repair_line_list(repair_order_id):
    return [l for l in core.repair_lines.values() if l["repair_order_id"] == repair_order_id]


# ---------------------------------------------------------------------------
# Cascade helpers (PRD 3.8).
# ---------------------------------------------------------------------------
def cascade_product_recalled(product):
    """Product ACTIVE->RECALLED plus registration/claim/special-order cascades."""
    product["status"] = "RECALLED"
    touch(product)
    for reg in core.registrations.values():
        if reg["product_id"] == product["id"] and reg["status"] == "ACTIVE":
            reg["status"] = "RECALL_FLAGGED"
            touch(reg)
            for claim in core.claims.values():
                if claim["registration_id"] == reg["id"] and claim["status"] in ("SUBMITTED", "UNDER_REVIEW"):
                    claim["status"] = "NEEDS_INFO"
                    touch(claim)
    for so in core.special_orders.values():
        if so["product_id"] == product["id"] and so["status"] in ("REQUESTED", "SOURCED"):
            so["status"] = "CANCELLED"
            touch(so)


def cascade_product_reactivated(product):
    """Product RECALLED->ACTIVE plus registration revert."""
    product["status"] = "ACTIVE"
    touch(product)
    for reg in core.registrations.values():
        if reg["product_id"] == product["id"] and reg["status"] == "RECALL_FLAGGED":
            reg["status"] = "ACTIVE"
            touch(reg)


# ---------------------------------------------------------------------------
# Scheduling conflict helpers (PRD 2.10).
# ---------------------------------------------------------------------------
def bench_conflict(bench_id, start, end, exclude_id):
    for ro in core.repair_orders.values():
        if ro["id"] == exclude_id:
            continue
        if ro.get("bench_id") != bench_id:
            continue
        if ro["status"] not in ("SCHEDULED", "IN_REPAIR", "PARTS_HOLD"):
            continue
        os_, oe = ro.get("bench_start"), ro.get("bench_end")
        if os_ is None or oe is None:
            continue
        # half-open [start,end): overlap iff start < oe and os < end
        if start < oe and os_ < end:
            return True
    return False


def station_conflict(station_id, start, end, exclude_id):
    from datetime import timedelta
    buf = timedelta(minutes=STATION_BUFFER_MIN)
    a_start, a_end = start - buf, end + buf
    for line in core.sales_order_lines.values():
        if line["id"] == exclude_id:
            continue
        if line.get("monogram_station_id") != station_id:
            continue
        if line["monogram_status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        os_, oe = line.get("monogram_start"), line.get("monogram_end")
        if os_ is None or oe is None:
            continue
        b_start, b_end = os_ - buf, oe + buf
        # closed-interval intersection after padding both windows
        if a_start <= b_end and b_start <= a_end:
            return True
    return False


# ---------------------------------------------------------------------------
# Error handlers.
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return envelope({"error_id": e.error_id, "message": e.message}, "error", e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return envelope({"error_id": "ERR_NOT_FOUND", "message": "not found"}, "error", 404)


@app.errorhandler(405)
def handle_405(e):
    return envelope({"error_id": "ERR_NOT_FOUND", "message": "method not allowed"}, "error", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return envelope({"error_id": "ERR_INVALID_REQUEST", "message": str(e)}, "error", 422)


# ===========================================================================
# Clock (test-driving)
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def clock_set():
    _, role = identity()
    require_role(role, {"Manager"})
    data = body()
    require_present(data, ["to_iso8601"])
    try:
        dt = parse_iso(data["to_iso8601"])
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "bad to_iso8601")
    set_clock(dt)
    return envelope({}, "object", 200)


# ===========================================================================
# Products
# ===========================================================================
@app.route("/store/products", methods=["POST"])
def create_product():
    _, role = identity()
    require_role(role, {"Manager", "Associate"})
    data = body()
    require_present(data, ["sku", "name", "category", "msrp_cents", "warranty_months",
                           "length_mm", "width_mm", "height_mm"])
    check_enum(data["category"], PRODUCT_CATEGORIES, "category")
    sku = data["sku"]
    for p in core.products.values():
        if p["sku"] == sku and p["status"] in ("ACTIVE", "RECALLED"):
            raise err("ERR_DUPLICATE", "sku already in use")
    msrp = require_nonneg_int(data, "msrp_cents")
    warranty_months = require_nonneg_int(data, "warranty_months")
    length_mm = require_nonneg_int(data, "length_mm")
    width_mm = require_nonneg_int(data, "width_mm")
    height_mm = require_nonneg_int(data, "height_mm")
    rec = create_record(core.products, {
        "sku": sku, "name": data["name"], "category": data["category"],
        "msrp_cents": msrp, "warranty_months": warranty_months,
        "length_mm": length_mm, "width_mm": width_mm, "height_mm": height_mm,
        "status": "ACTIVE",
    })
    return obj_response(rec, 201)


@app.route("/store/products/<pid>", methods=["GET"])
def get_product(pid):
    _, role = identity()
    require_role(role, {"Manager", "Associate", "Customer"})
    return obj_response(get_existing(core.products, pid))


@app.route("/store/products", methods=["GET"])
def list_products():
    _, role = identity()
    require_role(role, {"Manager", "Associate", "Customer"})
    items = list(core.products.values())
    category = request.args.get("category")
    status = request.args.get("status")
    if category is not None:
        items = [p for p in items if p["category"] == category]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, limit, offset, total = paginate(items)
    return list_response(page, limit, offset, total)


@app.route("/store/products/<pid>/airline-fit", methods=["GET"])
def airline_fit(pid):
    _, role = identity()
    require_role(role, {"Manager", "Associate", "Customer"})
    product = get_existing(core.products, pid)
    airline_id = request.args.get("airline_id")
    if not airline_id:
        raise err("ERR_INVALID_REQUEST", "airline_id required")
    airline = get_existing(core.airlines, airline_id)
    fits_carry_on = (product["length_mm"] <= airline["carry_on_max_length_mm"]
                     and product["width_mm"] <= airline["carry_on_max_width_mm"]
                     and product["height_mm"] <= airline["carry_on_max_height_mm"])
    linear_mm = product["length_mm"] + product["width_mm"] + product["height_mm"]
    fits_checked = linear_mm <= airline["checked_linear_limit_mm"]
    return envelope({"fits_carry_on": fits_carry_on, "fits_checked": fits_checked,
                     "linear_mm": linear_mm}, "object", 200)


@app.route("/store/products/<pid>/discontinue", methods=["POST"])
def discontinue_product(pid):
    _, role = identity()
    require_role(role, {"Manager"})
    product = get_existing(core.products, pid)
    if product["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "product not ACTIVE")
    for so in core.special_orders.values():
        if so["product_id"] == pid and so["status"] in ("REQUESTED", "SOURCED", "ARRIVED"):
            raise err("ERR_OPEN_SPECIAL_ORDER", "open special order references product")
    product["status"] = "DISCONTINUED"
    touch(product)
    return obj_response(product)


# ===========================================================================
# Airlines
# ===========================================================================
@app.route("/store/airlines", methods=["POST"])
def create_airline():
    _, role = identity()
    require_role(role, {"Manager", "Associate"})
    data = body()
    require_present(data, ["iata_code", "name", "carry_on_max_length_mm",
                           "carry_on_max_width_mm", "carry_on_max_height_mm",
                           "checked_linear_limit_mm"])
    cl = require_nonneg_int(data, "carry_on_max_length_mm")
    cw = require_nonneg_int(data, "carry_on_max_width_mm")
    ch = require_nonneg_int(data, "carry_on_max_height_mm")
    ck = require_nonneg_int(data, "checked_linear_limit_mm")
    rec = create_record(core.airlines, {
        "iata_code": data["iata_code"], "name": data["name"],
        "carry_on_max_length_mm": cl, "carry_on_max_width_mm": cw,
        "carry_on_max_height_mm": ch, "checked_linear_limit_mm": ck,
    }, common=False)
    return obj_response(rec, 201)


@app.route("/store/airlines/<aid>", methods=["GET"])
def get_airline(aid):
    _, role = identity()
    require_role(role, {"Manager", "Associate", "Customer"})
    return obj_response(get_existing(core.airlines, aid))


@app.route("/store/airlines", methods=["GET"])
def list_airlines():
    _, role = identity()
    require_role(role, {"Manager", "Associate", "Customer"})
    page, limit, offset, total = paginate(list(core.airlines.values()))
    return list_response(page, limit, offset, total)


# ===========================================================================
# Customers
# ===========================================================================
@app.route("/store/customers", methods=["POST"])
def create_customer():
    _, role = identity()
    require_role(role, {"Manager", "Associate"})
    data = body()
    require_present(data, ["email", "full_name"])
    email = data["email"]
    for c in core.customers.values():
        if c["email"] == email:
            raise err("ERR_DUPLICATE", "email already in use")
    rec = create_record(core.customers, {
        "email": email, "full_name": data["full_name"], "tier": "BRONZE",
        "lifetime_spend_cents": 0, "points_balance": 0, "store_credit_cents": 0,
    })
    return obj_response(rec, 201)


@app.route("/store/customers/<cid>", methods=["GET"])
def get_customer(cid):
    uid, role = identity()
    require_role(role, {"Manager", "Associate", "Customer"})
    if role == "Customer" and cid != uid:
        raise err("ERR_FORBIDDEN", "cannot read another customer")
    return obj_response(get_existing(core.customers, cid))


@app.route("/store/customers", methods=["GET"])
def list_customers():
    _, role = identity()
    require_role(role, {"Manager", "Associate"})
    page, limit, offset, total = paginate(list(core.customers.values()))
    return list_response(page, limit, offset, total)


# ===========================================================================
# Warranty Registrations
# ===========================================================================
@app.route("/store/warranty-registrations", methods=["POST"])
def create_registration():
    uid, role = identity()
    require_role(role, {"Manager", "Associate", "Customer"})
    data = body()
    require_present(data, ["product_id", "customer_id", "serial_number", "purchase_date"])
    if role == "Customer" and data["customer_id"] != uid:
        raise err("ERR_FORBIDDEN", "cannot register for another customer")
    product = get_existing(core.products, data["product_id"])
    get_existing(core.customers, data["customer_id"])
    serial = data["serial_number"]
    for reg in core.registrations.values():
        if reg["product_id"] == product["id"] and reg["serial_number"] == serial:
            raise err("ERR_DUPLICATE", "serial already registered for product")
    try:
        purchase_dt = parse_iso(data["purchase_date"])
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "bad purchase_date")
    expiry = add_months(purchase_dt, product["warranty_months"])
    rec = create_record(core.registrations, {
        "product_id": product["id"], "customer_id": data["customer_id"],
        "serial_number": serial, "purchase_date": purchase_dt,
        "warranty_expiry": expiry, "status": "ACTIVE",
    })
    return obj_response(rec, 201)


@app.route("/store/warranty-registrations/<rid>", methods=["GET"])
def get_registration(rid):
    uid, role = identity()
    require_role(role, {"Manager", "Associate", "Customer"})
    reg = get_existing(core.registrations, rid)
    if role == "Customer" and reg["customer_id"] != uid:
        raise err("ERR_FORBIDDEN", "not owner")
    return obj_response(reg)


@app.route("/store/warranty-registrations", methods=["GET"])
def list_registrations():
    uid, role = identity()
    require_role(role, {"Manager", "Associate", "Customer"})
    items = list(core.registrations.values())
    pid = request.args.get("product_id")
    cid = request.args.get("customer_id")
    if pid is not None:
        items = [r for r in items if r["product_id"] == pid]
    if cid is not None:
        items = [r for r in items if r["customer_id"] == cid]
    if role == "Customer":
        items = [r for r in items if r["customer_id"] == uid]
    page, limit, offset, total = paginate(items)
    return list_response(page, limit, offset, total)


@app.route("/store/warranty-registrations/<rid>/void", methods=["POST"])
def void_registration(rid):
    _, role = identity()
    require_role(role, {"Manager"})
    reg = get_existing(core.registrations, rid)
    if reg["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "registration not ACTIVE")
    for claim in core.claims.values():
        if claim["registration_id"] == rid and claim["status"] in ("UNDER_REVIEW", "NEEDS_INFO"):
            raise err("ERR_CLAIM_OPEN_ON_REGISTRATION", "open claim on registration")
    reg["status"] = "VOID"
    touch(reg)
    return obj_response(reg)


# ===========================================================================
# Warranty Claims
# ===========================================================================
@app.route("/store/warranty-claims", methods=["POST"])
def create_claim():
    uid, role = identity()
    require_role(role, {"Manager", "Associate", "Customer"})
    data = body()
    require_present(data, ["registration_id", "expected_warranty_registration_version",
                           "defect_type", "description"])
    reg = get_existing(core.registrations, data["registration_id"])
    if role == "Customer" and reg["customer_id"] != uid:
        raise err("ERR_FORBIDDEN", "not owner")
    # OCC guard (priority 14)
    expected = data["expected_warranty_registration_version"]
    if expected != reg["version"]:
        raise err("ERR_STALE_VERSION", "stale registration version")
    check_enum(data["defect_type"], DEFECT_TYPES, "defect_type")
    # supersede prior non-terminal claims on this registration
    for claim in core.claims.values():
        if claim["registration_id"] == reg["id"] and claim["status"] in ("SUBMITTED", "UNDER_REVIEW", "NEEDS_INFO"):
            claim["status"] = "SUPERSEDED"
            touch(claim)
    touch(reg)  # increments registration version by 1
    rec = create_record(core.claims, {
        "registration_id": reg["id"],
        "expected_warranty_registration_version": expected,
        "defect_type": data["defect_type"], "description": data["description"],
        "resolution": None, "status": "SUBMITTED",
    })
    return obj_response(rec, 201)


@app.route("/store/warranty-claims/<cid>", methods=["GET"])
def get_claim(cid):
    uid, role = identity()
    require_role(role, {"Manager", "Associate", "Customer"})
    claim = get_existing(core.claims, cid)
    if role == "Customer":
        reg = core.registrations.get(claim["registration_id"])
        if not reg or reg["customer_id"] != uid:
            raise err("ERR_FORBIDDEN", "not owner")
    return obj_response(claim)


@app.route("/store/warranty-claims", methods=["GET"])
def list_claims():
    uid, role = identity()
    require_role(role, {"Manager", "Associate", "Customer"})
    items = list(core.claims.values())
    rid = request.args.get("registration_id")
    if rid is not None:
        items = [c for c in items if c["registration_id"] == rid]
    if role == "Customer":
        items = [c for c in items
                 if core.registrations.get(c["registration_id"], {}).get("customer_id") == uid]
    page, limit, offset, total = paginate(items)
    return list_response(page, limit, offset, total)


@app.route("/store/warranty-claims/<cid>/review", methods=["POST"])
def claim_review(cid):
    _, role = identity()
    require_role(role, {"Manager", "Associate"})
    claim = get_existing(core.claims, cid)
    if claim["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "claim not SUBMITTED")
    reg = core.registrations[claim["registration_id"]]
    if reg["status"] != "ACTIVE":
        raise err("ERR_REGISTRATION_NOT_ACTIVE", "registration not ACTIVE")
    if not (now() < reg["warranty_expiry"]):
        raise err("ERR_WARRANTY_EXPIRED", "warranty expired")
    claim["status"] = "UNDER_REVIEW"
    touch(claim)
    return obj_response(claim)


@app.route("/store/warranty-claims/<cid>/request-info", methods=["POST"])
def claim_request_info(cid):
    _, role = identity()
    require_role(role, {"Manager", "Associate"})
    claim = get_existing(core.claims, cid)
    if claim["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "claim not UNDER_REVIEW")
    claim["status"] = "NEEDS_INFO"
    touch(claim)
    return obj_response(claim)


@app.route("/store/warranty-claims/<cid>/resubmit", methods=["POST"])
def claim_resubmit(cid):
    _, role = identity()
    require_role(role, {"Manager", "Associate"})
    claim = get_existing(core.claims, cid)
    if claim["status"] != "NEEDS_INFO":
        raise err("ERR_INVALID_STATE", "claim not NEEDS_INFO")
    claim["status"] = "UNDER_REVIEW"
    touch(claim)
    return obj_response(claim)


@app.route("/store/warranty-claims/<cid>/resolve", methods=["POST"])
def claim_resolve(cid):
    _, role = identity()
    require_role(role, {"Manager"})
    claim = get_existing(core.claims, cid)
    data = body()
    require_present(data, ["resolution"])
    check_enum(data["resolution"], RESOLUTIONS, "resolution")
    if claim["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "claim not UNDER_REVIEW")
    resolution = data["resolution"]
    if resolution in ("REPAIR", "REPLACE"):
        reg = core.registrations[claim["registration_id"]]
        if reg["status"] != "ACTIVE":
            raise err("ERR_REGISTRATION_NOT_ACTIVE", "registration not ACTIVE")
        claim["resolution"] = resolution
        claim["status"] = "RESOLVED"
    else:  # REJECT
        claim["resolution"] = "REJECT"
        claim["status"] = "REJECTED"
    touch(claim)
    return obj_response(claim)


# ===========================================================================
# Repair Orders
# ===========================================================================
@app.route("/store/repair-orders", methods=["POST"])
def create_repair_order():
    uid, role = identity()
    require_role(role, {"Manager", "Associate", "Customer"})
    data = body()
    require_present(data, ["customer_id", "product_id"])
    if role == "Customer" and data["customer_id"] != uid:
        raise err("ERR_FORBIDDEN", "not owner")
    get_existing(core.customers, data["customer_id"])
    get_existing(core.products, data["product_id"])
    claim_id = data.get("claim_id")
    if claim_id is not None:
        get_existing(core.claims, claim_id)
    rec = create_record(core.repair_orders, {
        "customer_id": data["customer_id"], "product_id": data["product_id"],
        "claim_id": claim_id, "bench_id": None,
        "pay_mode": None, "quoted_total_cents": 0, "warranty_cost_cents": 0,
        "bench_start": None, "bench_end": None, "status": "INTAKE",
    })
    rec["pay_mode"] = repair_pay_mode(rec)
    return obj_response(rec, 201)


@app.route("/store/repair-orders/<rid>", methods=["GET"])
def get_repair_order(rid):
    uid, role = identity()
    require_role(role, {"Manager", "Associate", "Customer"})
    ro = get_existing(core.repair_orders, rid)
    if role == "Customer" and ro["customer_id"] != uid:
        raise err("ERR_FORBIDDEN", "not owner")
    return obj_response(ro)


@app.route("/store/repair-orders", methods=["GET"])
def list_repair_orders():
    uid, role = identity()
    require_role(role, {"Manager", "Associate", "Customer"})
    items = list(core.repair_orders.values())
    for key in ("customer_id", "product_id", "claim_id", "bench_id"):
        val = request.args.get(key)
        if val is not None:
            items = [r for r in items if r.get(key) == val]
    if role == "Customer":
        items = [r for r in items if r["customer_id"] == uid]
    page, limit, offset, total = paginate(items)
    return list_response(page, limit, offset, total)


@app.route("/store/repair-orders/<rid>/quote", methods=["POST"])
def repair_quote(rid):
    _, role = identity()
    require_role(role, {"Manager", "Associate"})
    ro = get_existing(core.repair_orders, rid)
    if ro["status"] != "INTAKE":
        raise err("ERR_INVALID_STATE", "repair not INTAKE")
    product = core.products[ro["product_id"]]
    if product["status"] == "RECALLED":
        raise err("ERR_PRODUCT_RECALLED", "product recalled")
    lines = repair_line_list(rid)
    if not lines:
        raise err("ERR_NO_REPAIR_LINES", "no repair lines")
    ro["pay_mode"] = repair_pay_mode(ro)
    lines_total = 0
    for line in lines:
        raw = round_half_up(Decimal(LABOR_RATE[line["repair_type"]])
                            * Decimal(str(line["labor_hours"]))
                            * COMPLEXITY_MULT[line["complexity"]])
        line_labor = min(MAX_LABOR_CENTS, max(MIN_LABOR_CENTS, raw))
        line["line_labor_cents"] = line_labor
        line["line_total_cents"] = line_labor + line["parts_cost_cents"]
        lines_total += line["line_total_cents"]
        touch(line)
    if ro["pay_mode"] == "CUSTOMER_PAY":
        ro["quoted_total_cents"] = lines_total + DIAGNOSTIC_FEE_CENTS
        ro["warranty_cost_cents"] = 0
    else:
        ro["quoted_total_cents"] = 0
        ro["warranty_cost_cents"] = lines_total
    ro["status"] = "QUOTED"
    touch(ro)
    return obj_response(ro)


@app.route("/store/repair-orders/<rid>/approve", methods=["POST"])
def repair_approve(rid):
    uid, role = identity()
    require_role(role, {"Customer", "Manager"})
    ro = get_existing(core.repair_orders, rid)
    if role == "Customer" and ro["customer_id"] != uid:
        raise err("ERR_FORBIDDEN", "not owner")
    if ro["status"] != "QUOTED":
        raise err("ERR_INVALID_STATE", "repair not QUOTED")
    if core.products[ro["product_id"]]["status"] == "RECALLED":
        raise err("ERR_PRODUCT_RECALLED", "product recalled")
    ro["status"] = "APPROVED"
    touch(ro)
    return obj_response(ro)


@app.route("/store/repair-orders/<rid>/decline", methods=["POST"])
def repair_decline(rid):
    uid, role = identity()
    require_role(role, {"Customer", "Manager"})
    ro = get_existing(core.repair_orders, rid)
    if role == "Customer" and ro["customer_id"] != uid:
        raise err("ERR_FORBIDDEN", "not owner")
    if ro["status"] != "QUOTED":
        raise err("ERR_INVALID_STATE", "repair not QUOTED")
    ro["status"] = "DECLINED"
    touch(ro)
    return obj_response(ro)


@app.route("/store/repair-orders/<rid>/schedule", methods=["POST"])
def repair_schedule(rid):
    _, role = identity()
    require_role(role, {"Manager", "Associate"})
    ro = get_existing(core.repair_orders, rid)
    data = body()
    require_present(data, ["bench_id", "bench_start", "bench_end"])
    bench = get_existing(core.benches, data["bench_id"])
    if ro["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "repair not APPROVED")
    try:
        start = parse_iso(data["bench_start"])
        end = parse_iso(data["bench_end"])
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "bad bench window")
    if not (start < end):
        raise err("ERR_INVALID_REQUEST", "bench_start must be before bench_end")
    if bench_conflict(bench["id"], start, end, ro["id"]):
        raise err("ERR_SCHEDULE_CONFLICT", "bench window conflict")
    ro["bench_id"] = bench["id"]
    ro["bench_start"] = start
    ro["bench_end"] = end
    ro["status"] = "SCHEDULED"
    touch(ro)
    return obj_response(ro)


def _repair_transition(rid, from_status, to_status):
    _, role = identity()
    require_role(role, {"Manager", "Associate"})
    ro = get_existing(core.repair_orders, rid)
    if ro["status"] != from_status:
        raise err("ERR_INVALID_STATE", "repair not %s" % from_status)
    ro["status"] = to_status
    touch(ro)
    return ro


@app.route("/store/repair-orders/<rid>/start", methods=["POST"])
def repair_start(rid):
    return obj_response(_repair_transition(rid, "SCHEDULED", "IN_REPAIR"))


@app.route("/store/repair-orders/<rid>/parts-hold", methods=["POST"])
def repair_parts_hold(rid):
    return obj_response(_repair_transition(rid, "IN_REPAIR", "PARTS_HOLD"))


@app.route("/store/repair-orders/<rid>/resume", methods=["POST"])
def repair_resume(rid):
    return obj_response(_repair_transition(rid, "PARTS_HOLD", "IN_REPAIR"))


@app.route("/store/repair-orders/<rid>/ready", methods=["POST"])
def repair_ready(rid):
    return obj_response(_repair_transition(rid, "IN_REPAIR", "READY"))


@app.route("/store/repair-orders/<rid>/close", methods=["POST"])
def repair_close(rid):
    _, role = identity()
    require_role(role, {"Manager", "Associate"})
    ro = get_existing(core.repair_orders, rid)
    if ro["status"] != "READY":
        raise err("ERR_INVALID_STATE", "repair not READY")
    ro["status"] = "CLOSED"
    touch(ro)
    if ro["pay_mode"] == "CUSTOMER_PAY":
        customer = core.customers.get(ro["customer_id"])
        if customer:
            customer["points_balance"] += floor_div_100(ro["quoted_total_cents"])
            recompute_customer_tier(customer)
            touch(customer)
    return obj_response(ro)


# ===========================================================================
# Repair Lines
# ===========================================================================
@app.route("/store/repair-lines", methods=["POST"])
def create_repair_line():
    _, role = identity()
    require_role(role, {"Manager", "Associate"})
    data = body()
    require_present(data, ["repair_order_id", "repair_type", "labor_hours", "parts_cost_cents"])
    ro = get_existing(core.repair_orders, data["repair_order_id"])
    if ro["status"] != "INTAKE":
        raise err("ERR_INVALID_STATE", "repair order not INTAKE")
    check_enum(data["repair_type"], REPAIR_TYPES, "repair_type")
    complexity = data.get("complexity", "STANDARD")
    if complexity is None:
        complexity = "STANDARD"
    check_enum(complexity, COMPLEXITIES, "complexity")
    labor_hours = require_number(data, "labor_hours")
    if labor_hours < 0:
        raise err("ERR_VALIDATION_RANGE", "labor_hours must be non-negative")
    parts_cost = require_nonneg_int(data, "parts_cost_cents")
    rec = create_record(core.repair_lines, {
        "repair_order_id": ro["id"], "repair_type": data["repair_type"],
        "labor_hours": labor_hours, "complexity": complexity,
        "parts_cost_cents": parts_cost, "line_labor_cents": 0, "line_total_cents": 0,
    })
    return obj_response(rec, 201)


@app.route("/store/repair-lines/<lid>", methods=["GET"])
def get_repair_line(lid):
    uid, role = identity()
    require_role(role, {"Manager", "Associate", "Customer"})
    line = get_existing(core.repair_lines, lid)
    if role == "Customer":
        ro = core.repair_orders.get(line["repair_order_id"])
        if not ro or ro["customer_id"] != uid:
            raise err("ERR_FORBIDDEN", "not owner")
    return obj_response(line)


@app.route("/store/repair-lines", methods=["GET"])
def list_repair_lines():
    uid, role = identity()
    require_role(role, {"Manager", "Associate", "Customer"})
    items = list(core.repair_lines.values())
    roid = request.args.get("repair_order_id")
    if roid is not None:
        items = [l for l in items if l["repair_order_id"] == roid]
    if role == "Customer":
        items = [l for l in items
                 if core.repair_orders.get(l["repair_order_id"], {}).get("customer_id") == uid]
    page, limit, offset, total = paginate(items)
    return list_response(page, limit, offset, total)


# ===========================================================================
# Sales Orders
# ===========================================================================
@app.route("/store/sales-orders", methods=["POST"])
def create_sales_order():
    uid, role = identity()
    require_role(role, {"Manager", "Associate", "Customer"})
    data = body()
    require_present(data, ["customer_id"])
    if role == "Customer" and data["customer_id"] != uid:
        raise err("ERR_FORBIDDEN", "not owner")
    customer = get_existing(core.customers, data["customer_id"])
    is_gift = data.get("is_gift", False)
    if is_gift is None:
        is_gift = False
    if not isinstance(is_gift, bool):
        raise err("ERR_INVALID_REQUEST", "is_gift must be boolean")
    rec = create_record(core.sales_orders, {
        "customer_id": customer["id"], "is_gift": is_gift,
        "gift_message": data.get("gift_message"),
        "subtotal_cents": 0, "loyalty_discount_cents": 0, "tax_cents": 0,
        "gift_wrap_fee_cents": GIFT_WRAP_FEE_CENTS if is_gift else 0,
        "total_cents": 0, "provisional_points": 0, "points_credited": 0,
        "payment_status": "PENDING", "fulfillment_status": "UNFULFILLED",
        "_tier_at_creation": customer["tier"],
    })
    return obj_response(rec, 201)


@app.route("/store/sales-orders/<sid>", methods=["GET"])
def get_sales_order(sid):
    uid, role = identity()
    require_role(role, {"Manager", "Associate", "Customer"})
    so = get_existing(core.sales_orders, sid)
    if role == "Customer" and so["customer_id"] != uid:
        raise err("ERR_FORBIDDEN", "not owner")
    return obj_response(so)


@app.route("/store/sales-orders", methods=["GET"])
def list_sales_orders():
    uid, role = identity()
    require_role(role, {"Manager", "Associate", "Customer"})
    items = list(core.sales_orders.values())
    cid = request.args.get("customer_id")
    if cid is not None:
        items = [s for s in items if s["customer_id"] == cid]
    if role == "Customer":
        items = [s for s in items if s["customer_id"] == uid]
    page, limit, offset, total = paginate(items)
    return list_response(page, limit, offset, total)


@app.route("/store/sales-orders/<sid>/capture", methods=["POST"])
def sales_capture(sid):
    _, role = identity()
    require_role(role, {"Manager", "Associate"})
    so = get_existing(core.sales_orders, sid)
    if so["payment_status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "order not PENDING")
    lines = lines_of_order(sid)
    if not lines:
        raise err("ERR_INVALID_STATE", "order has no lines")
    for line in lines:
        product = core.products.get(line["product_id"])
        if product and product["status"] == "RECALLED":
            raise err("ERR_PRODUCT_RECALLED", "line references recalled product")
    customer = core.customers[so["customer_id"]]
    net = so["subtotal_cents"] - so["loyalty_discount_cents"]
    credited = points_for(net, customer["tier"])
    so["points_credited"] = credited
    so["payment_status"] = "CAPTURED"
    touch(so)
    customer["points_balance"] += credited
    customer["lifetime_spend_cents"] += net
    recompute_customer_tier(customer)
    touch(customer)
    return obj_response(so)


@app.route("/store/sales-orders/<sid>/refund", methods=["POST"])
def sales_refund(sid):
    _, role = identity()
    require_role(role, {"Manager"})
    so = get_existing(core.sales_orders, sid)
    if so["payment_status"] != "CAPTURED":
        raise err("ERR_INVALID_STATE", "order not CAPTURED")
    customer = core.customers[so["customer_id"]]
    net = so["subtotal_cents"] - so["loyalty_discount_cents"]
    so["payment_status"] = "REFUNDED"
    touch(so)
    customer["points_balance"] -= so["points_credited"]
    customer["lifetime_spend_cents"] -= net
    recompute_customer_tier(customer)
    touch(customer)
    return obj_response(so)


@app.route("/store/sales-orders/<sid>/fulfill", methods=["POST"])
def sales_fulfill(sid):
    _, role = identity()
    require_role(role, {"Manager", "Associate"})
    so = get_existing(core.sales_orders, sid)
    if so["fulfillment_status"] != "UNFULFILLED":
        raise err("ERR_INVALID_STATE", "order not UNFULFILLED")
    if so["payment_status"] != "CAPTURED":
        raise err("ERR_INVALID_STATE", "order not CAPTURED")
    for line in lines_of_order(sid):
        if line.get("monogram_text") and line["monogram_status"] != "DONE":
            raise err("ERR_MONOGRAM_PENDING", "monogram not done")
    so["fulfillment_status"] = "FULFILLED"
    touch(so)
    return obj_response(so)


@app.route("/store/sales-orders/<sid>/cancel", methods=["POST"])
def sales_cancel(sid):
    _, role = identity()
    require_role(role, {"Manager", "Associate"})
    so = get_existing(core.sales_orders, sid)
    if so["fulfillment_status"] != "UNFULFILLED":
        raise err("ERR_INVALID_STATE", "order not UNFULFILLED")
    so["fulfillment_status"] = "CANCELLED"
    touch(so)
    return obj_response(so)


# ===========================================================================
# Sales Order Lines
# ===========================================================================
@app.route("/store/sales-order-lines", methods=["POST"])
def create_sales_order_line():
    uid, role = identity()
    require_role(role, {"Manager", "Associate", "Customer"})
    data = body()
    require_present(data, ["sales_order_id", "product_id", "unit_price_cents", "qty"])
    so = get_existing(core.sales_orders, data["sales_order_id"])
    product = get_existing(core.products, data["product_id"])
    if role == "Customer" and so["customer_id"] != uid:
        raise err("ERR_FORBIDDEN", "not owner")
    if so["payment_status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "order not PENDING")
    unit_price = require_nonneg_int(data, "unit_price_cents")
    qty = require_int(data, "qty")
    if qty < 1:
        raise err("ERR_VALIDATION_RANGE", "qty must be >= 1")
    pct = data.get("line_discount_pct", 0)
    if pct is None:
        pct = 0
    if isinstance(pct, bool) or not isinstance(pct, (int, float)):
        raise err("ERR_INVALID_REQUEST", "line_discount_pct must be a number")
    if pct < 0 or pct > 1:
        raise err("ERR_VALIDATION_RANGE", "line_discount_pct out of range")
    monogram_text = data.get("monogram_text")
    monogram_fee = MONOGRAM_FEE_CENTS if monogram_text else 0
    base = round_half_up(Decimal(unit_price) * Decimal(qty) * (Decimal(1) - Decimal(str(pct))))
    line_subtotal = base + monogram_fee
    rec = create_record(core.sales_order_lines, {
        "sales_order_id": so["id"], "product_id": product["id"],
        "monogram_station_id": None, "unit_price_cents": unit_price, "qty": qty,
        "line_discount_pct": pct, "monogram_text": monogram_text,
        "monogram_fee_cents": monogram_fee, "line_subtotal_cents": line_subtotal,
        "monogram_start": None, "monogram_end": None,
        "monogram_status": "QUEUED" if monogram_text else "NONE",
    })
    recompute_sales_order(so)
    return obj_response(rec, 201)


@app.route("/store/sales-order-lines/<lid>", methods=["GET"])
def get_sales_order_line(lid):
    uid, role = identity()
    require_role(role, {"Manager", "Associate", "Customer"})
    line = get_existing(core.sales_order_lines, lid)
    if role == "Customer":
        so = core.sales_orders.get(line["sales_order_id"])
        if not so or so["customer_id"] != uid:
            raise err("ERR_FORBIDDEN", "not owner")
    return obj_response(line)


@app.route("/store/sales-order-lines", methods=["GET"])
def list_sales_order_lines():
    uid, role = identity()
    require_role(role, {"Manager", "Associate", "Customer"})
    items = list(core.sales_order_lines.values())
    for key in ("sales_order_id", "product_id", "monogram_station_id"):
        val = request.args.get(key)
        if val is not None:
            items = [l for l in items if l.get(key) == val]
    if role == "Customer":
        items = [l for l in items
                 if core.sales_orders.get(l["sales_order_id"], {}).get("customer_id") == uid]
    page, limit, offset, total = paginate(items)
    return list_response(page, limit, offset, total)


@app.route("/store/sales-order-lines/<lid>/schedule-monogram", methods=["POST"])
def schedule_monogram(lid):
    _, role = identity()
    require_role(role, {"Manager", "Associate"})
    line = get_existing(core.sales_order_lines, lid)
    data = body()
    require_present(data, ["monogram_station_id", "monogram_start", "monogram_end"])
    station = get_existing(core.stations, data["monogram_station_id"])
    if line["monogram_status"] != "QUEUED":
        raise err("ERR_INVALID_STATE", "line monogram not QUEUED")
    try:
        start = parse_iso(data["monogram_start"])
        end = parse_iso(data["monogram_end"])
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "bad monogram window")
    if not (start < end):
        raise err("ERR_INVALID_REQUEST", "monogram_start must be before monogram_end")
    if station_conflict(station["id"], start, end, line["id"]):
        raise err("ERR_SCHEDULE_CONFLICT", "station window conflict")
    line["monogram_station_id"] = station["id"]
    line["monogram_start"] = start
    line["monogram_end"] = end
    line["monogram_status"] = "SCHEDULED"
    touch(line)
    return obj_response(line)


@app.route("/store/sales-order-lines/<lid>/start-monogram", methods=["POST"])
def start_monogram(lid):
    _, role = identity()
    require_role(role, {"Manager", "Associate"})
    line = get_existing(core.sales_order_lines, lid)
    if line["monogram_status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "line monogram not SCHEDULED")
    so = core.sales_orders[line["sales_order_id"]]
    if so["payment_status"] != "CAPTURED":
        raise err("ERR_ORDER_NOT_CAPTURED", "order not captured")
    line["monogram_status"] = "IN_PROGRESS"
    touch(line)
    return obj_response(line)


@app.route("/store/sales-order-lines/<lid>/complete-monogram", methods=["POST"])
def complete_monogram(lid):
    _, role = identity()
    require_role(role, {"Manager", "Associate"})
    line = get_existing(core.sales_order_lines, lid)
    if line["monogram_status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "line monogram not IN_PROGRESS")
    line["monogram_status"] = "DONE"
    touch(line)
    return obj_response(line)


# ===========================================================================
# Trade-Ins
# ===========================================================================
@app.route("/store/trade-ins", methods=["POST"])
def create_trade_in():
    _, role = identity()
    require_role(role, {"Manager", "Associate"})
    data = body()
    require_present(data, ["customer_id", "product_id", "expected_customer_version", "condition"])
    customer = get_existing(core.customers, data["customer_id"])
    product = get_existing(core.products, data["product_id"])
    expected = data["expected_customer_version"]
    if expected != customer["version"]:
        raise err("ERR_STALE_VERSION", "stale customer version")
    check_enum(data["condition"], CONDITIONS, "condition")
    # supersede prior OFFERED trade-in for same customer+product
    for ti in core.trade_ins.values():
        if (ti["customer_id"] == customer["id"] and ti["product_id"] == product["id"]
                and ti["status"] == "OFFERED"):
            ti["status"] = "SUPERSEDED"
            touch(ti)
    touch(customer)  # increments customer version by 1
    raw = round_half_up(Decimal(product["msrp_cents"]) * CONDITION_FACTOR[data["condition"]])
    offer = max(MIN_TRADE_CENTS, raw)
    from datetime import timedelta
    created = now()
    expires = created + timedelta(days=TRADE_IN_OFFER_DAYS)
    rec = create_record(core.trade_ins, {
        "customer_id": customer["id"], "product_id": product["id"],
        "expected_customer_version": expected, "condition": data["condition"],
        "offer_amount_cents": offer, "expires_at": expires, "status": "OFFERED",
    })
    return obj_response(rec, 201)


@app.route("/store/trade-ins/<tid>", methods=["GET"])
def get_trade_in(tid):
    uid, role = identity()
    require_role(role, {"Manager", "Associate", "Customer"})
    ti = get_existing(core.trade_ins, tid)
    if role == "Customer" and ti["customer_id"] != uid:
        raise err("ERR_FORBIDDEN", "not owner")
    return obj_response(ti)


@app.route("/store/trade-ins", methods=["GET"])
def list_trade_ins():
    uid, role = identity()
    require_role(role, {"Manager", "Associate", "Customer"})
    items = list(core.trade_ins.values())
    for key in ("customer_id", "product_id"):
        val = request.args.get(key)
        if val is not None:
            items = [t for t in items if t.get(key) == val]
    if role == "Customer":
        items = [t for t in items if t["customer_id"] == uid]
    page, limit, offset, total = paginate(items)
    return list_response(page, limit, offset, total)


@app.route("/store/trade-ins/<tid>/accept", methods=["POST"])
def accept_trade_in(tid):
    _, role = identity()
    require_role(role, {"Manager"})
    ti = get_existing(core.trade_ins, tid)
    if ti["status"] != "OFFERED":
        raise err("ERR_INVALID_STATE", "trade-in not OFFERED")
    if now() >= ti["expires_at"]:
        ti["status"] = "EXPIRED"
        touch(ti)
        raise err("ERR_OFFER_EXPIRED", "offer expired")
    ti["status"] = "ACCEPTED"
    touch(ti)
    customer = core.customers.get(ti["customer_id"])
    if customer:
        customer["store_credit_cents"] += ti["offer_amount_cents"]
        touch(customer)
    return obj_response(ti)


@app.route("/store/trade-ins/<tid>/decline", methods=["POST"])
def decline_trade_in(tid):
    uid, role = identity()
    require_role(role, {"Manager", "Associate", "Customer"})
    ti = get_existing(core.trade_ins, tid)
    if role == "Customer" and ti["customer_id"] != uid:
        raise err("ERR_FORBIDDEN", "not owner")
    if ti["status"] != "OFFERED":
        raise err("ERR_INVALID_STATE", "trade-in not OFFERED")
    ti["status"] = "DECLINED"
    touch(ti)
    return obj_response(ti)


@app.route("/store/trade-ins/<tid>/void", methods=["POST"])
def void_trade_in(tid):
    _, role = identity()
    require_role(role, {"Manager"})
    ti = get_existing(core.trade_ins, tid)
    if ti["status"] != "ACCEPTED":
        raise err("ERR_INVALID_STATE", "trade-in not ACCEPTED")
    ti["status"] = "VOIDED"
    touch(ti)
    customer = core.customers.get(ti["customer_id"])
    if customer:
        customer["store_credit_cents"] -= ti["offer_amount_cents"]
        touch(customer)
    return obj_response(ti)


# ===========================================================================
# Special Orders
# ===========================================================================
@app.route("/store/special-orders", methods=["POST"])
def create_special_order():
    uid, role = identity()
    require_role(role, {"Manager", "Associate", "Customer"})
    data = body()
    require_present(data, ["customer_id", "product_id", "quantity"])
    if role == "Customer" and data["customer_id"] != uid:
        raise err("ERR_FORBIDDEN", "not owner")
    customer = get_existing(core.customers, data["customer_id"])
    product = get_existing(core.products, data["product_id"])
    quantity = require_int(data, "quantity")
    if quantity < 1:
        raise err("ERR_VALIDATION_RANGE", "quantity must be >= 1")
    deposit = data.get("deposit_cents", 0)
    if deposit is None:
        deposit = 0
    if isinstance(deposit, bool) or not isinstance(deposit, int):
        raise err("ERR_INVALID_REQUEST", "deposit_cents must be an integer")
    if deposit < 0:
        raise err("ERR_VALIDATION_RANGE", "deposit_cents must be non-negative")
    rec = create_record(core.special_orders, {
        "customer_id": customer["id"], "product_id": product["id"],
        "quantity": quantity, "deposit_cents": deposit, "status": "REQUESTED",
    })
    return obj_response(rec, 201)


@app.route("/store/special-orders/<soid>", methods=["GET"])
def get_special_order(soid):
    uid, role = identity()
    require_role(role, {"Manager", "Associate", "Customer"})
    so = get_existing(core.special_orders, soid)
    if role == "Customer" and so["customer_id"] != uid:
        raise err("ERR_FORBIDDEN", "not owner")
    return obj_response(so)


@app.route("/store/special-orders", methods=["GET"])
def list_special_orders():
    uid, role = identity()
    require_role(role, {"Manager", "Associate", "Customer"})
    items = list(core.special_orders.values())
    for key in ("customer_id", "product_id"):
        val = request.args.get(key)
        if val is not None:
            items = [s for s in items if s.get(key) == val]
    if role == "Customer":
        items = [s for s in items if s["customer_id"] == uid]
    page, limit, offset, total = paginate(items)
    return list_response(page, limit, offset, total)


@app.route("/store/special-orders/<soid>/source", methods=["POST"])
def special_source(soid):
    _, role = identity()
    require_role(role, {"Manager", "Associate"})
    so = get_existing(core.special_orders, soid)
    if so["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "special order not REQUESTED")
    if core.products[so["product_id"]]["status"] == "RECALLED":
        raise err("ERR_PRODUCT_RECALLED", "product recalled")
    so["status"] = "SOURCED"
    touch(so)
    return obj_response(so)


@app.route("/store/special-orders/<soid>/arrive", methods=["POST"])
def special_arrive(soid):
    _, role = identity()
    require_role(role, {"Manager", "Associate"})
    so = get_existing(core.special_orders, soid)
    if so["status"] != "SOURCED":
        raise err("ERR_INVALID_STATE", "special order not SOURCED")
    so["status"] = "ARRIVED"
    touch(so)
    return obj_response(so)


@app.route("/store/special-orders/<soid>/fulfill", methods=["POST"])
def special_fulfill(soid):
    _, role = identity()
    require_role(role, {"Manager", "Associate"})
    so = get_existing(core.special_orders, soid)
    if so["status"] != "ARRIVED":
        raise err("ERR_INVALID_STATE", "special order not ARRIVED")
    so["status"] = "FULFILLED"
    touch(so)
    return obj_response(so)


@app.route("/store/special-orders/<soid>/cancel", methods=["POST"])
def special_cancel(soid):
    _, role = identity()
    require_role(role, {"Manager", "Associate"})
    so = get_existing(core.special_orders, soid)
    if so["status"] not in ("REQUESTED", "SOURCED"):
        raise err("ERR_INVALID_STATE", "special order not cancellable")
    so["status"] = "CANCELLED"
    touch(so)
    return obj_response(so)


# ===========================================================================
# Recall Notices
# ===========================================================================
@app.route("/store/recall-notices", methods=["POST"])
def create_recall_notice():
    _, role = identity()
    require_role(role, {"Manager"})
    data = body()
    require_present(data, ["product_id", "reason", "remedy"])
    product = get_existing(core.products, data["product_id"])
    check_enum(data["remedy"], REMEDIES, "remedy")
    rec = create_record(core.recall_notices, {
        "product_id": product["id"], "reason": data["reason"],
        "remedy": data["remedy"], "status": "DRAFT",
    })
    return obj_response(rec, 201)


@app.route("/store/recall-notices/<nid>", methods=["GET"])
def get_recall_notice(nid):
    _, role = identity()
    require_role(role, {"Manager", "Associate", "Customer"})
    return obj_response(get_existing(core.recall_notices, nid))


@app.route("/store/recall-notices", methods=["GET"])
def list_recall_notices():
    _, role = identity()
    require_role(role, {"Manager", "Associate", "Customer"})
    items = list(core.recall_notices.values())
    pid = request.args.get("product_id")
    if pid is not None:
        items = [n for n in items if n["product_id"] == pid]
    page, limit, offset, total = paginate(items)
    return list_response(page, limit, offset, total)


@app.route("/store/recall-notices/<nid>/publish", methods=["POST"])
def publish_recall(nid):
    _, role = identity()
    require_role(role, {"Manager"})
    notice = get_existing(core.recall_notices, nid)
    if notice["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "notice not DRAFT")
    product = core.products[notice["product_id"]]
    if product["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "product not ACTIVE")
    notice["status"] = "PUBLISHED"
    touch(notice)
    cascade_product_recalled(product)
    return obj_response(notice)


@app.route("/store/recall-notices/<nid>/close", methods=["POST"])
def close_recall(nid):
    _, role = identity()
    require_role(role, {"Manager"})
    notice = get_existing(core.recall_notices, nid)
    if notice["status"] != "PUBLISHED":
        raise err("ERR_INVALID_STATE", "notice not PUBLISHED")
    notice["status"] = "CLOSED"
    touch(notice)
    product = core.products.get(notice["product_id"])
    if product and product["status"] == "RECALLED":
        cascade_product_reactivated(product)
    return obj_response(notice)


# ===========================================================================
# Service Benches
# ===========================================================================
@app.route("/store/service-benches", methods=["POST"])
def create_bench():
    _, role = identity()
    require_role(role, {"Manager"})
    data = body()
    require_present(data, ["label", "skill"])
    check_enum(data["skill"], BENCH_SKILLS, "skill")
    rec = create_record(core.benches, {"label": data["label"], "skill": data["skill"]},
                        common=False)
    return obj_response(rec, 201)


@app.route("/store/service-benches/<bid>", methods=["GET"])
def get_bench(bid):
    _, role = identity()
    require_role(role, {"Manager", "Associate"})
    return obj_response(get_existing(core.benches, bid))


@app.route("/store/service-benches", methods=["GET"])
def list_benches():
    _, role = identity()
    require_role(role, {"Manager", "Associate"})
    page, limit, offset, total = paginate(list(core.benches.values()))
    return list_response(page, limit, offset, total)


# ===========================================================================
# Monogram Stations
# ===========================================================================
@app.route("/store/monogram-stations", methods=["POST"])
def create_station():
    _, role = identity()
    require_role(role, {"Manager"})
    data = body()
    require_present(data, ["label", "method"])
    check_enum(data["method"], STATION_METHODS, "method")
    rec = create_record(core.stations, {"label": data["label"], "method": data["method"]},
                        common=False)
    return obj_response(rec, 201)


@app.route("/store/monogram-stations/<mid>", methods=["GET"])
def get_station(mid):
    _, role = identity()
    require_role(role, {"Manager", "Associate"})
    return obj_response(get_existing(core.stations, mid))


@app.route("/store/monogram-stations", methods=["GET"])
def list_stations():
    _, role = identity()
    require_role(role, {"Manager", "Associate"})
    page, limit, offset, total = paginate(list(core.stations.values()))
    return list_response(page, limit, offset, total)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
