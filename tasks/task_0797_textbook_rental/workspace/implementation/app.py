import os
import math
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"Customer", "WarehouseAgent", "CatalogAdmin"}
CONDITIONS = {"NEW", "LIKE_NEW", "GOOD", "ACCEPTABLE"}
FULFILLMENT_TYPES = {"RENT", "BUY", "EBOOK"}
PLAN_TIERS = {"STUDY", "SOLUTIONS"}
TXN_KINDS = {
    "TOP_UP", "ORDER_CHARGE", "ORDER_REFUND", "EXTENSION_FEE", "LATE_FEE",
    "DAMAGE_FEE", "REPLACEMENT_CHARGE", "BUYBACK_CREDIT", "SUBSCRIPTION_FEE",
    "SUBSCRIPTION_REFUND",
}

TERM_MULT = {30: Decimal("0.5"), 60: Decimal("0.75"), 90: Decimal("1.0"), 120: Decimal("1.25")}
VALID_RENT_TERMS = {30, 60, 90, 120}
LOYALTY_THRESHOLD_CENTS = 10000
LOYALTY_CREDIT_CENTS = 500

COND_MULT = {"NEW": Decimal("1.0"), "LIKE_NEW": Decimal("0.9"),
             "GOOD": Decimal("0.75"), "ACCEPTABLE": Decimal("0.5")}
GRADE_RANK = {"NEW": 0, "LIKE_NEW": 1, "GOOD": 2, "ACCEPTABLE": 3}

GRACE_DAYS = 3
DAILY_LATE_FEE_CENTS = 250
LOST_THRESHOLD_DAYS = 30

CONDITION_STEP_FEE_CENTS = 1500
HIGHLIGHT_FEE_PER_PCT_CENTS = 200
HIGHLIGHT_BANNED_FLAT_CENTS = 2500

EXTENSION_FEE_CENTS = 1500
EXTENSION_TERM_DAYS = 30
MAX_EXTENSIONS = 2
MAX_TOTAL_TERM_DAYS = 210

DAYS_PER_MONTH = 30
INSPECTION_BUFFER_DAYS = 2
QUOTE_VALIDITY_DAYS = 7

DEFAULT_CLOCK = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# In-memory storage (fresh on every process boot)
# ---------------------------------------------------------------------------
catalog_items = {}
inventory_units = {}
customers = {}
subscription_plans = {}
subscriptions = {}
orders = {}
rentals = {}
return_shipments = {}
buyback_quotes = {}
wallet_txns = {}

_seq_counter = 0
CLOCK = {"now": DEFAULT_CLOCK}


def now():
    return CLOCK["now"]


def next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


# ---------------------------------------------------------------------------
# Errors + response envelope
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def bad_request(msg="Malformed request body."):
    raise ApiError("ERR_INVALID_REQUEST", 400, msg)


def _meta(extra=None):
    m = {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": iso(datetime.now(timezone.utc)),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, response_type="object", status=200, pagination=None):
    body = {"meta": _meta(pagination), "response_type": response_type, "data": data}
    return jsonify(body), status


@app.errorhandler(ApiError)
def _handle_api_error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def _handle_404(_e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_RESOURCE_NOT_FOUND", "message": "Not found."},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def _handle_405(_e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST", "message": "Method not allowed."},
    }
    return jsonify(body), 405


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------
def iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    if not isinstance(value, str) or not value:
        bad_request("Invalid datetime value.")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        bad_request("Invalid ISO 8601 datetime.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def rhu(dec):
    """Round-half-up a Decimal to whole cents (int)."""
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------
def new_entity(**fields):
    n = now()
    e = {"id": str(uuid.uuid4()), "created_at": n, "updated_at": n,
         "version": 1, "_seq": next_seq()}
    e.update(fields)
    return e


def touch(entity):
    entity["updated_at"] = now()
    entity["version"] = entity.get("version", 1) + 1


def serialize(entity, extra=None):
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        out[k] = iso(v) if isinstance(v, datetime) else v
    if extra:
        out.update(extra)
    return out


def wallet_balance(customer_id):
    return sum(t["amount_cents"] for t in wallet_txns.values() if t["customer_id"] == customer_id)


def serialize_customer(cust):
    return serialize(cust, {"wallet_credit_cents": wallet_balance(cust["id"])})


def add_txn(customer_id, amount_cents, kind, reference_id=None):
    t = {"id": str(uuid.uuid4()), "created_at": now(), "_seq": next_seq(),
         "customer_id": customer_id, "amount_cents": amount_cents,
         "kind": kind, "reference_id": reference_id}
    wallet_txns[t["id"]] = t
    return t


def bump_customer_version(cust):
    touch(cust)


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def authenticate(allowed_roles):
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or not uid or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers.")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation.")
    return role, uid


def require_owner(role, uid, owner_id):
    if role == "Customer" and owner_id != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Customer may act only on its own resources.")


def get_or_404(store, rid):
    ent = store.get(rid)
    if ent is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", 404, "Referenced resource does not exist.")
    return ent


# ---------------------------------------------------------------------------
# Body parsing helpers
# ---------------------------------------------------------------------------
def get_body():
    if request.data:
        body = request.get_json(silent=True)
        if body is None:
            bad_request("Request body is not valid JSON.")
        if not isinstance(body, dict):
            bad_request("Request body must be a JSON object.")
        return body
    return {}


