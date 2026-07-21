"""
Sewing-Machine & Vacuum Sales/Service API (task_1030).

Single-file Flask implementation with in-memory storage. The store is empty on
every boot; the logical clock resets to 2026-07-01T00:00:00Z. No wall-clock time
is ever read.
"""
import os
import math
import random
import string
import calendar
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone, timedelta

from flask import Flask, request, jsonify

app = Flask(__name__)
app.url_map.strict_slashes = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"SalesAssociate", "ServiceTech", "StoreManager", "Customer"}

TRADE_IN_SCHEDULE = {"GOOD": 40000, "FAIR": 25000, "POOR": 10000}
TRADE_IN_BAND = 15000
LABOR_RATE_CENTS = 9000
TAX_RATE = Decimal("0.08")
DISCOUNT_PCT = {"STANDARD": Decimal("0.0"), "GOLD": Decimal("0.05"), "PLATINUM": Decimal("0.10")}
GOLD_THRESHOLD = 500000
PLATINUM_THRESHOLD = 1500000
PERIOD_DAYS = 30
LATE_MULTIPLIER = Decimal("1.5")
SCHEDULE_BUFFER = timedelta(minutes=30)

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_VALIDATION": 400,
    "ERR_PRODUCT_NOT_FOUND": 404,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_INVENTORY_ITEM_NOT_FOUND": 404,
    "ERR_SALES_ORDER_NOT_FOUND": 404,
    "ERR_REPAIR_TICKET_NOT_FOUND": 404,
    "ERR_RENTAL_NOT_FOUND": 404,
    "ERR_CLASS_SESSION_NOT_FOUND": 404,
    "ERR_ENROLLMENT_NOT_FOUND": 404,
    "ERR_SUBSCRIPTION_NOT_FOUND": 404,
    "ERR_SPECIAL_ORDER_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_ITEM_NOT_AVAILABLE": 409,
    "ERR_ALREADY_RECALLED": 409,
    "ERR_SESSION_NOT_OPEN": 409,
    "ERR_PRODUCT_RECALLED": 409,
    "ERR_RENTAL_OVERLAP": 409,
    "ERR_SCHEDULE_CONFLICT": 409,
    "ERR_NOT_A_PART": 409,
    "ERR_TUNE_UPS_EXHAUSTED": 409,
    "ERR_TRADE_IN_OUT_OF_BAND": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_INVALID_TRADE_IN": 400,
}


class ApiError(Exception):
    def __init__(self, error_id, http_status=None, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status if http_status is not None else ERROR_STATUS.get(error_id, 400)
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
_CLOCK = {"now": datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)}


def now():
    return _CLOCK["now"]


