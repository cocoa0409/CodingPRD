"""Vitamin & Supplement Store API — Flask reference implementation.

In-memory only. Every dict below is module-global and starts empty on each
process boot, so `start.sh` re-invocation wipes all state (required by the
per-test-server harness).
"""
import os
import random
import string
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from flask import Flask, request, g, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants (from SCAFFOLD calculations / PRD)
# ---------------------------------------------------------------------------
ROLES = ("StoreOperator", "Customer", "Practitioner")
GET_ALL = ["StoreOperator", "Customer", "Practitioner"]

FORMS = {"CAPSULE", "TABLET", "POWDER", "GUMMY", "LIQUID"}
GOALS = {"IMMUNITY", "SLEEP", "ENERGY", "JOINT", "DIGESTION"}
DSHEA_VALID = {"STRUCTURE_FUNCTION", "NONE"}
SEVERITIES = {"CLASS_I", "CLASS_II", "CLASS_III"}
RETURN_REASONS = {"DEFECT", "UNWANTED", "RECALL", "EXPIRED"}

LOYALTY_PURCHASE_DISCOUNT = {"BRONZE": 0.00, "SILVER": 0.05, "GOLD": 0.10}
AUTOSHIP_DISCOUNT = {30: 0.05, 60: 0.08, 90: 0.10}
TIER_EARN_MULTIPLIER = {"BRONZE": 1.0, "SILVER": 1.25, "GOLD": 1.5}
AUTOSHIP_EARN_BONUS = 0.25
POINTS_PER_DOLLAR_CENTS = 100
POINTS_PER_ORDER_CAP = 2000
POINT_REDEMPTION_VALUE_CENTS = 1
TIER_SILVER_THRESHOLD = 500
TIER_GOLD_THRESHOLD = 1000
RESTOCK_FEE_PCT = 0.15
SUBSCRIPTION_BUFFER_DAYS = 7
VALID_CADENCE = {30, 60, 90}

DEFAULT_CLOCK = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# In-memory stores
# ---------------------------------------------------------------------------
products = {}
lots = {}
customers = {}
practitioners = {}
recommendations = {}
bundles = {}
subscriptions = {}
orders = {}
order_lines = {}
returns = {}

_clock = DEFAULT_CLOCK
_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


def now():
    return datetime.now(timezone.utc)