def _present(body, field):
    return field in body and body[field] is not None


def as_str(body, field, required=True, default=None):
    if not _present(body, field):
        if required:
            bad_request(f"Missing required field: {field}.")
        return default
    v = body[field]
    if not isinstance(v, str) or v == "":
        bad_request(f"Field {field} must be a non-empty string.")
    return v


def as_int(body, field, required=True, default=None, minimum=None):
    if not _present(body, field):
        if required:
            bad_request(f"Missing required field: {field}.")
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        bad_request(f"Field {field} must be an integer.")
    if minimum is not None and v < minimum:
        bad_request(f"Field {field} below minimum.")
    return v


def as_num(body, field, required=True, default=None, minimum=None, maximum=None):
    if not _present(body, field):
        if required:
            bad_request(f"Missing required field: {field}.")
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        bad_request(f"Field {field} must be a number.")
    if minimum is not None and v < minimum:
        bad_request(f"Field {field} below minimum.")
    if maximum is not None and v > maximum:
        bad_request(f"Field {field} above maximum.")
    return v


def as_bool(body, field, default):
    if not _present(body, field):
        return default
    v = body[field]
    if not isinstance(v, bool):
        bad_request(f"Field {field} must be a boolean.")
    return v


def as_enum(body, field, choices, required=True, default=None):
    if not _present(body, field):
        if required:
            bad_request(f"Missing required field: {field}.")
        return default
    v = body[field]
    if not isinstance(v, str) or v not in choices:
        bad_request(f"Field {field} has an invalid value.")
    return v


def paginate(items):
    def _pint(name, default):
        raw = request.args.get(name)
        if raw is None:
            return default
        try:
            return int(raw)
        except (ValueError, TypeError):
            return default

    limit = _pint("limit", 10)
    offset = _pint("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    meta = {"limit": limit, "offset": offset, "total_count": total,
            "has_more": offset + limit < total}
    return page, meta


def sorted_values(store, predicate=None):
    items = [e for e in store.values() if (predicate is None or predicate(e))]
    items.sort(key=lambda e: e["_seq"])
    return items


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate({"CatalogAdmin"})
    body = get_body()
    ts = as_str(body, "to_iso8601")
    CLOCK["now"] = parse_dt(ts)
    return ok({}, "object", 200)


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------
@app.route("/catalog", methods=["POST"])
def create_catalog():
    authenticate({"CatalogAdmin"})
    body = get_body()
    isbn13 = as_str(body, "isbn13")
    edition = as_int(body, "edition", minimum=1)
    title = as_str(body, "title")
    author = as_str(body, "author")
    list_price = as_int(body, "list_price_cents", minimum=0)
    rental_base = as_int(body, "rental_base_cents", minimum=0)
    ebook_price = as_int(body, "ebook_price_cents", minimum=0)
    buyback_base = as_int(body, "buyback_base_cents", minimum=0)
    replacement_fee = as_int(body, "replacement_fee_cents", minimum=0)
    rentable = as_bool(body, "rentable", True)
    buyable = as_bool(body, "buyable", True)
    ebook_available = as_bool(body, "ebook_available", False)
    highlighting_allowed = as_bool(body, "highlighting_allowed", True)
    max_highlight_pct = as_num(body, "max_highlight_pct", required=False, default=10,
                               minimum=0, maximum=100)

    for item in catalog_items.values():
        if item["isbn13"] == isbn13 and item["edition"] == edition:
            raise ApiError("ERR_DUPLICATE_EDITION", 409,
                           "A catalog item with this (isbn13, edition) already exists.")

    item = new_entity(
        isbn13=isbn13, edition=edition, title=title, author=author,
        list_price_cents=list_price, rental_base_cents=rental_base,
        ebook_price_cents=ebook_price, buyback_base_cents=buyback_base,
        replacement_fee_cents=replacement_fee, rentable=rentable, buyable=buyable,
        ebook_available=ebook_available, highlighting_allowed=highlighting_allowed,
        max_highlight_pct=max_highlight_pct,
    )
    catalog_items[item["id"]] = item
    return ok(serialize(item), "object", 201)


@app.route("/catalog/<cid>", methods=["GET"])
def get_catalog(cid):
    authenticate({"CatalogAdmin", "Customer", "WarehouseAgent"})
    item = get_or_404(catalog_items, cid)
    return ok(serialize(item), "object", 200)


# ---------------------------------------------------------------------------
# Inventory units
# ---------------------------------------------------------------------------
@app.route("/inventory-units", methods=["POST"])
def create_inventory_unit():
    authenticate({"CatalogAdmin"})
    body = get_body()
    catalog_item_id = as_str(body, "catalog_item_id")
    get_or_404(catalog_items, catalog_item_id)
    condition_grade = as_enum(body, "condition_grade", CONDITIONS)
    acquisition_cost = as_int(body, "acquisition_cost_cents", minimum=0)

    unit = new_entity(
        catalog_item_id=catalog_item_id, condition_grade=condition_grade,
        status="AVAILABLE", acquisition_cost_cents=acquisition_cost, times_rented=0,
    )
    inventory_units[unit["id"]] = unit
    return ok(serialize(unit), "object", 201)


@app.route("/inventory-units/<uid>", methods=["GET"])
def get_inventory_unit(uid):
    authenticate({"CatalogAdmin", "WarehouseAgent"})
    unit = get_or_404(inventory_units, uid)
    return ok(serialize(unit), "object", 200)