def set_clock(dt):
    _CLOCK["now"] = dt


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------
def parse_iso(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def ceil_days(delta):
    """Exact ceiling of a timedelta divided by one day (works for negatives)."""
    frac = delta.seconds * 1_000_000 + delta.microseconds  # always >= 0 (normalized)
    if frac == 0:
        return delta.days
    return delta.days + 1


def add_months(dt, months):
    m = dt.month - 1 + months
    y = dt.year + m // 12
    mo = m % 12 + 1
    d = min(dt.day, calendar.monthrange(y, mo)[1])
    return dt.replace(year=y, month=mo, day=d)


def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def tier_of(spend):
    if spend >= PLATINUM_THRESHOLD:
        return "PLATINUM"
    if spend >= GOLD_THRESHOLD:
        return "GOLD"
    return "STANDARD"


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
products = {}
customers = {}
inventory = {}
sales_orders = {}
repair_tickets = {}
rentals = {}
class_sessions = {}
enrollments = {}
subscriptions = {}
special_orders = {}

_seq_counter = {"n": 0}


def next_seq():
    _seq_counter["n"] += 1
    return _seq_counter["n"]


def new_entity(fields):
    ts = now()
    e = {
        "id": _uuid(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    e.update(fields)
    return e


def _uuid():
    import uuid
    return str(uuid.uuid4())


def touch(entity):
    entity["version"] += 1
    entity["updated_at"] = now()


def serialize(entity):
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = format_iso(v)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def gen_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def make_meta(extra=None):
    meta = {"api_request_id": gen_req_id(), "api_request_timestamp": format_iso(now())}
    if extra:
        meta.update(extra)
    return meta


def respond_object(data, code=200):
    body = {"meta": make_meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def respond_array(items, limit, offset, total):
    has_more = offset + limit < total
    pag = {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}
    body = {"meta": make_meta(pag), "response_type": "array", "data": items}
    return jsonify(body), 200


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(err):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(err):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"},
    }
    return jsonify(body), 404


# ---------------------------------------------------------------------------
# Auth / validation helpers
# ---------------------------------------------------------------------------
def auth_and_role(allowed):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN")
    return uid, role


def check_ownership(role, uid, owner_id):
    if role == "Customer" and uid != owner_id:
        raise ApiError("ERR_FORBIDDEN")


def body_dict():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise ApiError("ERR_VALIDATION", message="Request body must be a JSON object")
    return b


def bad(msg="Invalid request body"):
    raise ApiError("ERR_VALIDATION", message=msg)


def req_str(b, name):
    v = b.get(name)
    if not isinstance(v, str) or v == "":
        bad("%s is required" % name)
    return v


def opt_str(b, name, default=None):
    if name not in b or b[name] is None:
        return default
    v = b[name]
    if not isinstance(v, str):
        bad("%s must be a string" % name)
    return v


def req_int(b, name, min_=None):
    v = b.get(name)
    if not isinstance(v, int) or isinstance(v, bool):
        bad("%s must be an integer" % name)
    if min_ is not None and v < min_:
        bad("%s must be >= %s" % (name, min_))
    return v


def opt_int(b, name, default=None, min_=None):
    if name not in b or b[name] is None:
        return default
    v = b[name]
    if not isinstance(v, int) or isinstance(v, bool):
        bad("%s must be an integer" % name)
    if min_ is not None and v < min_:
        bad("%s must be >= %s" % (name, min_))
    return v


def req_num(b, name, min_=None):
    v = b.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        bad("%s must be a number" % name)
    if min_ is not None and v < min_:
        bad("%s must be >= %s" % (name, min_))
    return v


def req_enum(b, name, allowed):
    v = req_str(b, name)
    if v not in allowed:
        bad("%s must be one of %s" % (name, sorted(allowed)))
    return v


def opt_enum(b, name, allowed, default=None):
    if name not in b or b[name] is None:
        return default
    v = b[name]
    if not isinstance(v, str) or v not in allowed:
        bad("%s must be one of %s" % (name, sorted(allowed)))
    return v


def opt_bool(b, name, default=False):
    if name not in b or b[name] is None:
        return default
    v = b[name]
    if not isinstance(v, bool):
        bad("%s must be a boolean" % name)
    return v


def req_dt(b, name):
    v = b.get(name)
    if not isinstance(v, str):
        bad("%s is required" % name)
    try:
        return parse_iso(v)
    except Exception:
        bad("%s is not a valid ISO 8601 datetime" % name)


def opt_dt(b, name, default=None):
    if name not in b or b[name] is None:
        return default
    try:
        return parse_iso(b[name])
    except Exception:
        bad("%s is not a valid ISO 8601 datetime" % name)


def get_or_404(store, id_, err):
    e = store.get(id_)
    if e is None:
        raise ApiError(err)
    return e


def fk_exists(store, b, name, err):
    """If FK field present in body, ensure it references an existing entity."""
    if name in b and b[name] is not None:
        val = b[name]
        if not isinstance(val, str) or val not in store:
            raise ApiError(err)


def get_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args["limit"] != "":
        try:
            limit = int(args["limit"])
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_PAGINATION", message="limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_PAGINATION", message="limit must be between 1 and 100")
    if "offset" in args and args["offset"] != "":
        try:
            offset = int(args["offset"])
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_PAGINATION", message="offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION", message="offset must be >= 0")
    return limit, offset


def list_and_respond(all_items):
    limit, offset = get_pagination()
    items = sorted(all_items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(items)
    window = items[offset:offset + limit]
    return respond_array([serialize(e) for e in window], limit, offset, total)


def recompute_loyalty(customer):
    customer["loyalty_tier"] = tier_of(customer["lifetime_spend_cents"])


# ===========================================================================
# Clock (test-driving)
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def clock_set():
    auth_and_role(ROLES)
    b = body_dict()
    dt = req_dt(b, "to_iso8601")
    set_clock(dt)
    return respond_object({}, 200)


# ===========================================================================
# Products
# ===========================================================================
@app.route("/products", methods=["POST"])
def create_product():
    auth_and_role({"StoreManager"})
    b = body_dict()
    model_name = req_str(b, "model_name")
    category = req_enum(b, "category", {"SEWING_MACHINE", "VACUUM", "PART", "ACCESSORY"})
    brand = req_str(b, "brand")
    msrp_cents = req_int(b, "msrp_cents", min_=0)
    warranty_months = opt_int(b, "warranty_months", default=12, min_=0)
    e = new_entity({
        "model_name": model_name,
        "category": category,
        "brand": brand,
        "msrp_cents": msrp_cents,
        "warranty_months": warranty_months,
        "recall_status": "NONE",
        "recall_reason": None,
    })
    products[e["id"]] = e
    return respond_object(serialize(e), 201)


@app.route("/products", methods=["GET"])
def list_products():
    auth_and_role(ROLES)
    cat = request.args.get("category")
    items = [p for p in products.values() if cat is None or p["category"] == cat]
    return list_and_respond(items)


@app.route("/products/<pid>", methods=["GET"])
def get_product(pid):
    auth_and_role(ROLES)
    p = get_or_404(products, pid, "ERR_PRODUCT_NOT_FOUND")
    return respond_object(serialize(p), 200)


@app.route("/products/<pid>/recall", methods=["POST"])
def recall_product(pid):
    auth_and_role({"StoreManager"})
    p = get_or_404(products, pid, "ERR_PRODUCT_NOT_FOUND")
    b = body_dict()
    reason = req_str(b, "recall_reason")
    if p["recall_status"] != "NONE":
        raise ApiError("ERR_ALREADY_RECALLED")
    p["recall_status"] = "RECALLED"
    p["recall_reason"] = reason
    touch(p)
    return respond_object(serialize(p), 200)


# ===========================================================================
# Inventory items
# ===========================================================================
@app.route("/inventory-items", methods=["POST"])
def create_inventory():
    auth_and_role({"StoreManager"})
    b = body_dict()
    fk_exists(products, b, "product_id", "ERR_PRODUCT_NOT_FOUND")
    product_id = req_str(b, "product_id")
    serial_number = opt_str(b, "serial_number", default=None)
    condition = opt_enum(b, "condition", {"NEW", "REFURBISHED", "USED_TRADE_IN"}, default="NEW")
    acquisition_cost_cents = req_int(b, "acquisition_cost_cents", min_=0)
    list_price_cents = req_int(b, "list_price_cents", min_=0)
    e = new_entity({
        "product_id": product_id,
        "serial_number": serial_number,
        "condition": condition,
        "acquisition_cost_cents": acquisition_cost_cents,
        "list_price_cents": list_price_cents,
        "status": "IN_STOCK",
    })
    inventory[e["id"]] = e
    return respond_object(serialize(e), 201)


@app.route("/inventory-items", methods=["GET"])
def list_inventory():
    auth_and_role(ROLES)
    pid = request.args.get("product_id")
    status = request.args.get("status")
    items = [i for i in inventory.values()
             if (pid is None or i["product_id"] == pid)
             and (status is None or i["status"] == status)]
    return list_and_respond(items)


@app.route("/inventory-items/<iid>", methods=["GET"])
def get_inventory(iid):
    auth_and_role(ROLES)
    i = get_or_404(inventory, iid, "ERR_INVENTORY_ITEM_NOT_FOUND")
    return respond_object(serialize(i), 200)


@app.route("/inventory-items/<iid>/scrap", methods=["POST"])
def scrap_inventory(iid):
    auth_and_role({"StoreManager"})
    i = get_or_404(inventory, iid, "ERR_INVENTORY_ITEM_NOT_FOUND")
    if i["status"] != "IN_STOCK":
        raise ApiError("ERR_ITEM_NOT_AVAILABLE")
    i["status"] = "SCRAPPED"
    touch(i)
    return respond_object(serialize(i), 200)


# ===========================================================================
# Customers
# ===========================================================================
@app.route("/customers", methods=["POST"])
def create_customer():
    auth_and_role({"SalesAssociate", "StoreManager"})
    b = body_dict()
    full_name = req_str(b, "full_name")
    email = req_str(b, "email")
    e = new_entity({
        "full_name": full_name,
        "email": email,
        "store_credit_cents": 0,
        "lifetime_spend_cents": 0,
        "loyalty_tier": "STANDARD",
    })
    customers[e["id"]] = e
    return respond_object(serialize(e), 201)


@app.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    auth_and_role(ROLES)
    c = get_or_404(customers, cid, "ERR_CUSTOMER_NOT_FOUND")
    return respond_object(serialize(c), 200)


@app.route("/customers/<cid>/store-credit/adjustments", methods=["POST"])
def adjust_credit(cid):
    auth_and_role({"StoreManager"})
    c = get_or_404(customers, cid, "ERR_CUSTOMER_NOT_FOUND")
    b = body_dict()
    amount = req_int(b, "amount_cents")  # may be negative
    req_str(b, "reason")
    c["store_credit_cents"] += amount
    touch(c)
    return respond_object(serialize(c), 200)


# ===========================================================================
# Sales orders
# ===========================================================================
@app.route("/sales-orders", methods=["POST"])
def create_sales_order():
    auth_and_role({"SalesAssociate"})
    b = body_dict()
    fk_exists(customers, b, "customer_id", "ERR_CUSTOMER_NOT_FOUND")
    fk_exists(inventory, b, "inventory_item_id", "ERR_INVENTORY_ITEM_NOT_FOUND")
    customer_id = req_str(b, "customer_id")
    inventory_item_id = req_str(b, "inventory_item_id")
    sale_price_cents = req_int(b, "sale_price_cents", min_=0)
    trade_in_model = opt_str(b, "trade_in_model", default=None)
    trade_in_condition = opt_enum(b, "trade_in_condition", {"GOOD", "FAIR", "POOR"}, default=None)
    # trade-in is all-or-nothing at intake
    if (trade_in_model is None) != (trade_in_condition is None):
        raise ApiError("ERR_INVALID_TRADE_IN")
    item = inventory[inventory_item_id]
    if item["status"] != "IN_STOCK":
        raise ApiError("ERR_ITEM_NOT_AVAILABLE")
    estimate = TRADE_IN_SCHEDULE[trade_in_condition] if trade_in_condition else 0
    e = new_entity({
        "customer_id": customer_id,
        "inventory_item_id": inventory_item_id,
        "sale_price_cents": sale_price_cents,
        "trade_in_model": trade_in_model,
        "trade_in_condition": trade_in_condition,
        "trade_in_estimate_cents": estimate,
        "trade_in_final_cents": None,
        "loyalty_discount_cents": 0,
        "tax_cents": 0,
        "credit_applied_cents": 0,
        "total_due_cents": 0,
        "warranty_expires_at": None,
        "status": "RESERVED",
    })
    item["status"] = "RESERVED"
    touch(item)
    sales_orders[e["id"]] = e
    return respond_object(serialize(e), 201)


@app.route("/sales-orders", methods=["GET"])
def list_sales_orders():
    auth_and_role(ROLES)
    cid = request.args.get("customer_id")
    iid = request.args.get("inventory_item_id")
    items = [s for s in sales_orders.values()
             if (cid is None or s["customer_id"] == cid)
             and (iid is None or s["inventory_item_id"] == iid)]
    return list_and_respond(items)


@app.route("/sales-orders/<sid>", methods=["GET"])
def get_sales_order(sid):
    auth_and_role(ROLES)
    s = get_or_404(sales_orders, sid, "ERR_SALES_ORDER_NOT_FOUND")
    return respond_object(serialize(s), 200)


@app.route("/sales-orders/<sid>/complete", methods=["POST"])
def complete_sales_order(sid):
    auth_and_role({"SalesAssociate"})
    order = get_or_404(sales_orders, sid, "ERR_SALES_ORDER_NOT_FOUND")
    b = body_dict()
    if order["status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE")
    item = inventory[order["inventory_item_id"]]
    product = products[item["product_id"]]
    if product["recall_status"] == "RECALLED":
        raise ApiError("ERR_PRODUCT_RECALLED")
    has_trade_in = order["trade_in_model"] is not None
    trade_in_final = None
    if has_trade_in:
        trade_in_final = req_int(b, "trade_in_final_cents", min_=0)
        if abs(trade_in_final - order["trade_in_estimate_cents"]) > TRADE_IN_BAND:
            raise ApiError("ERR_TRADE_IN_OUT_OF_BAND")

    customer = customers[order["customer_id"]]
    pre_tier = tier_of(customer["lifetime_spend_cents"])
    loyalty_discount = round_half_up(Decimal(order["sale_price_cents"]) * DISCOUNT_PCT[pre_tier])
    taxable = order["sale_price_cents"] - loyalty_discount
    tax = round_half_up(Decimal(taxable) * TAX_RATE)
    pre_credit = customer["store_credit_cents"]
    credit_applied = min(pre_credit, taxable + tax)
    total_due = taxable + tax - credit_applied

    order["loyalty_discount_cents"] = loyalty_discount
    order["tax_cents"] = tax
    order["credit_applied_cents"] = credit_applied
    order["total_due_cents"] = total_due
    order["trade_in_final_cents"] = trade_in_final
    order["warranty_expires_at"] = add_months(now(), product["warranty_months"])
    order["status"] = "COMPLETED"
    touch(order)

    # Ledger + inventory + loyalty
    customer["store_credit_cents"] -= credit_applied
    if has_trade_in:
        customer["store_credit_cents"] += trade_in_final
    customer["lifetime_spend_cents"] += total_due
    recompute_loyalty(customer)
    touch(customer)

    item["status"] = "SOLD"
    touch(item)

    return respond_object(serialize(order), 200)


@app.route("/sales-orders/<sid>/cancel", methods=["POST"])
def cancel_sales_order(sid):
    uid, role = auth_and_role({"SalesAssociate", "StoreManager"})
    order = get_or_404(sales_orders, sid, "ERR_SALES_ORDER_NOT_FOUND")
    item = inventory[order["inventory_item_id"]]
    if order["status"] == "RESERVED":
        order["status"] = "CANCELLED"
        touch(order)
        item["status"] = "IN_STOCK"
        touch(item)
        return respond_object(serialize(order), 200)
    if order["status"] == "COMPLETED":
        # Reversal path — StoreManager only
        if role != "StoreManager":
            raise ApiError("ERR_FORBIDDEN")
        customer = customers[order["customer_id"]]
        item["status"] = "IN_STOCK"
        touch(item)
        customer["store_credit_cents"] += order["credit_applied_cents"]
        if order["trade_in_model"] is not None and order["trade_in_final_cents"] is not None:
            customer["store_credit_cents"] -= order["trade_in_final_cents"]
        customer["lifetime_spend_cents"] -= order["total_due_cents"]
        recompute_loyalty(customer)
        touch(customer)
        order["status"] = "CANCELLED"
        touch(order)
        return respond_object(serialize(order), 200)
    raise ApiError("ERR_INVALID_STATE")


# ===========================================================================
# Repair tickets
# ===========================================================================
@app.route("/repair-tickets", methods=["POST"])
def create_repair_ticket():
    auth_and_role({"ServiceTech", "SalesAssociate"})
    b = body_dict()
    fk_exists(customers, b, "customer_id", "ERR_CUSTOMER_NOT_FOUND")
    fk_exists(products, b, "product_id", "ERR_PRODUCT_NOT_FOUND")
    customer_id = req_str(b, "customer_id")
    product_id = req_str(b, "product_id")
    is_warranty = opt_bool(b, "is_warranty", default=False)
    e = new_entity({
        "customer_id": customer_id,
        "product_id": product_id,
        "is_warranty": is_warranty,
        "diagnosis": None,
        "labor_hours": None,
        "labor_estimate_cents": 0,
        "parts_cost_cents": 0,
        "final_invoice_cents": None,
        "status": "INTAKE",
    })
    repair_tickets[e["id"]] = e
    return respond_object(serialize(e), 201)


@app.route("/repair-tickets", methods=["GET"])
def list_repair_tickets():
    auth_and_role(ROLES)
    cid = request.args.get("customer_id")
    pid = request.args.get("product_id")
    items = [t for t in repair_tickets.values()
             if (cid is None or t["customer_id"] == cid)
             and (pid is None or t["product_id"] == pid)]
    return list_and_respond(items)


@app.route("/repair-tickets/<tid>", methods=["GET"])
def get_repair_ticket(tid):
    auth_and_role(ROLES)
    t = get_or_404(repair_tickets, tid, "ERR_REPAIR_TICKET_NOT_FOUND")
    return respond_object(serialize(t), 200)


@app.route("/repair-tickets/<tid>/quote", methods=["POST"])
def quote_repair(tid):
    auth_and_role({"ServiceTech"})
    t = get_or_404(repair_tickets, tid, "ERR_REPAIR_TICKET_NOT_FOUND")
    b = body_dict()
    diagnosis = req_str(b, "diagnosis")
    labor_hours = req_num(b, "labor_hours", min_=0)
    if t["status"] != "INTAKE":
        raise ApiError("ERR_INVALID_STATE")
    t["diagnosis"] = diagnosis
    t["labor_hours"] = labor_hours
    t["labor_estimate_cents"] = round_half_up(Decimal(str(labor_hours)) * LABOR_RATE_CENTS)
    t["status"] = "AWAITING_APPROVAL"
    touch(t)
    return respond_object(serialize(t), 200)


@app.route("/repair-tickets/<tid>/approve", methods=["POST"])
def approve_repair(tid):
    uid, role = auth_and_role({"Customer", "SalesAssociate"})
    t = get_or_404(repair_tickets, tid, "ERR_REPAIR_TICKET_NOT_FOUND")
    check_ownership(role, uid, t["customer_id"])
    if t["status"] != "AWAITING_APPROVAL":
        raise ApiError("ERR_INVALID_STATE")
    product = products[t["product_id"]]
    if product["recall_status"] == "RECALLED":
        raise ApiError("ERR_PRODUCT_RECALLED")
    t["status"] = "IN_REPAIR"
    touch(t)
    return respond_object(serialize(t), 200)


@app.route("/repair-tickets/<tid>/reject", methods=["POST"])
def reject_repair(tid):
    uid, role = auth_and_role({"Customer", "SalesAssociate"})
    t = get_or_404(repair_tickets, tid, "ERR_REPAIR_TICKET_NOT_FOUND")
    check_ownership(role, uid, t["customer_id"])
    if t["status"] != "AWAITING_APPROVAL":
        raise ApiError("ERR_INVALID_STATE")
    t["diagnosis"] = None
    t["labor_hours"] = None
    t["labor_estimate_cents"] = 0
    t["status"] = "INTAKE"
    touch(t)
    return respond_object(serialize(t), 200)


@app.route("/repair-tickets/<tid>/consume-part", methods=["POST"])
def consume_part(tid):
    auth_and_role({"ServiceTech"})
    t = get_or_404(repair_tickets, tid, "ERR_REPAIR_TICKET_NOT_FOUND")
    b = body_dict()
    fk_exists(inventory, b, "inventory_item_id", "ERR_INVENTORY_ITEM_NOT_FOUND")
    inventory_item_id = req_str(b, "inventory_item_id")
    if inventory_item_id not in inventory:
        raise ApiError("ERR_INVENTORY_ITEM_NOT_FOUND")
    if t["status"] != "IN_REPAIR":
        raise ApiError("ERR_INVALID_STATE")
    item = inventory[inventory_item_id]
    if item["status"] != "IN_STOCK":
        raise ApiError("ERR_ITEM_NOT_AVAILABLE")
    product = products[item["product_id"]]
    if product["category"] != "PART":
        raise ApiError("ERR_NOT_A_PART")
    item["status"] = "SOLD"
    touch(item)
    t["parts_cost_cents"] += item["list_price_cents"]
    touch(t)
    return respond_object(serialize(t), 200)


@app.route("/repair-tickets/<tid>/complete", methods=["POST"])
def complete_repair(tid):
    auth_and_role({"ServiceTech"})
    t = get_or_404(repair_tickets, tid, "ERR_REPAIR_TICKET_NOT_FOUND")
    if t["status"] != "IN_REPAIR":
        raise ApiError("ERR_INVALID_STATE")
    if t["is_warranty"]:
        t["final_invoice_cents"] = t["parts_cost_cents"]
    else:
        t["final_invoice_cents"] = t["labor_estimate_cents"] + t["parts_cost_cents"]
    t["status"] = "READY"
    touch(t)
    return respond_object(serialize(t), 200)


@app.route("/repair-tickets/<tid>/close", methods=["POST"])
def close_repair(tid):
    auth_and_role({"SalesAssociate"})
    t = get_or_404(repair_tickets, tid, "ERR_REPAIR_TICKET_NOT_FOUND")
    if t["status"] != "READY":
        raise ApiError("ERR_INVALID_STATE")
    customer = customers[t["customer_id"]]
    applied = min(customer["store_credit_cents"], t["final_invoice_cents"])
    customer["store_credit_cents"] -= applied
    touch(customer)
    t["status"] = "CLOSED"
    touch(t)
    return respond_object(serialize(t), 200)


@app.route("/repair-tickets/<tid>/cancel", methods=["POST"])
def cancel_repair(tid):
    auth_and_role({"SalesAssociate"})
    t = get_or_404(repair_tickets, tid, "ERR_REPAIR_TICKET_NOT_FOUND")
    if t["status"] not in ("INTAKE", "AWAITING_APPROVAL", "IN_REPAIR"):
        raise ApiError("ERR_INVALID_STATE")
    t["status"] = "CANCELLED"
    touch(t)
    return respond_object(serialize(t), 200)


# ===========================================================================
# Rental agreements
# ===========================================================================
@app.route("/rental-agreements", methods=["POST"])
def create_rental():
    auth_and_role({"SalesAssociate"})
    b = body_dict()
    fk_exists(customers, b, "customer_id", "ERR_CUSTOMER_NOT_FOUND")
    fk_exists(inventory, b, "inventory_item_id", "ERR_INVENTORY_ITEM_NOT_FOUND")
    customer_id = req_str(b, "customer_id")
    inventory_item_id = req_str(b, "inventory_item_id")
    start_at = req_dt(b, "start_at")
    due_at = req_dt(b, "due_at")
    daily_rate_cents = req_int(b, "daily_rate_cents", min_=0)
    deposit_cents = req_int(b, "deposit_cents", min_=0)
    if not (due_at > start_at):
        bad("due_at must be strictly after start_at")
    # temporal overlap against existing ACTIVE rentals of the same unit (half-open)
    for r in rentals.values():
        if r["inventory_item_id"] != inventory_item_id or r["status"] != "ACTIVE":
            continue
        if start_at < r["due_at"] and r["start_at"] < due_at:
            raise ApiError("ERR_RENTAL_OVERLAP")
    rental_days = ceil_days(due_at - start_at)
    customer = customers[customer_id]
    customer["store_credit_cents"] -= deposit_cents
    touch(customer)
    e = new_entity({
        "customer_id": customer_id,
        "inventory_item_id": inventory_item_id,
        "start_at": start_at,
        "due_at": due_at,
        "daily_rate_cents": daily_rate_cents,
        "deposit_cents": deposit_cents,
        "returned_at": None,
        "rental_days": rental_days,
        "late_fee_cents": 0,
        "total_charge_cents": 0,
        "status": "ACTIVE",
    })
    rentals[e["id"]] = e
    return respond_object(serialize(e), 201)


@app.route("/rental-agreements", methods=["GET"])
def list_rentals():
    auth_and_role(ROLES)
    cid = request.args.get("customer_id")
    iid = request.args.get("inventory_item_id")
    items = [r for r in rentals.values()
             if (cid is None or r["customer_id"] == cid)
             and (iid is None or r["inventory_item_id"] == iid)]
    return list_and_respond(items)


@app.route("/rental-agreements/<rid>", methods=["GET"])
def get_rental(rid):
    auth_and_role(ROLES)
    r = get_or_404(rentals, rid, "ERR_RENTAL_NOT_FOUND")
    return respond_object(serialize(r), 200)


@app.route("/rental-agreements/<rid>/return", methods=["POST"])
def return_rental(rid):
    auth_and_role({"SalesAssociate"})
    r = get_or_404(rentals, rid, "ERR_RENTAL_NOT_FOUND")
    b = body_dict()
    returned_at = opt_dt(b, "returned_at", default=None)
    if r["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    if returned_at is None:
        returned_at = now()
    days_late = max(0, ceil_days(returned_at - r["due_at"]))
    late_fee = round_half_up(Decimal(days_late) * Decimal(r["daily_rate_cents"]) * LATE_MULTIPLIER)
    total_charge = r["rental_days"] * r["daily_rate_cents"] + late_fee
    r["returned_at"] = returned_at
    r["late_fee_cents"] = late_fee
    r["total_charge_cents"] = total_charge
    r["status"] = "RETURNED"
    touch(r)
    customer = customers[r["customer_id"]]
    customer["store_credit_cents"] += (r["deposit_cents"] - late_fee)
    touch(customer)
    return respond_object(serialize(r), 200)


@app.route("/rental-agreements/<rid>/cancel", methods=["POST"])
def cancel_rental(rid):
    auth_and_role({"SalesAssociate"})
    r = get_or_404(rentals, rid, "ERR_RENTAL_NOT_FOUND")
    if r["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    r["status"] = "CANCELLED"
    touch(r)
    customer = customers[r["customer_id"]]
    customer["store_credit_cents"] += r["deposit_cents"]
    touch(customer)
    return respond_object(serialize(r), 200)


# ===========================================================================
# Class sessions
# ===========================================================================
@app.route("/class-sessions", methods=["POST"])
def create_class_session():
    auth_and_role({"StoreManager"})
    b = body_dict()
    title = req_str(b, "title")
    machine_type = req_enum(b, "machine_type", {"SEWING", "VACUUM"})
    start_at = req_dt(b, "start_at")
    end_at = req_dt(b, "end_at")
    capacity = req_int(b, "capacity", min_=1)
    fee_cents = req_int(b, "fee_cents", min_=0)
    if not (end_at > start_at):
        bad("end_at must be strictly after start_at")
    e = new_entity({
        "title": title,
        "machine_type": machine_type,
        "start_at": start_at,
        "end_at": end_at,
        "capacity": capacity,
        "fee_cents": fee_cents,
        "enrolled_count": 0,
        "waitlist_count": 0,
        "status": "SCHEDULED",
    })
    class_sessions[e["id"]] = e
    return respond_object(serialize(e), 201)


@app.route("/class-sessions", methods=["GET"])
def list_class_sessions():
    auth_and_role(ROLES)
    mt = request.args.get("machine_type")
    items = [s for s in class_sessions.values() if mt is None or s["machine_type"] == mt]
    return list_and_respond(items)


@app.route("/class-sessions/<csid>", methods=["GET"])
def get_class_session(csid):
    auth_and_role(ROLES)
    s = get_or_404(class_sessions, csid, "ERR_CLASS_SESSION_NOT_FOUND")
    return respond_object(serialize(s), 200)


@app.route("/class-sessions/<csid>/complete", methods=["POST"])
def complete_class_session(csid):
    auth_and_role({"StoreManager"})
    s = get_or_404(class_sessions, csid, "ERR_CLASS_SESSION_NOT_FOUND")
    if s["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")
    s["status"] = "COMPLETED"
    touch(s)
    for en in enrollments.values():
        if en["class_session_id"] == csid and en["status"] == "ENROLLED":
            en["status"] = "ATTENDED"
            touch(en)
    return respond_object(serialize(s), 200)


@app.route("/class-sessions/<csid>/cancel", methods=["POST"])
def cancel_class_session(csid):
    auth_and_role({"StoreManager"})
    s = get_or_404(class_sessions, csid, "ERR_CLASS_SESSION_NOT_FOUND")
    if s["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")
    s["status"] = "CANCELLED"
    touch(s)
    affected = [en for en in enrollments.values()
                if en["class_session_id"] == csid and en["status"] in ("ENROLLED", "WAITLISTED")]
    affected.sort(key=lambda e: (e["created_at"], e["_seq"]))
    for en in affected:
        en["status"] = "CANCELLED"
        touch(en)
        customer = customers[en["customer_id"]]
        customer["store_credit_cents"] += en["fee_charged_cents"]
        touch(customer)
    s["enrolled_count"] = 0
    s["waitlist_count"] = 0
    return respond_object(serialize(s), 200)


# ===========================================================================
# Class enrollments
# ===========================================================================
@app.route("/class-sessions/<csid>/enrollments", methods=["POST"])
def enroll(csid):
    auth_and_role({"Customer", "SalesAssociate"})
    s = get_or_404(class_sessions, csid, "ERR_CLASS_SESSION_NOT_FOUND")
    b = body_dict()
    fk_exists(customers, b, "customer_id", "ERR_CUSTOMER_NOT_FOUND")
    customer_id = req_str(b, "customer_id")
    customer = customers[customer_id]
    if s["status"] != "SCHEDULED":
        raise ApiError("ERR_SESSION_NOT_OPEN")
    # schedule conflict check (closed interval + 30-min buffer)
    new_s, new_e = s["start_at"], s["end_at"]
    for en in enrollments.values():
        if en["customer_id"] != customer_id or en["status"] not in ("ENROLLED", "WAITLISTED"):
            continue
        other = class_sessions[en["class_session_id"]]
        os_, oe = other["start_at"], other["end_at"]
        ok = (oe + SCHEDULE_BUFFER <= new_s) or (new_e + SCHEDULE_BUFFER <= os_)
        if not ok:
            raise ApiError("ERR_SCHEDULE_CONFLICT")
    fee = s["fee_cents"]
    if s["enrolled_count"] < s["capacity"]:
        status = "ENROLLED"
        s["enrolled_count"] += 1
    else:
        status = "WAITLISTED"
        s["waitlist_count"] += 1
    touch(s)
    customer["store_credit_cents"] -= fee
    touch(customer)
    e = new_entity({
        "class_session_id": csid,
        "customer_id": customer_id,
        "fee_charged_cents": fee,
        "status": status,
    })
    enrollments[e["id"]] = e
    return respond_object(serialize(e), 201)


@app.route("/class-enrollments", methods=["GET"])
def list_enrollments():
    auth_and_role(ROLES)
    csid = request.args.get("class_session_id")
    cid = request.args.get("customer_id")
    items = [en for en in enrollments.values()
             if (csid is None or en["class_session_id"] == csid)
             and (cid is None or en["customer_id"] == cid)]
    return list_and_respond(items)


@app.route("/class-enrollments/<eid>", methods=["GET"])
def get_enrollment(eid):
    auth_and_role(ROLES)
    en = get_or_404(enrollments, eid, "ERR_ENROLLMENT_NOT_FOUND")
    return respond_object(serialize(en), 200)


@app.route("/class-enrollments/<eid>/cancel", methods=["POST"])
def cancel_enrollment(eid):
    uid, role = auth_and_role({"Customer", "SalesAssociate"})
    en = get_or_404(enrollments, eid, "ERR_ENROLLMENT_NOT_FOUND")
    check_ownership(role, uid, en["customer_id"])
    if en["status"] not in ("ENROLLED", "WAITLISTED"):
        raise ApiError("ERR_INVALID_STATE")
    session = class_sessions[en["class_session_id"]]
    customer = customers[en["customer_id"]]
    was_enrolled = en["status"] == "ENROLLED"
    en["status"] = "CANCELLED"
    touch(en)
    customer["store_credit_cents"] += en["fee_charged_cents"]
    touch(customer)
    if was_enrolled:
        session["enrolled_count"] -= 1
        # promote earliest-created WAITLISTED enrollment on this session
        waitlisted = [w for w in enrollments.values()
                      if w["class_session_id"] == session["id"] and w["status"] == "WAITLISTED"]
        waitlisted.sort(key=lambda w: (w["created_at"], w["_seq"]))
        if waitlisted:
            promoted = waitlisted[0]
            promoted["status"] = "ENROLLED"
            touch(promoted)
            session["waitlist_count"] -= 1
            session["enrolled_count"] += 1
        touch(session)
    else:
        session["waitlist_count"] -= 1
        touch(session)
    return respond_object(serialize(en), 200)


# ===========================================================================
# Tune-up subscriptions
# ===========================================================================
@app.route("/tune-up-subscriptions", methods=["POST"])
def create_subscription():
    auth_and_role({"SalesAssociate"})
    b = body_dict()
    fk_exists(customers, b, "customer_id", "ERR_CUSTOMER_NOT_FOUND")
    customer_id = req_str(b, "customer_id")
    plan_tier = req_enum(b, "plan_tier", {"BASIC", "PRO"})
    monthly_fee_cents = req_int(b, "monthly_fee_cents", min_=0)
    tune_ups_included = req_int(b, "tune_ups_included", min_=0)
    start = now()
    e = new_entity({
        "customer_id": customer_id,
        "plan_tier": plan_tier,
        "monthly_fee_cents": monthly_fee_cents,
        "tune_ups_included": tune_ups_included,
        "tune_ups_used": 0,
        "current_period_start": start,
        "current_period_end": start + timedelta(days=PERIOD_DAYS),
        "status": "ACTIVE",
    })
    subscriptions[e["id"]] = e
    return respond_object(serialize(e), 201)


@app.route("/tune-up-subscriptions", methods=["GET"])
def list_subscriptions():
    auth_and_role(ROLES)
    cid = request.args.get("customer_id")
    items = [s for s in subscriptions.values() if cid is None or s["customer_id"] == cid]
    return list_and_respond(items)


@app.route("/tune-up-subscriptions/<sid>", methods=["GET"])
def get_subscription(sid):
    auth_and_role(ROLES)
    s = get_or_404(subscriptions, sid, "ERR_SUBSCRIPTION_NOT_FOUND")
    return respond_object(serialize(s), 200)


@app.route("/tune-up-subscriptions/<sid>/redeem", methods=["POST"])
def redeem_subscription(sid):
    auth_and_role({"ServiceTech", "SalesAssociate"})
    s = get_or_404(subscriptions, sid, "ERR_SUBSCRIPTION_NOT_FOUND")
    if s["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    if now() >= s["current_period_end"]:
        raise ApiError("ERR_INVALID_STATE")
    if s["tune_ups_used"] >= s["tune_ups_included"]:
        raise ApiError("ERR_TUNE_UPS_EXHAUSTED")
    s["tune_ups_used"] += 1
    touch(s)
    return respond_object(serialize(s), 200)


@app.route("/tune-up-subscriptions/<sid>/lapse", methods=["POST"])
def lapse_subscription(sid):
    auth_and_role({"StoreManager"})
    s = get_or_404(subscriptions, sid, "ERR_SUBSCRIPTION_NOT_FOUND")
    if s["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    s["status"] = "PAST_DUE"
    touch(s)
    return respond_object(serialize(s), 200)


@app.route("/tune-up-subscriptions/<sid>/reinstate", methods=["POST"])
def reinstate_subscription(sid):
    auth_and_role({"SalesAssociate"})
    s = get_or_404(subscriptions, sid, "ERR_SUBSCRIPTION_NOT_FOUND")
    if s["status"] != "PAST_DUE":
        raise ApiError("ERR_INVALID_STATE")
    s["status"] = "ACTIVE"
    touch(s)
    return respond_object(serialize(s), 200)


@app.route("/tune-up-subscriptions/<sid>/cancel", methods=["POST"])
def cancel_subscription(sid):
    uid, role = auth_and_role({"Customer", "SalesAssociate"})
    s = get_or_404(subscriptions, sid, "ERR_SUBSCRIPTION_NOT_FOUND")
    check_ownership(role, uid, s["customer_id"])
    if s["status"] not in ("ACTIVE", "PAST_DUE"):
        raise ApiError("ERR_INVALID_STATE")
    from_active = s["status"] == "ACTIVE"
    s["status"] = "CANCELLED"
    if from_active and now() < s["current_period_end"]:
        period_days = ceil_days(s["current_period_end"] - s["current_period_start"])
        unused_days = max(0, ceil_days(s["current_period_end"] - now()))
        refund = round_half_up(Decimal(s["monthly_fee_cents"] * unused_days) / Decimal(period_days))
        if refund != 0:
            customer = customers[s["customer_id"]]
            customer["store_credit_cents"] += refund
            touch(customer)
    touch(s)
    return respond_object(serialize(s), 200)


# ===========================================================================
# Special orders
# ===========================================================================
@app.route("/special-orders", methods=["POST"])
def create_special_order():
    auth_and_role({"SalesAssociate"})
    b = body_dict()
    fk_exists(customers, b, "customer_id", "ERR_CUSTOMER_NOT_FOUND")
    fk_exists(products, b, "product_id", "ERR_PRODUCT_NOT_FOUND")
    customer_id = req_str(b, "customer_id")
    product_id = req_str(b, "product_id")
    quantity = req_int(b, "quantity", min_=1)
    unit_price_cents = req_int(b, "unit_price_cents", min_=0)
    deposit_cents = req_int(b, "deposit_cents", min_=0)
    balance_due = quantity * unit_price_cents - deposit_cents
    e = new_entity({
        "customer_id": customer_id,
        "product_id": product_id,
        "quantity": quantity,
        "unit_price_cents": unit_price_cents,
        "deposit_cents": deposit_cents,
        "balance_due_cents": balance_due,
        "status": "REQUESTED",
    })
    special_orders[e["id"]] = e
    return respond_object(serialize(e), 201)


@app.route("/special-orders", methods=["GET"])
def list_special_orders():
    auth_and_role(ROLES)
    cid = request.args.get("customer_id")
    pid = request.args.get("product_id")
    items = [s for s in special_orders.values()
             if (cid is None or s["customer_id"] == cid)
             and (pid is None or s["product_id"] == pid)]
    return list_and_respond(items)


@app.route("/special-orders/<soid>", methods=["GET"])
def get_special_order(soid):
    auth_and_role(ROLES)
    s = get_or_404(special_orders, soid, "ERR_SPECIAL_ORDER_NOT_FOUND")
    return respond_object(serialize(s), 200)


@app.route("/special-orders/<soid>", methods=["PATCH"])
def amend_special_order(soid):
    auth_and_role({"SalesAssociate"})
    s = get_or_404(special_orders, soid, "ERR_SPECIAL_ORDER_NOT_FOUND")
    b = body_dict()
    expected = req_int(b, "expected_special_order_version")
    quantity = opt_int(b, "quantity", default=None, min_=1)
    deposit_cents = opt_int(b, "deposit_cents", default=None, min_=0)
    if s["status"] not in ("REQUESTED", "RECEIVED"):
        raise ApiError("ERR_INVALID_STATE")
    if expected != s["version"]:
        raise ApiError("ERR_STALE_VERSION")
    if quantity is not None:
        s["quantity"] = quantity
    if deposit_cents is not None:
        s["deposit_cents"] = deposit_cents
    s["balance_due_cents"] = s["quantity"] * s["unit_price_cents"] - s["deposit_cents"]
    touch(s)
    return respond_object(serialize(s), 200)


@app.route("/special-orders/<soid>/receive", methods=["POST"])
def receive_special_order(soid):
    auth_and_role({"SalesAssociate"})
    s = get_or_404(special_orders, soid, "ERR_SPECIAL_ORDER_NOT_FOUND")
    if s["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE")
    s["status"] = "RECEIVED"
    touch(s)
    return respond_object(serialize(s), 200)


@app.route("/special-orders/<soid>/fulfill", methods=["POST"])
def fulfill_special_order(soid):
    auth_and_role({"SalesAssociate"})
    s = get_or_404(special_orders, soid, "ERR_SPECIAL_ORDER_NOT_FOUND")
    if s["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE")
    s["status"] = "FULFILLED"
    touch(s)
    return respond_object(serialize(s), 200)


@app.route("/special-orders/<soid>/cancel", methods=["POST"])
def cancel_special_order(soid):
    auth_and_role({"SalesAssociate"})
    s = get_or_404(special_orders, soid, "ERR_SPECIAL_ORDER_NOT_FOUND")
    if s["status"] not in ("REQUESTED", "RECEIVED"):
        raise ApiError("ERR_INVALID_STATE")
    s["status"] = "CANCELLED"
    touch(s)
    return respond_object(serialize(s), 200)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
