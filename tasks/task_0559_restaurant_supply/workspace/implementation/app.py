import os
import re
import uuid
import random
import string
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone, timedelta

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"AccountManager", "Buyer", "WarehouseOps"}

PARCEL_MAX_LBS = 150
PARCEL_BASE_CENTS = 1200
PARCEL_RATE_CPL = 50
LTL_BASE_CENTS = 7500
LTL_RATE_CPL = 30
LIFTGATE_FEE_CENTS = 4500
FREE_FREIGHT_THRESHOLD_CENTS = 250000

SEALED_RESTOCK_PCT = Decimal("0.15")
OPENED_RESTOCK_PCT = Decimal("0.25")

RETURN_WINDOW_DAYS = 30
INSTALL_BUFFER_MINUTES = 60

DEFAULT_TAX_RATE = 0.08

CREDIT_TERMS = {"PREPAID", "NET_15", "NET_30"}
PRODUCT_CATEGORIES = {"SMALLWARE", "EQUIPMENT", "CONSUMABLE"}
FULFILLMENT_TYPES = {"STOCK", "DROPSHIP"}
FREIGHT_TYPES = {"PARCEL", "LTL"}
RETURN_CONDITIONS = {"SEALED", "OPENED"}

# ---------------------------------------------------------------------------
# In-memory stores (start empty on every boot)
# ---------------------------------------------------------------------------
accounts = {}
certificates = {}
products = {}
orders = {}
order_lines = {}
shipments = {}
returns = {}
return_lines = {}
docks = {}
appointments = {}
crews = {}
jobs = {}

_seq_counter = [0]
# logical clock, default 2026-05-01T00:00:00Z
_clock = [datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)]


def next_seq():
    _seq_counter[0] += 1
    return _seq_counter[0]


def clock_now():
    return _clock[0]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


NOT_FOUND = {
    "account": "ERR_ACCOUNT_NOT_FOUND",
    "cert": "ERR_CERT_NOT_FOUND",
    "product": "ERR_PRODUCT_NOT_FOUND",
    "order": "ERR_ORDER_NOT_FOUND",
    "order_line": "ERR_ORDER_LINE_NOT_FOUND",
    "shipment": "ERR_SHIPMENT_NOT_FOUND",
    "return": "ERR_RETURN_NOT_FOUND",
    "return_line": "ERR_RETURN_LINE_NOT_FOUND",
    "dock": "ERR_DOCK_NOT_FOUND",
    "appointment": "ERR_APPOINTMENT_NOT_FOUND",
    "crew": "ERR_CREW_NOT_FOUND",
    "job": "ERR_JOB_NOT_FOUND",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def now_dt():
    return datetime.now(timezone.utc)


def iso_ms(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_iso(s):
    if not isinstance(s, str) or not s.strip():
        raise ValueError("bad datetime")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    m = re.match(r"^(.*T\d{2}:\d{2}:\d{2})(\.\d+)?(.*)$", t)
    if m:
        base, frac, rest = m.group(1), m.group(2), m.group(3)
        if frac:
            digits = (frac[1:] + "000000")[:6]
            frac = "." + digits
        else:
            frac = ""
        t = base + frac + rest
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def meta_base():
    return {"api_request_id": req_id(), "api_request_timestamp": iso_ms(now_dt())}


def success(data, response_type="object", status=200, pagination=None):
    meta = meta_base()
    if pagination:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def touch(entity):
    entity["updated_at"] = now_dt()
    entity["version"] += 1


def new_common():
    ts = now_dt()
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def auth(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400)
    if role not in allowed_roles:
        raise ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403)
    return user_id, role


def require_owner(account_id, user_id, role):
    if role == "Buyer" and user_id != account_id:
        raise ApiError("ERR_NOT_ACCOUNT_OWNER", 403)


# ---------------------------------------------------------------------------
# Body / field parsing
# ---------------------------------------------------------------------------
def get_body():
    if not request.data:
        return {}
    body = request.get_json(force=True, silent=True)
    if body is None:
        raise ApiError("ERR_INVALID_REQUEST", 400)
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400)
    return body


def need_str(body, key):
    v = body.get(key)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_INVALID_REQUEST", 400)
    return v


def opt_str(body, key, default=None):
    if key not in body or body.get(key) is None:
        return default
    v = body.get(key)
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", 400)
    return v


def need_int(body, key, minimum=None):
    v = body.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", 400)
    if minimum is not None and v < minimum:
        raise ApiError("ERR_INVALID_REQUEST", 400)
    return v


def opt_int(body, key, default, minimum=None):
    if key not in body or body.get(key) is None:
        return default
    return need_int(body, key, minimum)


def need_enum(body, key, allowed):
    v = body.get(key)
    if v not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", 400)
    return v


def opt_bool(body, key, default):
    if key not in body or body.get(key) is None:
        return default
    v = body.get(key)
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400)
    return v


def need_dt(body, key):
    v = body.get(key)
    try:
        return parse_iso(v)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def get_or_404(store, rid, kind):
    ent = store.get(rid)
    if ent is None:
        raise ApiError(NOT_FOUND[kind], 404)
    return ent


# ---------------------------------------------------------------------------
# Computed field helpers
# ---------------------------------------------------------------------------
def lines_of_order(order_id):
    return [l for l in order_lines.values() if l["order_id"] == order_id]


def rlines_of_return(return_id):
    return [l for l in return_lines.values() if l["return_id"] == return_id]


def product_needs_reorder(p):
    return p["on_hand_qty"] <= p["reorder_point"]


def product_reorder_suggested(p):
    if product_needs_reorder(p):
        return max(0, p["par_level"] - p["on_hand_qty"])
    return 0


def order_merch_subtotal(order):
    total = 0
    for l in lines_of_order(order["id"]):
        if l["status"] != "CANCELLED":
            total += l["line_subtotal_cents"]
    return total


