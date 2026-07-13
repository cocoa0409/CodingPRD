"""Resume Career Coaching API — Python + Flask reference implementation.

In-memory only. Storage starts empty on every boot; every entity is created
through the declared API surface. See workspace/PRD.md and SCAFFOLD.yaml.
"""
import os
import re
import uuid
import random
import string
import itertools
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"Client", "Coach", "CareerAdmin"}

ADDON_PRICES = {
    "EXTRA_REVISION": 4000,
    "EXTRA_COACHING": 12000,
    "EXTRA_DELIVERABLE": 9000,
    "INTERVIEW_PREP": 15000,
    "RUSH": 0,
}
SESSION_PRICES = {"COACHING": 12000, "INTERVIEW_PREP": 15000}
ADDON_TYPES = set(ADDON_PRICES.keys())

DELIVERABLE_TYPES = {"RESUME", "LINKEDIN", "COVER_LETTER"}
PLAN_TIERS = {"BASIC", "PRO", "EXECUTIVE"}
COACH_SPECIALTIES = {"TECH", "FINANCE", "GENERAL", "EXECUTIVE"}
GUARANTEE_TYPES = {"NONE", "SATISFACTION", "INTERVIEW"}
ACCOUNT_STATUS = {"ACTIVE", "INACTIVE"}
SESSION_TYPES = {"COACHING", "INTERVIEW_PREP"}
CLAIM_TYPES = {"SATISFACTION", "INTERVIEW"}
COUPONS = {"WELCOME10", "SAVE50"}

ADDON_VOLUME_DISCOUNT_PCT = Decimal("0.10")
COUPON_WELCOME10_PCT = Decimal("0.10")
COUPON_SAVE50_FLAT = 5000

DEFAULT_CLOCK = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# In-memory store (empty on every boot)
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.clients = {}
        self.coaches = {}
        self.plans = {}
        self.orders = {}
        self.deliverables = {}
        self.revisions = {}
        self.sessions = {}
        self.addons = {}
        self.payments = {}
        self.claims = {}
        self.ats_scans = {}
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)

    def seq(self):
        return next(self._seq)


db = Store()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


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
        "data": {"error_id": "ERR_ORDER_NOT_FOUND", "message": "Not found."},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def _handle_405(_e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": "Method not allowed."},
    }
    return jsonify(body), 405


# ---------------------------------------------------------------------------
# Time / id helpers
# ---------------------------------------------------------------------------
def wall_now():
    return datetime.now(timezone.utc)


