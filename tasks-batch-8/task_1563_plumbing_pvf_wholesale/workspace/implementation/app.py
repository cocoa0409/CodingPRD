#!/usr/bin/env python3
"""Plumbing & PVF Wholesale Distribution API — Flask implementation.

Single-file, in-memory implementation. State resets on every boot (the harness
restarts the server before each test). Logical clock starts at
2026-08-01T00:00:00Z and is advanced only via POST /pvf/_clock/set_current_utc.
"""

import math
import os
import re
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

API_PREFIX = "/pvf"
ROLES = {"BranchManager", "CounterRep", "InsideSales", "WarehouseLead", "Contractor"}

TIER_DISCOUNT_PCT = {"STANDARD": 0, "SILVER": 5, "GOLD": 10, "PLATINUM": 15}
MIN_MARGIN_PCT = 5
VOLUME_TIERS = [(2000000, 5), (500000, 2)]  # descending threshold, highest qualifying applies
FREIGHT_FREE_THRESHOLD_CENTS = 50000
FLAT_FREIGHT_CENTS = 2500
HOLD_RELEASE_RATIO = Decimal("0.80")
TERMS_DAYS = {"COD": 0, "NET_15": 15, "NET_30": 30}
RESTOCK_FEE_TIER1_DAYS = 30
RESTOCK_FEE_TIER1_PCT = 10
RESTOCK_FEE_TIER2_DAYS = 90
RESTOCK_FEE_TIER2_PCT = 25
RETURN_WINDOW_DAYS = 90
WILL_CALL_BUFFER_HOURS = 2

PRODUCT_CATEGORIES = {"PIPE", "VALVE", "FITTING", "FIXTURE"}
PRICING_TIERS = {"STANDARD", "SILVER", "GOLD", "PLATINUM"}
TERMS = {"COD", "NET_15", "NET_30"}
PAYMENT_METHODS = {"CHECK", "ACH", "CARD"}
CREDIT_REVIEW_ACTIONS = {"RELEASE_HOLD", "SUSPEND", "ADJUST_LIMIT"}
DECISIONS = {"APPROVE", "REJECT"}
ACCOUNT_STATUS_FILTER = {"ACTIVE", "CREDIT_HOLD", "SUSPENDED"}
QUOTE_STATUS_FILTER = {"DRAFT", "SUBMITTED", "AWARDED", "REVISED", "LOST", "EXPIRED", "CONVERTED"}
SHEET_STATUS_FILTER = {"DRAFT", "PRESENTED", "APPROVED", "REVISED", "ORDERED"}
PROGRAM_STATUS_FILTER = {"ACTIVE", "CLOSED", "SETTLED"}
FULFILLMENT_STATUS_FILTER = {
    "DRAFT", "OPEN", "PICKING", "STAGED", "DISPATCHED", "DELIVERED", "PICKED_UP", "CANCELLED"
}

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------

store = {
    "branches": {},
    "products": {},
    "accounts": {},
    "programs": {},
    "stock": {},
    "receipts": {},
    "payments": {},
    "quotes": {},
    "sheets": {},
    "orders": {},
    "order_lines": {},
    "kits": {},
    "slots": {},
    "returns": {},
    "allocations": [],  # [{order_id, payment_id, amount_cents}]
}

_logical_clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def now_wall():
    return datetime.now(timezone.utc)


def now_ms(dt=None):
    dt = dt or now_wall()
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def clock_iso():
    c = _logical_clock
    base = c.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    frac = c.strftime(".%f")[:7].rstrip("0").rstrip(".")
    return base + frac + "Z"


ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")


def parse_dt(value):
    """Parse an ISO-8601 datetime string; return None if not valid."""
    if not isinstance(value, str):
        return None
    if not ISO_RE.match(value):
        return None
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc)