@app.route("/inventory-units", methods=["GET"])
def list_inventory_units():
    authenticate({"CatalogAdmin", "WarehouseAgent"})
    cat = request.args.get("catalog_item_id")
    status = request.args.get("status")

    def pred(u):
        if cat is not None and u["catalog_item_id"] != cat:
            return False
        if status is not None and u["status"] != status:
            return False
        return True

    items = sorted_values(inventory_units, pred)
    page, meta = paginate(items)
    return ok([serialize(u) for u in page], "array", 200, meta)


# ---------------------------------------------------------------------------
# Customers + wallet
# ---------------------------------------------------------------------------
@app.route("/customers", methods=["POST"])
def create_customer():
    authenticate({"CatalogAdmin"})
    body = get_body()
    email = as_str(body, "email")
    full_name = as_str(body, "full_name")
    cust = new_entity(email=email, full_name=full_name, active_subscription_id=None)
    customers[cust["id"]] = cust
    return ok(serialize_customer(cust), "object", 201)


@app.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    role, uid = authenticate({"CatalogAdmin", "Customer"})
    cust = get_or_404(customers, cid)
    require_owner(role, uid, cust["id"])
    return ok(serialize_customer(cust), "object", 200)


@app.route("/customers/<cid>/wallet/adjustments", methods=["POST"])
def wallet_adjustment(cid):
    authenticate({"CatalogAdmin"})
    cust = get_or_404(customers, cid)
    body = get_body()
    amount = as_int(body, "amount_cents")
    kind = as_enum(body, "kind", TXN_KINDS, required=False, default="TOP_UP")
    txn = add_txn(cust["id"], amount, kind)
    bump_customer_version(cust)
    return ok(serialize(txn), "object", 201)


@app.route("/customers/<cid>/wallet-transactions", methods=["GET"])
def list_wallet_transactions(cid):
    role, uid = authenticate({"CatalogAdmin", "Customer"})
    cust = get_or_404(customers, cid)
    require_owner(role, uid, cust["id"])
    items = sorted_values(wallet_txns, lambda t: t["customer_id"] == cust["id"])
    page, meta = paginate(items)
    return ok([serialize(t) for t in page], "array", 200, meta)


# ---------------------------------------------------------------------------
# Subscription plans + subscriptions
# ---------------------------------------------------------------------------
@app.route("/subscription-plans", methods=["POST"])
def create_subscription_plan():
    authenticate({"CatalogAdmin"})
    body = get_body()
    tier = as_enum(body, "tier", PLAN_TIERS)
    monthly_fee = as_int(body, "monthly_fee_cents", minimum=0)
    rental_discount = as_num(body, "rental_discount_pct", minimum=0, maximum=1)
    includes_solutions = as_bool(body, "includes_solutions", None)
    if not _present(body, "includes_solutions"):
        bad_request("Missing required field: includes_solutions.")
    term_months = as_int(body, "term_months", required=False, default=1, minimum=1)

    plan = new_entity(
        tier=tier, monthly_fee_cents=monthly_fee, rental_discount_pct=rental_discount,
        includes_solutions=includes_solutions, term_months=term_months,
    )
    subscription_plans[plan["id"]] = plan
    return ok(serialize(plan), "object", 201)


@app.route("/customers/<cid>/subscription", methods=["POST"])
def create_subscription(cid):
    role, uid = authenticate({"Customer"})
    cust = get_or_404(customers, cid)
    require_owner(role, uid, cust["id"])
    body = get_body()
    plan_id = as_str(body, "plan_id")
    plan = get_or_404(subscription_plans, plan_id)

    start_date = now()
    if _present(body, "start_date"):
        start_date = parse_dt(body["start_date"])
    term_days = plan["term_months"] * DAYS_PER_MONTH
    period_start = start_date
    period_end = period_start + timedelta(days=term_days)

    # temporal: closed-interval non-overlap vs non-CANCELLED subscriptions
    for sub in subscriptions.values():
        if sub["customer_id"] != cust["id"] or sub["status"] == "CANCELLED":
            continue
        if period_start <= sub["period_end"] and sub["period_start"] <= period_end:
            raise ApiError("ERR_SUBSCRIPTION_PERIOD_OVERLAP", 409,
                           "New subscription period overlaps an existing period.")

    sub = new_entity(
        customer_id=cust["id"], plan_id=plan_id, status="ACTIVE",
        period_start=period_start, period_end=period_end,
        monthly_fee_cents=plan["monthly_fee_cents"],
        rental_discount_pct=plan["rental_discount_pct"],
    )
    subscriptions[sub["id"]] = sub
    add_txn(cust["id"], -plan["monthly_fee_cents"], "SUBSCRIPTION_FEE", sub["id"])
    if period_start <= now() < period_end:
        cust["active_subscription_id"] = sub["id"]
    bump_customer_version(cust)
    return ok(serialize(sub), "object", 201)


@app.route("/subscriptions/<sid>", methods=["GET"])
def get_subscription(sid):
    role, uid = authenticate({"Customer", "CatalogAdmin"})
    sub = get_or_404(subscriptions, sid)
    require_owner(role, uid, sub["customer_id"])
    return ok(serialize(sub), "object", 200)