def order_tax(order):
    account = accounts.get(order["account_id"])
    if account and account["tax_exempt_status"] == "CERTIFIED":
        return 0
    rate = Decimal(str(account["tax_rate"])) if account else Decimal(str(DEFAULT_TAX_RATE))
    tax = 0
    for l in lines_of_order(order["id"]):
        if l["status"] == "CANCELLED":
            continue
        p = products.get(l["product_id"])
        if p and p.get("taxable"):
            tax += round_half_up(Decimal(l["line_subtotal_cents"]) * rate)
    return tax


def order_total(order):
    return order_merch_subtotal(order) + order_tax(order) + order["freight_cents"]


def account_outstanding(account):
    total = 0
    for o in orders.values():
        if o["account_id"] != account["id"]:
            continue
        if o["lifecycle_status"] in ("CONFIRMED", "SHIPPED", "COMPLETED") and \
           o["payment_status"] in ("UNPAID", "INVOICED"):
            total += order_total(o)
    for r in returns.values():
        if r["status"] != "REFUNDED":
            continue
        o = orders.get(r["order_id"])
        if o and o["account_id"] == account["id"]:
            total -= r["refund_cents"]
    return total


def credit_available(account):
    return account["credit_limit_cents"] - account_outstanding(account)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def base_out(e):
    return {
        "id": e["id"],
        "created_at": iso_ms(e["created_at"]),
        "updated_at": iso_ms(e["updated_at"]),
        "version": e["version"],
    }


def account_out(a):
    o = base_out(a)
    o.update({
        "business_name": a["business_name"],
        "credit_terms": a["credit_terms"],
        "credit_limit_cents": a["credit_limit_cents"],
        "tax_rate": a["tax_rate"],
        "outstanding_cents": account_outstanding(a),
        "credit_available_cents": credit_available(a),
        "tax_exempt_status": a["tax_exempt_status"],
        "status": a["status"],
    })
    return o


def cert_out(c):
    o = base_out(c)
    o.update({
        "account_id": c["account_id"],
        "cert_number": c["cert_number"],
        "state_code": c["state_code"],
        "expiry_date": iso_ms(c["expiry_date"]),
        "status": c["status"],
    })
    return o


def product_out(p):
    o = base_out(p)
    o.update({
        "sku": p["sku"],
        "name": p["name"],
        "category": p["category"],
        "taxable": p["taxable"],
        "unit_price_cents": p["unit_price_cents"],
        "case_qty": p["case_qty"],
        "case_price_cents": p["case_price_cents"],
        "pallet_case_qty": p["pallet_case_qty"],
        "pallet_price_cents": p["pallet_price_cents"],
        "weight_lbs_per_unit": p["weight_lbs_per_unit"],
        "fulfillment_type": p["fulfillment_type"],
        "freight_type": p["freight_type"],
        "lead_time_days": p["lead_time_days"],
        "on_hand_qty": p["on_hand_qty"],
        "par_level": p["par_level"],
        "reorder_point": p["reorder_point"],
        "needs_reorder": product_needs_reorder(p),
        "reorder_suggested_qty": product_reorder_suggested(p),
    })
    return o


def order_out(o):
    d = base_out(o)
    d.update({
        "account_id": o["account_id"],
        "confirmed_at": iso_ms(o["confirmed_at"]),
        "merchandise_subtotal_cents": order_merch_subtotal(o),
        "tax_cents": order_tax(o),
        "freight_cents": o["freight_cents"],
        "total_cents": order_total(o),
        "lifecycle_status": o["lifecycle_status"],
        "payment_status": o["payment_status"],
    })
    return d


def line_out(l):
    o = base_out(l)
    o.update({
        "order_id": l["order_id"],
        "product_id": l["product_id"],
        "quantity": l["quantity"],
        "pricing_tier": l["pricing_tier"],
        "line_subtotal_cents": l["line_subtotal_cents"],
        "allocated_qty": l["allocated_qty"],
        "backordered_qty": l["backordered_qty"],
        "status": l["status"],
    })
    return o


def shipment_out(s):
    o = base_out(s)
    o.update({
        "order_id": s["order_id"],
        "carrier": s["carrier"],
        "liftgate_required": s["liftgate_required"],
        "shipping_mode": s["shipping_mode"],
        "freight_quote_cents": s["freight_quote_cents"],
        "final_freight_cents": s["final_freight_cents"],
        "delivered_at": iso_ms(s["delivered_at"]),
        "status": s["status"],
    })
    return o


def return_out(r):
    o = base_out(r)
    o.update({
        "order_id": r["order_id"],
        "reason": r["reason"],
        "restock_fee_cents": r["restock_fee_cents"],
        "refund_cents": r["refund_cents"],
        "status": r["status"],
    })
    return o


def rline_out(l):
    o = base_out(l)
    o.update({
        "return_id": l["return_id"],
        "product_id": l["product_id"],
        "quantity": l["quantity"],
        "condition": l["condition"],
        "line_refund_cents": l["line_refund_cents"],
        "status": l["status"],
    })
    return o


def dock_out(d):
    o = base_out(d)
    o.update({"name": d["name"], "location": d["location"]})
    return o


def appt_out(a):
    o = base_out(a)
    o.update({
        "order_id": a["order_id"],
        "dock_id": a["dock_id"],
        "window_start": iso_ms(a["window_start"]),
        "window_end": iso_ms(a["window_end"]),
        "status": a["status"],
    })
    return o


def crew_out(c):
    o = base_out(c)
    o.update({"name": c["name"]})
    return o


def job_out(j):
    o = base_out(j)
    o.update({
        "order_id": j["order_id"],
        "crew_id": j["crew_id"],
        "window_start": iso_ms(j["window_start"]),
        "window_end": iso_ms(j["window_end"]),
        "status": j["status"],
    })
    return o


# ---------------------------------------------------------------------------
# Pagination / listing
# ---------------------------------------------------------------------------
def get_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400)
        limit = max(1, min(100, limit))
    if "offset" in args:
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400)
        offset = max(0, offset)
    return limit, offset