def clock_now():
    return _clock


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------
def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_iso(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Errors + response envelope
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def request_meta():
    rid = "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return {"api_request_id": rid, "api_request_timestamp": iso(now())}


def success(data, response_type="object", pagination=None, status=200):
    meta = request_meta()
    if pagination:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(error_id, http_status, message):
    body = {
        "meta": request_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", 404, "Method not allowed")


@app.errorhandler(500)
def handle_500(e):
    return error_response("ERR_VALIDATION", 500, "Internal error")


# ---------------------------------------------------------------------------
# Auth / routing
# ---------------------------------------------------------------------------
def require_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid auth headers")
    g.uid = uid
    g.role = role
    return uid, role


def route(path, methods, roles):
    def deco(fn):
        def wrapper(**kw):
            require_auth()
            if g.role not in roles:
                raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted")
            return fn(**kw)
        wrapper.__name__ = fn.__name__
        app.add_url_rule(path, fn.__name__, wrapper, methods=methods)
        return fn
    return deco


def check_customer_owner(owner_id):
    if g.role == "Customer" and owner_id != g.uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Caller does not own resource")


# ---------------------------------------------------------------------------
# Body parsing / validation helpers
# ---------------------------------------------------------------------------
def body_json():
    if not request.data:
        return {}
    j = request.get_json(silent=True, force=True)
    return j if isinstance(j, dict) else {}


def verr(msg="Invalid request body"):
    raise ApiError("ERR_VALIDATION", 422, msg)


def req_str(b, k):
    v = b.get(k)
    if not isinstance(v, str) or v == "":
        verr("Missing or invalid field: %s" % k)
    return v


def req_int(b, k):
    v = b.get(k)
    if isinstance(v, bool) or not isinstance(v, int):
        verr("Missing or invalid integer field: %s" % k)
    return v


def opt_int(b, k, default):
    if k not in b or b.get(k) is None:
        return default
    v = b.get(k)
    if isinstance(v, bool) or not isinstance(v, int):
        verr("Invalid integer field: %s" % k)
    return v


def req_number(b, k):
    v = b.get(k)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        verr("Missing or invalid number field: %s" % k)
    return float(v)


# ---------------------------------------------------------------------------
# Entity factory / mutation
# ---------------------------------------------------------------------------
def new_entity(store, fields):
    t = now()
    obj = dict(fields)
    obj["id"] = str(uuid.uuid4())
    obj["created_at"] = t
    obj["updated_at"] = t
    obj["version"] = 1
    obj["_seq"] = next_seq()
    store[obj["id"]] = obj
    return obj


def touch(obj):
    obj["updated_at"] = now()
    obj["version"] += 1


def get_or_404(store, oid):
    obj = store.get(oid)
    if obj is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found")
    return obj


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------
def round_half_up(dec):
    return int(dec.to_integral_value(rounding=ROUND_HALF_UP))


def compute_net_unit(gross, bundle_pct, purchase_pct):
    val = (Decimal(gross)
           * (Decimal(1) - Decimal(str(bundle_pct)))
           * (Decimal(1) - Decimal(str(purchase_pct))))
    return round_half_up(val)


def compute_points(base_source_cents, tier, is_autoship):
    base_points = base_source_cents // POINTS_PER_DOLLAR_CENTS
    mult = TIER_EARN_MULTIPLIER[tier] + (AUTOSHIP_EARN_BONUS if is_autoship else 0.0)
    raw = Decimal(base_points) * Decimal(str(mult))
    pts = int(raw.to_integral_value(rounding=ROUND_FLOOR))
    return min(pts, POINTS_PER_ORDER_CAP)


def tier_for(lifetime):
    if lifetime >= TIER_GOLD_THRESHOLD:
        return "GOLD"
    if lifetime >= TIER_SILVER_THRESHOLD:
        return "SILVER"
    return "BRONZE"


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def base_ser(o):
    return {
        "id": o["id"],
        "created_at": iso(o["created_at"]),
        "updated_at": iso(o["updated_at"]),
        "version": o["version"],
    }


def ser_product(o):
    d = base_ser(o)
    d.update({
        "name": o["name"],
        "form": o["form"],
        "regimen_goals": o["regimen_goals"],
        "is_practitioner_line": o["is_practitioner_line"],
        "dshea_claim_type": o["dshea_claim_type"],
        "requires_fda_disclaimer": o["requires_fda_disclaimer"],
        "unit_price_cents": o["unit_price_cents"],
    })
    return d


def ser_lot(o):
    d = base_ser(o)
    d.update({
        "product_id": o["product_id"],
        "lot_number": o["lot_number"],
        "expiration_date": iso(o["expiration_date"]),
        "quantity_received": o["quantity_received"],
        "quantity_on_hand": o["quantity_on_hand"],
        "quantity_reserved": o["quantity_reserved"],
        "quantity_available": o["quantity_on_hand"] - o["quantity_reserved"],
        "status": o["status"],
        "recall_reason": o["recall_reason"],
        "recall_severity": o["recall_severity"],
    })
    return d


def ser_customer(o):
    d = base_ser(o)
    d.update({
        "email": o["email"],
        "full_name": o["full_name"],
        "status": o["status"],
        "lifetime_points_earned": o["lifetime_points_earned"],
        "points_balance": o["points_balance"],
        "loyalty_tier": o["loyalty_tier"],
    })
    return d


def ser_practitioner(o):
    d = base_ser(o)
    d.update({"full_name": o["full_name"], "license_number": o["license_number"]})
    return d


def ser_recommendation(o):
    d = base_ser(o)
    d.update({
        "practitioner_id": o["practitioner_id"],
        "customer_id": o["customer_id"],
        "product_id": o["product_id"],
        "issued_at": iso(o["issued_at"]),
        "expires_at": iso(o["expires_at"]),
        "max_units": o["max_units"],
        "consumed_units": o["consumed_units"],
        "status": o["status"],
    })
    return d


def ser_bundle(o):
    d = base_ser(o)
    d.update({
        "name": o["name"],
        "component_product_ids": o["component_product_ids"],
        "discount_pct": o["discount_pct"],
    })
    return d


def ser_subscription(o):
    d = base_ser(o)
    d.update({
        "customer_id": o["customer_id"],
        "product_id": o["product_id"],
        "quantity_per_cycle": o["quantity_per_cycle"],
        "cadence_days": o["cadence_days"],
        "first_ship_date": iso(o["first_ship_date"]),
        "next_ship_date": iso(o["next_ship_date"]),
        "autoship_discount_pct": o["autoship_discount_pct"],
        "status": o["status"],
    })
    return d


def ser_order(o):
    d = base_ser(o)
    d.update({
        "customer_id": o["customer_id"],
        "subscription_id": o["subscription_id"],
        "order_type": o["order_type"],
        "points_redeemed": o["points_redeemed"],
        "status": o["status"],
        "provisional_subtotal_cents": o["provisional_subtotal_cents"],
        "final_subtotal_cents": o["final_subtotal_cents"],
        "redemption_cents": o["redemption_cents"],
        "total_cents": o["total_cents"],
        "points_earned": o["points_earned"],
    })
    return d


def ser_order_line(o):
    d = base_ser(o)
    d.update({
        "order_id": o["order_id"],
        "product_id": o["product_id"],
        "bundle_id": o["bundle_id"],
        "quantity": o["quantity"],
        "gross_unit_price_cents": o["gross_unit_price_cents"],
        "net_unit_price_cents": o["net_unit_price_cents"],
        "line_total_cents": o["line_total_cents"],
        "lot_allocations": [
            {"lot_id": a["lot_id"], "quantity": a["quantity"], "status": a["status"]}
            for a in o["lot_allocations"]
        ],
        "short_quantity": o["short_quantity"],
    })
    return d


def ser_return(o):
    d = base_ser(o)
    d.update({
        "order_id": o["order_id"],
        "order_line_id": o["order_line_id"],
        "quantity": o["quantity"],
        "reason": o["reason"],
        "status": o["status"],
        "refund_cents": o["refund_cents"],
        "points_reversed": o["points_reversed"],
        "restock": o["restock"],
    })
    return d


# ---------------------------------------------------------------------------
# Pagination + list helper
# ---------------------------------------------------------------------------
def paginate(items, serializer):
    try:
        limit = request.args.get("limit", None)
        limit = 10 if limit is None else int(limit)
    except (ValueError, TypeError):
        limit = 10
    try:
        offset = request.args.get("offset", None)
        offset = 0 if offset is None else int(offset)
    except (ValueError, TypeError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    items = sorted(items, key=lambda o: (o["created_at"], o["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    data = [serializer(o) for o in page]
    return success(data, response_type="array", pagination=pagination)


# ===========================================================================
# Product
# ===========================================================================
@route("/products", ["POST"], ["StoreOperator"])
def create_product():
    b = body_json()
    name = req_str(b, "name")
    form = req_str(b, "form")
    if form not in FORMS:
        verr("Invalid form")
    goals = b.get("regimen_goals")
    if not isinstance(goals, list) or any(gg not in GOALS for gg in goals):
        verr("Invalid regimen_goals")
    is_pl = b.get("is_practitioner_line", False)
    if not isinstance(is_pl, bool):
        verr("Invalid is_practitioner_line")
    dshea = b.get("dshea_claim_type")
    if dshea == "DISEASE":
        raise ApiError("ERR_DSHEA_DISEASE_CLAIM", 422, "Disease claims are prohibited under DSHEA")
    if dshea not in DSHEA_VALID:
        verr("Invalid dshea_claim_type")
    price = req_int(b, "unit_price_cents")
    obj = new_entity(products, {
        "name": name,
        "form": form,
        "regimen_goals": list(goals),
        "is_practitioner_line": is_pl,
        "dshea_claim_type": dshea,
        "requires_fda_disclaimer": (dshea == "STRUCTURE_FUNCTION"),
        "unit_price_cents": price,
    })
    return success(ser_product(obj), status=201)


@route("/products/<pid>", ["GET"], GET_ALL)
def get_product(pid):
    return success(ser_product(get_or_404(products, pid)))


# ===========================================================================
# Lot
# ===========================================================================
@route("/products/<pid>/lots", ["POST"], ["StoreOperator"])
def create_lot(pid):
    get_or_404(products, pid)
    b = body_json()
    lot_number = req_str(b, "lot_number")
    try:
        expiration = parse_iso(b.get("expiration_date"))
    except (ValueError, TypeError):
        verr("Invalid expiration_date")
    qty = req_int(b, "quantity_received")
    obj = new_entity(lots, {
        "product_id": pid,
        "lot_number": lot_number,
        "expiration_date": expiration,
        "quantity_received": qty,
        "quantity_on_hand": qty,
        "quantity_reserved": 0,
        "status": "AVAILABLE",
        "recall_reason": None,
        "recall_severity": None,
    })
    return success(ser_lot(obj), status=201)


@route("/products/<pid>/lots", ["GET"], GET_ALL)
def list_product_lots(pid):
    get_or_404(products, pid)
    items = [l for l in lots.values() if l["product_id"] == pid]
    status = request.args.get("status")
    if status:
        items = [l for l in items if l["status"] == status]
    return paginate(items, ser_lot)


@route("/lots/<lid>", ["GET"], GET_ALL)
def get_lot(lid):
    return success(ser_lot(get_or_404(lots, lid)))


def recall_cascade(lot):
    released_total = 0
    for line in order_lines.values():
        line_changed = False
        for alloc in line["lot_allocations"]:
            if alloc["lot_id"] == lot["id"] and alloc["status"] == "RESERVED":
                alloc["status"] = "RELEASED"
                line["short_quantity"] += alloc["quantity"]
                released_total += alloc["quantity"]
                line_changed = True
        if line_changed:
            touch(line)
    lot["quantity_reserved"] -= released_total


@route("/lots/<lid>/state", ["POST"], ["StoreOperator"])
def lot_state(lid):
    lot = get_or_404(lots, lid)
    b = body_json()
    to_status = b.get("to_status")
    if to_status not in {"QUARANTINED", "AVAILABLE", "RECALLED"}:
        verr("Invalid to_status")
    cur = lot["status"]
    if to_status == "QUARANTINED":
        if cur != "AVAILABLE":
            raise ApiError("ERR_INVALID_STATE", 409, "Lot not AVAILABLE")
        lot["status"] = "QUARANTINED"
    elif to_status == "AVAILABLE":
        if cur != "QUARANTINED":
            raise ApiError("ERR_INVALID_STATE", 409, "Lot not QUARANTINED")
        lot["status"] = "AVAILABLE"
    else:  # RECALLED
        if cur not in ("AVAILABLE", "QUARANTINED"):
            raise ApiError("ERR_INVALID_STATE", 409, "Lot cannot be recalled from this state")
        reason = req_str(b, "reason")
        severity = b.get("severity")
        if severity not in SEVERITIES:
            verr("Invalid severity")
        lot["status"] = "RECALLED"
        lot["recall_reason"] = reason
        lot["recall_severity"] = severity
        recall_cascade(lot)
    touch(lot)
    return success(ser_lot(lot))


# ===========================================================================
# Customer
# ===========================================================================
@route("/customers", ["POST"], ["StoreOperator"])
def create_customer():
    b = body_json()
    email = req_str(b, "email")
    full_name = req_str(b, "full_name")
    obj = new_entity(customers, {
        "email": email,
        "full_name": full_name,
        "status": "ACTIVE",
        "lifetime_points_earned": 0,
        "points_balance": 0,
        "loyalty_tier": "BRONZE",
    })
    return success(ser_customer(obj), status=201)


@route("/customers/<cid>", ["GET"], GET_ALL)
def get_customer(cid):
    return success(ser_customer(get_or_404(customers, cid)))


def release_placed_allocations(order):
    """Release RESERVED allocations of an order's lines back to their lots."""
    for line in order_lines.values():
        if line["order_id"] != order["id"]:
            continue
        changed = False
        for alloc in line["lot_allocations"]:
            if alloc["status"] == "RESERVED":
                alloc["status"] = "RELEASED"
                lot = lots.get(alloc["lot_id"])
                if lot:
                    lot["quantity_reserved"] -= alloc["quantity"]
                    touch(lot)
                changed = True
        if changed:
            touch(line)


@route("/customers/<cid>/suspend", ["POST"], ["StoreOperator"])
def suspend_customer(cid):
    cust = get_or_404(customers, cid)
    if cust["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Customer not ACTIVE")
    cust["status"] = "SUSPENDED"
    for sub in subscriptions.values():
        if sub["customer_id"] == cid and sub["status"] == "ACTIVE":
            sub["status"] = "PAUSED"
            touch(sub)
            for order in orders.values():
                if (order.get("subscription_id") == sub["id"]
                        and order["order_type"] == "AUTOSHIP"
                        and order["status"] == "DRAFT"):
                    release_placed_allocations(order)
                    order["status"] = "CANCELLED"
                    touch(order)
    touch(cust)
    return success(ser_customer(cust))


# ===========================================================================
# Practitioner
# ===========================================================================
@route("/practitioners", ["POST"], ["StoreOperator"])
def create_practitioner():
    b = body_json()
    full_name = req_str(b, "full_name")
    license_number = req_str(b, "license_number")
    obj = new_entity(practitioners, {
        "full_name": full_name,
        "license_number": license_number,
    })
    return success(ser_practitioner(obj), status=201)


@route("/practitioners/<pid>", ["GET"], GET_ALL)
def get_practitioner(pid):
    return success(ser_practitioner(get_or_404(practitioners, pid)))


# ===========================================================================
# Recommendation
# ===========================================================================
@route("/recommendations", ["POST"], ["Practitioner"])
def create_recommendation():
    b = body_json()
    customer_id = req_str(b, "customer_id")
    product_id = req_str(b, "product_id")
    try:
        expires_at = parse_iso(b.get("expires_at"))
    except (ValueError, TypeError):
        verr("Invalid expires_at")
    max_units = req_int(b, "max_units")
    # left-to-right existence
    get_or_404(customers, customer_id)
    get_or_404(products, product_id)
    issued_at = clock_now()
    # overlap check with existing ISSUED for same (customer, product); half-open
    for r in recommendations.values():
        if (r["customer_id"] == customer_id and r["product_id"] == product_id
                and r["status"] == "ISSUED"):
            if issued_at < r["expires_at"] and r["issued_at"] < expires_at:
                raise ApiError("ERR_RECOMMENDATION_OVERLAP", 409,
                               "Overlapping recommendation interval")
    obj = new_entity(recommendations, {
        "practitioner_id": g.uid,
        "customer_id": customer_id,
        "product_id": product_id,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "max_units": max_units,
        "consumed_units": 0,
        "status": "ISSUED",
    })
    return success(ser_recommendation(obj), status=201)


@route("/recommendations/<rid>", ["GET"], GET_ALL)
def get_recommendation(rid):
    return success(ser_recommendation(get_or_404(recommendations, rid)))


@route("/recommendations", ["GET"], GET_ALL)
def list_recommendations():
    items = list(recommendations.values())
    for key in ("practitioner_id", "customer_id", "product_id", "status"):
        v = request.args.get(key)
        if v:
            items = [r for r in items if r[key] == v]
    return paginate(items, ser_recommendation)


@route("/recommendations/<rid>/revoke", ["POST"], ["Practitioner"])
def revoke_recommendation(rid):
    rec = get_or_404(recommendations, rid)
    if rec["practitioner_id"] != g.uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not the issuing practitioner")
    if rec["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", 409, "Recommendation not ISSUED")
    rec["status"] = "REVOKED"
    touch(rec)
    return success(ser_recommendation(rec))


# ===========================================================================
# Bundle
# ===========================================================================
@route("/bundles", ["POST"], ["StoreOperator"])
def create_bundle():
    b = body_json()
    name = req_str(b, "name")
    comp = b.get("component_product_ids")
    if not isinstance(comp, list) or any(not isinstance(c, str) for c in comp):
        verr("Invalid component_product_ids")
    discount_pct = req_number(b, "discount_pct")
    for c in comp:
        get_or_404(products, c)
    obj = new_entity(bundles, {
        "name": name,
        "component_product_ids": list(comp),
        "discount_pct": discount_pct,
    })
    return success(ser_bundle(obj), status=201)


@route("/bundles/<bid>", ["GET"], GET_ALL)
def get_bundle(bid):
    return success(ser_bundle(get_or_404(bundles, bid)))


# ===========================================================================
# Subscription
# ===========================================================================
@route("/subscriptions", ["POST"], ["Customer"])
def create_subscription():
    b = body_json()
    product_id = req_str(b, "product_id")
    quantity_per_cycle = req_int(b, "quantity_per_cycle")
    cadence_days = req_int(b, "cadence_days")
    try:
        first_ship_date = parse_iso(b.get("first_ship_date"))
    except (ValueError, TypeError):
        verr("Invalid first_ship_date")
    # existence
    get_or_404(products, product_id)
    # customer suspended check (priority 9)
    cust = customers.get(g.uid)
    if cust is not None and cust["status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_SUSPENDED", 409, "Customer is suspended")
    # quantity (priority 11)
    if quantity_per_cycle < 1:
        raise ApiError("ERR_INVALID_QUANTITY", 422, "quantity_per_cycle must be >= 1")
    # cadence (priority 12)
    if cadence_days not in VALID_CADENCE:
        raise ApiError("ERR_INVALID_CADENCE", 422, "cadence_days must be 30, 60 or 90")
    # window conflict (priority 14)
    buffer_secs = SUBSCRIPTION_BUFFER_DAYS * 86400
    for s in subscriptions.values():
        if (s["customer_id"] == g.uid and s["product_id"] == product_id
                and s["status"] in ("ACTIVE", "PAUSED")):
            diff = abs((first_ship_date - s["next_ship_date"]).total_seconds())
            if diff < buffer_secs:
                raise ApiError("ERR_SUBSCRIPTION_WINDOW_CONFLICT", 409,
                               "first_ship_date too close to an existing subscription")
    obj = new_entity(subscriptions, {
        "customer_id": g.uid,
        "product_id": product_id,
        "quantity_per_cycle": quantity_per_cycle,
        "cadence_days": cadence_days,
        "first_ship_date": first_ship_date,
        "next_ship_date": first_ship_date,
        "autoship_discount_pct": AUTOSHIP_DISCOUNT[cadence_days],
        "status": "ACTIVE",
    })
    return success(ser_subscription(obj), status=201)


@route("/subscriptions/<sid>", ["GET"], GET_ALL)
def get_subscription(sid):
    return success(ser_subscription(get_or_404(subscriptions, sid)))


@route("/subscriptions", ["GET"], GET_ALL)
def list_subscriptions():
    items = list(subscriptions.values())
    for key in ("customer_id", "product_id", "status"):
        v = request.args.get(key)
        if v:
            items = [s for s in items if s[key] == v]
    return paginate(items, ser_subscription)


@route("/subscriptions/<sid>/state", ["POST"], ["Customer"])
def subscription_state(sid):
    sub = get_or_404(subscriptions, sid)
    check_customer_owner(sub["customer_id"])
    b = body_json()
    to_status = b.get("to_status")
    if to_status not in {"ACTIVE", "PAUSED", "CANCELLED"}:
        verr("Invalid to_status")
    cur = sub["status"]
    ok = ((to_status == "PAUSED" and cur == "ACTIVE")
          or (to_status == "ACTIVE" and cur == "PAUSED")
          or (to_status == "CANCELLED" and cur in ("ACTIVE", "PAUSED")))
    if not ok:
        raise ApiError("ERR_INVALID_STATE", 409, "Transition not admitted")
    sub["status"] = to_status
    touch(sub)
    return success(ser_subscription(sub))


@route("/subscriptions/<sid>/generate-order", ["POST"], ["Customer"])
def generate_order(sid):
    sub = get_or_404(subscriptions, sid)
    check_customer_owner(sub["customer_id"])
    b = body_json()
    expected = b.get("expected_subscription_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        verr("Missing or invalid expected_subscription_version")
    if sub["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Subscription not ACTIVE")
    if expected != sub["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Stale subscription version")
    product = products.get(sub["product_id"])
    order = new_entity(orders, {
        "customer_id": sub["customer_id"],
        "subscription_id": sub["id"],
        "order_type": "AUTOSHIP",
        "points_redeemed": 0,
        "status": "DRAFT",
        "provisional_subtotal_cents": None,
        "final_subtotal_cents": None,
        "redemption_cents": 0,
        "total_cents": None,
        "points_earned": 0,
    })
    new_entity(order_lines, {
        "order_id": order["id"],
        "product_id": sub["product_id"],
        "bundle_id": None,
        "quantity": sub["quantity_per_cycle"],
        "gross_unit_price_cents": product["unit_price_cents"] if product else 0,
        "net_unit_price_cents": None,
        "line_total_cents": None,
        "lot_allocations": [],
        "short_quantity": 0,
    })
    sub["next_ship_date"] = sub["next_ship_date"] + timedelta(days=sub["cadence_days"])
    touch(sub)  # advances version (the OCC field)
    return success(ser_order(order), status=201)


# ===========================================================================
# Order & OrderLine
# ===========================================================================
@route("/orders", ["POST"], ["Customer"])
def create_order():
    b = body_json()
    points_redeemed = opt_int(b, "points_redeemed", 0)
    if points_redeemed < 0:
        verr("points_redeemed must be >= 0")
    cust = customers.get(g.uid)
    if cust is not None and cust["status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_SUSPENDED", 409, "Customer is suspended")
    obj = new_entity(orders, {
        "customer_id": g.uid,
        "subscription_id": None,
        "order_type": "ONE_OFF",
        "points_redeemed": points_redeemed,
        "status": "DRAFT",
        "provisional_subtotal_cents": None,
        "final_subtotal_cents": None,
        "redemption_cents": 0,
        "total_cents": None,
        "points_earned": 0,
    })
    return success(ser_order(obj), status=201)


@route("/orders/<oid>", ["GET"], GET_ALL)
def get_order(oid):
    return success(ser_order(get_or_404(orders, oid)))


@route("/orders", ["GET"], GET_ALL)
def list_orders():
    items = list(orders.values())
    for key in ("customer_id", "subscription_id", "status"):
        v = request.args.get(key)
        if v:
            items = [o for o in items if o.get(key) == v]
    return paginate(items, ser_order)


@route("/orders/<oid>/lines", ["POST"], ["Customer"])
def add_order_line(oid):
    order = get_or_404(orders, oid)
    check_customer_owner(order["customer_id"])
    b = body_json()
    product_id = req_str(b, "product_id")
    quantity = req_int(b, "quantity")
    bundle_id = b.get("bundle_id")
    if bundle_id is not None and not isinstance(bundle_id, str):
        verr("Invalid bundle_id")
    # existence
    product = get_or_404(products, product_id)
    bundle = None
    if bundle_id is not None:
        bundle = get_or_404(bundles, bundle_id)
    # state
    if order["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Order not DRAFT")
    # business: bundle mismatch (priority 10) then quantity (priority 11)
    if bundle is not None and product_id not in bundle["component_product_ids"]:
        raise ApiError("ERR_BUNDLE_PRODUCT_MISMATCH", 422, "Product not a bundle component")
    if quantity < 1:
        raise ApiError("ERR_INVALID_QUANTITY", 422, "quantity must be >= 1")
    obj = new_entity(order_lines, {
        "order_id": oid,
        "product_id": product_id,
        "bundle_id": bundle_id,
        "quantity": quantity,
        "gross_unit_price_cents": product["unit_price_cents"],
        "net_unit_price_cents": None,
        "line_total_cents": None,
        "lot_allocations": [],
        "short_quantity": 0,
    })
    return success(ser_order_line(obj), status=201)


@route("/orders/<oid>/lines", ["GET"], GET_ALL)
def list_order_lines(oid):
    get_or_404(orders, oid)
    items = [l for l in order_lines.values() if l["order_id"] == oid]
    return paginate(items, ser_order_line)


@route("/order-lines/<lid>", ["GET"], GET_ALL)
def get_order_line(lid):
    return success(ser_order_line(get_or_404(order_lines, lid)))


@route("/order-lines", ["GET"], GET_ALL)
def list_all_order_lines():
    items = list(order_lines.values())
    for key in ("product_id", "bundle_id"):
        v = request.args.get(key)
        if v:
            items = [l for l in items if l.get(key) == v]
    return paginate(items, ser_order_line)


def sellable_lots_for(product_id):
    cn = clock_now()
    result = [l for l in lots.values()
              if l["product_id"] == product_id
              and l["status"] == "AVAILABLE"
              and l["expiration_date"] > cn]
    result.sort(key=lambda l: (l["expiration_date"], l["_seq"]))
    return result


def has_blocking_lot(product_id):
    cn = clock_now()
    for l in lots.values():
        if l["product_id"] != product_id:
            continue
        if not (l["status"] == "AVAILABLE" and l["expiration_date"] > cn):
            return True
    return False


def find_backing_recommendation(customer_id, product_id, need_qty, exclude_capacity=True):
    cn = clock_now()
    candidates = []
    for r in recommendations.values():
        if (r["customer_id"] == customer_id and r["product_id"] == product_id
                and r["status"] == "ISSUED" and r["expires_at"] > cn):
            if not exclude_capacity or (r["consumed_units"] + need_qty <= r["max_units"]):
                candidates.append(r)
    candidates.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return candidates[0] if candidates else None


@route("/orders/<oid>/place", ["POST"], ["Customer"])
def place_order(oid):
    order = get_or_404(orders, oid)
    check_customer_owner(order["customer_id"])
    if order["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Order not DRAFT")

    lines = sorted([l for l in order_lines.values() if l["order_id"] == oid],
                   key=lambda l: (l["created_at"], l["_seq"]))
    cust = customers.get(order["customer_id"])

    # --- Business rules in PRD 3.6 order ---
    # 1. Practitioner authorization
    backing = {}
    for line in lines:
        product = products.get(line["product_id"])
        if product and product["is_practitioner_line"]:
            rec = find_backing_recommendation(order["customer_id"], line["product_id"], line["quantity"])
            if rec is None:
                raise ApiError("ERR_PRACTITIONER_AUTH_REQUIRED", 403,
                               "Practitioner authorization required")
            backing[line["id"]] = rec["id"]

    # Simulate FEFO allocation across all lines (shared availability per lot)
    working = {}
    for line in lines:
        for lot in sellable_lots_for(line["product_id"]):
            working.setdefault(lot["id"], lot["quantity_on_hand"] - lot["quantity_reserved"])
    plan = {}
    uncoverable = set()
    for line in lines:
        remaining = line["quantity"]
        allocs = []
        for lot in sellable_lots_for(line["product_id"]):
            avail = working.get(lot["id"], 0)
            take = min(remaining, avail)
            if take > 0:
                allocs.append((lot["id"], take))
                working[lot["id"]] = avail - take
                remaining -= take
            if remaining == 0:
                break
        if remaining > 0:
            uncoverable.add(line["id"])
        else:
            plan[line["id"]] = allocs

    # 2. Lot sellable (a blocking non-sellable lot prevents covering a line)
    for line in lines:
        if line["id"] in uncoverable and has_blocking_lot(line["product_id"]):
            raise ApiError("ERR_LOT_NOT_SELLABLE", 409, "No sellable lot can serve the line")

    # 3. Customer suspended
    if cust is not None and cust["status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_SUSPENDED", 409, "Customer is suspended")

    # 4. Empty order
    if not lines:
        raise ApiError("ERR_INVALID_QUANTITY", 422, "Order has no lines")

    # 5. Insufficient inventory
    if uncoverable:
        raise ApiError("ERR_INSUFFICIENT_INVENTORY", 409, "Insufficient inventory")

    # Pricing (per line)
    tier = cust["loyalty_tier"] if cust else "BRONZE"
    if order["order_type"] == "AUTOSHIP":
        sub = subscriptions.get(order["subscription_id"])
        purchase_pct = sub["autoship_discount_pct"] if sub else 0.0
    else:
        purchase_pct = LOYALTY_PURCHASE_DISCOUNT[tier]
    priced = {}
    provisional_subtotal = 0
    for line in lines:
        bundle_pct = 0.0
        if line["bundle_id"]:
            bundle = bundles.get(line["bundle_id"])
            if bundle and line["product_id"] in bundle["component_product_ids"]:
                bundle_pct = bundle["discount_pct"]
        net = compute_net_unit(line["gross_unit_price_cents"], bundle_pct, purchase_pct)
        line_total = net * line["quantity"]
        priced[line["id"]] = (net, line_total)
        provisional_subtotal += line_total

    # 6. Points affordability
    points_redeemed = order["points_redeemed"]
    redemption_cents = points_redeemed * POINT_REDEMPTION_VALUE_CENTS
    bal = cust["points_balance"] if cust else 0
    if points_redeemed > bal or redemption_cents > provisional_subtotal:
        raise ApiError("ERR_INSUFFICIENT_POINTS", 409, "Insufficient or excessive points redemption")

    # --- Commit ---
    for line in lines:
        for (lot_id, qty) in plan[line["id"]]:
            line["lot_allocations"].append({"lot_id": lot_id, "quantity": qty, "status": "RESERVED"})
            lot = lots[lot_id]
            lot["quantity_reserved"] += qty
            touch(lot)
        net, line_total = priced[line["id"]]
        line["net_unit_price_cents"] = net
        line["line_total_cents"] = line_total
        if line["id"] in backing:
            line["_recommendation_id"] = backing[line["id"]]
        touch(line)

    order["provisional_subtotal_cents"] = provisional_subtotal
    order["redemption_cents"] = redemption_cents
    order["total_cents"] = provisional_subtotal - redemption_cents
    order["points_earned"] = compute_points(provisional_subtotal, tier,
                                             order["order_type"] == "AUTOSHIP")
    order["status"] = "PLACED"
    touch(order)

    if points_redeemed > 0 and cust is not None:
        cust["points_balance"] -= points_redeemed
        touch(cust)

    return success(ser_order(order))


@route("/orders/<oid>/fulfill", ["POST"], ["StoreOperator"])
def fulfill_order(oid):
    order = get_or_404(orders, oid)
    if order["status"] != "PLACED":
        raise ApiError("ERR_INVALID_STATE", 409, "Order not PLACED")
    lines = [l for l in order_lines.values() if l["order_id"] == oid]

    # consume reserved allocations
    for line in lines:
        changed = False
        for alloc in line["lot_allocations"]:
            if alloc["status"] == "RESERVED":
                alloc["status"] = "CONSUMED"
                lot = lots.get(alloc["lot_id"])
                if lot:
                    lot["quantity_on_hand"] -= alloc["quantity"]
                    lot["quantity_reserved"] -= alloc["quantity"]
                    touch(lot)
                changed = True
        if changed:
            touch(line)

    # final subtotal
    final_subtotal = sum(l["net_unit_price_cents"] * (l["quantity"] - l["short_quantity"])
                         for l in lines)
    order["final_subtotal_cents"] = final_subtotal
    order["total_cents"] = final_subtotal - order["redemption_cents"]

    # settle points
    cust = customers.get(order["customer_id"])
    tier = cust["loyalty_tier"] if cust else "BRONZE"
    earned = compute_points(final_subtotal, tier, order["order_type"] == "AUTOSHIP")
    order["points_earned"] = earned
    if cust is not None and earned > 0:
        cust["points_balance"] += earned
        cust["lifetime_points_earned"] += earned
        cust["loyalty_tier"] = tier_for(cust["lifetime_points_earned"])
        touch(cust)

    # recommendation consumption
    for line in lines:
        product = products.get(line["product_id"])
        if product and product["is_practitioner_line"]:
            eff_qty = line["quantity"] - line["short_quantity"]
            if eff_qty <= 0:
                continue
            rec = None
            rid = line.get("_recommendation_id")
            if rid and rid in recommendations and recommendations[rid]["status"] == "ISSUED":
                rec = recommendations[rid]
            if rec is None:
                rec = find_backing_recommendation(order["customer_id"], line["product_id"], eff_qty)
            if rec is not None:
                rec["consumed_units"] += eff_qty
                if rec["consumed_units"] >= rec["max_units"]:
                    rec["status"] = "EXHAUSTED"
                touch(rec)

    order["status"] = "FULFILLED"
    touch(order)
    return success(ser_order(order))


@route("/orders/<oid>/cancel", ["POST"], ["Customer", "StoreOperator"])
def cancel_order(oid):
    order = get_or_404(orders, oid)
    if g.role == "Customer":
        check_customer_owner(order["customer_id"])
    if order["status"] not in ("DRAFT", "PLACED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Order cannot be cancelled")
    if order["status"] == "PLACED":
        release_placed_allocations(order)
        cust = customers.get(order["customer_id"])
        if order["points_redeemed"] > 0 and cust is not None:
            cust["points_balance"] += order["points_redeemed"]
            touch(cust)
    order["status"] = "CANCELLED"
    touch(order)
    return success(ser_order(order))


# ===========================================================================
# Return
# ===========================================================================
@route("/returns", ["POST"], ["Customer"])
def create_return():
    b = body_json()
    order_id = req_str(b, "order_id")
    order_line_id = req_str(b, "order_line_id")
    quantity = req_int(b, "quantity")
    reason = b.get("reason")
    if reason not in RETURN_REASONS:
        verr("Invalid reason")
    # existence + ownership (left-to-right)
    order = get_or_404(orders, order_id)
    check_customer_owner(order["customer_id"])
    line = get_or_404(order_lines, order_line_id)
    if line["order_id"] != order_id:
        raise ApiError("ERR_NOT_FOUND", 404, "Order line does not belong to order")
    # state: only fulfilled orders can be returned against
    if order["status"] != "FULFILLED":
        raise ApiError("ERR_INVALID_STATE", 409, "Order is not FULFILLED")
    # quantity checks
    if quantity < 1:
        raise ApiError("ERR_INVALID_QUANTITY", 422, "quantity must be >= 1")
    fulfilled_qty = line["quantity"] - line["short_quantity"]
    if quantity > fulfilled_qty:
        raise ApiError("ERR_RETURN_QUANTITY_EXCEEDS", 422,
                       "Return quantity exceeds fulfilled quantity")
    obj = new_entity(returns, {
        "order_id": order_id,
        "order_line_id": order_line_id,
        "quantity": quantity,
        "reason": reason,
        "status": "REQUESTED",
        "refund_cents": None,
        "points_reversed": None,
        "restock": None,
    })
    return success(ser_return(obj), status=201)


@route("/returns/<rid>", ["GET"], GET_ALL)
def get_return(rid):
    return success(ser_return(get_or_404(returns, rid)))


@route("/returns", ["GET"], GET_ALL)
def list_returns():
    items = list(returns.values())
    for key in ("order_id", "order_line_id", "status"):
        v = request.args.get(key)
        if v:
            items = [r for r in items if r[key] == v]
    return paginate(items, ser_return)


@route("/returns/<rid>/state", ["POST"], ["StoreOperator"])
def return_state(rid):
    ret = get_or_404(returns, rid)
    b = body_json()
    to_status = b.get("to_status")
    if to_status not in {"APPROVED", "REJECTED", "REFUNDED"}:
        verr("Invalid to_status")
    cur = ret["status"]
    if to_status == "APPROVED":
        if cur != "REQUESTED":
            raise ApiError("ERR_INVALID_STATE", 409, "Return not REQUESTED")
        ret["status"] = "APPROVED"
    elif to_status == "REJECTED":
        if cur != "REQUESTED":
            raise ApiError("ERR_INVALID_STATE", 409, "Return not REQUESTED")
        ret["status"] = "REJECTED"
    else:  # REFUNDED
        if cur != "APPROVED":
            raise ApiError("ERR_INVALID_STATE", 409, "Return not APPROVED")
        _process_refund(ret)
        ret["status"] = "REFUNDED"
    touch(ret)
    return success(ser_return(ret))


def _process_refund(ret):
    line = order_lines.get(ret["order_line_id"])
    order = orders.get(ret["order_id"])
    gross_refund = line["net_unit_price_cents"] * ret["quantity"]
    # points attributable to returned merchandise (proportional to settled points)
    final_subtotal = order["final_subtotal_cents"] or 0
    if final_subtotal > 0:
        points_reversed = (order["points_earned"] * gross_refund) // final_subtotal
    else:
        points_reversed = 0

    # source lot = the lot of the line's first allocation
    source_lot = None
    if line["lot_allocations"]:
        source_lot = lots.get(line["lot_allocations"][0]["lot_id"])

    if ret["reason"] in ("DEFECT", "RECALL", "EXPIRED"):
        refund_cents = gross_refund
        restock = False
    else:  # UNWANTED
        refund_cents = round_half_up(Decimal(gross_refund) * (Decimal(1) - Decimal(str(RESTOCK_FEE_PCT))))
        restock = source_lot is not None and source_lot["status"] == "AVAILABLE"

    ret["refund_cents"] = refund_cents
    ret["points_reversed"] = points_reversed
    ret["restock"] = restock

    cust = customers.get(order["customer_id"])
    if cust is not None:
        cust["points_balance"] -= points_reversed
        touch(cust)
    if restock and source_lot is not None and source_lot["status"] == "AVAILABLE":
        source_lot["quantity_on_hand"] += ret["quantity"]
        touch(source_lot)


# ===========================================================================
# Test-driving endpoints (/_ namespace)
# ===========================================================================
@route("/_clock/set_current_utc", ["POST"], ["StoreOperator"])
def set_clock():
    global _clock
    b = body_json()
    try:
        _clock = parse_iso(b.get("to_iso8601"))
    except (ValueError, TypeError):
        verr("Invalid to_iso8601")
    return success({})


@route("/_jobs/run-expiry-sweep", ["POST"], ["StoreOperator"])
def run_expiry_sweep():
    cn = clock_now()
    for lot in lots.values():
        if lot["status"] in ("AVAILABLE", "QUARANTINED") and lot["expiration_date"] <= cn:
            lot["status"] = "EXPIRED"
            touch(lot)
    for rec in recommendations.values():
        if rec["status"] == "ISSUED" and rec["expires_at"] <= cn:
            rec["status"] = "EXPIRED"
            touch(rec)
    return success({})


@route("/_inject/loyalty_state", ["POST"], ["StoreOperator"])
def inject_loyalty_state():
    b = body_json()
    customer_id = req_str(b, "customer_id")
    cust = get_or_404(customers, customer_id)
    if "lifetime_points_earned" in b and b.get("lifetime_points_earned") is not None:
        v = b.get("lifetime_points_earned")
        if isinstance(v, bool) or not isinstance(v, int):
            verr("Invalid lifetime_points_earned")
        cust["lifetime_points_earned"] = v
    if "points_balance" in b and b.get("points_balance") is not None:
        v = b.get("points_balance")
        if isinstance(v, bool) or not isinstance(v, int):
            verr("Invalid points_balance")
        cust["points_balance"] = v
    cust["loyalty_tier"] = tier_for(cust["lifetime_points_earned"])
    touch(cust)
    return success(ser_customer(cust))


# ===========================================================================
# Health
# ===========================================================================
@app.route("/", methods=["GET"])
def health():
    return success({})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