@app.route("/subscriptions", methods=["GET"])
def list_subscriptions():
    role, uid = authenticate({"Customer", "CatalogAdmin"})
    customer_id = request.args.get("customer_id")
    plan_id = request.args.get("plan_id")
    if role == "Customer":
        customer_id = uid

    def pred(s):
        if customer_id is not None and s["customer_id"] != customer_id:
            return False
        if plan_id is not None and s["plan_id"] != plan_id:
            return False
        return True

    items = sorted_values(subscriptions, pred)
    page, meta = paginate(items)
    return ok([serialize(s) for s in page], "array", 200, meta)


@app.route("/subscriptions/<sid>/cancel", methods=["POST"])
def cancel_subscription(sid):
    role, uid = authenticate({"Customer"})
    sub = get_or_404(subscriptions, sid)
    require_owner(role, uid, sub["customer_id"])
    if sub["status"] != "ACTIVE":
        raise ApiError("ERR_SUBSCRIPTION_NOT_ACTIVE", 409, "Subscription is not active.")

    term_days = (sub["period_end"] - sub["period_start"]).days
    if term_days <= 0:
        term_days = 1
    elapsed_raw = (now() - sub["period_start"]).total_seconds() / 86400.0
    elapsed = math.floor(elapsed_raw)
    if elapsed < 0:
        elapsed = 0
    if elapsed > term_days:
        elapsed = term_days
    remaining = term_days - elapsed
    refund = rhu(Decimal(sub["monthly_fee_cents"]) * Decimal(remaining) / Decimal(term_days))

    sub["status"] = "CANCELLED"
    touch(sub)
    if refund > 0:
        add_txn(sub["customer_id"], refund, "SUBSCRIPTION_REFUND", sub["id"])
    cust = customers.get(sub["customer_id"])
    if cust is not None and cust.get("active_subscription_id") == sub["id"]:
        cust["active_subscription_id"] = None
        touch(cust)
    return ok(serialize(sub), "object", 200)


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------
def member_discount(cust):
    sid = cust.get("active_subscription_id")
    if sid and sid in subscriptions and subscriptions[sid]["status"] == "ACTIVE":
        return subscriptions[sid]["rental_discount_pct"]
    return 0


def compute_quoted_charge(cust, catalog, fulfillment_type, rental_term_days):
    if fulfillment_type == "RENT":
        base = Decimal(catalog["rental_base_cents"])
        mult = TERM_MULT[rental_term_days]
        disc = Decimal(str(member_discount(cust)))
        return rhu(base * mult * (Decimal(1) - disc))
    if fulfillment_type == "BUY":
        return catalog["list_price_cents"]
    return catalog["ebook_price_cents"]  # EBOOK


@app.route("/orders", methods=["POST"])
def create_order():
    role, uid = authenticate({"Customer"})
    cust = get_or_404(customers, uid)
    body = get_body()

    catalog_item_id = as_str(body, "catalog_item_id")
    catalog = get_or_404(catalog_items, catalog_item_id)
    fulfillment_type = as_enum(body, "fulfillment_type", FULFILLMENT_TYPES)

    # tier 7: referential eligibility
    if fulfillment_type == "RENT" and not catalog["rentable"]:
        raise ApiError("ERR_ITEM_NOT_RENTABLE", 422, "Item is not rentable.")
    if fulfillment_type == "BUY" and not catalog["buyable"]:
        raise ApiError("ERR_ITEM_NOT_BUYABLE", 422, "Item is not buyable.")
    if fulfillment_type == "EBOOK" and not catalog["ebook_available"]:
        raise ApiError("ERR_ITEM_NOT_EBOOK_AVAILABLE", 422, "Item is not available as an ebook.")

    # tier 9: term validity
    rental_term_days = None
    if fulfillment_type == "RENT":
        if not _present(body, "rental_term_days") or \
                not isinstance(body["rental_term_days"], int) or \
                isinstance(body["rental_term_days"], bool) or \
                body["rental_term_days"] not in VALID_RENT_TERMS:
            raise ApiError("ERR_INVALID_TERM", 422, "Invalid rental_term_days for RENT.")
        rental_term_days = body["rental_term_days"]
    elif fulfillment_type == "EBOOK":
        if not _present(body, "rental_term_days") or \
                not isinstance(body["rental_term_days"], int) or \
                isinstance(body["rental_term_days"], bool) or \
                body["rental_term_days"] <= 0:
            raise ApiError("ERR_INVALID_TERM", 422, "EBOOK requires rental_term_days.")
        rental_term_days = body["rental_term_days"]
    else:  # BUY
        if _present(body, "rental_term_days"):
            raise ApiError("ERR_INVALID_TERM", 422, "BUY must not supply rental_term_days.")

    desired_start_date = None
    if fulfillment_type == "RENT":
        if _present(body, "desired_start_date"):
            desired_start_date = parse_dt(body["desired_start_date"])
        else:
            desired_start_date = now()

    # tier 8: EBOOK license window overlap (prospective window from current clock)
    if fulfillment_type == "EBOOK":
        prosp_start = now()
        prosp_end = prosp_start + timedelta(days=rental_term_days)
        for o in orders.values():
            if o["customer_id"] != cust["id"] or o["catalog_item_id"] != catalog_item_id:
                continue
            if o["fulfillment_type"] != "EBOOK" or o["payment_status"] == "REFUNDED":
                continue
            if o["access_start"] is None or o["access_end"] is None:
                continue
            if prosp_start < o["access_end"] and o["access_start"] < prosp_end:
                raise ApiError("ERR_EBOOK_LICENSE_OVERLAP", 409,
                               "EBOOK access window overlaps an existing active license.")

    quoted = compute_quoted_charge(cust, catalog, fulfillment_type, rental_term_days)

    order = new_entity(
        customer_id=cust["id"], catalog_item_id=catalog_item_id, inventory_unit_id=None,
        fulfillment_type=fulfillment_type, rental_term_days=rental_term_days,
        desired_start_date=desired_start_date, access_start=None, access_end=None,
        payment_status="UNPAID", fulfillment_status="PENDING",
        quoted_charge_cents=quoted, final_charge_cents=None, refunded_cents=0,
    )
    orders[order["id"]] = order
    return ok(serialize(order), "object", 201)