def list_response(items, serializer):
    limit, offset = get_pagination()
    items = sorted(items, key=lambda e: e["_seq"])
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    data = [serializer(e) for e in page]
    return success(data, "array", 200, pagination)


# ---------------------------------------------------------------------------
# Pricing / freight
# ---------------------------------------------------------------------------
def price_line(product, quantity):
    u = product["unit_price_cents"]
    c = product["case_qty"]
    cp = product["case_price_cents"]
    pc = product["pallet_case_qty"]
    pp = product["pallet_price_cents"]
    units_per_pallet = c * pc
    full_pallets = quantity // units_per_pallet if units_per_pallet else 0
    rem1 = quantity % units_per_pallet if units_per_pallet else quantity
    full_cases = rem1 // c if c else 0
    eaches = rem1 % c if c else rem1
    subtotal = full_pallets * pp + full_cases * cp + eaches * u
    if full_pallets > 0:
        tier = "PALLET"
    elif full_cases > 0:
        tier = "CASE"
    else:
        tier = "EACH"
    return tier, subtotal


def order_weight(order_id, use_allocated):
    w = 0
    for l in lines_of_order(order_id):
        if l["status"] == "CANCELLED":
            continue
        p = products.get(l["product_id"])
        if not p or p["fulfillment_type"] == "DROPSHIP":
            continue
        qty = l["allocated_qty"] if use_allocated else l["quantity"]
        w += qty * p["weight_lbs_per_unit"]
    return w


def compute_freight(weight, merch_subtotal, liftgate):
    if weight <= PARCEL_MAX_LBS:
        mode = "PARCEL"
        base = PARCEL_BASE_CENTS + round_half_up(Decimal(PARCEL_RATE_CPL) * Decimal(weight))
        if merch_subtotal >= FREE_FREIGHT_THRESHOLD_CENTS:
            base = 0
        return mode, base
    else:
        mode = "LTL"
        freight = LTL_BASE_CENTS + round_half_up(Decimal(LTL_RATE_CPL) * Decimal(weight))
        if liftgate:
            freight += LIFTGATE_FEE_CENTS
        return mode, freight


# ---------------------------------------------------------------------------
# Error handler
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(err):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(err):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": "ERR_METHOD_NOT_ALLOWED", "message": "Method not allowed"},
    }
    return jsonify(body), 405


@app.route("/", methods=["GET"])
def root():
    return success({}, "object", 200)


# ===========================================================================
# Accounts
# ===========================================================================
@app.route("/accounts", methods=["POST"])
def create_account():
    auth({"AccountManager"})
    body = get_body()
    business_name = need_str(body, "business_name")
    credit_terms = need_enum(body, "credit_terms", CREDIT_TERMS)
    credit_limit = need_int(body, "credit_limit_cents", minimum=0)
    tax_rate = body.get("tax_rate", DEFAULT_TAX_RATE)
    if "tax_rate" in body and body.get("tax_rate") is not None:
        if isinstance(tax_rate, bool) or not isinstance(tax_rate, (int, float)):
            raise ApiError("ERR_INVALID_REQUEST", 400)
    else:
        tax_rate = DEFAULT_TAX_RATE
    a = new_common()
    a.update({
        "business_name": business_name,
        "credit_terms": credit_terms,
        "credit_limit_cents": credit_limit,
        "tax_rate": tax_rate,
        "tax_exempt_status": "NONE",
        "status": "ACTIVE",
    })
    accounts[a["id"]] = a
    return success(account_out(a), "object", 201)


@app.route("/accounts", methods=["GET"])
def list_accounts():
    auth(ROLES)
    return list_response(list(accounts.values()), account_out)


@app.route("/accounts/<account_id>", methods=["GET"])
def get_account(account_id):
    auth(ROLES)
    a = get_or_404(accounts, account_id, "account")
    return success(account_out(a), "object", 200)


@app.route("/accounts/<account_id>/suspend", methods=["POST"])
def suspend_account(account_id):
    auth({"AccountManager"})
    a = get_or_404(accounts, account_id, "account")
    if a["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE", 409)
    a["status"] = "SUSPENDED"
    touch(a)
    return success(account_out(a), "object", 200)


@app.route("/accounts/<account_id>/reinstate", methods=["POST"])
def reinstate_account(account_id):
    auth({"AccountManager"})
    a = get_or_404(accounts, account_id, "account")
    if a["status"] != "SUSPENDED":
        raise ApiError("ERR_ACCOUNT_NOT_SUSPENDED", 409)
    a["status"] = "ACTIVE"
    touch(a)
    return success(account_out(a), "object", 200)


# ===========================================================================
# Tax-exempt certificates
# ===========================================================================
@app.route("/accounts/<account_id>/tax-certificates", methods=["POST"])
def create_cert(account_id):
    user_id, role = auth({"Buyer"})
    a = get_or_404(accounts, account_id, "account")
    require_owner(account_id, user_id, role)
    body = get_body()
    cert_number = need_str(body, "cert_number")
    state_code = need_str(body, "state_code")
    expiry_date = need_dt(body, "expiry_date")
    c = new_common()
    c.update({
        "account_id": account_id,
        "cert_number": cert_number,
        "state_code": state_code,
        "expiry_date": expiry_date,
        "status": "SUBMITTED",
    })
    certificates[c["id"]] = c
    return success(cert_out(c), "object", 201)


@app.route("/accounts/<account_id>/tax-certificates", methods=["GET"])
def list_account_certs(account_id):
    auth(ROLES)
    get_or_404(accounts, account_id, "account")
    items = [c for c in certificates.values() if c["account_id"] == account_id]
    return list_response(items, cert_out)


@app.route("/tax-certificates", methods=["GET"])
def list_certs():
    auth(ROLES)
    items = list(certificates.values())
    acc = request.args.get("account_id")
    if acc is not None:
        items = [c for c in items if c["account_id"] == acc]
    return list_response(items, cert_out)