def iso3(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def new_id():
    return str(uuid.uuid4())


def request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(pagination=None):
    m = {"api_request_id": request_id(), "api_request_timestamp": iso3(wall_now())}
    if pagination:
        m.update(pagination)
    return m


def rhu(value):
    """round-half-up to nearest integer; accepts Decimal/int."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------
def ok(data, response_type="object", status=200, pagination=None):
    body = {"meta": _meta(pagination), "response_type": response_type, "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(items)) < total,
    }
    return ok(items, "array", 200, pagination)


# ---------------------------------------------------------------------------
# Entity lifecycle helpers
# ---------------------------------------------------------------------------
def base_entity():
    now = wall_now()
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.seq(),
    }


def light_entity():
    return {"id": new_id(), "created_at": wall_now(), "_seq": db.seq()}


def touch(entity):
    entity["updated_at"] = wall_now()
    entity["version"] = entity.get("version", 1) + 1


def serialize(entity):
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = iso3(v)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Auth / validation helpers
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers.")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this endpoint.")


def get_body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", 422, "Request body must be a JSON object.")
    return data


def verr(msg="Invalid request body."):
    raise ApiError("ERR_VALIDATION", 422, msg)


def require(data, field):
    if field not in data or data[field] is None:
        verr(f"Missing required field: {field}.")
    return data[field]


def require_str(data, field):
    v = require(data, field)
    if not isinstance(v, str) or v == "":
        verr(f"Field {field} must be a non-empty string.")
    return v


def require_int(data, field, minimum=None):
    v = require(data, field)
    if isinstance(v, bool) or not isinstance(v, int):
        verr(f"Field {field} must be an integer.")
    if minimum is not None and v < minimum:
        verr(f"Field {field} must be >= {minimum}.")
    return v


def optional_int(data, field, default, minimum=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if isinstance(v, bool) or not isinstance(v, int):
        verr(f"Field {field} must be an integer.")
    if minimum is not None and v < minimum:
        verr(f"Field {field} must be >= {minimum}.")
    return v


def require_enum(data, field, allowed):
    v = require(data, field)
    if v not in allowed:
        verr(f"Field {field} must be one of {sorted(allowed)}.")
    return v


def optional_enum(data, field, allowed, default):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if v not in allowed:
        verr(f"Field {field} must be one of {sorted(allowed)}.")
    return v


def optional_bool(data, field, default):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, bool):
        verr(f"Field {field} must be a boolean.")
    return v


def optional_number(data, field, default, minimum=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        verr(f"Field {field} must be a number.")
    if minimum is not None and v < minimum:
        verr(f"Field {field} must be >= {minimum}.")
    return v


def paginate(items):
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    ordered = sorted(items, key=lambda e: e["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total


# ---------------------------------------------------------------------------
# Existence helpers
# ---------------------------------------------------------------------------
def get_or_404(coll, ident, error_id):
    ent = coll.get(ident)
    if ent is None:
        raise ApiError(error_id, 404, "Referenced resource does not exist.")
    return ent


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def ser_client(c):
    return serialize(c)


def ser_coach(c):
    return serialize(c)


def ser_plan(p):
    return serialize(p)  # light: no updated_at/version stored


def ser_payment(p):
    return serialize(p)  # light


def ser_ats(a):
    return serialize(a)  # light


def ser_deliverable(d):
    return serialize(d)


def ser_revision(r):
    return serialize(r)


def ser_session(s):
    out = serialize(s)
    return out


def ser_addon(a):
    return serialize(a)


def ser_claim(c):
    return serialize(c)


def ser_order(o):
    out = serialize(o)
    out["net_collected_cents"] = o["amount_charged_cents"] - o["amount_refunded_cents"]
    out["revision_credits_remaining"] = max(
        0,
        o["revision_credits_included"] + o["revision_credits_purchased"] - o["revision_credits_used"],
    )
    return out


# ---------------------------------------------------------------------------
# Pricing / calculation
# ---------------------------------------------------------------------------
def compute_quote(base_price, addons, coupon_code, rush, rush_pct):
    addons_subtotal = sum(a["price_cents"] for a in addons)
    addon_count = len(addons)
    subtotal_before = base_price + addons_subtotal

    if addon_count >= 3:
        addon_discount = rhu(Decimal(addons_subtotal) * ADDON_VOLUME_DISCOUNT_PCT)
    else:
        addon_discount = 0

    if coupon_code == "WELCOME10":
        coupon_discount = rhu(Decimal(base_price) * COUPON_WELCOME10_PCT)
    elif coupon_code == "SAVE50":
        coupon_discount = min(COUPON_SAVE50_FLAT, subtotal_before)
    else:
        coupon_discount = 0

    discount = addon_discount + coupon_discount
    discounted = max(0, subtotal_before - discount)

    if rush:
        rush_surcharge = rhu(Decimal(discounted) * Decimal(str(rush_pct)))
    else:
        rush_surcharge = 0

    total = discounted + rush_surcharge
    return {
        "addons_subtotal_cents": addons_subtotal,
        "discount_cents": discount,
        "rush_surcharge_cents": rush_surcharge,
        "total_cents": total,
    }


def order_intake_addons(order):
    return [a for a in db.addons.values()
            if a["order_id"] == order["id"] and not a["auto_generated"]
            and a.get("_intake", False)]


def order_final_addons(order):
    return [a for a in db.addons.values()
            if a["order_id"] == order["id"] and a["status"] != "CANCELLED"]


# ---------------------------------------------------------------------------
# Ledger helper
# ---------------------------------------------------------------------------
def record_payment(order, ptype, amount, reason):
    p = light_entity()
    p.update({
        "order_id": order["id"],
        "type": ptype,
        "amount_cents": amount,
        "reason": reason,
    })
    db.payments[p["id"]] = p
    if ptype == "CHARGE":
        order["amount_charged_cents"] += amount
    else:
        order["amount_refunded_cents"] += amount
    return p


def charge_addon(order, addon, reason):
    """Move an addon PENDING -> CHARGED and write a CHARGE payment."""
    addon["status"] = "CHARGED"
    touch(addon)
    record_payment(order, "CHARGE", addon["price_cents"], reason)


# ===========================================================================
# Routes: catalogue / actors
# ===========================================================================
@app.route("/package-plans", methods=["POST"])
def create_plan():
    _, role = authenticate()
    authorize(role, {"CareerAdmin"})
    data = get_body()
    tier = require_enum(data, "tier", PLAN_TIERS)
    base_price = require_int(data, "base_price_cents", minimum=0)
    included = require(data, "included_deliverables")
    if not isinstance(included, list) or not included or any(x not in DELIVERABLE_TYPES for x in included):
        verr("included_deliverables must be a non-empty subset of RESUME/LINKEDIN/COVER_LETTER.")
    inc_rev = require_int(data, "included_revision_rounds", minimum=0)
    inc_sess = require_int(data, "included_coaching_sessions", minimum=0)
    inc_prep = optional_bool(data, "includes_interview_prep", False)
    inc_ats = optional_bool(data, "includes_ats", False)
    guarantee = optional_enum(data, "guarantee_type", GUARANTEE_TYPES, "NONE")
    rush_pct = optional_number(data, "rush_surcharge_pct", 0.30, minimum=0)

    p = light_entity()
    p.update({
        "tier": tier,
        "base_price_cents": base_price,
        "included_deliverables": list(included),
        "included_revision_rounds": inc_rev,
        "included_coaching_sessions": inc_sess,
        "includes_interview_prep": inc_prep,
        "includes_ats": inc_ats,
        "guarantee_type": guarantee,
        "rush_surcharge_pct": rush_pct,
    })
    db.plans[p["id"]] = p
    return ok(ser_plan(p), "object", 201)


@app.route("/package-plans/<pid>", methods=["GET"])
def get_plan(pid):
    _, role = authenticate()
    authorize(role, ROLES)
    p = get_or_404(db.plans, pid, "ERR_PLAN_NOT_FOUND")
    return ok(ser_plan(p))


@app.route("/package-plans", methods=["GET"])
def list_plans():
    _, role = authenticate()
    authorize(role, ROLES)
    items = list(db.plans.values())
    tier = request.args.get("tier")
    if tier is not None:
        items = [p for p in items if p["tier"] == tier]
    page, limit, offset, total = paginate(items)
    return ok_list([ser_plan(p) for p in page], limit, offset, total)


@app.route("/clients", methods=["POST"])
def create_client():
    _, role = authenticate()
    authorize(role, {"CareerAdmin"})
    data = get_body()
    name = require_str(data, "name")
    email = require_str(data, "email")
    status = optional_enum(data, "status", ACCOUNT_STATUS, "ACTIVE")
    c = base_entity()
    c.update({"name": name, "email": email, "status": status})
    db.clients[c["id"]] = c
    return ok(ser_client(c), "object", 201)


@app.route("/clients/<cid>", methods=["GET"])
def get_client(cid):
    _, role = authenticate()
    authorize(role, ROLES)
    c = get_or_404(db.clients, cid, "ERR_CLIENT_NOT_FOUND")
    return ok(ser_client(c))


@app.route("/coaches", methods=["POST"])
def create_coach():
    _, role = authenticate()
    authorize(role, {"CareerAdmin"})
    data = get_body()
    name = require_str(data, "name")
    email = require_str(data, "email")
    specialty = require_enum(data, "specialty", COACH_SPECIALTIES)
    buffer_minutes = optional_int(data, "buffer_minutes", 15, minimum=0)
    status = optional_enum(data, "status", ACCOUNT_STATUS, "ACTIVE")
    c = base_entity()
    c.update({
        "name": name,
        "email": email,
        "specialty": specialty,
        "buffer_minutes": buffer_minutes,
        "status": status,
    })
    db.coaches[c["id"]] = c
    return ok(ser_coach(c), "object", 201)


@app.route("/coaches/<cid>", methods=["GET"])
def get_coach(cid):
    _, role = authenticate()
    authorize(role, ROLES)
    c = get_or_404(db.coaches, cid, "ERR_COACH_NOT_FOUND")
    return ok(ser_coach(c))


@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authenticate()
    authorize(role, {"CareerAdmin"})
    data = get_body()
    to_iso = require(data, "to_iso8601")
    dt = parse_iso(to_iso)
    if dt is None:
        verr("to_iso8601 must be a valid ISO 8601 timestamp.")
    db.clock = dt
    return ok({}, "object", 200)


# ===========================================================================
# Routes: orders
# ===========================================================================
@app.route("/orders", methods=["POST"])
def create_order():
    uid, role = authenticate()
    authorize(role, {"Client"})
    data = get_body()
    plan_id = require_str(data, "plan_id")
    target_role = require_str(data, "target_role")
    target_industry = require_str(data, "target_industry")
    requested_delivery_days = require_int(data, "requested_delivery_days", minimum=1)
    rush = optional_bool(data, "rush", False)
    coupon = data.get("coupon_code")
    if coupon is not None and coupon not in COUPONS:
        verr("coupon_code must be WELCOME10, SAVE50 or null.")
    addon_types = data.get("addon_types")
    if addon_types is None:
        addon_types = []
    if not isinstance(addon_types, list) or any(t not in ADDON_TYPES for t in addon_types):
        verr("addon_types must be a list of valid add-on types.")

    plan = get_or_404(db.plans, plan_id, "ERR_PLAN_NOT_FOUND")

    # Only ACTIVE clients may create orders.
    client = db.clients.get(uid)
    if client is not None and client["status"] != "ACTIVE":
        verr("Only ACTIVE clients may create orders.")

    o = base_entity()
    sessions_included = plan["included_coaching_sessions"] + (1 if plan["includes_interview_prep"] else 0)
    o.update({
        "client_id": uid,
        "plan_id": plan_id,
        "target_role": target_role,
        "target_industry": target_industry,
        "rush": rush,
        "requested_delivery_days": requested_delivery_days,
        "coupon_code": coupon,
        "status": "INTAKE",
        "base_price_cents": plan["base_price_cents"],
        "addons_subtotal_cents": 0,
        "discount_cents": 0,
        "rush_surcharge_cents": 0,
        "provisional_total_cents": 0,
        "final_total_cents": None,
        "amount_charged_cents": 0,
        "amount_refunded_cents": 0,
        "revision_credits_included": plan["included_revision_rounds"],
        "revision_credits_purchased": 0,
        "revision_credits_used": 0,
        "sessions_included": sessions_included,
        "sessions_purchased": 0,
        "sessions_used": 0,
        "deliverables_total": 0,
        "deliverables_approved": 0,
        "guarantee_type": plan["guarantee_type"],
        "delivered_at": None,
        "deadline_at": None,
        "_rush_pct": plan["rush_surcharge_pct"],
    })
    db.orders[o["id"]] = o

    # Create one deliverable per included type.
    for dtype in plan["included_deliverables"]:
        _create_deliverable(o, dtype)

    # Intake add-ons: created PENDING, not individually charged (confirm covers
    # them), grants applied at intake.
    for t in addon_types:
        addon = base_entity()
        addon.update({
            "order_id": o["id"],
            "type": t,
            "price_cents": ADDON_PRICES[t],
            "status": "PENDING",
            "auto_generated": False,
            "source_ref": None,
            "_intake": True,
        })
        db.addons[addon["id"]] = addon
        _apply_addon_grant(o, addon)

    # Provisional quote over intake-time add-ons.
    quote = compute_quote(o["base_price_cents"], order_intake_addons(o), coupon, rush, o["_rush_pct"])
    o["addons_subtotal_cents"] = quote["addons_subtotal_cents"]
    o["discount_cents"] = quote["discount_cents"]
    o["rush_surcharge_cents"] = quote["rush_surcharge_cents"]
    o["provisional_total_cents"] = quote["total_cents"]

    return ok(ser_order(o), "object", 201)


def _create_deliverable(order, dtype):
    d = base_entity()
    d.update({
        "order_id": order["id"],
        "type": dtype,
        "status": "PENDING",
        "revision_round_count": 0,
        "draft_count": 0,
        "current_strict_ats_score": None,
        "current_semantic_ats_score": None,
    })
    db.deliverables[d["id"]] = d
    order["deliverables_total"] += 1
    return d


def _apply_addon_grant(order, addon):
    """Apply the credit/deliverable grant for a manual add-on."""
    t = addon["type"]
    if t == "EXTRA_REVISION":
        order["revision_credits_purchased"] += 1
    elif t in ("EXTRA_COACHING", "INTERVIEW_PREP"):
        order["sessions_purchased"] += 1
    elif t == "EXTRA_DELIVERABLE":
        _create_deliverable(order, "RESUME")
    # RUSH: no grant


@app.route("/orders/<oid>", methods=["GET"])
def get_order(oid):
    _, role = authenticate()
    authorize(role, ROLES)
    o = get_or_404(db.orders, oid, "ERR_ORDER_NOT_FOUND")
    return ok(ser_order(o))


@app.route("/orders", methods=["GET"])
def list_orders():
    _, role = authenticate()
    authorize(role, ROLES)
    items = list(db.orders.values())
    client_id = request.args.get("client_id")
    plan_id = request.args.get("plan_id")
    status = request.args.get("status")
    if client_id is not None:
        items = [o for o in items if o["client_id"] == client_id]
    if plan_id is not None:
        items = [o for o in items if o["plan_id"] == plan_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    page, limit, offset, total = paginate(items)
    return ok_list([ser_order(o) for o in page], limit, offset, total)


def _require_order_owner(order, uid):
    if order["client_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Client does not own this order.")


@app.route("/orders/<oid>/confirm", methods=["POST"])
def confirm_order(oid):
    uid, role = authenticate()
    authorize(role, {"Client"})
    o = get_or_404(db.orders, oid, "ERR_ORDER_NOT_FOUND")
    _require_order_owner(o, uid)
    if o["status"] != "INTAKE":
        raise ApiError("ERR_INVALID_STATE", 409, "Order is not in INTAKE.")
    # Charge the provisional quote up front.
    record_payment(o, "CHARGE", o["provisional_total_cents"], "CONFIRM")
    # Flip intake add-ons to CHARGED (covered by the single CONFIRM charge).
    for a in db.addons.values():
        if a["order_id"] == o["id"] and a.get("_intake") and a["status"] == "PENDING":
            a["status"] = "CHARGED"
            touch(a)
    o["deadline_at"] = db.clock + timedelta(days=o["requested_delivery_days"])
    o["status"] = "IN_PRODUCTION"
    touch(o)
    return ok(ser_order(o))


@app.route("/orders/<oid>/deliver", methods=["POST"])
def deliver_order(oid):
    _, role = authenticate()
    authorize(role, {"CareerAdmin"})
    o = get_or_404(db.orders, oid, "ERR_ORDER_NOT_FOUND")
    if o["status"] != "READY":
        raise ApiError("ERR_INVALID_STATE", 409, "Order is not READY.")
    quote = compute_quote(o["base_price_cents"], order_final_addons(o),
                          o["coupon_code"], o["rush"], o["_rush_pct"])
    o["addons_subtotal_cents"] = quote["addons_subtotal_cents"]
    o["discount_cents"] = quote["discount_cents"]
    o["rush_surcharge_cents"] = quote["rush_surcharge_cents"]
    o["final_total_cents"] = quote["total_cents"]
    o["delivered_at"] = db.clock
    o["status"] = "DELIVERED"
    touch(o)
    return ok(ser_order(o))


@app.route("/orders/<oid>/accept", methods=["POST"])
def accept_order(oid):
    uid, role = authenticate()
    authorize(role, {"Client"})
    o = get_or_404(db.orders, oid, "ERR_ORDER_NOT_FOUND")
    _require_order_owner(o, uid)
    if o["status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_STATE", 409, "Order is not DELIVERED.")
    o["status"] = "CLOSED"
    touch(o)
    return ok(ser_order(o))


@app.route("/orders/<oid>/deliverables", methods=["GET"])
def list_order_deliverables(oid):
    _, role = authenticate()
    authorize(role, ROLES)
    get_or_404(db.orders, oid, "ERR_ORDER_NOT_FOUND")
    items = [d for d in db.deliverables.values() if d["order_id"] == oid]
    page, limit, offset, total = paginate(items)
    return ok_list([ser_deliverable(d) for d in page], limit, offset, total)


@app.route("/orders/<oid>/addons", methods=["GET"])
def list_order_addons(oid):
    _, role = authenticate()
    authorize(role, ROLES)
    get_or_404(db.orders, oid, "ERR_ORDER_NOT_FOUND")
    items = [a for a in db.addons.values() if a["order_id"] == oid]
    page, limit, offset, total = paginate(items)
    return ok_list([ser_addon(a) for a in page], limit, offset, total)


@app.route("/orders/<oid>/payments", methods=["GET"])
def list_order_payments(oid):
    _, role = authenticate()
    authorize(role, ROLES)
    get_or_404(db.orders, oid, "ERR_ORDER_NOT_FOUND")
    items = [p for p in db.payments.values() if p["order_id"] == oid]
    page, limit, offset, total = paginate(items)
    return ok_list([ser_payment(p) for p in page], limit, offset, total)


@app.route("/orders/<oid>/guarantee-claims", methods=["GET"])
def list_order_claims(oid):
    _, role = authenticate()
    authorize(role, ROLES)
    get_or_404(db.orders, oid, "ERR_ORDER_NOT_FOUND")
    items = [c for c in db.claims.values() if c["order_id"] == oid]
    page, limit, offset, total = paginate(items)
    return ok_list([ser_claim(c) for c in page], limit, offset, total)


@app.route("/orders/<oid>/addons", methods=["POST"])
def purchase_addon(oid):
    uid, role = authenticate()
    authorize(role, {"Client"})
    data = get_body()
    atype = require_enum(data, "type", ADDON_TYPES)
    o = get_or_404(db.orders, oid, "ERR_ORDER_NOT_FOUND")
    _require_order_owner(o, uid)

    addon = base_entity()
    addon.update({
        "order_id": o["id"],
        "type": atype,
        "price_cents": ADDON_PRICES[atype],
        "status": "PENDING",
        "auto_generated": False,
        "source_ref": None,
        "_intake": False,
    })
    db.addons[addon["id"]] = addon
    # Charge synchronously, then apply grant.
    charge_addon(o, addon, "MANUAL_ADDON")
    _apply_addon_grant(o, addon)
    touch(o)
    return ok(ser_addon(addon), "object", 201)


@app.route("/orders/<oid>/sessions", methods=["POST"])
def book_session(oid):
    uid, role = authenticate()
    authorize(role, {"Client"})
    data = get_body()
    coach_id = require_str(data, "coach_id")
    session_type = require_enum(data, "session_type", SESSION_TYPES)
    start_raw = require_str(data, "scheduled_start")
    end_raw = require_str(data, "scheduled_end")
    start_dt = parse_iso(start_raw)
    end_dt = parse_iso(end_raw)
    if start_dt is None or end_dt is None:
        verr("scheduled_start/scheduled_end must be valid ISO 8601 timestamps.")
    if not end_dt > start_dt:
        verr("scheduled_end must be strictly after scheduled_start.")
    expected_version = require_int(data, "expected_order_version")

    # existence: order (path), coach (body)
    o = get_or_404(db.orders, oid, "ERR_ORDER_NOT_FOUND")
    coach = get_or_404(db.coaches, coach_id, "ERR_COACH_NOT_FOUND")

    # ownership
    _require_order_owner(o, uid)

    # state: order IN_PRODUCTION
    if o["status"] != "IN_PRODUCTION":
        raise ApiError("ERR_ORDER_NOT_IN_PRODUCTION", 409, "Order is not IN_PRODUCTION.")

    # cross-entity referential: coach active
    if coach["status"] != "ACTIVE":
        raise ApiError("ERR_COACH_INACTIVE", 409, "Coach is not ACTIVE.")

    # coach buffer-expanded overlap
    buffer = timedelta(minutes=coach["buffer_minutes"])
    for s in db.sessions.values():
        if s["coach_id"] == coach_id and s["status"] == "SCHEDULED":
            if start_dt < s["_end_dt"] + buffer and s["_start_dt"] - buffer < end_dt:
                raise ApiError("ERR_COACH_SLOT_CONFLICT", 409, "Coach slot conflict.")

    # client half-open overlap
    for s in db.sessions.values():
        if s["client_id"] == o["client_id"] and s["status"] == "SCHEDULED":
            if start_dt < s["_end_dt"] and s["_start_dt"] < end_dt:
                raise ApiError("ERR_CLIENT_SLOT_CONFLICT", 409, "Client slot conflict.")

    # OCC (last)
    if expected_version != o["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Order version is stale.")

    # session billing
    pool = o["sessions_included"] + o["sessions_purchased"]
    if o["sessions_used"] < pool:
        billable = False
        fee = 0
    else:
        billable = True
        fee = SESSION_PRICES[session_type]

    s = base_entity()
    s.update({
        "order_id": o["id"],
        "coach_id": coach_id,
        "client_id": o["client_id"],
        "session_type": session_type,
        "scheduled_start": start_raw,
        "scheduled_end": end_raw,
        "status": "SCHEDULED",
        "billable": billable,
        "fee_cents": fee,
        "_start_dt": start_dt,
        "_end_dt": end_dt,
    })
    db.sessions[s["id"]] = s

    if billable:
        addon = base_entity()
        addon.update({
            "order_id": o["id"],
            "type": "EXTRA_COACHING" if session_type == "COACHING" else "INTERVIEW_PREP",
            "price_cents": fee,
            "status": "PENDING",
            "auto_generated": True,
            "source_ref": s["id"],
            "_intake": False,
        })
        db.addons[addon["id"]] = addon
        charge_addon(o, addon, "SESSION_OVERAGE")

    o["sessions_used"] += 1
    touch(o)  # advances Order.version
    return ok(ser_session(s), "object", 201)


@app.route("/orders/<oid>/guarantee-claims", methods=["POST"])
def submit_claim(oid):
    uid, role = authenticate()
    authorize(role, {"Client"})
    data = get_body()
    claim_type = require_enum(data, "claim_type", CLAIM_TYPES)
    evidence = require_str(data, "evidence")
    o = get_or_404(db.orders, oid, "ERR_ORDER_NOT_FOUND")
    _require_order_owner(o, uid)

    # state: order DELIVERED or CLOSED
    if o["status"] not in ("DELIVERED", "CLOSED"):
        raise ApiError("ERR_ORDER_NOT_DELIVERED", 409, "Order is not DELIVERED or CLOSED.")

    # plan offers guarantee
    if o["guarantee_type"] == "NONE" or o["guarantee_type"] != claim_type:
        raise ApiError("ERR_GUARANTEE_NOT_OFFERED", 409, "Guarantee not offered by this order's plan.")

    # no open (SUBMITTED/APPROVED) claim already
    for c in db.claims.values():
        if c["order_id"] == o["id"] and c["status"] in ("SUBMITTED", "APPROVED"):
            raise ApiError("ERR_CLAIM_ALREADY_EXISTS", 409, "An open claim already exists.")

    # eligibility window
    elapsed = db.clock - o["delivered_at"]
    if claim_type == "SATISFACTION":
        if elapsed > timedelta(days=14):
            raise ApiError("ERR_CLAIM_NOT_ELIGIBLE", 409, "SATISFACTION window elapsed.")
    else:  # INTERVIEW
        completed_prep = sum(
            1 for s in db.sessions.values()
            if s["order_id"] == o["id"] and s["session_type"] == "INTERVIEW_PREP"
            and s["status"] == "COMPLETED"
        )
        if elapsed < timedelta(days=90) or completed_prep > 0:
            raise ApiError("ERR_CLAIM_NOT_ELIGIBLE", 409, "INTERVIEW claim not eligible.")

    c = base_entity()
    c.update({
        "order_id": o["id"],
        "claim_type": claim_type,
        "status": "SUBMITTED",
        "refund_amount_cents": 0,
        "evidence": evidence,
    })
    db.claims[c["id"]] = c
    return ok(ser_claim(c), "object", 201)


# ===========================================================================
# Routes: deliverables
# ===========================================================================
@app.route("/deliverables/<did>", methods=["GET"])
def get_deliverable(did):
    _, role = authenticate()
    authorize(role, ROLES)
    d = get_or_404(db.deliverables, did, "ERR_DELIVERABLE_NOT_FOUND")
    return ok(ser_deliverable(d))


@app.route("/deliverables/<did>/revisions", methods=["GET"])
def list_deliverable_revisions(did):
    _, role = authenticate()
    authorize(role, ROLES)
    get_or_404(db.deliverables, did, "ERR_DELIVERABLE_NOT_FOUND")
    items = [r for r in db.revisions.values() if r["deliverable_id"] == did]
    page, limit, offset, total = paginate(items)
    return ok_list([ser_revision(r) for r in page], limit, offset, total)


@app.route("/deliverables/<did>/ats-scans", methods=["GET"])
def list_deliverable_ats(did):
    _, role = authenticate()
    authorize(role, ROLES)
    get_or_404(db.deliverables, did, "ERR_DELIVERABLE_NOT_FOUND")
    items = [a for a in db.ats_scans.values() if a["deliverable_id"] == did]
    page, limit, offset, total = paginate(items)
    return ok_list([ser_ats(a) for a in page], limit, offset, total)


@app.route("/deliverables/<did>/drafts", methods=["POST"])
def upload_draft(did):
    _, role = authenticate()
    authorize(role, {"Coach"})
    get_body()  # notes optional; tolerate empty body
    d = get_or_404(db.deliverables, did, "ERR_DELIVERABLE_NOT_FOUND")
    o = db.orders[d["order_id"]]
    # deliverable must be in a draftable state
    if d["status"] not in ("PENDING", "IN_REVISION"):
        raise ApiError("ERR_INVALID_STATE", 409, "Deliverable is not in a draftable state.")
    if o["status"] != "IN_PRODUCTION":
        raise ApiError("ERR_ORDER_NOT_IN_PRODUCTION", 409, "Parent order is not IN_PRODUCTION.")

    if d["status"] == "IN_REVISION":
        # close the open revision round with the highest round_no
        open_reqs = [r for r in db.revisions.values()
                     if r["deliverable_id"] == did and r["status"] == "OPEN"]
        if open_reqs:
            top = max(open_reqs, key=lambda r: r["round_no"])
            top["status"] = "ADDRESSED"
            touch(top)
    d["draft_count"] += 1
    d["status"] = "DRAFTED"
    touch(d)
    return ok(ser_deliverable(d))


@app.route("/deliverables/<did>/revisions", methods=["POST"])
def open_revision(did):
    uid, role = authenticate()
    authorize(role, {"Client"})
    data = get_body()
    reason = require_str(data, "reason")
    d = get_or_404(db.deliverables, did, "ERR_DELIVERABLE_NOT_FOUND")
    o = db.orders[d["order_id"]]
    _require_order_owner(o, uid)
    if d["status"] != "DRAFTED":
        raise ApiError("ERR_DELIVERABLE_NOT_DRAFTED", 409, "Deliverable is not DRAFTED.")

    pool = o["revision_credits_included"] + o["revision_credits_purchased"]
    billable = o["revision_credits_used"] >= pool

    r = base_entity()
    r.update({
        "deliverable_id": d["id"],
        "round_no": d["revision_round_count"] + 1,
        "reason": reason,
        "billable": billable,
        "status": "OPEN",
    })
    db.revisions[r["id"]] = r

    d["revision_round_count"] += 1
    d["status"] = "IN_REVISION"
    touch(d)

    if billable:
        addon = base_entity()
        addon.update({
            "order_id": o["id"],
            "type": "EXTRA_REVISION",
            "price_cents": ADDON_PRICES["EXTRA_REVISION"],
            "status": "PENDING",
            "auto_generated": True,
            "source_ref": r["id"],
            "_intake": False,
        })
        db.addons[addon["id"]] = addon
        charge_addon(o, addon, "REVISION_OVERAGE")

    o["revision_credits_used"] += 1
    touch(o)
    return ok(ser_revision(r), "object", 201)


@app.route("/deliverables/<did>/approve", methods=["POST"])
def approve_deliverable(did):
    uid, role = authenticate()
    authorize(role, {"Client"})
    d = get_or_404(db.deliverables, did, "ERR_DELIVERABLE_NOT_FOUND")
    o = db.orders[d["order_id"]]
    _require_order_owner(o, uid)
    if d["status"] != "DRAFTED":
        raise ApiError("ERR_DELIVERABLE_NOT_DRAFTED", 409, "Deliverable is not DRAFTED.")

    d["status"] = "APPROVED"
    touch(d)
    o["deliverables_approved"] += 1
    if o["deliverables_approved"] == o["deliverables_total"] and o["status"] == "IN_PRODUCTION":
        o["status"] = "READY"
    touch(o)
    return ok(ser_deliverable(d))


@app.route("/deliverables/<did>/ats-scans", methods=["POST"])
def run_ats_scan(did):
    _, role = authenticate()
    authorize(role, {"Coach"})
    data = get_body()
    sections = require(data, "sections")
    if not isinstance(sections, list) or not sections:
        verr("sections must be a non-empty list.")
    for s in sections:
        if not isinstance(s, dict):
            verr("each section must be an object.")
        for f in ("name", "weight", "keywords_total", "matched_strict", "matched_semantic"):
            if f not in s or s[f] is None:
                verr(f"section missing field {f}.")
        if isinstance(s["keywords_total"], bool) or not isinstance(s["keywords_total"], (int, float)) or s["keywords_total"] <= 0:
            verr("keywords_total must be > 0.")
    d = get_or_404(db.deliverables, did, "ERR_DELIVERABLE_NOT_FOUND")

    total_weight = Decimal("0")
    strict_pcts = {}
    semantic_pcts = {}
    strict_weighted = Decimal("0")
    semantic_weighted = Decimal("0")
    coverage = {}
    for idx, s in enumerate(sections):
        w = Decimal(str(s["weight"]))
        total_weight += w
        strict_pct = rhu(Decimal(str(s["matched_strict"])) / Decimal(str(s["keywords_total"])) * 100)
        semantic_pct = rhu(Decimal(str(s["matched_semantic"])) / Decimal(str(s["keywords_total"])) * 100)
        strict_pcts[idx] = strict_pct
        semantic_pcts[idx] = semantic_pct
        strict_weighted += Decimal(strict_pct) * w
        semantic_weighted += Decimal(semantic_pct) * w
        coverage[s["name"]] = strict_pct

    if total_weight == 0:
        strict_score = 0
        semantic_score = 0
    else:
        strict_score = rhu(strict_weighted / total_weight)
        semantic_score = rhu(semantic_weighted / total_weight)

    a = light_entity()
    a.update({
        "deliverable_id": d["id"],
        "sections": sections,
        "strict_score": strict_score,
        "semantic_score": semantic_score,
        "coverage_by_section": coverage,
    })
    db.ats_scans[a["id"]] = a

    # refresh current scores (most recent by created_at == this scan)
    d["current_strict_ats_score"] = strict_score
    d["current_semantic_ats_score"] = semantic_score
    touch(d)
    return ok(ser_ats(a), "object", 201)


# ===========================================================================
# Routes: revisions
# ===========================================================================
@app.route("/revisions/<rid>/withdraw", methods=["POST"])
def withdraw_revision(rid):
    uid, role = authenticate()
    authorize(role, {"Client"})
    r = get_or_404(db.revisions, rid, "ERR_REVISION_NOT_FOUND")
    d = db.deliverables[r["deliverable_id"]]
    o = db.orders[d["order_id"]]
    _require_order_owner(o, uid)
    if r["status"] != "OPEN" or r["billable"]:
        raise ApiError("ERR_REVISION_NOT_WITHDRAWABLE", 409, "Revision is not OPEN or is billable.")

    r["status"] = "WITHDRAWN"
    touch(r)
    d["revision_round_count"] -= 1
    d["status"] = "DRAFTED"
    touch(d)
    o["revision_credits_used"] -= 1
    touch(o)
    return ok(ser_revision(r))


# ===========================================================================
# Routes: sessions
# ===========================================================================
@app.route("/sessions/<sid>", methods=["GET"])
def get_session(sid):
    _, role = authenticate()
    authorize(role, ROLES)
    s = get_or_404(db.sessions, sid, "ERR_SESSION_NOT_FOUND")
    return ok(ser_session(s))


@app.route("/sessions", methods=["GET"])
def list_sessions():
    _, role = authenticate()
    authorize(role, ROLES)
    items = list(db.sessions.values())
    for key in ("order_id", "coach_id", "client_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [s for s in items if s[key] == val]
    page, limit, offset, total = paginate(items)
    return ok_list([ser_session(s) for s in page], limit, offset, total)


@app.route("/sessions/<sid>/complete", methods=["POST"])
def complete_session(sid):
    uid, role = authenticate()
    authorize(role, {"Coach"})
    s = get_or_404(db.sessions, sid, "ERR_SESSION_NOT_FOUND")
    if s["coach_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Coach does not own this session.")
    if s["status"] != "SCHEDULED":
        raise ApiError("ERR_SESSION_NOT_SCHEDULED", 409, "Session is not SCHEDULED.")
    s["status"] = "COMPLETED"
    touch(s)
    return ok(ser_session(s))


@app.route("/sessions/<sid>/cancel", methods=["POST"])
def cancel_session(sid):
    uid, role = authenticate()
    authorize(role, {"Client", "CareerAdmin"})
    s = get_or_404(db.sessions, sid, "ERR_SESSION_NOT_FOUND")
    o = db.orders[s["order_id"]]
    if role == "Client" and s["client_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Client does not own this session.")
    if s["status"] != "SCHEDULED":
        raise ApiError("ERR_SESSION_NOT_SCHEDULED", 409, "Session is not SCHEDULED.")

    s["status"] = "CANCELLED"
    touch(s)
    o["sessions_used"] -= 1
    if s["billable"]:
        record_payment(o, "REFUND", s["fee_cents"], "SESSION_REFUND")
        for a in db.addons.values():
            if a.get("source_ref") == s["id"] and a["auto_generated"] and a["status"] == "CHARGED":
                a["status"] = "CANCELLED"
                touch(a)
    touch(o)
    return ok(ser_session(s))


@app.route("/sessions/<sid>/no-show", methods=["POST"])
def no_show_session(sid):
    uid, role = authenticate()
    authorize(role, {"Coach"})
    s = get_or_404(db.sessions, sid, "ERR_SESSION_NOT_FOUND")
    if s["coach_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Coach does not own this session.")
    if s["status"] != "SCHEDULED":
        raise ApiError("ERR_SESSION_NOT_SCHEDULED", 409, "Session is not SCHEDULED.")
    s["status"] = "NO_SHOW"
    touch(s)
    return ok(ser_session(s))


# ===========================================================================
# Routes: guarantee claims
# ===========================================================================
@app.route("/guarantee-claims/<cid>", methods=["GET"])
def get_claim(cid):
    _, role = authenticate()
    authorize(role, ROLES)
    c = get_or_404(db.claims, cid, "ERR_CLAIM_NOT_FOUND")
    return ok(ser_claim(c))


@app.route("/guarantee-claims/<cid>/approve", methods=["POST"])
def approve_claim(cid):
    _, role = authenticate()
    authorize(role, {"CareerAdmin"})
    c = get_or_404(db.claims, cid, "ERR_CLAIM_NOT_FOUND")
    if c["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Claim is not SUBMITTED.")
    o = db.orders[c["order_id"]]

    if c["claim_type"] == "SATISFACTION":
        refund = o["amount_charged_cents"] - o["amount_refunded_cents"]  # net_collected
    else:
        refund = o["base_price_cents"]
    c["refund_amount_cents"] = refund
    c["status"] = "APPROVED"
    touch(c)

    # Drive order into REFUNDED (guarantee refund cascade).
    record_payment(o, "REFUND", refund, "GUARANTEE_REFUND")
    # cancel every SCHEDULED session (no per-session refund here)
    for s in db.sessions.values():
        if s["order_id"] == o["id"] and s["status"] == "SCHEDULED":
            s["status"] = "CANCELLED"
            touch(s)
    # cancel every non-terminal deliverable
    for d in db.deliverables.values():
        if d["order_id"] == o["id"] and d["status"] in ("PENDING", "DRAFTED", "IN_REVISION"):
            d["status"] = "CANCELLED"
            touch(d)
    o["status"] = "REFUNDED"
    touch(o)
    return ok(ser_claim(c))


@app.route("/guarantee-claims/<cid>/reject", methods=["POST"])
def reject_claim(cid):
    _, role = authenticate()
    authorize(role, {"CareerAdmin"})
    c = get_or_404(db.claims, cid, "ERR_CLAIM_NOT_FOUND")
    if c["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Claim is not SUBMITTED.")
    c["status"] = "REJECTED"
    touch(c)
    return ok(ser_claim(c))


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