def round_half_up(numer, denom=100):
    """Round numer/denom to an integer using ROUND_HALF_UP."""
    return int((Decimal(numer) / Decimal(denom)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def err(error_id, status, message):
    raise ApiError(error_id, status, message)


def envelope(data, response_type, status=200, pagination=None):
    meta = {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": now_ms(),
    }
    if pagination:
        meta.update(pagination)
    return {"meta": meta, "response_type": response_type, "data": data}, status


def ok(data, status=200):
    return envelope(data, "object", status)


def list_response(items, status=200):
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return envelope(page, "array", status, pagination)


def parse_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            err("ERR_INVALID_REQUEST", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            err("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            err("ERR_INVALID_REQUEST", 400, "offset must be an integer")
        if offset < 0:
            err("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    return limit, offset


def sorted_created(items):
    return sorted(items, key=lambda r: (r["created_at"], r["id"]))


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": {
            "api_request_id": "req_" + uuid.uuid4().hex[:24],
            "api_request_timestamp": now_ms(),
        },
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return body, e.status


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": {
            "api_request_id": "req_" + uuid.uuid4().hex[:24],
            "api_request_timestamp": now_ms(),
        },
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST", "message": "Route not found"},
    }
    return body, 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": {
            "api_request_id": "req_" + uuid.uuid4().hex[:24],
            "api_request_timestamp": now_ms(),
        },
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST", "message": "Method not allowed"},
    }
    return body, 405


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def require_roles(*roles):
    """Pipeline steps 1-2: authentication and role authorization."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        err("ERR_UNAUTHENTICATED", 401, "Missing or unrecognized X-User-Role / X-User-ID headers")
    if role not in roles:
        err("ERR_FORBIDDEN", 403, "Role not permitted on this endpoint")
    return user_id, role


def check_contractor_scope(user_id, role, account_id):
    """Pipeline step 3: Contractor ownership scope."""
    if role == "Contractor" and user_id != account_id:
        err("ERR_FORBIDDEN", 403, "Contractor acting outside its own account scope")


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        err("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            err("ERR_INVALID_REQUEST", 400, f"Missing required field: {f}")


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def check_int(value, name, minimum=None):
    if not is_int(value):
        err("ERR_INVALID_REQUEST", 400, f"{name} must be an integer")
    if minimum is not None and value < minimum:
        err("ERR_INVALID_REQUEST", 400, f"{name} must be >= {minimum}")


def check_enum(value, allowed, name):
    if value not in allowed:
        err("ERR_INVALID_REQUEST", 400, f"{name} must be one of {sorted(allowed)}")


# ---------------------------------------------------------------------------
# Fetch helpers (pipeline step 5: path ids resolve)
# ---------------------------------------------------------------------------

NOT_FOUND = {
    "branches": ("ERR_BRANCH_NOT_FOUND", "branch"),
    "products": ("ERR_PRODUCT_NOT_FOUND", "product"),
    "accounts": ("ERR_ACCOUNT_NOT_FOUND", "account"),
    "programs": ("ERR_PROGRAM_NOT_FOUND", "program"),
    "quotes": ("ERR_QUOTE_NOT_FOUND", "quote"),
    "sheets": ("ERR_SHEET_NOT_FOUND", "selection sheet"),
    "orders": ("ERR_ORDER_NOT_FOUND", "order"),
    "order_lines": ("ERR_ORDER_LINE_NOT_FOUND", "order line"),
    "kits": ("ERR_KIT_NOT_FOUND", "kit"),
    "slots": ("ERR_SLOT_NOT_FOUND", "delivery slot"),
    "returns": ("ERR_RETURN_NOT_FOUND", "return request"),
}


def fetch(collection, rid):
    rec = store[collection].get(rid)
    if rec is None:
        eid, label = NOT_FOUND[collection]
        err(eid, 404, f"{label} not found")
    return rec


def get_or_none(collection, rid):
    if rid is None:
        return None
    return store[collection].get(rid)


# ---------------------------------------------------------------------------
# Record factory
# ---------------------------------------------------------------------------


def new_record(collection, **fields):
    rec = {
        "id": str(uuid.uuid4()),
        "created_at": now_ms(),
        "updated_at": now_ms(),
        "version": 1,
    }
    rec.update(fields)
    store[collection][rec["id"]] = rec
    return rec


def touch(rec):
    rec["version"] += 1
    rec["updated_at"] = now_ms()


# ---------------------------------------------------------------------------
# Domain services
# ---------------------------------------------------------------------------


def stock_available(stock_rec):
    return stock_rec["on_hand"] - stock_rec["reserved"]


def get_stock(branch_id, product_id):
    for s in store["stock"].values():
        if s["branch_id"] == branch_id and s["product_id"] == product_id:
            return s
    return None


def price_floor_cents(product):
    # ceil(cost * 1.05): smallest whole-cent >= 105% of cost
    return math.ceil(product["cost_cents"] * 105 / 100)


def resolve_counter_price(account, product, price_override):
    """Return (unit_price_cents, price_source) for a COUNTER order line."""
    if price_override is not None:
        check_int(price_override, "price_override_cents", 1)
        floor = price_floor_cents(product)
        if price_override < floor:
            err("ERR_PRICE_FLOOR_VIOLATION", 422, "Price override below the price floor")
        return price_override, "MANUAL_OVERRIDE"
    tier_pct = TIER_DISCOUNT_PCT[account["pricing_tier"]]
    tier_price = round_half_up(product["list_price_cents"] * (100 - tier_pct), 100)
    if product.get("promo_price_cents") is not None:
        if product["promo_price_cents"] < tier_price:
            return product["promo_price_cents"], "PROMO"
        return tier_price, "COUNTER_TIER"
    return tier_price, "COUNTER_TIER"


def line_extension(line, product):
    ext = line["qty_ordered"] * line["unit_price_cents"]
    if product["is_cut_to_order"]:
        ext *= line["cut_length_ft"]
    return ext


def select_volume_tier(subtotal_cents):
    for threshold, pct in VOLUME_TIERS:
        if subtotal_cents >= threshold:
            return pct
    return 0


def compute_quote_totals(quote):
    lines = quote["lines"]
    subtotal = 0
    for ln in lines:
        subtotal += ln["qty"] * ln["unit_price_cents"]
    pct = select_volume_tier(subtotal)
    discount = round_half_up(subtotal * pct, 100)
    post = subtotal - discount
    freight = 0 if post >= FREIGHT_FREE_THRESHOLD_CENTS else FLAT_FREIGHT_CENTS
    quote["subtotal_cents"] = subtotal
    quote["volume_discount_pct"] = pct
    quote["discount_cents"] = discount
    quote["freight_cents"] = freight
    quote["total_cents"] = post + freight


def compute_order_totals(order):
    lines = order_lines_of(order["id"])
    subtotal = 0
    cubes = 0
    for ln in lines:
        if ln["status"] == "CANCELLED":
            continue
        product = store["products"][ln["product_id"]]
        subtotal += line_extension(ln, product)
        cubes += ln["qty_allocated"] * product["cubes_per_unit"]
    if order["source"] == "PROJECT":
        pct = order["volume_discount_pct"]
    else:
        pct = select_volume_tier(subtotal)
    discount = round_half_up(subtotal * pct, 100)
    post = subtotal - discount
    freight = 0 if post >= FREIGHT_FREE_THRESHOLD_CENTS else FLAT_FREIGHT_CENTS
    order["subtotal_cents"] = subtotal
    order["volume_discount_pct"] = pct
    order["discount_cents"] = discount
    order["freight_cents"] = freight
    order["total_cents"] = post + freight
    order["cubes_total"] = cubes


def order_lines_of(order_id):
    return [ln for ln in store["order_lines"].values() if ln["order_id"] == order_id]


def kits_of_order(order_id):
    return [k for k in store["kits"].values() if k["order_id"] == order_id]


def statement_balance(account_id):
    total = 0
    for o in store["orders"].values():
        if o["account_id"] == account_id and o["payment_status"] in ("INVOICED", "PAID"):
            total += o["total_cents"]
    for p in store["payments"].values():
        if p["account_id"] == account_id:
            total -= p["amount_cents"]
    for r in store["returns"].values():
        if r["status"] == "CREDITED":
            order = store["orders"].get(r["order_id"])
            if order and order["account_id"] == account_id:
                total -= r["credit_cents"]
    return total


def forward_exposure(account_id):
    total = statement_balance(account_id)
    for o in store["orders"].values():
        if (
            o["account_id"] == account_id
            and o["payment_status"] == "UNINVOICED"
            and o["fulfillment_status"] not in ("DRAFT", "CANCELLED")
        ):
            total += o["total_cents"]
    return total


def is_past_due(order, account):
    if order["payment_status"] != "INVOICED" or order["invoiced_at"] is None:
        return False
    invoiced = parse_dt(order["invoiced_at"])
    if invoiced is None:
        return False
    due = invoiced + timedelta(days=TERMS_DAYS[account["terms"]])
    return _logical_clock > due


def any_past_due(account):
    for o in store["orders"].values():
        if o["account_id"] == account["id"] and is_past_due(o, account):
            return True
    return False


def evaluate_credit_hold(account):
    """Automatic credit cycle with hysteresis. Returns True if status changed."""
    balance = statement_balance(account["id"])
    past_due = any_past_due(account)
    if account["status"] == "ACTIVE":
        if balance > account["credit_limit_cents"] or past_due:
            account["status"] = "CREDIT_HOLD"
            touch(account)
            return True
    elif account["status"] == "CREDIT_HOLD":
        threshold = int((Decimal(account["credit_limit_cents"]) * HOLD_RELEASE_RATIO).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP))
        if balance <= threshold and not past_due:
            account["status"] = "ACTIVE"
            touch(account)
            return True
    return False


def sync_account_credit_fields(account):
    account["outstanding_balance_cents"] = statement_balance(account["id"])
    account["forward_exposure_cents"] = forward_exposure(account["id"])
    account["available_credit_cents"] = account["credit_limit_cents"] - account["forward_exposure_cents"]


def account_view(account):
    sync_account_credit_fields(account)
    return dict(account)


def order_bubble_up(order):
    """OPEN -> PICKING when every non-CANCELLED line is ALLOCATED or FILLED."""
    if order["fulfillment_status"] != "OPEN":
        return
    lines = [ln for ln in order_lines_of(order["id"]) if ln["status"] != "CANCELLED"]
    if lines and all(ln["status"] in ("ALLOCATED", "FILLED") for ln in lines):
        order["fulfillment_status"] = "PICKING"
        touch(order)


def kit_posture_update(kit):
    """DRAFT -> ASSEMBLED when every member line is ALLOCATED or FILLED."""
    if kit["status"] != "DRAFT":
        return
    members = [ln for ln in store["order_lines"].values() if ln["kit_id"] == kit["id"]]
    if members and all(ln["status"] in ("ALLOCATED", "FILLED") for ln in members):
        kit["status"] = "ASSEMBLED"
        touch(kit)


def backorder_allocation(branch_id, product_id):
    """Waterfall: fill BACKORDERED lines for (branch, product) from available stock."""
    stock_rec = get_stock(branch_id, product_id)
    if stock_rec is None:
        return
    candidates = []
    for ln in store["order_lines"].values():
        if ln["status"] != "BACKORDERED" or ln["product_id"] != product_id:
            continue
        order = store["orders"].get(ln["order_id"])
        if order is None or order["branch_id"] != branch_id:
            continue
        if order["fulfillment_status"] == "CANCELLED":
            continue
        candidates.append((ln, order))
    candidates.sort(key=lambda t: (t[0]["created_at"], t[1]["created_at"]))
    for ln, order in candidates:
        available = stock_available(stock_rec)
        if available <= 0:
            break
        shortage = ln["qty_ordered"] - ln["qty_allocated"] - ln["qty_fulfilled"]
        if shortage <= 0:
            continue
        take = min(shortage, available)
        ln["qty_allocated"] += take
        stock_rec["reserved"] += take
        touch(stock_rec)
        if ln["qty_allocated"] + ln["qty_fulfilled"] >= ln["qty_ordered"]:
            ln["status"] = "ALLOCATED"
        touch(ln)
        compute_order_totals(order)
        touch(order)
        order_bubble_up(order)
        if ln["kit_id"]:
            kit = store["kits"].get(ln["kit_id"])
            if kit:
                kit_posture_update(kit)


def sync_slot_status(slot):
    if slot["status"] in ("OPEN", "FULL"):
        desired = "FULL" if slot["booked_cubes"] >= slot["capacity_cubes"] else "OPEN"
        if slot["status"] != desired:
            slot["status"] = desired
            touch(slot)


def run_clock_sweep():
    """Fire time-driven transitions: quote expiry, slot completion, credit sweep."""
    for q in list(store["quotes"].values()):
        if q["status"] == "SUBMITTED":
            vu = parse_dt(q["valid_until"])
            if vu is not None and _logical_clock > vu:
                q["status"] = "EXPIRED"
                touch(q)
    for s in list(store["slots"].values()):
        if s["status"] in ("OPEN", "FULL"):
            we = parse_dt(s["window_end"])
            if we is not None and _logical_clock > we:
                s["status"] = "COMPLETED"
                touch(s)
    for a in list(store["accounts"].values()):
        evaluate_credit_hold(a)


def fulfill_order_invoice(order):
    """Auto-invoice cascade on delivery/pickup."""
    if order["payment_status"] == "UNINVOICED":
        order["payment_status"] = "INVOICED"
        order["invoiced_at"] = clock_iso()
        account = store["accounts"].get(order["account_id"])
        if account:
            sync_account_credit_fields(account)
            evaluate_credit_hold(account)


def order_fulfillment_timestamp(order):
    """Timestamp the order reached DELIVERED/PICKED_UP (== invoiced_at)."""
    return parse_dt(order["invoiced_at"]) if order.get("invoiced_at") else None


# ---------------------------------------------------------------------------
# Clock endpoint
# ---------------------------------------------------------------------------


@app.post(f"{API_PREFIX}/_clock/set_current_utc")
def set_clock():
    global _logical_clock
    user_id, role = require_roles("BranchManager")
    body = get_body()
    require_fields(body, ["to_iso8601"])
    dt = parse_dt(body["to_iso8601"])
    if dt is None:
        err("ERR_INVALID_REQUEST", 400, "to_iso8601 must be a valid ISO 8601 datetime")
    _logical_clock = dt
    run_clock_sweep()
    return ok({"current_utc": clock_iso()})


# ---------------------------------------------------------------------------
# Branches
# ---------------------------------------------------------------------------


@app.post(f"{API_PREFIX}/branches")
def create_branch():
    require_roles("BranchManager")
    body = get_body()
    require_fields(body, ["name", "code"])
    if not isinstance(body["name"], str) or not body["name"]:
        err("ERR_INVALID_REQUEST", 400, "name is required")
    if not isinstance(body["code"], str) or not body["code"]:
        err("ERR_INVALID_REQUEST", 400, "code is required")
    for b in store["branches"].values():
        if b["code"] == body["code"]:
            err("ERR_BRANCH_CODE_EXISTS", 409, "Branch code already exists")
    rec = new_record("branches", name=body["name"], code=body["code"])
    return ok(rec, 201)


@app.get(f"{API_PREFIX}/branches")
def list_branches():
    require_roles(*ROLES)
    return list_response(sorted_created(store["branches"].values()))


@app.get(f"{API_PREFIX}/branches/<bid>")
def get_branch(bid):
    require_roles(*ROLES)
    return ok(fetch("branches", bid))


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------


@app.post(f"{API_PREFIX}/products")
def create_product():
    require_roles("BranchManager")
    body = get_body()
    require_fields(body, ["sku", "description", "category", "list_price_cents",
                          "cost_cents", "manufacturer_name", "cubes_per_unit"])
    if not isinstance(body["sku"], str) or not body["sku"]:
        err("ERR_INVALID_REQUEST", 400, "sku is required")
    check_enum(body["category"], PRODUCT_CATEGORIES, "category")
    check_int(body["list_price_cents"], "list_price_cents", 1)
    check_int(body["cost_cents"], "cost_cents", 0)
    if not isinstance(body["manufacturer_name"], str) or not body["manufacturer_name"]:
        err("ERR_INVALID_REQUEST", 400, "manufacturer_name is required")
    check_int(body["cubes_per_unit"], "cubes_per_unit", 0)
    is_cut = body.get("is_cut_to_order", False)
    is_special = body.get("is_special_order", False)
    if not isinstance(is_cut, bool) or not isinstance(is_special, bool):
        err("ERR_INVALID_REQUEST", 400, "is_cut_to_order / is_special_order must be boolean")
    sub_group = body.get("substitute_group")
    if sub_group is not None and not isinstance(sub_group, str):
        err("ERR_INVALID_REQUEST", 400, "substitute_group must be a string")
    promo = body.get("promo_price_cents")
    if promo is not None:
        check_int(promo, "promo_price_cents", 1)
    for p in store["products"].values():
        if p["sku"] == body["sku"]:
            err("ERR_SKU_EXISTS", 409, "Product SKU already exists")
    rec = new_record(
        "products",
        sku=body["sku"],
        description=body["description"],
        category=body["category"],
        list_price_cents=body["list_price_cents"],
        cost_cents=body["cost_cents"],
        manufacturer_name=body["manufacturer_name"],
        cubes_per_unit=body["cubes_per_unit"],
        is_cut_to_order=is_cut,
        is_special_order=is_special,
        substitute_group=sub_group,
        promo_price_cents=promo,
    )
    return ok(rec, 201)


@app.get(f"{API_PREFIX}/products")
def list_products():
    require_roles(*ROLES)
    items = list(store["products"].values())
    for param in ("category", "manufacturer_name", "substitute_group"):
        v = request.args.get(param)
        if v is not None:
            items = [p for p in items if p.get(param) == v]
    return list_response(sorted_created(items))


@app.get(f"{API_PREFIX}/products/<pid>")
def get_product(pid):
    require_roles(*ROLES)
    return ok(fetch("products", pid))


@app.get(f"{API_PREFIX}/products/<pid>/inventory")
def product_inventory(pid):
    require_roles("BranchManager", "CounterRep", "InsideSales", "WarehouseLead")
    fetch("products", pid)
    items = [s for s in store["stock"].values() if s["product_id"] == pid]
    for s in items:
        s["available"] = s["on_hand"] - s["reserved"]
    return list_response(sorted_created(items))


@app.get(f"{API_PREFIX}/products/<pid>/order-lines")
def product_order_lines(pid):
    require_roles("BranchManager", "CounterRep", "InsideSales", "WarehouseLead")
    fetch("products", pid)
    items = [
        ln for ln in store["order_lines"].values()
        if ln["product_id"] == pid or ln.get("proposed_substitute_product_id") == pid
    ]
    return list_response(sorted_created(items))


# ---------------------------------------------------------------------------
# Contractor accounts
# ---------------------------------------------------------------------------


@app.post(f"{API_PREFIX}/contractor-accounts")
def create_account():
    require_roles("InsideSales")
    body = get_body()
    require_fields(body, ["company_name", "pricing_tier", "terms", "credit_limit_cents"])
    if not isinstance(body["company_name"], str) or not body["company_name"]:
        err("ERR_INVALID_REQUEST", 400, "company_name is required")
    check_enum(body["pricing_tier"], PRICING_TIERS, "pricing_tier")
    check_enum(body["terms"], TERMS, "terms")
    check_int(body["credit_limit_cents"], "credit_limit_cents", 0)
    rec = new_record(
        "accounts",
        company_name=body["company_name"],
        pricing_tier=body["pricing_tier"],
        terms=body["terms"],
        credit_limit_cents=body["credit_limit_cents"],
        status="ACTIVE",
        outstanding_balance_cents=0,
        forward_exposure_cents=0,
        available_credit_cents=body["credit_limit_cents"],
    )
    return ok(dict(rec), 201)


@app.get(f"{API_PREFIX}/contractor-accounts")
def list_accounts():
    require_roles("BranchManager", "CounterRep", "InsideSales", "WarehouseLead")
    items = list(store["accounts"].values())
    v = request.args.get("status")
    if v is not None:
        items = [a for a in items if a["status"] == v]
    return list_response(sorted_created([account_view(a) for a in items]))


@app.get(f"{API_PREFIX}/contractor-accounts/<aid>")
def get_account(aid):
    user_id, role = require_roles(*ROLES)
    account = fetch("accounts", aid)
    check_contractor_scope(user_id, role, account["id"])
    return ok(account_view(account))


@app.post(f"{API_PREFIX}/contractor-accounts/<aid>/credit-review")
def credit_review(aid):
    require_roles("BranchManager")
    account = fetch("accounts", aid)
    body = get_body()
    require_fields(body, ["action"])
    action = body["action"]
    check_enum(action, CREDIT_REVIEW_ACTIONS, "action")
    if action == "SUSPEND":
        if account["status"] not in ("ACTIVE", "CREDIT_HOLD"):
            err("ERR_INVALID_STATE", 409, "Account status does not permit SUSPEND")
        account["status"] = "SUSPENDED"
        touch(account)
    elif action == "RELEASE_HOLD":
        if account["status"] not in ("CREDIT_HOLD", "SUSPENDED"):
            err("ERR_INVALID_STATE", 409, "Account status does not permit RELEASE_HOLD")
        account["status"] = "ACTIVE"
        touch(account)
    elif action == "ADJUST_LIMIT":
        if account["status"] != "ACTIVE":
            err("ERR_INVALID_STATE", 409, "ADJUST_LIMIT requires an ACTIVE account")
        require_fields(body, ["new_credit_limit_cents"])
        check_int(body["new_credit_limit_cents"], "new_credit_limit_cents", 0)
        account["credit_limit_cents"] = body["new_credit_limit_cents"]
        touch(account)
        sync_account_credit_fields(account)
        evaluate_credit_hold(account)
    sync_account_credit_fields(account)
    return ok(dict(account))


@app.get(f"{API_PREFIX}/contractor-accounts/<aid>/credit-exposure")
def credit_exposure(aid):
    user_id, role = require_roles(*ROLES)
    account = fetch("accounts", aid)
    check_contractor_scope(user_id, role, account["id"])
    balance = statement_balance(aid)
    fwd = forward_exposure(aid)
    return ok({
        "account_id": aid,
        "credit_limit_cents": account["credit_limit_cents"],
        "statement_balance_cents": balance,
        "forward_exposure_cents": fwd,
        "available_credit_cents": account["credit_limit_cents"] - fwd,
        "status": account["status"],
    })


@app.get(f"{API_PREFIX}/contractor-accounts/<aid>/job-costing")
def job_costing(aid):
    user_id, role = require_roles(*ROLES)
    account = fetch("accounts", aid)
    check_contractor_scope(user_id, role, account["id"])
    job_name = request.args.get("job_name")
    if not job_name:
        err("ERR_INVALID_REQUEST", 400, "job_name query parameter is required")
    orders = [
        o for o in store["orders"].values()
        if o["account_id"] == aid and o.get("job_name") == job_name
        and o["fulfillment_status"] != "CANCELLED"
    ]
    order_ids = {o["id"] for o in orders}
    provisional = 0
    final = 0
    line_count = 0
    for ln in store["order_lines"].values():
        if ln["order_id"] not in order_ids or ln["status"] == "CANCELLED":
            continue
        product = store["products"][ln["product_id"]]
        ext = line_extension(ln, product)
        if ln["status"] in ("OPEN", "ALLOCATED", "BACKORDERED", "FILLED"):
            provisional += ext
            line_count += 1
        if ln["status"] == "FILLED":
            returned_value = ln["qty_returned"] * ln["unit_price_cents"]
            if product["is_cut_to_order"]:
                returned_value *= ln["cut_length_ft"]
            final += ext - returned_value
    return ok({
        "job_name": job_name,
        "provisional_cost_cents": provisional,
        "final_cost_cents": final,
        "order_count": len(orders),
        "line_count": line_count,
    })


@app.get(f"{API_PREFIX}/contractor-accounts/<aid>/quotes")
def account_quotes(aid):
    user_id, role = require_roles(*ROLES)
    account = fetch("accounts", aid)
    check_contractor_scope(user_id, role, account["id"])
    items = [q for q in store["quotes"].values() if q["account_id"] == aid]
    return list_response(sorted_created(items))


@app.get(f"{API_PREFIX}/contractor-accounts/<aid>/selection-sheets")
def account_sheets(aid):
    user_id, role = require_roles(*ROLES)
    account = fetch("accounts", aid)
    check_contractor_scope(user_id, role, account["id"])
    items = [s for s in store["sheets"].values() if s["account_id"] == aid]
    return list_response(sorted_created(items))


@app.get(f"{API_PREFIX}/contractor-accounts/<aid>/orders")
def account_orders(aid):
    user_id, role = require_roles(*ROLES)
    account = fetch("accounts", aid)
    check_contractor_scope(user_id, role, account["id"])
    items = [o for o in store["orders"].values() if o["account_id"] == aid]
    v = request.args.get("fulfillment_status")
    if v is not None:
        items = [o for o in items if o["fulfillment_status"] == v]
    return list_response(sorted_created(items))


@app.get(f"{API_PREFIX}/contractor-accounts/<aid>/payments")
def account_payments(aid):
    user_id, role = require_roles(*ROLES)
    account = fetch("accounts", aid)
    check_contractor_scope(user_id, role, account["id"])
    items = [p for p in store["payments"].values() if p["account_id"] == aid]
    return list_response(sorted_created(items))


@app.post(f"{API_PREFIX}/contractor-accounts/<aid>/payments")
def create_payment(aid):
    require_roles("CounterRep")
    account = fetch("accounts", aid)
    body = get_body()
    require_fields(body, ["amount_cents", "method"])
    check_int(body["amount_cents"], "amount_cents", 1)
    check_enum(body["method"], PAYMENT_METHODS, "method")
    allocations = body.get("allocations")

    explicit = []
    if allocations is not None:
        if not isinstance(allocations, list):
            err("ERR_INVALID_REQUEST", 400, "allocations must be an array")
        for a in allocations:
            if not isinstance(a, dict) or "order_id" not in a or "amount_cents" not in a:
                err("ERR_INVALID_REQUEST", 400, "each allocation needs order_id and amount_cents")
            check_int(a["amount_cents"], "allocation amount_cents", 1)
            order = get_or_none("orders", a["order_id"])
            if order is None:
                err("ERR_ORDER_NOT_FOUND", 404, "allocation order not found")
            if order["account_id"] != aid:
                err("ERR_INVALID_REQUEST", 400, "allocation order does not belong to this account")
            explicit.append((order, a["amount_cents"]))

    payment = new_record(
        "payments",
        account_id=aid,
        amount_cents=body["amount_cents"],
        method=body["method"],
        allocations=allocations,
        applied_at=clock_iso(),
        status="APPLIED",
    )

    def already_allocated(order_id):
        return sum(a["amount_cents"] for a in store["allocations"] if a["order_id"] == order_id)

    if explicit:
        for order, amount in explicit:
            store["allocations"].append({
                "order_id": order["id"], "payment_id": payment["id"], "amount_cents": amount,
            })
            if order["payment_status"] == "INVOICED" and already_allocated(order["id"]) >= order["total_cents"]:
                order["payment_status"] = "PAID"
                touch(order)
    else:
        remaining = payment["amount_cents"]
        targets = [o for o in store["orders"].values()
                   if o["account_id"] == aid and o["payment_status"] == "INVOICED"]
        targets.sort(key=lambda o: (o["invoiced_at"] or "", o["created_at"]))
        for order in targets:
            if remaining <= 0:
                break
            owed = order["total_cents"] - already_allocated(order["id"])
            if owed <= 0:
                continue
            take = min(owed, remaining)
            store["allocations"].append({
                "order_id": order["id"], "payment_id": payment["id"], "amount_cents": take,
            })
            remaining -= take
            if already_allocated(order["id"]) >= order["total_cents"]:
                order["payment_status"] = "PAID"
                touch(order)

    touch(account)
    sync_account_credit_fields(account)
    evaluate_credit_hold(account)
    return ok(dict(payment), 201)


# ---------------------------------------------------------------------------
# Inventory & receiving
# ---------------------------------------------------------------------------


@app.post(f"{API_PREFIX}/branches/<bid>/inventory")
def create_inventory(bid):
    require_roles("WarehouseLead")
    fetch("branches", bid)
    body = get_body()
    require_fields(body, ["product_id", "initial_on_hand"])
    product = get_or_none("products", body["product_id"])
    if product is None:
        err("ERR_PRODUCT_NOT_FOUND", 404, "product not found")
    check_int(body["initial_on_hand"], "initial_on_hand", 0)
    if get_stock(bid, product["id"]) is not None:
        err("ERR_STOCK_RECORD_EXISTS", 409, "Stock record already exists for this branch/product")
    rec = new_record(
        "stock",
        branch_id=bid,
        product_id=product["id"],
        on_hand=body["initial_on_hand"],
        reserved=0,
    )
    rec["available"] = rec["on_hand"] - rec["reserved"]
    return ok(dict(rec), 201)


@app.get(f"{API_PREFIX}/branches/<bid>/inventory")
def list_inventory(bid):
    require_roles("BranchManager", "CounterRep", "InsideSales", "WarehouseLead")
    fetch("branches", bid)
    items = [s for s in store["stock"].values() if s["branch_id"] == bid]
    v = request.args.get("product_id")
    if v is not None:
        items = [s for s in items if s["product_id"] == v]
    for s in items:
        s["available"] = s["on_hand"] - s["reserved"]
    return list_response(sorted_created(items))


@app.post(f"{API_PREFIX}/branches/<bid>/stock-receipts")
def create_stock_receipt(bid):
    user_id, _ = require_roles("WarehouseLead")
    fetch("branches", bid)
    body = get_body()
    require_fields(body, ["lines"])
    lines = body["lines"]
    if not isinstance(lines, list) or len(lines) < 1:
        err("ERR_INVALID_REQUEST", 400, "lines must contain at least one line")
    parsed = []
    for ln in lines:
        if not isinstance(ln, dict):
            err("ERR_INVALID_REQUEST", 400, "receipt line must be an object")
        require_fields(ln, ["product_id", "qty", "unit_cost_cents"])
        check_int(ln["qty"], "qty", 1)
        check_int(ln["unit_cost_cents"], "unit_cost_cents", 0)
        product = get_or_none("products", ln["product_id"])
        if product is None:
            err("ERR_PRODUCT_NOT_FOUND", 404, "product not found")
        parsed.append((product, ln["qty"], ln["unit_cost_cents"]))

    received_at = clock_iso()
    receipt = new_record(
        "receipts",
        branch_id=bid,
        lines=[{"product_id": p["id"], "qty": q, "unit_cost_cents": c} for p, q, c in parsed],
        received_at=received_at,
        posted_by=user_id,
        status="POSTED",
    )

    receipt_dt = _logical_clock
    touched_products = []
    for product, qty, unit_cost in parsed:
        stock_rec = get_stock(bid, product["id"])
        if stock_rec is None:
            stock_rec = new_record(
                "stock", branch_id=bid, product_id=product["id"], on_hand=0, reserved=0,
            )
        stock_rec["on_hand"] += qty
        touch(stock_rec)
        # manufacturer program accrual (only while the program is ACTIVE)
        for prog in store["programs"].values():
            if prog["manufacturer_name"] != product["manufacturer_name"]:
                continue
            if prog["status"] != "ACTIVE":
                continue
            ps = parse_dt(prog["period_start"])
            pe = parse_dt(prog["period_end"])
            if ps is not None and pe is not None and ps <= receipt_dt <= pe:
                prog["purchases_cents"] += qty * unit_cost
                touch(prog)
        touched_products.append(product["id"])

    for product_id in dict.fromkeys(touched_products):
        backorder_allocation(bid, product_id)

    return ok(dict(receipt), 201)


@app.get(f"{API_PREFIX}/branches/<bid>/stock-receipts")
def list_stock_receipts(bid):
    require_roles("BranchManager", "CounterRep", "InsideSales", "WarehouseLead")
    fetch("branches", bid)
    items = [r for r in store["receipts"].values() if r["branch_id"] == bid]
    return list_response(sorted_created(items))


@app.get(f"{API_PREFIX}/branches/<bid>/orders")
def branch_orders(bid):
    require_roles("BranchManager", "CounterRep", "InsideSales", "WarehouseLead")
    fetch("branches", bid)
    items = [o for o in store["orders"].values() if o["branch_id"] == bid]
    v = request.args.get("fulfillment_status")
    if v is not None:
        items = [o for o in items if o["fulfillment_status"] == v]
    return list_response(sorted_created(items))


@app.get(f"{API_PREFIX}/branches/<bid>/delivery-slots")
def branch_slots(bid):
    require_roles("BranchManager", "CounterRep", "InsideSales", "WarehouseLead")
    fetch("branches", bid)
    items = [s for s in store["slots"].values() if s["branch_id"] == bid]
    v = request.args.get("truck_label")
    if v is not None:
        items = [s for s in items if s["truck_label"] == v]
    return list_response(sorted_created(items))


# ---------------------------------------------------------------------------
# Quotes
# ---------------------------------------------------------------------------


def validate_quote_lines(lines, check_floor=True):
    if not isinstance(lines, list) or len(lines) < 1:
        err("ERR_INVALID_REQUEST", 400, "lines must contain at least one line")
    parsed = []
    for ln in lines:
        if not isinstance(ln, dict):
            err("ERR_INVALID_REQUEST", 400, "quote line must be an object")
        require_fields(ln, ["product_id", "qty", "unit_price_cents"])
        check_int(ln["qty"], "qty", 1)
        check_int(ln["unit_price_cents"], "unit_price_cents", 0)
        product = get_or_none("products", ln["product_id"])
        if product is None:
            err("ERR_PRODUCT_NOT_FOUND", 404, "product not found")
        parsed.append({
            "product_id": product["id"],
            "qty": ln["qty"],
            "unit_price_cents": ln["unit_price_cents"],
        })
    if check_floor:
        validate_quote_line_floors(parsed)
    return parsed


def validate_quote_line_floors(parsed_lines):
    for ln in parsed_lines:
        product = store["products"][ln["product_id"]]
        if ln["unit_price_cents"] < price_floor_cents(product):
            err("ERR_PRICE_FLOOR_VIOLATION", 422, "Quote line price below the price floor")


@app.post(f"{API_PREFIX}/quotes")
def create_quote():
    require_roles("InsideSales")
    body = get_body()
    require_fields(body, ["account_id", "branch_id", "job_name", "valid_until", "lines"])
    if not isinstance(body["job_name"], str) or not body["job_name"]:
        err("ERR_INVALID_REQUEST", 400, "job_name is required")
    if parse_dt(body["valid_until"]) is None:
        err("ERR_INVALID_REQUEST", 400, "valid_until must be a valid ISO 8601 datetime")
    lines = validate_quote_lines(body["lines"], check_floor=False)
    account = get_or_none("accounts", body["account_id"])
    if account is None:
        err("ERR_ACCOUNT_NOT_FOUND", 404, "account not found")
    branch = get_or_none("branches", body["branch_id"])
    if branch is None:
        err("ERR_BRANCH_NOT_FOUND", 404, "branch not found")
    supersedes = body.get("supersedes_quote_id")
    if supersedes is not None:
        fetch("quotes", supersedes)
    validate_quote_line_floors(lines)
    rec = new_record(
        "quotes",
        account_id=account["id"],
        branch_id=branch["id"],
        job_name=body["job_name"],
        valid_until=body["valid_until"],
        lines=lines,
        revision_no=1,
        supersedes_quote_id=supersedes,
        status="DRAFT",
        volume_discount_pct=0,
        subtotal_cents=0,
        discount_cents=0,
        freight_cents=0,
        total_cents=0,
        awarded_at=None,
    )
    compute_quote_totals(rec)
    return ok(dict(rec), 201)


@app.get(f"{API_PREFIX}/quotes")
def list_quotes():
    require_roles("BranchManager", "CounterRep", "InsideSales", "WarehouseLead")
    items = list(store["quotes"].values())
    for param in ("account_id", "branch_id", "status", "supersedes_quote_id"):
        v = request.args.get(param)
        if v is not None:
            items = [q for q in items if q.get(param) == v]
    return list_response(sorted_created(items))


@app.get(f"{API_PREFIX}/quotes/<qid>")
def get_quote(qid):
    user_id, role = require_roles(*ROLES)
    quote = fetch("quotes", qid)
    check_contractor_scope(user_id, role, quote["account_id"])
    return ok(dict(quote))


@app.post(f"{API_PREFIX}/quotes/<qid>/submit")
def submit_quote(qid):
    require_roles("InsideSales")
    quote = fetch("quotes", qid)
    if quote["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "Quote status does not permit submit")
    vu = parse_dt(quote["valid_until"])
    if vu is not None and _logical_clock >= vu:
        err("ERR_QUOTE_EXPIRED", 409, "Quote validity deadline has passed")
    quote["status"] = "SUBMITTED"
    touch(quote)
    return ok(dict(quote))


@app.post(f"{API_PREFIX}/quotes/<qid>/award")
def award_quote(qid):
    user_id, role = require_roles("Contractor")
    quote = fetch("quotes", qid)
    check_contractor_scope(user_id, role, quote["account_id"])
    if quote["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", 409, "Quote status does not permit award")
    vu = parse_dt(quote["valid_until"])
    if vu is not None and _logical_clock >= vu:
        quote["status"] = "EXPIRED"
        touch(quote)
        err("ERR_QUOTE_EXPIRED", 409, "Quote validity deadline has passed")
    quote["status"] = "AWARDED"
    quote["awarded_at"] = clock_iso()
    touch(quote)
    return ok(dict(quote))


@app.post(f"{API_PREFIX}/quotes/<qid>/lose")
def lose_quote(qid):
    require_roles("InsideSales")
    quote = fetch("quotes", qid)
    if quote["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", 409, "Quote status does not permit lose")
    quote["status"] = "LOST"
    touch(quote)
    return ok(dict(quote))


@app.post(f"{API_PREFIX}/quotes/<qid>/revisions")
def revise_quote(qid):
    require_roles("InsideSales")
    quote = fetch("quotes", qid)
    body = get_body()
    require_fields(body, ["expected_quote_version", "valid_until"])
    check_int(body["expected_quote_version"], "expected_quote_version")
    if parse_dt(body["valid_until"]) is None:
        err("ERR_INVALID_REQUEST", 400, "valid_until must be a valid ISO 8601 datetime")
    if quote["status"] != "AWARDED":
        err("ERR_INVALID_STATE", 409, "Only an AWARDED quote may be revised")
    if body["expected_quote_version"] != quote["version"]:
        err("ERR_STALE_QUOTE_VERSION", 412, "Stale quote version")

    if "lines" in body and body["lines"] is not None:
        new_lines = validate_quote_lines(body["lines"], check_floor=False)
        validate_quote_line_floors(new_lines)
    else:
        new_lines = [dict(ln) for ln in quote["lines"]]

    quote["status"] = "REVISED"
    touch(quote)

    rec = new_record(
        "quotes",
        account_id=quote["account_id"],
        branch_id=quote["branch_id"],
        job_name=quote["job_name"],
        valid_until=body["valid_until"],
        lines=new_lines,
        revision_no=quote["revision_no"] + 1,
        supersedes_quote_id=quote["id"],
        status="DRAFT",
        volume_discount_pct=0,
        subtotal_cents=0,
        discount_cents=0,
        freight_cents=0,
        total_cents=0,
        awarded_at=None,
    )
    compute_quote_totals(rec)
    return ok(dict(rec), 201)


@app.post(f"{API_PREFIX}/quotes/<qid>/convert")
def convert_quote(qid):
    require_roles("InsideSales")
    quote = fetch("quotes", qid)
    if quote["status"] != "AWARDED":
        err("ERR_INVALID_STATE", 409, "Only an AWARDED quote may be converted")

    order = new_record(
        "orders",
        account_id=quote["account_id"],
        branch_id=quote["branch_id"],
        quote_id=quote["id"],
        sheet_id=None,
        delivery_slot_id=None,
        source="PROJECT",
        job_name=quote["job_name"],
        will_call=False,
        payment_status="UNINVOICED",
        fulfillment_status="DRAFT",
        volume_discount_pct=quote["volume_discount_pct"],
        subtotal_cents=0,
        discount_cents=0,
        freight_cents=0,
        total_cents=0,
        cubes_total=0,
        invoiced_at=None,
    )
    for ln in quote["lines"]:
        line = new_record(
            "order_lines",
            order_id=order["id"],
            product_id=ln["product_id"],
            kit_id=None,
            qty_ordered=ln["qty"],
            cut_length_ft=None,
            price_override_cents=None,
            unit_price_cents=ln["unit_price_cents"],
            price_source="QUOTE_LOCKED",
            qty_allocated=0,
            qty_backordered=0,
            qty_fulfilled=0,
            qty_returned=0,
            status="OPEN",
            substitute_status="NONE",
            proposed_substitute_product_id=None,
            line_total_cents=0,
        )
        product = store["products"][line["product_id"]]
        line["line_total_cents"] = line_extension(line, product)
    compute_order_totals(order)
    quote["status"] = "CONVERTED"
    touch(quote)
    return ok(dict(order), 201)


@app.get(f"{API_PREFIX}/quotes/<qid>/orders")
def quote_orders(qid):
    require_roles("BranchManager", "CounterRep", "InsideSales", "WarehouseLead")
    fetch("quotes", qid)
    items = [o for o in store["orders"].values() if o.get("quote_id") == qid]
    return list_response(sorted_created(items))


# ---------------------------------------------------------------------------
# Selection sheets
# ---------------------------------------------------------------------------


def validate_selections(selections):
    if not isinstance(selections, list) or len(selections) < 1:
        err("ERR_INVALID_REQUEST", 400, "selections must contain at least one selection")
    parsed = []
    for s in selections:
        if not isinstance(s, dict):
            err("ERR_INVALID_REQUEST", 400, "selection must be an object")
        require_fields(s, ["product_id", "finish", "qty"])
        check_int(s["qty"], "qty", 1)
        product = get_or_none("products", s["product_id"])
        if product is None:
            err("ERR_PRODUCT_NOT_FOUND", 404, "product not found")
        if product["category"] != "FIXTURE" and not product["is_special_order"]:
            err("ERR_INVALID_REQUEST", 400,
                "selection products must be FIXTURE category or special-order")
        parsed.append({
            "product_id": product["id"],
            "finish": s["finish"],
            "qty": s["qty"],
        })
    return parsed


@app.post(f"{API_PREFIX}/selection-sheets")
def create_sheet():
    require_roles("InsideSales")
    body = get_body()
    require_fields(body, ["account_id", "branch_id", "customer_name", "selections"])
    if not isinstance(body["customer_name"], str) or not body["customer_name"]:
        err("ERR_INVALID_REQUEST", 400, "customer_name is required")
    selections = validate_selections(body["selections"])
    account = get_or_none("accounts", body["account_id"])
    if account is None:
        err("ERR_ACCOUNT_NOT_FOUND", 404, "account not found")
    branch = get_or_none("branches", body["branch_id"])
    if branch is None:
        err("ERR_BRANCH_NOT_FOUND", 404, "branch not found")
    rec = new_record(
        "sheets",
        account_id=account["id"],
        branch_id=branch["id"],
        customer_name=body["customer_name"],
        selections=selections,
        status="DRAFT",
        approved_at=None,
    )
    return ok(dict(rec), 201)


@app.get(f"{API_PREFIX}/selection-sheets")
def list_sheets():
    require_roles("BranchManager", "CounterRep", "InsideSales", "WarehouseLead")
    items = list(store["sheets"].values())
    for param in ("account_id", "branch_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [s for s in items if s.get(param) == v]
    return list_response(sorted_created(items))


@app.get(f"{API_PREFIX}/selection-sheets/<sid>")
def get_sheet(sid):
    user_id, role = require_roles(*ROLES)
    sheet = fetch("sheets", sid)
    check_contractor_scope(user_id, role, sheet["account_id"])
    return ok(dict(sheet))


@app.post(f"{API_PREFIX}/selection-sheets/<sid>/present")
def present_sheet(sid):
    require_roles("InsideSales")
    sheet = fetch("sheets", sid)
    if sheet["status"] not in ("DRAFT", "REVISED"):
        err("ERR_INVALID_STATE", 409, "Sheet status does not permit present")
    sheet["status"] = "PRESENTED"
    touch(sheet)
    return ok(dict(sheet))


@app.post(f"{API_PREFIX}/selection-sheets/<sid>/approve")
def approve_sheet(sid):
    user_id, role = require_roles("Contractor")
    sheet = fetch("sheets", sid)
    check_contractor_scope(user_id, role, sheet["account_id"])
    if sheet["status"] != "PRESENTED":
        err("ERR_INVALID_STATE", 409, "Sheet status does not permit approve")
    sheet["status"] = "APPROVED"
    sheet["approved_at"] = clock_iso()
    touch(sheet)
    return ok(dict(sheet))


@app.post(f"{API_PREFIX}/selection-sheets/<sid>/revise")
def revise_sheet(sid):
    require_roles("InsideSales")
    sheet = fetch("sheets", sid)
    body = get_body()
    require_fields(body, ["selections"])
    selections = validate_selections(body["selections"])
    if sheet["status"] != "APPROVED":
        err("ERR_INVALID_STATE", 409, "Sheet status does not permit revise")
    sheet["selections"] = selections
    sheet["status"] = "REVISED"
    sheet["approved_at"] = None
    touch(sheet)
    return ok(dict(sheet))


@app.post(f"{API_PREFIX}/selection-sheets/<sid>/convert")
def convert_sheet(sid):
    require_roles("InsideSales")
    sheet = fetch("sheets", sid)
    if sheet["status"] != "APPROVED":
        err("ERR_INVALID_STATE", 409, "Only an APPROVED sheet may be converted")

    order = new_record(
        "orders",
        account_id=sheet["account_id"],
        branch_id=sheet["branch_id"],
        quote_id=None,
        sheet_id=sheet["id"],
        delivery_slot_id=None,
        source="SHOWROOM",
        job_name=None,
        will_call=False,
        payment_status="UNINVOICED",
        fulfillment_status="DRAFT",
        volume_discount_pct=0,
        subtotal_cents=0,
        discount_cents=0,
        freight_cents=0,
        total_cents=0,
        cubes_total=0,
        invoiced_at=None,
    )
    for s in sheet["selections"]:
        product = store["products"][s["product_id"]]
        line = new_record(
            "order_lines",
            order_id=order["id"],
            product_id=product["id"],
            kit_id=None,
            qty_ordered=s["qty"],
            cut_length_ft=None,
            price_override_cents=None,
            unit_price_cents=product["list_price_cents"],
            price_source="SHOWROOM_LIST",
            qty_allocated=0,
            qty_backordered=0,
            qty_fulfilled=0,
            qty_returned=0,
            status="OPEN",
            substitute_status="NONE",
            proposed_substitute_product_id=None,
            line_total_cents=0,
        )
        line["line_total_cents"] = line_extension(line, product)
    compute_order_totals(order)
    sheet["status"] = "ORDERED"
    touch(sheet)
    return ok(dict(order), 201)


@app.get(f"{API_PREFIX}/selection-sheets/<sid>/orders")
def sheet_orders(sid):
    require_roles("BranchManager", "CounterRep", "InsideSales", "WarehouseLead")
    fetch("sheets", sid)
    items = [o for o in store["orders"].values() if o.get("sheet_id") == sid]
    return list_response(sorted_created(items))


# ---------------------------------------------------------------------------
# Orders & lines
# ---------------------------------------------------------------------------


def line_view(line):
    line = dict(line)
    if line["status"] in ("FILLED", "CANCELLED"):
        line["qty_backordered"] = 0
    else:
        line["qty_backordered"] = (
            line["qty_ordered"] - line["qty_allocated"] - line["qty_fulfilled"]
        )
    return line


@app.post(f"{API_PREFIX}/orders")
def create_order():
    require_roles("CounterRep")
    body = get_body()
    require_fields(body, ["account_id", "branch_id"])
    job_name = body.get("job_name")
    if job_name is not None and not isinstance(job_name, str):
        err("ERR_INVALID_REQUEST", 400, "job_name must be a string")
    will_call = body.get("will_call", False)
    if not isinstance(will_call, bool):
        err("ERR_INVALID_REQUEST", 400, "will_call must be a boolean")
    account = get_or_none("accounts", body["account_id"])
    if account is None:
        err("ERR_ACCOUNT_NOT_FOUND", 404, "account not found")
    branch = get_or_none("branches", body["branch_id"])
    if branch is None:
        err("ERR_BRANCH_NOT_FOUND", 404, "branch not found")
    rec = new_record(
        "orders",
        account_id=account["id"],
        branch_id=branch["id"],
        quote_id=None,
        sheet_id=None,
        delivery_slot_id=None,
        source="COUNTER",
        job_name=job_name,
        will_call=will_call,
        payment_status="UNINVOICED",
        fulfillment_status="DRAFT",
        volume_discount_pct=0,
        subtotal_cents=0,
        discount_cents=0,
        freight_cents=0,
        total_cents=0,
        cubes_total=0,
        invoiced_at=None,
    )
    compute_order_totals(rec)
    return ok(dict(rec), 201)


@app.get(f"{API_PREFIX}/orders/<oid>")
def get_order(oid):
    user_id, role = require_roles(*ROLES)
    order = fetch("orders", oid)
    check_contractor_scope(user_id, role, order["account_id"])
    return ok(dict(order))


@app.post(f"{API_PREFIX}/orders/<oid>/lines")
def add_order_line(oid):
    user_id, role = require_roles("CounterRep", "BranchManager")
    order = fetch("orders", oid)
    body = get_body()
    require_fields(body, ["product_id", "qty"])
    check_int(body["qty"], "qty", 1)
    price_override = body.get("price_override_cents")
    if price_override is not None:
        check_int(price_override, "price_override_cents", 1)
    cut_length = body.get("cut_length_ft")
    if cut_length is not None:
        check_int(cut_length, "cut_length_ft", 1)
    product = get_or_none("products", body["product_id"])
    if product is None:
        err("ERR_PRODUCT_NOT_FOUND", 404, "product not found")
    if product["is_cut_to_order"]:
        if cut_length is None:
            err("ERR_INVALID_REQUEST", 400, "cut_length_ft is required for cut-to-order products")
    else:
        if cut_length is not None:
            err("ERR_INVALID_REQUEST", 400, "cut_length_ft is forbidden for non-cut products")
    if order["fulfillment_status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "Lines may only be added to a DRAFT order")
    if order["source"] == "PROJECT":
        err("ERR_INVALID_STATE", 409, "PROJECT order lines are locked to the source quote")

    account = store["accounts"][order["account_id"]]
    if price_override is not None:
        # Floor check outranks the role check (PRD section 2.7).
        if price_override < price_floor_cents(product):
            err("ERR_PRICE_FLOOR_VIOLATION", 422, "Price override below the price floor")
        if role != "BranchManager":
            err("ERR_OVERRIDE_REQUIRES_MANAGER", 403, "price_override_cents requires BranchManager")

    if order["source"] == "SHOWROOM":
        unit_price, price_source = product["list_price_cents"], "SHOWROOM_LIST"
    else:
        unit_price, price_source = resolve_counter_price(account, product, price_override)

    line = new_record(
        "order_lines",
        order_id=order["id"],
        product_id=product["id"],
        kit_id=None,
        qty_ordered=body["qty"],
        cut_length_ft=cut_length,
        price_override_cents=price_override,
        unit_price_cents=unit_price,
        price_source=price_source,
        qty_allocated=0,
        qty_backordered=0,
        qty_fulfilled=0,
        qty_returned=0,
        status="OPEN",
        substitute_status="NONE",
        proposed_substitute_product_id=None,
        line_total_cents=0,
    )
    line["line_total_cents"] = line_extension(line, product)
    compute_order_totals(order)
    touch(order)
    return ok(line_view(line), 201)


@app.get(f"{API_PREFIX}/orders/<oid>/lines")
def get_order_lines(oid):
    user_id, role = require_roles(*ROLES)
    order = fetch("orders", oid)
    check_contractor_scope(user_id, role, order["account_id"])
    items = [line_view(ln) for ln in order_lines_of(order["id"])]
    return list_response(sorted_created(items))


@app.post(f"{API_PREFIX}/orders/<oid>/submit")
def submit_order(oid):
    require_roles("CounterRep")
    order = fetch("orders", oid)
    if order["fulfillment_status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "Order status does not permit submit")
    account = store["accounts"][order["account_id"]]
    if account["status"] != "ACTIVE":
        err("ERR_ACCOUNT_CREDIT_HOLD", 409, "Account is not ACTIVE")
    compute_order_totals(order)
    if forward_exposure(account["id"]) + order["total_cents"] > account["credit_limit_cents"]:
        err("ERR_CREDIT_LIMIT_EXCEEDED", 402, "Credit limit would be exceeded")
    lines = order_lines_of(order["id"])
    if len(lines) < 1:
        err("ERR_INVALID_STATE", 409, "Order must carry at least one line")

    order["fulfillment_status"] = "OPEN"
    for line in lines:
        stock_rec = get_stock(order["branch_id"], line["product_id"])
        available = stock_available(stock_rec) if stock_rec else 0
        take = min(line["qty_ordered"], max(available, 0))
        if take >= line["qty_ordered"]:
            line["qty_allocated"] = line["qty_ordered"]
            line["status"] = "ALLOCATED"
        else:
            line["qty_allocated"] = take
            line["status"] = "BACKORDERED"
        if take > 0 and stock_rec is not None:
            stock_rec["reserved"] += take
            touch(stock_rec)
        touch(line)
    compute_order_totals(order)
    touch(order)
    order_bubble_up(order)
    for line in lines:
        if line["kit_id"]:
            kit = store["kits"].get(line["kit_id"])
            if kit:
                kit_posture_update(kit)
    sync_account_credit_fields(account)
    return ok(dict(order))


@app.post(f"{API_PREFIX}/orders/<oid>/cancel")
def cancel_order(oid):
    require_roles("CounterRep")
    order = fetch("orders", oid)
    if order["fulfillment_status"] not in ("DRAFT", "OPEN", "PICKING"):
        err("ERR_INVALID_STATE", 409, "Order status does not permit cancel")
    if order["fulfillment_status"] in ("OPEN", "PICKING"):
        for line in order_lines_of(order["id"]):
            if line["status"] in ("OPEN", "ALLOCATED", "BACKORDERED"):
                if line["qty_allocated"] > 0:
                    stock_rec = get_stock(order["branch_id"], line["product_id"])
                    if stock_rec is not None:
                        stock_rec["reserved"] -= line["qty_allocated"]
                        touch(stock_rec)
                line["qty_allocated"] = 0
                line["status"] = "CANCELLED"
                touch(line)
        if order["delivery_slot_id"]:
            slot = store["slots"].get(order["delivery_slot_id"])
            if slot is not None:
                slot["booked_cubes"] -= order["cubes_total"]
                sync_slot_status(slot)
            order["delivery_slot_id"] = None
    order["fulfillment_status"] = "CANCELLED"
    compute_order_totals(order)
    touch(order)
    account = store["accounts"].get(order["account_id"])
    if account:
        sync_account_credit_fields(account)
    return ok(dict(order))


@app.post(f"{API_PREFIX}/orders/<oid>/mark-staged")
def mark_staged(oid):
    require_roles("WarehouseLead")
    order = fetch("orders", oid)
    if order["fulfillment_status"] != "PICKING":
        err("ERR_INVALID_STATE", 409, "Order status does not permit mark-staged")
    if order["will_call"]:
        kits = kits_of_order(order["id"])
        if kits and any(k["status"] != "STAGED" for k in kits):
            err("ERR_INVALID_STATE", 409, "All kits of a will-call order must be STAGED")
    for line in order_lines_of(order["id"]):
        if line["status"] == "ALLOCATED":
            line["qty_fulfilled"] = line["qty_allocated"]
            line["status"] = "FILLED"
            stock_rec = get_stock(order["branch_id"], line["product_id"])
            if stock_rec is not None:
                stock_rec["on_hand"] -= line["qty_allocated"]
                stock_rec["reserved"] -= line["qty_allocated"]
                touch(stock_rec)
            touch(line)
    order["fulfillment_status"] = "STAGED"
    compute_order_totals(order)
    touch(order)
    return ok(dict(order))


def release_order_kits(order):
    for kit in kits_of_order(order["id"]):
        if kit["status"] == "STAGED":
            kit["status"] = "RELEASED"
            touch(kit)


@app.post(f"{API_PREFIX}/orders/<oid>/dispatch")
def dispatch_order(oid):
    require_roles("WarehouseLead")
    order = fetch("orders", oid)
    if order["fulfillment_status"] != "STAGED":
        err("ERR_INVALID_STATE", 409, "Order status does not permit dispatch")
    if not order["delivery_slot_id"]:
        err("ERR_INVALID_STATE", 409, "Dispatch requires an active delivery booking")
    order["fulfillment_status"] = "DISPATCHED"
    release_order_kits(order)
    touch(order)
    return ok(dict(order))


@app.post(f"{API_PREFIX}/orders/<oid>/confirm-delivery")
def confirm_delivery(oid):
    require_roles("WarehouseLead")
    order = fetch("orders", oid)
    if order["fulfillment_status"] != "DISPATCHED":
        err("ERR_INVALID_STATE", 409, "Order status does not permit confirm-delivery")
    order["fulfillment_status"] = "DELIVERED"
    fulfill_order_invoice(order)
    touch(order)
    return ok(dict(order))


@app.post(f"{API_PREFIX}/orders/<oid>/pickup")
def pickup_order(oid):
    require_roles("CounterRep")
    order = fetch("orders", oid)
    if order["fulfillment_status"] != "STAGED":
        err("ERR_INVALID_STATE", 409, "Order status does not permit pickup")
    if not order["will_call"]:
        err("ERR_INVALID_STATE", 409, "Pickup requires a will-call order")
    order["fulfillment_status"] = "PICKED_UP"
    release_order_kits(order)
    fulfill_order_invoice(order)
    touch(order)
    return ok(dict(order))


@app.post(f"{API_PREFIX}/orders/<oid>/delivery-booking")
def book_delivery(oid):
    require_roles("CounterRep")
    order = fetch("orders", oid)
    body = get_body()
    require_fields(body, ["slot_id", "expected_order_version"])
    check_int(body["expected_order_version"], "expected_order_version")
    slot = get_or_none("slots", body["slot_id"])
    if slot is None:
        err("ERR_SLOT_NOT_FOUND", 404, "delivery slot not found")
    if order["fulfillment_status"] not in ("OPEN", "PICKING", "STAGED"):
        err("ERR_INVALID_STATE", 409, "Order status does not permit delivery booking")
    if order["delivery_slot_id"]:
        err("ERR_INVALID_STATE", 409, "Order already holds an active booking")
    account = store["accounts"][order["account_id"]]
    if account["status"] != "ACTIVE":
        err("ERR_ACCOUNT_CREDIT_HOLD", 409, "Account is not ACTIVE")
    if body["expected_order_version"] != order["version"]:
        err("ERR_STALE_ORDER_VERSION", 412, "Stale order version")
    we = parse_dt(slot["window_end"])
    if we is not None and _logical_clock >= we:
        err("ERR_DELIVERY_WINDOW_PAST", 422, "Delivery window has passed")
    compute_order_totals(order)
    if slot["booked_cubes"] + order["cubes_total"] > slot["capacity_cubes"]:
        err("ERR_SLOT_FULL", 409, "Delivery slot capacity exceeded")
    order["delivery_slot_id"] = slot["id"]
    slot["booked_cubes"] += order["cubes_total"]
    sync_slot_status(slot)
    touch(order)
    return ok(dict(order))


@app.post(f"{API_PREFIX}/orders/<oid>/delivery-booking/cancel")
def cancel_delivery_booking(oid):
    require_roles("CounterRep")
    order = fetch("orders", oid)
    if not order["delivery_slot_id"]:
        err("ERR_INVALID_STATE", 409, "Order holds no active delivery booking")
    slot = store["slots"].get(order["delivery_slot_id"])
    if slot is not None:
        slot["booked_cubes"] -= order["cubes_total"]
        sync_slot_status(slot)
    order["delivery_slot_id"] = None
    touch(order)
    return ok(dict(order))


# ---------------------------------------------------------------------------
# Substitutions
# ---------------------------------------------------------------------------


@app.post(f"{API_PREFIX}/order-lines/<lid>/propose-substitute")
def propose_substitute(lid):
    require_roles("InsideSales")
    line = fetch("order_lines", lid)
    body = get_body()
    require_fields(body, ["substitute_product_id"])
    substitute = get_or_none("products", body["substitute_product_id"])
    if substitute is None:
        err("ERR_PRODUCT_NOT_FOUND", 404, "substitute product not found")
    if line["status"] != "BACKORDERED" or line["price_source"] == "QUOTE_LOCKED":
        err("ERR_INVALID_STATE", 409, "Substitutes may only be proposed on a BACKORDERED line")
    original = store["products"][line["product_id"]]
    if (original.get("substitute_group") is None
            or substitute.get("substitute_group") is None
            or original["substitute_group"] != substitute["substitute_group"]):
        err("ERR_SUBSTITUTE_GROUP_MISMATCH", 422, "Substitute product does not share the substitute group")
    line["substitute_status"] = "PROPOSED"
    line["proposed_substitute_product_id"] = substitute["id"]
    touch(line)
    return ok(line_view(line))


@app.post(f"{API_PREFIX}/order-lines/<lid>/substitute-decision")
def substitute_decision(lid):
    user_id, role = require_roles("Contractor")
    line = fetch("order_lines", lid)
    order = store["orders"].get(line["order_id"])
    if order is None:
        err("ERR_ORDER_NOT_FOUND", 404, "order not found")
    check_contractor_scope(user_id, role, order["account_id"])
    body = get_body()
    require_fields(body, ["decision", "expected_order_line_version"])
    check_enum(body["decision"], DECISIONS, "decision")
    check_int(body["expected_order_line_version"], "expected_order_line_version")
    if line["substitute_status"] != "PROPOSED":
        err("ERR_INVALID_STATE", 409, "No pending substitute proposal on this line")
    if body["expected_order_line_version"] != line["version"]:
        err("ERR_STALE_LINE_VERSION", 412, "Stale order line version")

    if body["decision"] == "REJECT":
        line["substitute_status"] = "REJECTED"
        line["proposed_substitute_product_id"] = None
        touch(line)
        return ok(line_view(line))

    # APPROVE
    substitute = store["products"][line["proposed_substitute_product_id"]]
    # Release the existing reservation on the old product before re-resolving.
    if line["qty_allocated"] > 0:
        old_stock = get_stock(order["branch_id"], line["product_id"])
        if old_stock is not None:
            old_stock["reserved"] -= line["qty_allocated"]
            touch(old_stock)
        line["qty_allocated"] = 0
    line["product_id"] = substitute["id"]
    line["proposed_substitute_product_id"] = None
    line["substitute_status"] = "APPROVED"
    account = store["accounts"][order["account_id"]]
    unit_price, price_source = resolve_counter_price(account, substitute, None)
    line["unit_price_cents"] = unit_price
    line["price_source"] = price_source
    line["line_total_cents"] = line_extension(line, substitute)
    # Retry the reservation against the substitute product's stock.
    stock_rec = get_stock(order["branch_id"], substitute["id"])
    available = stock_available(stock_rec) if stock_rec else 0
    take = min(line["qty_ordered"] - line["qty_fulfilled"], max(available, 0))
    if take > 0 and stock_rec is not None:
        line["qty_allocated"] = take
        stock_rec["reserved"] += take
        touch(stock_rec)
    if line["qty_allocated"] + line["qty_fulfilled"] >= line["qty_ordered"]:
        line["status"] = "ALLOCATED"
    else:
        line["status"] = "BACKORDERED"
    touch(line)
    compute_order_totals(order)
    touch(order)
    order_bubble_up(order)
    if line["kit_id"]:
        kit = store["kits"].get(line["kit_id"])
        if kit:
            kit_posture_update(kit)
    # If still short, run the waterfall for the substitute product (stock may exist).
    if line["status"] == "BACKORDERED":
        backorder_allocation(order["branch_id"], substitute["id"])
    return ok(line_view(line))


# ---------------------------------------------------------------------------
# Kits
# ---------------------------------------------------------------------------


@app.post(f"{API_PREFIX}/orders/<oid>/kits")
def create_kit(oid):
    require_roles("InsideSales")
    order = fetch("orders", oid)
    body = get_body()
    require_fields(body, ["floor_label", "order_line_ids"])
    if not isinstance(body["floor_label"], str) or not body["floor_label"]:
        err("ERR_INVALID_REQUEST", 400, "floor_label is required")
    line_ids = body["order_line_ids"]
    if not isinstance(line_ids, list) or len(line_ids) < 1:
        err("ERR_INVALID_REQUEST", 400, "order_line_ids must contain at least one id")
    lines = []
    for lid in line_ids:
        line = get_or_none("order_lines", lid)
        if line is None:
            err("ERR_ORDER_LINE_NOT_FOUND", 404, "order line not found")
        if line["order_id"] != order["id"]:
            err("ERR_LINE_ORDER_MISMATCH", 422, "order line does not belong to the path order")
        if line["kit_id"]:
            existing = store["kits"].get(line["kit_id"])
            if existing is not None and existing["status"] != "RELEASED":
                err("ERR_KIT_LINE_CONFLICT", 409, "order line already assigned to an active kit")
        lines.append(line)

    kit = new_record(
        "kits",
        order_id=order["id"],
        floor_label=body["floor_label"],
        status="DRAFT",
        staging_bin=None,
        staged_window_start=None,
        staged_window_end=None,
    )
    for line in lines:
        line["kit_id"] = kit["id"]
        touch(line)
    kit_posture_update(kit)
    return ok(dict(kit), 201)


@app.get(f"{API_PREFIX}/orders/<oid>/kits")
def list_order_kits(oid):
    require_roles("BranchManager", "CounterRep", "InsideSales", "WarehouseLead")
    fetch("orders", oid)
    return list_response(sorted_created(kits_of_order(oid)))


@app.get(f"{API_PREFIX}/kits/<kid>")
def get_kit(kid):
    require_roles("BranchManager", "CounterRep", "InsideSales", "WarehouseLead")
    return ok(dict(fetch("kits", kid)))


@app.get(f"{API_PREFIX}/kits/<kid>/lines")
def kit_lines(kid):
    require_roles("BranchManager", "CounterRep", "InsideSales", "WarehouseLead")
    fetch("kits", kid)
    items = [line_view(ln) for ln in store["order_lines"].values() if ln["kit_id"] == kid]
    return list_response(sorted_created(items))


@app.post(f"{API_PREFIX}/kits/<kid>/stage")
def stage_kit(kid):
    require_roles("WarehouseLead")
    kit = fetch("kits", kid)
    body = get_body()
    require_fields(body, ["staging_bin", "window_start", "window_end"])
    if not isinstance(body["staging_bin"], str) or not body["staging_bin"]:
        err("ERR_INVALID_REQUEST", 400, "staging_bin is required")
    ws = parse_dt(body["window_start"])
    we = parse_dt(body["window_end"])
    if ws is None or we is None:
        err("ERR_INVALID_REQUEST", 400, "window_start / window_end must be valid ISO 8601 datetimes")
    if we <= ws:
        err("ERR_INVALID_REQUEST", 400, "window_end must be after window_start")
    if kit["status"] != "ASSEMBLED":
        err("ERR_INVALID_STATE", 409, "Only an ASSEMBLED kit may be staged")

    buffer = timedelta(hours=WILL_CALL_BUFFER_HOURS)
    for other in store["kits"].values():
        if other["id"] == kit["id"] or other["status"] != "STAGED":
            continue
        if other["staging_bin"] != body["staging_bin"]:
            continue
        ows = parse_dt(other["staged_window_start"])
        owe = parse_dt(other["staged_window_end"])
        if ows is None or owe is None:
            continue
        # Occupancy: [ows, owe + buffer). New window [ws, we) may not intersect;
        # starting exactly at owe + buffer is allowed.
        if ws < owe + buffer and we > ows:
            err("ERR_BIN_OVERLAP", 409, "Staging bin is occupied for a colliding window")
    kit["staging_bin"] = body["staging_bin"]
    kit["staged_window_start"] = body["window_start"]
    kit["staged_window_end"] = body["window_end"]
    kit["status"] = "STAGED"
    touch(kit)
    return ok(dict(kit))


@app.post(f"{API_PREFIX}/kits/<kid>/unstage")
def unstage_kit(kid):
    require_roles("WarehouseLead")
    kit = fetch("kits", kid)
    if kit["status"] != "STAGED":
        err("ERR_INVALID_STATE", 409, "Only a STAGED kit may be unstaged")
    kit["staging_bin"] = None
    kit["staged_window_start"] = None
    kit["staged_window_end"] = None
    kit["status"] = "ASSEMBLED"
    touch(kit)
    return ok(dict(kit))


# ---------------------------------------------------------------------------
# Delivery slots
# ---------------------------------------------------------------------------


@app.post(f"{API_PREFIX}/branches/<bid>/delivery-slots")
def create_slot(bid):
    require_roles("BranchManager")
    fetch("branches", bid)
    body = get_body()
    require_fields(body, ["truck_label", "window_start", "window_end", "capacity_cubes"])
    if not isinstance(body["truck_label"], str) or not body["truck_label"]:
        err("ERR_INVALID_REQUEST", 400, "truck_label is required")
    ws = parse_dt(body["window_start"])
    we = parse_dt(body["window_end"])
    if ws is None or we is None:
        err("ERR_INVALID_REQUEST", 400, "window_start / window_end must be valid ISO 8601 datetimes")
    if we <= ws:
        err("ERR_INVALID_REQUEST", 400, "window_end must be after window_start")
    check_int(body["capacity_cubes"], "capacity_cubes", 1)

    for other in store["slots"].values():
        if other["branch_id"] != bid or other["truck_label"] != body["truck_label"]:
            continue
        if other["status"] in ("CANCELLED", "COMPLETED"):
            continue
        ows = parse_dt(other["window_start"])
        owe = parse_dt(other["window_end"])
        if ows is None or owe is None:
            continue
        # Half-open [start, end): touching endpoints allowed.
        if ws < owe and we > ows:
            err("ERR_SLOT_OVERLAP", 409, "Delivery slot overlaps an existing slot on this truck")
    rec = new_record(
        "slots",
        branch_id=bid,
        truck_label=body["truck_label"],
        window_start=body["window_start"],
        window_end=body["window_end"],
        capacity_cubes=body["capacity_cubes"],
        booked_cubes=0,
        status="OPEN",
    )
    return ok(dict(rec), 201)


@app.get(f"{API_PREFIX}/delivery-slots/<sid>")
def get_slot(sid):
    require_roles("BranchManager", "CounterRep", "InsideSales", "WarehouseLead")
    return ok(dict(fetch("slots", sid)))


@app.post(f"{API_PREFIX}/delivery-slots/<sid>/cancel")
def cancel_slot(sid):
    require_roles("BranchManager")
    slot = fetch("slots", sid)
    if slot["status"] not in ("OPEN", "FULL"):
        err("ERR_INVALID_STATE", 409, "Slot status does not permit cancel")
    if slot["booked_cubes"] != 0:
        err("ERR_INVALID_STATE", 409, "Slot has active bookings")
    slot["status"] = "CANCELLED"
    touch(slot)
    return ok(dict(slot))


@app.get(f"{API_PREFIX}/delivery-slots/<sid>/orders")
def slot_orders(sid):
    require_roles("BranchManager", "CounterRep", "InsideSales", "WarehouseLead")
    fetch("slots", sid)
    items = [o for o in store["orders"].values() if o.get("delivery_slot_id") == sid]
    return list_response(sorted_created(items))


# ---------------------------------------------------------------------------
# Manufacturer programs
# ---------------------------------------------------------------------------


@app.post(f"{API_PREFIX}/manufacturer-programs")
def create_program():
    require_roles("BranchManager")
    body = get_body()
    require_fields(body, ["manufacturer_name", "period_start", "period_end", "tiers",
                          "committed_stock_value_cents"])
    if not isinstance(body["manufacturer_name"], str) or not body["manufacturer_name"]:
        err("ERR_INVALID_REQUEST", 400, "manufacturer_name is required")
    ps = parse_dt(body["period_start"])
    pe = parse_dt(body["period_end"])
    if ps is None or pe is None:
        err("ERR_INVALID_REQUEST", 400, "period_start / period_end must be valid ISO 8601 datetimes")
    if pe <= ps:
        err("ERR_INVALID_REQUEST", 400, "period_end must be after period_start")
    tiers = body["tiers"]
    if not isinstance(tiers, list) or len(tiers) < 1:
        err("ERR_INVALID_REQUEST", 400, "tiers must contain at least one tier")
    prev_threshold = None
    for t in tiers:
        if not isinstance(t, dict) or "threshold_cents" not in t or "rebate_pct" not in t:
            err("ERR_INVALID_REQUEST", 400, "each tier needs threshold_cents and rebate_pct")
        check_int(t["threshold_cents"], "threshold_cents", 0)
        check_int(t["rebate_pct"], "rebate_pct")
        if t["rebate_pct"] < 1 or t["rebate_pct"] > 50:
            err("ERR_INVALID_REQUEST", 400, "rebate_pct must be an integer percent 1..50")
        if prev_threshold is not None and t["threshold_cents"] <= prev_threshold:
            err("ERR_INVALID_REQUEST", 400, "tier thresholds must be strictly ascending")
        prev_threshold = t["threshold_cents"]
    check_int(body["committed_stock_value_cents"], "committed_stock_value_cents", 0)

    for other in store["programs"].values():
        if other["manufacturer_name"] != body["manufacturer_name"]:
            continue
        ops = parse_dt(other["period_start"])
        ope = parse_dt(other["period_end"])
        if ops is None or ope is None:
            continue
        # Closed intervals: touching boundaries conflict.
        if ps <= ope and pe >= ops:
            err("ERR_PROGRAM_OVERLAP", 409, "Program period overlaps an existing program")
    rec = new_record(
        "programs",
        manufacturer_name=body["manufacturer_name"],
        period_start=body["period_start"],
        period_end=body["period_end"],
        tiers=[{"threshold_cents": t["threshold_cents"], "rebate_pct": t["rebate_pct"]} for t in tiers],
        committed_stock_value_cents=body["committed_stock_value_cents"],
        purchases_cents=0,
        attained_rebate_pct=None,
        earned_rebate_cents=None,
        status="ACTIVE",
    )
    return ok(dict(rec), 201)


@app.get(f"{API_PREFIX}/manufacturer-programs")
def list_programs():
    require_roles("BranchManager", "CounterRep", "InsideSales", "WarehouseLead")
    items = list(store["programs"].values())
    for param in ("manufacturer_name", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [p for p in items if p.get(param) == v]
    return list_response(sorted_created(items))


@app.get(f"{API_PREFIX}/manufacturer-programs/<pid>")
def get_program(pid):
    require_roles("BranchManager", "CounterRep", "InsideSales", "WarehouseLead")
    return ok(dict(fetch("programs", pid)))


@app.post(f"{API_PREFIX}/manufacturer-programs/<pid>/close")
def close_program(pid):
    require_roles("BranchManager")
    prog = fetch("programs", pid)
    if prog["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Only an ACTIVE program may be closed")
    pe = parse_dt(prog["period_end"])
    if pe is not None and _logical_clock <= pe:
        err("ERR_PROGRAM_PERIOD_NOT_ENDED", 422, "Program period has not ended")
    attained = 0
    for t in prog["tiers"]:
        if prog["purchases_cents"] >= t["threshold_cents"]:
            attained = max(attained, t["rebate_pct"])
    prog["attained_rebate_pct"] = attained
    prog["earned_rebate_cents"] = round_half_up(prog["purchases_cents"] * attained, 100)
    prog["status"] = "CLOSED"
    touch(prog)
    return ok(dict(prog))


@app.post(f"{API_PREFIX}/manufacturer-programs/<pid>/settle")
def settle_program(pid):
    require_roles("BranchManager")
    prog = fetch("programs", pid)
    if prog["status"] != "CLOSED":
        err("ERR_INVALID_STATE", 409, "Only a CLOSED program may be settled")
    prog["status"] = "SETTLED"
    touch(prog)
    return ok(dict(prog))


# ---------------------------------------------------------------------------
# Returns
# ---------------------------------------------------------------------------


@app.post(f"{API_PREFIX}/returns")
def create_return():
    require_roles("CounterRep")
    body = get_body()
    require_fields(body, ["order_id", "reason", "lines"])
    if not isinstance(body["reason"], str):
        err("ERR_INVALID_REQUEST", 400, "reason is required")
    lines = body["lines"]
    if not isinstance(lines, list) or len(lines) < 1:
        err("ERR_INVALID_REQUEST", 400, "lines must contain at least one line")
    parsed = []
    for ln in lines:
        if not isinstance(ln, dict):
            err("ERR_INVALID_REQUEST", 400, "return line must be an object")
        require_fields(ln, ["order_line_id", "qty"])
        check_int(ln["qty"], "qty", 1)
        parsed.append({"order_line_id": ln["order_line_id"], "qty": ln["qty"]})
    order = get_or_none("orders", body["order_id"])
    if order is None:
        err("ERR_ORDER_NOT_FOUND", 404, "order not found")
    for ln in parsed:
        line = get_or_none("order_lines", ln["order_line_id"])
        if line is None:
            err("ERR_ORDER_LINE_NOT_FOUND", 404, "order line not found")
        if line["order_id"] != order["id"]:
            err("ERR_LINE_ORDER_MISMATCH", 422, "return line does not belong to the order")
    rec = new_record(
        "returns",
        order_id=order["id"],
        reason=body["reason"],
        lines=parsed,
        status="DRAFT",
        submitted_by=None,
        decided_by=None,
        submitted_at=None,
        restocking_fee_cents=None,
        credit_cents=None,
    )
    return ok(dict(rec), 201)


@app.get(f"{API_PREFIX}/returns/<rid>")
def get_return(rid):
    require_roles("BranchManager", "CounterRep", "InsideSales", "WarehouseLead")
    return ok(dict(fetch("returns", rid)))


@app.get(f"{API_PREFIX}/orders/<oid>/returns")
def order_returns(oid):
    user_id, role = require_roles(*ROLES)
    order = fetch("orders", oid)
    check_contractor_scope(user_id, role, order["account_id"])
    items = [r for r in store["returns"].values() if r["order_id"] == oid]
    return list_response(sorted_created(items))


@app.post(f"{API_PREFIX}/returns/<rid>/submit")
def submit_return(rid):
    user_id, _ = require_roles("CounterRep")
    ret = fetch("returns", rid)
    if ret["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "Return status does not permit submit")
    order = store["orders"][ret["order_id"]]

    # Resolve body-referenced line ids (priority 6).
    lines = []
    for rl in ret["lines"]:
        line = store["order_lines"].get(rl["order_line_id"])
        if line is None:
            err("ERR_ORDER_LINE_NOT_FOUND", 404, "order line not found")
        lines.append((line, rl["qty"]))

    # Window check first (priority 12).
    fulfilled_at = order_fulfillment_timestamp(order)
    if fulfilled_at is not None:
        if (_logical_clock - fulfilled_at) > timedelta(days=RETURN_WINDOW_DAYS):
            err("ERR_RETURN_WINDOW_EXPIRED", 422, "Return window has expired")

    # Returnability (priority 20).
    for line, _qty in lines:
        product = store["products"][line["product_id"]]
        if product["is_cut_to_order"] or product["is_special_order"]:
            err("ERR_NON_RETURNABLE_ITEM", 422, "Cut-to-order and special-order items are not returnable")

    # Aggregate empty check (priority 21).
    if all((line["qty_fulfilled"] - line["qty_returned"]) <= 0 for line, _q in lines):
        err("ERR_EMPTY_RETURN", 422, "No returnable quantity across the referenced lines")

    # Per-line quantity (priority 22).
    for line, qty in lines:
        if qty > line["qty_fulfilled"] - line["qty_returned"]:
            err("ERR_RETURN_QTY_EXCEEDS_FULFILLED", 422, "Return qty exceeds fulfilled minus returned")

    # Line-order membership (priority 25).
    for line, _qty in lines:
        if line["order_id"] != order["id"]:
            err("ERR_LINE_ORDER_MISMATCH", 422, "return line does not belong to the order")

    ret["submitted_by"] = user_id
    ret["submitted_at"] = clock_iso()
    ret["status"] = "SUBMITTED"
    touch(ret)
    return ok(dict(ret))


@app.post(f"{API_PREFIX}/returns/<rid>/decision")
def decide_return(rid):
    user_id, _ = require_roles("BranchManager")
    ret = fetch("returns", rid)
    body = get_body()
    require_fields(body, ["decision"])
    check_enum(body["decision"], DECISIONS, "decision")
    if ret["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", 409, "Return status does not permit decision")
    if user_id == ret["submitted_by"]:
        err("ERR_SEGREGATION_OF_DUTIES", 409, "Return decision maker must differ from the submitter")

    ret["decided_by"] = user_id
    if body["decision"] == "REJECT":
        ret["status"] = "REJECTED"
        touch(ret)
        return ok(dict(ret))

    # APPROVE: compute restocking fee (per-line rounding) and credit.
    order = store["orders"][ret["order_id"]]
    fulfilled_at = order_fulfillment_timestamp(order)
    submitted_at = parse_dt(ret["submitted_at"])
    days = 0
    if fulfilled_at is not None and submitted_at is not None:
        days = int((submitted_at - fulfilled_at).total_seconds() // 86400)
    fee_pct = RESTOCK_FEE_TIER1_PCT if days <= RESTOCK_FEE_TIER1_DAYS else RESTOCK_FEE_TIER2_PCT

    total_value = 0
    total_fee = 0
    for rl in ret["lines"]:
        line = store["order_lines"][rl["order_line_id"]]
        product = store["products"][line["product_id"]]
        value = rl["qty"] * line["unit_price_cents"]
        if product["is_cut_to_order"]:
            value *= line["cut_length_ft"]
        total_value += value
        total_fee += round_half_up(value * fee_pct, 100)
    ret["restocking_fee_cents"] = total_fee
    ret["credit_cents"] = total_value - total_fee
    ret["status"] = "APPROVED"
    touch(ret)
    return ok(dict(ret))


@app.post(f"{API_PREFIX}/returns/<rid>/receive")
def receive_return(rid):
    require_roles("WarehouseLead")
    ret = fetch("returns", rid)
    if ret["status"] != "APPROVED":
        err("ERR_INVALID_STATE", 409, "Return status does not permit receive")
    order = store["orders"][ret["order_id"]]

    restocked = []
    for rl in ret["lines"]:
        line = store["order_lines"][rl["order_line_id"]]
        line["qty_returned"] += rl["qty"]
        touch(line)
        stock_rec = get_stock(order["branch_id"], line["product_id"])
        if stock_rec is None:
            stock_rec = new_record(
                "stock", branch_id=order["branch_id"], product_id=line["product_id"],
                on_hand=0, reserved=0,
            )
        stock_rec["on_hand"] += rl["qty"]
        touch(stock_rec)
        restocked.append(line["product_id"])

    ret["status"] = "CREDITED"
    touch(ret)

    account = store["accounts"].get(order["account_id"])
    if account:
        sync_account_credit_fields(account)
        evaluate_credit_hold(account)

    for product_id in dict.fromkeys(restocked):
        backorder_allocation(order["branch_id"], product_id)

    return ok(dict(ret))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