@app.route("/tax-certificates/<cert_id>", methods=["GET"])
def get_cert(cert_id):
    auth(ROLES)
    c = get_or_404(certificates, cert_id, "cert")
    return success(cert_out(c), "object", 200)


@app.route("/tax-certificates/<cert_id>/approve", methods=["POST"])
def approve_cert(cert_id):
    auth({"AccountManager"})
    c = get_or_404(certificates, cert_id, "cert")
    if c["status"] != "SUBMITTED":
        raise ApiError("ERR_CERT_NOT_SUBMITTED", 409)
    if not (c["expiry_date"] > clock_now()):
        raise ApiError("ERR_CERT_ALREADY_EXPIRED", 409)
    c["status"] = "APPROVED"
    touch(c)
    a = accounts.get(c["account_id"])
    if a:
        a["tax_exempt_status"] = "CERTIFIED"
        touch(a)
    return success(cert_out(c), "object", 200)


@app.route("/tax-certificates/<cert_id>/reject", methods=["POST"])
def reject_cert(cert_id):
    auth({"AccountManager"})
    c = get_or_404(certificates, cert_id, "cert")
    if c["status"] != "SUBMITTED":
        raise ApiError("ERR_CERT_NOT_SUBMITTED", 409)
    c["status"] = "REJECTED"
    touch(c)
    return success(cert_out(c), "object", 200)


@app.route("/tax-certificates/<cert_id>/resubmit", methods=["POST"])
def resubmit_cert(cert_id):
    user_id, role = auth({"Buyer"})
    c = get_or_404(certificates, cert_id, "cert")
    require_owner(c["account_id"], user_id, role)
    if c["status"] != "REJECTED":
        raise ApiError("ERR_CERT_NOT_REJECTED", 409)
    c["status"] = "SUBMITTED"
    touch(c)
    return success(cert_out(c), "object", 200)


# ===========================================================================
# Products
# ===========================================================================
@app.route("/products", methods=["POST"])
def create_product():
    auth({"WarehouseOps"})
    body = get_body()
    p = new_common()
    p.update({
        "sku": need_str(body, "sku"),
        "name": need_str(body, "name"),
        "category": need_enum(body, "category", PRODUCT_CATEGORIES),
        "taxable": opt_bool(body, "taxable", True),
        "unit_price_cents": need_int(body, "unit_price_cents", minimum=0),
        "case_qty": need_int(body, "case_qty", minimum=1),
        "case_price_cents": need_int(body, "case_price_cents", minimum=0),
        "pallet_case_qty": need_int(body, "pallet_case_qty", minimum=1),
        "pallet_price_cents": need_int(body, "pallet_price_cents", minimum=0),
        "weight_lbs_per_unit": need_int(body, "weight_lbs_per_unit", minimum=0),
        "fulfillment_type": need_enum(body, "fulfillment_type", FULFILLMENT_TYPES),
        "freight_type": need_enum(body, "freight_type", FREIGHT_TYPES),
        "lead_time_days": opt_int(body, "lead_time_days", 0, minimum=0),
        "on_hand_qty": need_int(body, "on_hand_qty", minimum=0),
        "par_level": need_int(body, "par_level", minimum=0),
        "reorder_point": need_int(body, "reorder_point", minimum=0),
    })
    products[p["id"]] = p
    return success(product_out(p), "object", 201)


@app.route("/products", methods=["GET"])
def list_products():
    auth(ROLES)
    return list_response(list(products.values()), product_out)


@app.route("/products/<product_id>", methods=["GET"])
def get_product(product_id):
    auth(ROLES)
    p = get_or_404(products, product_id, "product")
    return success(product_out(p), "object", 200)


@app.route("/products/<product_id>/restock", methods=["POST"])
def restock_product(product_id):
    auth({"WarehouseOps"})
    p = get_or_404(products, product_id, "product")
    body = get_body()
    qty = need_int(body, "quantity", minimum=1)
    p["on_hand_qty"] += qty
    touch(p)
    return success(product_out(p), "object", 200)


# ===========================================================================
# Orders
# ===========================================================================
@app.route("/orders", methods=["POST"])
def create_order():
    user_id, role = auth({"Buyer"})
    body = get_body()
    account_id = need_str(body, "account_id")
    require_owner(account_id, user_id, role)
    get_or_404(accounts, account_id, "account")
    o = new_common()
    o.update({
        "account_id": account_id,
        "confirmed_at": None,
        "freight_cents": 0,
        "_freight_shipment_id": None,
        "lifecycle_status": "DRAFT",
        "payment_status": "UNPAID",
    })
    orders[o["id"]] = o
    return success(order_out(o), "object", 201)


@app.route("/orders", methods=["GET"])
def list_orders():
    auth(ROLES)
    items = list(orders.values())
    acc = request.args.get("account_id")
    if acc is not None:
        items = [o for o in items if o["account_id"] == acc]
    return list_response(items, order_out)


@app.route("/orders/<order_id>", methods=["GET"])
def get_order(order_id):
    auth(ROLES)
    o = get_or_404(orders, order_id, "order")
    return success(order_out(o), "object", 200)


@app.route("/orders/<order_id>/lines", methods=["POST"])
def add_line(order_id):
    user_id, role = auth({"Buyer"})
    o = get_or_404(orders, order_id, "order")
    require_owner(o["account_id"], user_id, role)
    body = get_body()
    product_id = need_str(body, "product_id")
    p = get_or_404(products, product_id, "product")
    if o["lifecycle_status"] != "DRAFT":
        raise ApiError("ERR_ORDER_NOT_DRAFT", 409)
    quantity = need_int(body, "quantity", minimum=1)
    tier, subtotal = price_line(p, quantity)
    l = new_common()
    l.update({
        "order_id": order_id,
        "product_id": product_id,
        "quantity": quantity,
        "pricing_tier": tier,
        "line_subtotal_cents": subtotal,
        "allocated_qty": 0,
        "backordered_qty": 0,
        "status": "PENDING",
    })
    order_lines[l["id"]] = l
    touch(o)
    return success(line_out(l), "object", 201)