@app.route("/orders/<oid>", methods=["GET"])
def get_order(oid):
    role, uid = authenticate({"Customer", "CatalogAdmin", "WarehouseAgent"})
    order = get_or_404(orders, oid)
    require_owner(role, uid, order["customer_id"])
    return ok(serialize(order), "object", 200)


@app.route("/orders", methods=["GET"])
def list_orders():
    role, uid = authenticate({"Customer", "CatalogAdmin", "WarehouseAgent"})
    customer_id = request.args.get("customer_id")
    catalog_item_id = request.args.get("catalog_item_id")
    inventory_unit_id = request.args.get("inventory_unit_id")
    if role == "Customer":
        customer_id = uid

    def pred(o):
        if customer_id is not None and o["customer_id"] != customer_id:
            return False
        if catalog_item_id is not None and o["catalog_item_id"] != catalog_item_id:
            return False
        if inventory_unit_id is not None and o["inventory_unit_id"] != inventory_unit_id:
            return False
        return True

    items = sorted_values(orders, pred)
    page, meta = paginate(items)
    return ok([serialize(o) for o in page], "array", 200, meta)


@app.route("/orders/<oid>/pay", methods=["POST"])
def pay_order(oid):
    role, uid = authenticate({"Customer"})
    order = get_or_404(orders, oid)
    require_owner(role, uid, order["customer_id"])
    if order["payment_status"] != "UNPAID":
        raise ApiError("ERR_ORDER_NOT_PAYABLE", 409, "Order is not payable.")
    if wallet_balance(order["customer_id"]) < order["quoted_charge_cents"]:
        raise ApiError("ERR_INSUFFICIENT_CREDIT", 402, "Wallet credit does not cover the charge.")

    add_txn(order["customer_id"], -order["quoted_charge_cents"], "ORDER_CHARGE", order["id"])
    order["payment_status"] = "PAID"
    if order["fulfillment_type"] == "EBOOK":
        order["fulfillment_status"] = "DELIVERED"
        order["access_start"] = now()
        order["access_end"] = now() + timedelta(days=order["rental_term_days"])
    touch(order)
    return ok(serialize(order), "object", 200)


def select_unit(order):
    units = [u for u in inventory_units.values()
             if u["catalog_item_id"] == order["catalog_item_id"] and u["status"] == "AVAILABLE"]
    if not units:
        raise ApiError("ERR_NO_AVAILABLE_UNIT", 409, "No available inventory unit for the catalog item.")

    if order["fulfillment_type"] == "RENT":
        start = order["desired_start_date"]
        new_due = start + timedelta(days=order["rental_term_days"])
        req_start = start
        req_end = new_due + timedelta(days=INSPECTION_BUFFER_DAYS)
        eligible = []
        for u in units:
            conflict = False
            for r in rentals.values():
                if r["inventory_unit_id"] != u["id"]:
                    continue
                r_start = r["start_date"]
                r_end = r["due_date"] + timedelta(days=INSPECTION_BUFFER_DAYS)
                if req_start < r_end and r_start < req_end:
                    conflict = True
                    break
            if not conflict:
                eligible.append(u)
        if not eligible:
            raise ApiError("ERR_UNIT_WINDOW_CONFLICT", 409,
                           "Every available unit conflicts on the requested window.")
        pool = eligible
    else:
        pool = units

    pool.sort(key=lambda u: (GRADE_RANK[u["condition_grade"]], u["times_rented"],
                             u["created_at"], u["_seq"]))
    return pool[0]


@app.route("/orders/<oid>/confirm", methods=["POST"])
def confirm_order(oid):
    authenticate({"WarehouseAgent"})
    order = get_or_404(orders, oid)
    if not (order["fulfillment_status"] == "PENDING" and order["payment_status"] == "PAID"):
        raise ApiError("ERR_ORDER_NOT_PAID", 409, "Order is not pending and paid.")
    if order["fulfillment_type"] not in ("RENT", "BUY"):
        raise ApiError("ERR_ORDER_NOT_PAID", 409, "Only RENT/BUY orders can be confirmed.")

    unit = select_unit(order)
    order["inventory_unit_id"] = unit["id"]

    if order["fulfillment_type"] == "RENT":
        unit["status"] = "RENTED"
        unit["times_rented"] += 1
        touch(unit)
        start = order["desired_start_date"]
        rental = new_entity(
            order_id=order["id"], customer_id=order["customer_id"],
            inventory_unit_id=unit["id"], status="ACTIVE", start_date=start,
            due_date=start + timedelta(days=order["rental_term_days"]),
            term_days=order["rental_term_days"], extension_count=0,
            highlight_pct_used=0, late_days=0, late_fee_cents=0, damage_fee_cents=0,
        )
        rentals[rental["id"]] = rental
        order["fulfillment_status"] = "CONFIRMED"
    else:  # BUY
        unit["status"] = "SOLD"
        touch(unit)
        order["fulfillment_status"] = "DELIVERED"

    touch(order)
    return ok(serialize(order), "object", 200)