@app.route("/orders/<order_id>/lines", methods=["GET"])
def list_order_lines(order_id):
    auth(ROLES)
    get_or_404(orders, order_id, "order")
    items = lines_of_order(order_id)
    return list_response(items, line_out)


@app.route("/order-lines", methods=["GET"])
def list_lines():
    auth(ROLES)
    items = list(order_lines.values())
    oid = request.args.get("order_id")
    pid = request.args.get("product_id")
    if oid is not None:
        items = [l for l in items if l["order_id"] == oid]
    if pid is not None:
        items = [l for l in items if l["product_id"] == pid]
    return list_response(items, line_out)


@app.route("/order-lines/<order_line_id>", methods=["GET"])
def get_line(order_line_id):
    auth(ROLES)
    l = get_or_404(order_lines, order_line_id, "order_line")
    return success(line_out(l), "object", 200)


@app.route("/orders/<order_id>/confirm", methods=["POST"])
def confirm_order(order_id):
    user_id, role = auth({"Buyer"})
    o = get_or_404(orders, order_id, "order")
    require_owner(o["account_id"], user_id, role)
    if o["lifecycle_status"] != "DRAFT":
        raise ApiError("ERR_ORDER_NOT_DRAFT", 409)
    lines = [l for l in lines_of_order(order_id) if l["status"] != "CANCELLED"]
    if len(lines) < 1:
        raise ApiError("ERR_ORDER_HAS_NO_LINES", 422)
    account = accounts.get(o["account_id"])
    if account is None:
        raise ApiError("ERR_ACCOUNT_NOT_FOUND", 404)
    if account["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_SUSPENDED", 409)
    # total = subtotal + tax (freight still 0)
    total = order_merch_subtotal(o) + order_tax(o)
    if total > credit_available(account):
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED", 402)
    body = get_body()
    expected = body.get("expected_account_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError("ERR_INVALID_REQUEST", 400)
    if expected != account["version"]:
        raise ApiError("ERR_STALE_ACCOUNT_VERSION", 412)

    # success: stock cascade
    o["confirmed_at"] = clock_now()
    touched_products = set()
    for l in lines:
        p = products.get(l["product_id"])
        if p and p["fulfillment_type"] == "DROPSHIP":
            l["status"] = "DROPSHIP_PENDING"
            touch(l)
            continue
        allocated = min(l["quantity"], p["on_hand_qty"]) if p else 0
        backordered = l["quantity"] - allocated
        if p:
            p["on_hand_qty"] -= allocated
            touched_products.add(p["id"])
        l["allocated_qty"] = allocated
        l["backordered_qty"] = backordered
        if backordered == 0:
            l["status"] = "ALLOCATED"
        elif allocated == 0:
            l["status"] = "BACKORDERED"
        else:
            l["status"] = "PARTIAL"
        touch(l)
    for pid in touched_products:
        touch(products[pid])
    o["lifecycle_status"] = "CONFIRMED"
    touch(o)
    account["version"] += 1
    account["updated_at"] = now_dt()
    return success(order_out(o), "object", 200)


@app.route("/orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    user_id, role = auth({"Buyer"})
    o = get_or_404(orders, order_id, "order")
    require_owner(o["account_id"], user_id, role)
    if o["lifecycle_status"] not in ("DRAFT", "CONFIRMED"):
        raise ApiError("ERR_ORDER_NOT_CANCELLABLE", 409)
    was_confirmed = o["lifecycle_status"] == "CONFIRMED"
    touched_products = set()
    for l in lines_of_order(order_id):
        if l["status"] == "CANCELLED":
            continue
        if was_confirmed:
            p = products.get(l["product_id"])
            if p and l["allocated_qty"]:
                p["on_hand_qty"] += l["allocated_qty"]
                touched_products.add(p["id"])
            l["allocated_qty"] = 0
            l["backordered_qty"] = 0
        l["status"] = "CANCELLED"
        touch(l)
    for pid in touched_products:
        touch(products[pid])
    o["lifecycle_status"] = "CANCELLED"
    touch(o)
    return success(order_out(o), "object", 200)


@app.route("/orders/<order_id>/invoice", methods=["POST"])
def invoice_order(order_id):
    auth({"AccountManager"})
    o = get_or_404(orders, order_id, "order")
    if o["lifecycle_status"] not in ("CONFIRMED", "SHIPPED"):
        raise ApiError("ERR_ORDER_NOT_CONFIRMED", 409)
    if o["payment_status"] != "UNPAID":
        raise ApiError("ERR_PAYMENT_NOT_UNPAID", 409)
    o["payment_status"] = "INVOICED"
    touch(o)
    return success(order_out(o), "object", 200)


@app.route("/orders/<order_id>/pay", methods=["POST"])
def pay_order(order_id):
    user_id, role = auth({"Buyer"})
    o = get_or_404(orders, order_id, "order")
    require_owner(o["account_id"], user_id, role)
    if o["payment_status"] != "INVOICED":
        raise ApiError("ERR_PAYMENT_NOT_INVOICED", 409)
    o["payment_status"] = "PAID"
    touch(o)
    return success(order_out(o), "object", 200)


# ===========================================================================
# Shipments
# ===========================================================================
@app.route("/shipments", methods=["POST"])
def create_shipment():
    auth({"WarehouseOps"})
    body = get_body()
    order_id = need_str(body, "order_id")
    o = get_or_404(orders, order_id, "order")
    carrier = need_str(body, "carrier")
    liftgate = opt_bool(body, "liftgate_required", False)
    weight = order_weight(order_id, use_allocated=False)
    merch = order_merch_subtotal(o)
    mode, quote = compute_freight(weight, merch, liftgate)
    s = new_common()
    s.update({
        "order_id": order_id,
        "carrier": carrier,
        "liftgate_required": liftgate,
        "shipping_mode": mode,
        "freight_quote_cents": quote,
        "final_freight_cents": None,
        "delivered_at": None,
        "status": "QUOTED",
    })
    shipments[s["id"]] = s
    o["freight_cents"] = quote
    o["_freight_shipment_id"] = s["id"]
    touch(o)
    return success(shipment_out(s), "object", 201)


@app.route("/shipments", methods=["GET"])
def list_shipments():
    auth(ROLES)
    items = list(shipments.values())
    oid = request.args.get("order_id")
    if oid is not None:
        items = [s for s in items if s["order_id"] == oid]
    return list_response(items, shipment_out)


@app.route("/shipments/<shipment_id>", methods=["GET"])
def get_shipment(shipment_id):
    auth(ROLES)
    s = get_or_404(shipments, shipment_id, "shipment")
    return success(shipment_out(s), "object", 200)


@app.route("/shipments/<shipment_id>/book", methods=["POST"])
def book_shipment(shipment_id):
    auth({"WarehouseOps"})
    s = get_or_404(shipments, shipment_id, "shipment")
    if s["status"] != "QUOTED":
        raise ApiError("ERR_SHIPMENT_NOT_QUOTED", 409)
    o = orders.get(s["order_id"])
    if o is None:
        raise ApiError("ERR_ORDER_NOT_FOUND", 404)
    if o["lifecycle_status"] != "CONFIRMED":
        raise ApiError("ERR_ORDER_NOT_CONFIRMED", 409)
    body = get_body()
    new_carrier = opt_str(body, "carrier")
    if new_carrier is not None:
        s["carrier"] = new_carrier
    weight = order_weight(o["id"], use_allocated=True)
    merch = order_merch_subtotal(o)
    mode, final = compute_freight(weight, merch, s["liftgate_required"])
    s["shipping_mode"] = mode
    s["final_freight_cents"] = final
    s["status"] = "BOOKED"
    touch(s)
    o["freight_cents"] = final
    o["_freight_shipment_id"] = s["id"]
    o["lifecycle_status"] = "SHIPPED"
    touch(o)
    for l in lines_of_order(o["id"]):
        if l["status"] != "CANCELLED":
            l["status"] = "SHIPPED"
            touch(l)
    return success(shipment_out(s), "object", 200)


@app.route("/shipments/<shipment_id>/deliver", methods=["POST"])
def deliver_shipment(shipment_id):
    auth({"WarehouseOps"})
    s = get_or_404(shipments, shipment_id, "shipment")
    if s["status"] != "BOOKED":
        raise ApiError("ERR_SHIPMENT_NOT_BOOKED", 409)
    s["delivered_at"] = clock_now()
    s["status"] = "DELIVERED"
    touch(s)
    o = orders.get(s["order_id"])
    if o and o["lifecycle_status"] == "SHIPPED":
        o["lifecycle_status"] = "COMPLETED"
        touch(o)
    return success(shipment_out(s), "object", 200)


@app.route("/shipments/<shipment_id>/cancel", methods=["POST"])
def cancel_shipment(shipment_id):
    auth({"WarehouseOps"})
    s = get_or_404(shipments, shipment_id, "shipment")
    if s["status"] not in ("QUOTED", "BOOKED"):
        raise ApiError("ERR_SHIPMENT_NOT_CANCELLABLE", 409)
    s["status"] = "CANCELLED"
    touch(s)
    o = orders.get(s["order_id"])
    if o and o.get("_freight_shipment_id") == s["id"]:
        o["freight_cents"] = 0
        o["_freight_shipment_id"] = None
        touch(o)
    return success(shipment_out(s), "object", 200)


# ===========================================================================
# Returns
# ===========================================================================
@app.route("/orders/<order_id>/returns", methods=["POST"])
def open_return(order_id):
    user_id, role = auth({"Buyer"})
    o = get_or_404(orders, order_id, "order")
    require_owner(o["account_id"], user_id, role)
    if o["lifecycle_status"] != "COMPLETED":
        raise ApiError("ERR_ORDER_NOT_COMPLETED", 409)
    delivered_at = None
    for s in shipments.values():
        if s["order_id"] == order_id and s["delivered_at"] is not None:
            delivered_at = s["delivered_at"]
            break
    if delivered_at is not None:
        if clock_now() > delivered_at + timedelta(days=RETURN_WINDOW_DAYS):
            raise ApiError("ERR_RETURN_WINDOW_EXPIRED", 422)
    body = get_body()
    reason = need_str(body, "reason")
    r = new_common()
    r.update({
        "order_id": order_id,
        "reason": reason,
        "restock_fee_cents": 0,
        "refund_cents": 0,
        "status": "REQUESTED",
    })
    returns[r["id"]] = r
    return success(return_out(r), "object", 201)


@app.route("/returns", methods=["GET"])
def list_returns():
    auth(ROLES)
    items = list(returns.values())
    oid = request.args.get("order_id")
    if oid is not None:
        items = [r for r in items if r["order_id"] == oid]
    return list_response(items, return_out)


@app.route("/returns/<return_id>", methods=["GET"])
def get_return(return_id):
    auth(ROLES)
    r = get_or_404(returns, return_id, "return")
    return success(return_out(r), "object", 200)


@app.route("/returns/<return_id>/lines", methods=["POST"])
def add_return_line(return_id):
    user_id, role = auth({"Buyer"})
    r = get_or_404(returns, return_id, "return")
    order = orders.get(r["order_id"])
    owner_account = order["account_id"] if order else None
    require_owner(owner_account, user_id, role)
    body = get_body()
    product_id = need_str(body, "product_id")
    get_or_404(products, product_id, "product")
    if r["status"] != "REQUESTED":
        raise ApiError("ERR_RETURN_NOT_REQUESTED", 409)
    # product must appear on original order
    order_prod_qty = 0
    found = False
    for l in lines_of_order(r["order_id"]):
        if l["product_id"] == product_id:
            found = True
            order_prod_qty += l["quantity"]
    if not found:
        raise ApiError("ERR_PRODUCT_NOT_IN_ORDER", 422)
    quantity = need_int(body, "quantity", minimum=1)
    condition = need_enum(body, "condition", RETURN_CONDITIONS)
    if quantity > order_prod_qty:
        raise ApiError("ERR_RETURN_QTY_EXCEEDS_ORDERED", 422)
    l = new_common()
    l.update({
        "return_id": return_id,
        "product_id": product_id,
        "quantity": quantity,
        "condition": condition,
        "line_refund_cents": 0,
        "status": "PENDING",
    })
    return_lines[l["id"]] = l
    touch(r)
    return success(rline_out(l), "object", 201)


@app.route("/returns/<return_id>/lines", methods=["GET"])
def list_return_lines(return_id):
    auth(ROLES)
    get_or_404(returns, return_id, "return")
    items = rlines_of_return(return_id)
    return list_response(items, rline_out)


@app.route("/return-lines", methods=["GET"])
def list_rlines():
    auth(ROLES)
    items = list(return_lines.values())
    rid = request.args.get("return_id")
    pid = request.args.get("product_id")
    if rid is not None:
        items = [l for l in items if l["return_id"] == rid]
    if pid is not None:
        items = [l for l in items if l["product_id"] == pid]
    return list_response(items, rline_out)


@app.route("/return-lines/<return_line_id>", methods=["GET"])
def get_rline(return_line_id):
    auth(ROLES)
    l = get_or_404(return_lines, return_line_id, "return_line")
    return success(rline_out(l), "object", 200)


@app.route("/returns/<return_id>/approve", methods=["POST"])
def approve_return(return_id):
    auth({"WarehouseOps"})
    r = get_or_404(returns, return_id, "return")
    if r["status"] != "REQUESTED":
        raise ApiError("ERR_RETURN_NOT_REQUESTED", 409)
    rlines = rlines_of_return(return_id)
    if len(rlines) < 1:
        raise ApiError("ERR_RETURN_HAS_NO_LINES", 422)
    total_restock = 0
    total_refund = 0
    for l in rlines:
        p = products.get(l["product_id"])
        unit = p["unit_price_cents"] if p else 0
        merch_value = l["quantity"] * unit
        pct = SEALED_RESTOCK_PCT if l["condition"] == "SEALED" else OPENED_RESTOCK_PCT
        restock_fee = round_half_up(Decimal(merch_value) * pct)
        line_refund = merch_value - restock_fee
        l["line_refund_cents"] = line_refund
        touch(l)
        total_restock += restock_fee
        total_refund += line_refund
    r["restock_fee_cents"] = total_restock
    r["refund_cents"] = total_refund
    r["status"] = "APPROVED"
    touch(r)
    return success(return_out(r), "object", 200)


@app.route("/returns/<return_id>/revise", methods=["POST"])
def revise_return(return_id):
    auth({"WarehouseOps"})
    r = get_or_404(returns, return_id, "return")
    if r["status"] != "APPROVED":
        raise ApiError("ERR_RETURN_NOT_APPROVED", 409)
    for l in rlines_of_return(return_id):
        l["line_refund_cents"] = 0
        touch(l)
    r["refund_cents"] = 0
    r["restock_fee_cents"] = 0
    r["status"] = "REQUESTED"
    touch(r)
    return success(return_out(r), "object", 200)


@app.route("/returns/<return_id>/reject", methods=["POST"])
def reject_return(return_id):
    auth({"WarehouseOps"})
    r = get_or_404(returns, return_id, "return")
    if r["status"] != "REQUESTED":
        raise ApiError("ERR_RETURN_NOT_REQUESTED", 409)
    r["status"] = "REJECTED"
    touch(r)
    return success(return_out(r), "object", 200)


@app.route("/returns/<return_id>/receive", methods=["POST"])
def receive_return(return_id):
    auth({"WarehouseOps"})
    r = get_or_404(returns, return_id, "return")
    if r["status"] != "APPROVED":
        raise ApiError("ERR_RETURN_NOT_APPROVED", 409)
    touched_products = set()
    for l in rlines_of_return(return_id):
        p = products.get(l["product_id"])
        if p:
            p["on_hand_qty"] += l["quantity"]
            touched_products.add(p["id"])
        l["status"] = "RECEIVED"
        touch(l)
    for pid in touched_products:
        touch(products[pid])
    r["status"] = "RECEIVED"
    touch(r)
    return success(return_out(r), "object", 200)


@app.route("/returns/<return_id>/refund", methods=["POST"])
def refund_return(return_id):
    auth({"WarehouseOps"})
    r = get_or_404(returns, return_id, "return")
    if r["status"] != "RECEIVED":
        raise ApiError("ERR_RETURN_NOT_RECEIVED", 409)
    r["status"] = "REFUNDED"
    touch(r)
    return success(return_out(r), "object", 200)


# ===========================================================================
# Docks / Delivery appointments
# ===========================================================================
@app.route("/docks", methods=["POST"])
def create_dock():
    auth({"WarehouseOps"})
    body = get_body()
    d = new_common()
    d.update({
        "name": need_str(body, "name"),
        "location": opt_str(body, "location", ""),
    })
    docks[d["id"]] = d
    return success(dock_out(d), "object", 201)


@app.route("/docks", methods=["GET"])
def list_docks():
    auth(ROLES)
    return list_response(list(docks.values()), dock_out)


@app.route("/docks/<dock_id>", methods=["GET"])
def get_dock(dock_id):
    auth(ROLES)
    d = get_or_404(docks, dock_id, "dock")
    return success(dock_out(d), "object", 200)


@app.route("/delivery-appointments", methods=["POST"])
def create_appointment():
    auth({"WarehouseOps"})
    body = get_body()
    order_id = need_str(body, "order_id")
    get_or_404(orders, order_id, "order")
    dock_id = need_str(body, "dock_id")
    get_or_404(docks, dock_id, "dock")
    window_start = need_dt(body, "window_start")
    window_end = need_dt(body, "window_end")
    if not (window_end > window_start):
        raise ApiError("ERR_INVALID_TIME_WINDOW", 422)
    for a in appointments.values():
        if a["dock_id"] != dock_id or a["status"] != "SCHEDULED":
            continue
        # half-open overlap
        if window_start < a["window_end"] and a["window_start"] < window_end:
            raise ApiError("ERR_DOCK_DOUBLE_BOOKED", 409)
    a = new_common()
    a.update({
        "order_id": order_id,
        "dock_id": dock_id,
        "window_start": window_start,
        "window_end": window_end,
        "status": "SCHEDULED",
    })
    appointments[a["id"]] = a
    return success(appt_out(a), "object", 201)


@app.route("/delivery-appointments", methods=["GET"])
def list_appointments():
    auth(ROLES)
    items = list(appointments.values())
    oid = request.args.get("order_id")
    did = request.args.get("dock_id")
    if oid is not None:
        items = [a for a in items if a["order_id"] == oid]
    if did is not None:
        items = [a for a in items if a["dock_id"] == did]
    return list_response(items, appt_out)


@app.route("/delivery-appointments/<appointment_id>", methods=["GET"])
def get_appointment(appointment_id):
    auth(ROLES)
    a = get_or_404(appointments, appointment_id, "appointment")
    return success(appt_out(a), "object", 200)


@app.route("/delivery-appointments/<appointment_id>/cancel", methods=["POST"])
def cancel_appointment(appointment_id):
    auth({"WarehouseOps"})
    a = get_or_404(appointments, appointment_id, "appointment")
    if a["status"] != "SCHEDULED":
        raise ApiError("ERR_APPOINTMENT_NOT_SCHEDULED", 409)
    a["status"] = "CANCELLED"
    touch(a)
    return success(appt_out(a), "object", 200)


# ===========================================================================
# Install crews / jobs
# ===========================================================================
@app.route("/install-crews", methods=["POST"])
def create_crew():
    auth({"WarehouseOps"})
    body = get_body()
    c = new_common()
    c.update({"name": need_str(body, "name")})
    crews[c["id"]] = c
    return success(crew_out(c), "object", 201)


@app.route("/install-crews", methods=["GET"])
def list_crews():
    auth(ROLES)
    return list_response(list(crews.values()), crew_out)


@app.route("/install-crews/<crew_id>", methods=["GET"])
def get_crew(crew_id):
    auth(ROLES)
    c = get_or_404(crews, crew_id, "crew")
    return success(crew_out(c), "object", 200)


@app.route("/install-jobs", methods=["POST"])
def create_job():
    auth({"WarehouseOps"})
    body = get_body()
    order_id = need_str(body, "order_id")
    o = get_or_404(orders, order_id, "order")
    crew_id = need_str(body, "crew_id")
    get_or_404(crews, crew_id, "crew")
    window_start = need_dt(body, "window_start")
    window_end = need_dt(body, "window_end")
    if not (window_end > window_start):
        raise ApiError("ERR_INVALID_TIME_WINDOW", 422)
    # order must contain an EQUIPMENT line
    equip_lines = []
    for l in lines_of_order(order_id):
        if l["status"] == "CANCELLED":
            continue
        p = products.get(l["product_id"])
        if p and p["category"] == "EQUIPMENT":
            equip_lines.append((l, p))
    if not equip_lines:
        raise ApiError("ERR_NO_EQUIPMENT_LINE", 422)
    # lead time
    max_lead = max(p["lead_time_days"] for (_, p) in equip_lines)
    if o["confirmed_at"] is not None:
        earliest = o["confirmed_at"] + timedelta(days=max_lead)
        if window_start < earliest:
            raise ApiError("ERR_LEAD_TIME_NOT_ELAPSED", 422)
    # crew buffer
    buffer = timedelta(minutes=INSTALL_BUFFER_MINUTES)
    for j in jobs.values():
        if j["crew_id"] != crew_id or j["status"] != "SCHEDULED":
            continue
        if window_start < j["window_end"] + buffer and j["window_start"] < window_end + buffer:
            raise ApiError("ERR_CREW_BUFFER_CONFLICT", 409)
    j = new_common()
    j.update({
        "order_id": order_id,
        "crew_id": crew_id,
        "window_start": window_start,
        "window_end": window_end,
        "status": "SCHEDULED",
    })
    jobs[j["id"]] = j
    return success(job_out(j), "object", 201)


@app.route("/install-jobs", methods=["GET"])
def list_jobs():
    auth(ROLES)
    items = list(jobs.values())
    oid = request.args.get("order_id")
    cid = request.args.get("crew_id")
    if oid is not None:
        items = [j for j in items if j["order_id"] == oid]
    if cid is not None:
        items = [j for j in items if j["crew_id"] == cid]
    return list_response(items, job_out)


@app.route("/install-jobs/<job_id>", methods=["GET"])
def get_job(job_id):
    auth(ROLES)
    j = get_or_404(jobs, job_id, "job")
    return success(job_out(j), "object", 200)


@app.route("/install-jobs/<job_id>/cancel", methods=["POST"])
def cancel_job(job_id):
    auth({"WarehouseOps"})
    j = get_or_404(jobs, job_id, "job")
    if j["status"] != "SCHEDULED":
        raise ApiError("ERR_JOB_NOT_SCHEDULED", 409)
    j["status"] = "CANCELLED"
    touch(j)
    return success(job_out(j), "object", 200)


# ===========================================================================
# Logical clock (test-driving)
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth({"WarehouseOps"})
    body = get_body()
    target = need_dt(body, "to_iso8601")
    _clock[0] = target
    # expire APPROVED certs whose expiry_date <= now
    for c in certificates.values():
        if c["status"] == "APPROVED" and c["expiry_date"] <= target:
            c["status"] = "EXPIRED"
            touch(c)
            a = accounts.get(c["account_id"])
            if a:
                a["tax_exempt_status"] = "EXPIRED"
                touch(a)
    return success({}, "object", 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