@app.route("/orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    role, uid = authenticate({"Customer"})
    order = get_or_404(orders, oid)
    require_owner(role, uid, order["customer_id"])

    if order["fulfillment_type"] == "EBOOK" and order["fulfillment_status"] == "DELIVERED":
        raise ApiError("ERR_EBOOK_ALREADY_DELIVERED", 422,
                       "A delivered ebook order cannot be cancelled.")
    if order["fulfillment_status"] != "PENDING":
        raise ApiError("ERR_ORDER_NOT_CANCELLABLE", 409, "Order is not cancellable.")

    if order["payment_status"] == "PAID":
        add_txn(order["customer_id"], order["quoted_charge_cents"], "ORDER_REFUND", order["id"])
        order["refunded_cents"] += order["quoted_charge_cents"]
        order["payment_status"] = "REFUNDED"
    order["fulfillment_status"] = "CANCELLED"
    touch(order)
    return ok(serialize(order), "object", 200)


# ---------------------------------------------------------------------------
# Rentals
# ---------------------------------------------------------------------------
@app.route("/rentals/<rid>", methods=["GET"])
def get_rental(rid):
    role, uid = authenticate({"Customer", "WarehouseAgent"})
    rental = get_or_404(rentals, rid)
    require_owner(role, uid, rental["customer_id"])
    return ok(serialize(rental), "object", 200)


@app.route("/rentals", methods=["GET"])
def list_rentals():
    role, uid = authenticate({"Customer", "WarehouseAgent"})
    order_id = request.args.get("order_id")
    customer_id = request.args.get("customer_id")
    inventory_unit_id = request.args.get("inventory_unit_id")
    if role == "Customer":
        customer_id = uid

    def pred(r):
        if order_id is not None and r["order_id"] != order_id:
            return False
        if customer_id is not None and r["customer_id"] != customer_id:
            return False
        if inventory_unit_id is not None and r["inventory_unit_id"] != inventory_unit_id:
            return False
        return True

    items = sorted_values(rentals, pred)
    page, meta = paginate(items)
    return ok([serialize(r) for r in page], "array", 200, meta)


@app.route("/rentals/<rid>/extend", methods=["POST"])
def extend_rental(rid):
    role, uid = authenticate({"Customer"})
    rental = get_or_404(rentals, rid)
    require_owner(role, uid, rental["customer_id"])
    if rental["status"] != "ACTIVE":
        raise ApiError("ERR_RENTAL_NOT_ACTIVE", 409, "Rental is not active.")
    if rental["extension_count"] >= MAX_EXTENSIONS or \
            rental["term_days"] + EXTENSION_TERM_DAYS > MAX_TOTAL_TERM_DAYS:
        raise ApiError("ERR_MAX_EXTENSIONS_REACHED", 422, "Extension limit reached.")
    if wallet_balance(rental["customer_id"]) < EXTENSION_FEE_CENTS:
        raise ApiError("ERR_INSUFFICIENT_CREDIT", 402, "Wallet credit does not cover the extension fee.")

    rental["extension_count"] += 1
    rental["term_days"] += EXTENSION_TERM_DAYS
    rental["due_date"] = rental["start_date"] + timedelta(days=rental["term_days"])
    add_txn(rental["customer_id"], -EXTENSION_FEE_CENTS, "EXTENSION_FEE", rental["id"])
    touch(rental)
    return ok(serialize(rental), "object", 200)


@app.route("/rentals/<rid>/return", methods=["POST"])
def start_return(rid):
    role, uid = authenticate({"Customer"})
    rental = get_or_404(rentals, rid)
    require_owner(role, uid, rental["customer_id"])
    for rs in return_shipments.values():
        if rs["rental_id"] == rental["id"] and rs["status"] == "LABEL_ISSUED":
            raise ApiError("ERR_RETURN_ALREADY_OPEN", 409, "A return is already open for this rental.")
    if rental["status"] != "ACTIVE":
        raise ApiError("ERR_RENTAL_NOT_ACTIVE", 409, "Rental is not active.")

    shipment = new_entity(
        rental_id=rental["id"], status="LABEL_ISSUED",
        carrier_label="LBL_" + uuid.uuid4().hex[:16].upper(),
        reported_condition=None, highlight_pct_reported=0, is_lost=False,
        damage_fee_cents=0,
    )
    return_shipments[shipment["id"]] = shipment
    rental["status"] = "RETURN_INITIATED"
    touch(rental)
    unit = inventory_units.get(rental["inventory_unit_id"])
    if unit is not None:
        unit["status"] = "IN_INSPECTION"
        touch(unit)
    return ok(serialize(shipment), "object", 201)


@app.route("/rentals/<rid>/return-shipments", methods=["GET"])
def list_return_shipments(rid):
    role, uid = authenticate({"Customer", "WarehouseAgent"})
    rental = get_or_404(rentals, rid)
    require_owner(role, uid, rental["customer_id"])
    items = sorted_values(return_shipments, lambda rs: rs["rental_id"] == rental["id"])
    page, meta = paginate(items)
    return ok([serialize(rs) for rs in page], "array", 200, meta)


def compute_late(rental, catalog):
    delta = (now() - rental["due_date"]).total_seconds()
    if delta <= 0:
        days_overdue = 0
    else:
        days_overdue = math.ceil(delta / 86400.0)
    late_days = max(0, days_overdue - GRACE_DAYS)
    late_fee = min(late_days * DAILY_LATE_FEE_CENTS, catalog["replacement_fee_cents"])
    return days_overdue, late_days, late_fee


def compute_damage(rental, shipment, catalog, unit, reported_condition, highlight_pct):
    original_rank = GRADE_RANK[unit["condition_grade"]]
    assessed_rank = GRADE_RANK[reported_condition]
    severity = max(0, assessed_rank - original_rank)
    condition_fee = severity * CONDITION_STEP_FEE_CENTS
    if catalog["highlighting_allowed"]:
        overage = max(0, highlight_pct - catalog["max_highlight_pct"])
        highlight_fee = rhu(Decimal(str(overage)) * Decimal(HIGHLIGHT_FEE_PER_PCT_CENTS))
    else:
        highlight_fee = HIGHLIGHT_BANNED_FLAT_CENTS if highlight_pct > 0 else 0
    return min(condition_fee + highlight_fee, catalog["list_price_cents"])


@app.route("/return-shipments/<sid>/inspect", methods=["POST"])
def inspect_return(sid):
    authenticate({"WarehouseAgent"})
    shipment = get_or_404(return_shipments, sid)
    if shipment["status"] != "LABEL_ISSUED":
        raise ApiError("ERR_RETURN_NOT_OPEN", 409, "Return shipment is not open.")

    body = get_body()
    is_lost = as_bool(body, "is_lost", False)
    highlight_pct = as_num(body, "highlight_pct_reported", required=False, default=0, minimum=0)
    if _present(body, "reported_condition"):
        reported_condition = as_enum(body, "reported_condition", CONDITIONS)
    else:
        reported_condition = None
        if not is_lost:
            bad_request("Missing required field: reported_condition.")

    rental = rentals[shipment["rental_id"]]
    order = orders[rental["order_id"]]
    catalog = catalog_items[order["catalog_item_id"]]
    unit = inventory_units[rental["inventory_unit_id"]]

    days_overdue, late_days, late_fee = compute_late(rental, catalog)
    lost_outcome = is_lost or days_overdue > LOST_THRESHOLD_DAYS

    shipment["reported_condition"] = reported_condition
    shipment["highlight_pct_reported"] = highlight_pct
    shipment["is_lost"] = is_lost
    rental["highlight_pct_used"] = highlight_pct

    if lost_outcome:
        shipment["status"] = "CLOSED_LOST"
        rental["late_days"] = 0
        rental["late_fee_cents"] = 0
        rental["damage_fee_cents"] = 0
        rental["status"] = "CLOSED_LOST"
        add_txn(rental["customer_id"], -catalog["replacement_fee_cents"],
                "REPLACEMENT_CHARGE", rental["id"])
        unit["status"] = "RETIRED"
        order["fulfillment_status"] = "COMPLETED"
        order["final_charge_cents"] = order["quoted_charge_cents"] + catalog["replacement_fee_cents"]
    else:
        damage_fee = compute_damage(rental, shipment, catalog, unit,
                                    reported_condition, highlight_pct)
        if damage_fee > 0 or late_fee > 0:
            shipment["status"] = "CLOSED_DAMAGED"
            shipment["damage_fee_cents"] = damage_fee
        else:
            shipment["status"] = "CLOSED_GOOD"
        rental["late_days"] = late_days
        rental["late_fee_cents"] = late_fee
        rental["damage_fee_cents"] = damage_fee
        rental["status"] = "CLOSED_RETURNED"
        if late_fee > 0:
            add_txn(rental["customer_id"], -late_fee, "LATE_FEE", rental["id"])
        if damage_fee > 0:
            add_txn(rental["customer_id"], -damage_fee, "DAMAGE_FEE", rental["id"])
        unit["status"] = "AVAILABLE"
        unit["condition_grade"] = reported_condition
        order["fulfillment_status"] = "COMPLETED"
        t0 = order["quoted_charge_cents"] + late_fee + damage_fee
        loyalty = LOYALTY_CREDIT_CENTS if t0 >= LOYALTY_THRESHOLD_CENTS else 0
        order["final_charge_cents"] = t0 - loyalty

    touch(shipment)
    touch(rental)
    touch(unit)
    touch(order)
    return ok(serialize(shipment), "object", 200)


# ---------------------------------------------------------------------------
# Buyback quotes
# ---------------------------------------------------------------------------
@app.route("/buyback-quotes", methods=["POST"])
def create_buyback_quote():
    role, uid = authenticate({"Customer"})
    cust = get_or_404(customers, uid)
    body = get_body()
    catalog_item_id = as_str(body, "catalog_item_id")
    catalog = get_or_404(catalog_items, catalog_item_id)
    declared_condition = as_enum(body, "declared_condition", CONDITIONS)
    expected_version = as_int(body, "expected_customer_version")

    if expected_version != cust["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Stale customer version.")

    # supersede any prior QUOTED quote for this (customer, item)
    for q in buyback_quotes.values():
        if q["customer_id"] == cust["id"] and q["catalog_item_id"] == catalog_item_id \
                and q["status"] == "QUOTED":
            q["status"] = "SUPERSEDED"
            touch(q)

    quoted_price = rhu(Decimal(catalog["buyback_base_cents"]) * COND_MULT[declared_condition])
    quote = new_entity(
        customer_id=cust["id"], catalog_item_id=catalog_item_id, inventory_unit_id=None,
        declared_condition=declared_condition, assessed_condition=None, status="QUOTED",
        quoted_price_cents=quoted_price, revised_price_cents=None, paid_price_cents=None,
        quote_expires_at=now() + timedelta(days=QUOTE_VALIDITY_DAYS),
    )
    buyback_quotes[quote["id"]] = quote
    bump_customer_version(cust)
    return ok(serialize(quote), "object", 201)


@app.route("/buyback-quotes/<qid>", methods=["GET"])
def get_buyback_quote(qid):
    role, uid = authenticate({"Customer", "WarehouseAgent"})
    quote = get_or_404(buyback_quotes, qid)
    require_owner(role, uid, quote["customer_id"])
    return ok(serialize(quote), "object", 200)


@app.route("/buyback-quotes", methods=["GET"])
def list_buyback_quotes():
    role, uid = authenticate({"Customer", "WarehouseAgent"})
    customer_id = request.args.get("customer_id")
    catalog_item_id = request.args.get("catalog_item_id")
    inventory_unit_id = request.args.get("inventory_unit_id")
    if role == "Customer":
        customer_id = uid

    def pred(q):
        if customer_id is not None and q["customer_id"] != customer_id:
            return False
        if catalog_item_id is not None and q["catalog_item_id"] != catalog_item_id:
            return False
        if inventory_unit_id is not None and q["inventory_unit_id"] != inventory_unit_id:
            return False
        return True

    items = sorted_values(buyback_quotes, pred)
    page, meta = paginate(items)
    return ok([serialize(q) for q in page], "array", 200, meta)


@app.route("/buyback-quotes/<qid>/accept", methods=["POST"])
def accept_buyback_quote(qid):
    role, uid = authenticate({"Customer"})
    quote = get_or_404(buyback_quotes, qid)
    require_owner(role, uid, quote["customer_id"])
    if quote["status"] != "QUOTED":
        raise ApiError("ERR_QUOTE_NOT_OPEN", 409, "Quote is not open.")
    if now() >= quote["quote_expires_at"]:
        raise ApiError("ERR_QUOTE_EXPIRED", 409, "Quote has expired.")
    quote["status"] = "ACCEPTED"
    touch(quote)
    return ok(serialize(quote), "object", 200)


def create_buyback_unit(quote, condition, price):
    unit = new_entity(
        catalog_item_id=quote["catalog_item_id"], condition_grade=condition,
        status="AVAILABLE", acquisition_cost_cents=price, times_rented=0,
    )
    inventory_units[unit["id"]] = unit
    return unit


@app.route("/buyback-quotes/<qid>/inspect", methods=["POST"])
def inspect_buyback_quote(qid):
    authenticate({"WarehouseAgent"})
    quote = get_or_404(buyback_quotes, qid)
    if quote["status"] != "ACCEPTED":
        raise ApiError("ERR_QUOTE_NOT_ACCEPTED", 409, "Quote is not accepted.")
    body = get_body()
    assessed_condition = as_enum(body, "assessed_condition", CONDITIONS)
    catalog = catalog_items[quote["catalog_item_id"]]

    quote["assessed_condition"] = assessed_condition
    if assessed_condition == quote["declared_condition"]:
        quote["status"] = "PAID"
        quote["paid_price_cents"] = quote["quoted_price_cents"]
        unit = create_buyback_unit(quote, assessed_condition, quote["quoted_price_cents"])
        quote["inventory_unit_id"] = unit["id"]
        add_txn(quote["customer_id"], quote["quoted_price_cents"], "BUYBACK_CREDIT", quote["id"])
    else:
        quote["status"] = "REVISED"
        quote["revised_price_cents"] = rhu(
            Decimal(catalog["buyback_base_cents"]) * COND_MULT[assessed_condition])
    touch(quote)
    return ok(serialize(quote), "object", 200)


@app.route("/buyback-quotes/<qid>/respond-revision", methods=["POST"])
def respond_revision(qid):
    role, uid = authenticate({"Customer"})
    quote = get_or_404(buyback_quotes, qid)
    require_owner(role, uid, quote["customer_id"])
    if quote["status"] != "REVISED":
        raise ApiError("ERR_QUOTE_NOT_REVISED", 409, "Quote is not in a revised state.")
    body = get_body()
    action = as_enum(body, "action", {"ACCEPT", "DECLINE"})

    if action == "ACCEPT":
        quote["status"] = "PAID"
        quote["paid_price_cents"] = quote["revised_price_cents"]
        unit = create_buyback_unit(quote, quote["assessed_condition"], quote["revised_price_cents"])
        quote["inventory_unit_id"] = unit["id"]
        add_txn(quote["customer_id"], quote["revised_price_cents"], "BUYBACK_CREDIT", quote["id"])
    else:
        quote["status"] = "DECLINED"
    touch(quote)
    return ok(serialize(quote), "object", 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
