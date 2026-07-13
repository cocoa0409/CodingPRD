import os
import re
import uuid
import random
import string
import itertools
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# ---------------------------------------------------------------------------
# In-memory data store (fresh on every boot; nothing is seeded)
# ---------------------------------------------------------------------------
DB = {
    "customers": {},
    "pros": {},
    "categories": {},
    "plans": {},
    "requests": {},
    "leads": {},
    "quotes": {},
    "bookings": {},
    "reviews": {},
    "disputes": {},
    "slots": {},
}

_seq = itertools.count(1)


def next_seq():
    return next(_seq)


# Logical clock: defaults to 2026-03-01T00:00:00Z, never the wall clock.
CLOCK = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)

ROLES = {"Customer", "Pro", "PlatformAdmin", "CustomerService"}

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_REFERENCE_MISMATCH": 409,
    "ERR_PRO_NOT_VERIFIED": 409,
    "ERR_NO_ELIGIBLE_PROS": 409,
    "ERR_INSUFFICIENT_CREDIT": 402,
    "ERR_REFUND_WINDOW_CLOSED": 409,
    "ERR_SLOT_OVERLAP": 409,
    "ERR_BOOKING_CONFLICT": 409,
    "ERR_DUPLICATE_REVIEW": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_VALIDATION_DECISION": 422,
    "ERR_SUBSCRIPTION_REQUIRED": 409,
    "ERR_DISPUTE_NOT_ALLOWED": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http = ERROR_STATUS.get(error_id, 400)
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def now_dt():
    return CLOCK


def iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}".format(dt.microsecond // 1000) + "Z"


def now_iso():
    return iso(CLOCK)


def parse_dt(value):
    if not isinstance(value, str) or not value:
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


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------
def rhu_cents(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu2(value):
    return float(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def new_id():
    return str(uuid.uuid4())


def req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def serialize(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def meta_block():
    return {"api_request_id": req_id(), "api_request_timestamp": now_iso()}


def success(data, code=200, response_type="object", pagination=None):
    meta = meta_block()
    if pagination:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), code


def obj(rec, code=200):
    return success(serialize(rec), code=code, response_type="object")


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": meta_block(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": meta_block(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found."},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": meta_block(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed."},
    }
    return jsonify(body), 404


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def require(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = request.headers.get("X-User-Role")
            uid = request.headers.get("X-User-ID")
            if not uid or role not in ROLES:
                raise ApiError("ERR_UNAUTHENTICATED", "Missing or invalid auth headers.")
            if role not in roles:
                raise ApiError("ERR_FORBIDDEN_ROLE", "Role not permitted for this operation.")
            g.uid = uid
            g.role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco


def body():
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


# ---------------------------------------------------------------------------
# Common record builders / mutation
# ---------------------------------------------------------------------------
def base_common():
    ts = now_iso()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1, "_seq": next_seq()}


def base_config():
    return {"id": new_id(), "created_at": now_iso(), "_seq": next_seq()}


def touch(rec):
    rec["updated_at"] = now_iso()
    rec["version"] += 1


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def bad(msg="Invalid request."):
    raise ApiError("ERR_INVALID_REQUEST", msg)


def req_str(b, key):
    v = b.get(key)
    if not isinstance(v, str) or v.strip() == "":
        bad("Field '%s' must be a non-empty string." % key)
    return v


def req_int(b, key, minimum=None):
    v = b.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        bad("Field '%s' must be an integer." % key)
    if minimum is not None and v < minimum:
        bad("Field '%s' must be >= %s." % (key, minimum))
    return v


def req_num(b, key, minimum=None, maximum=None):
    v = b.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        bad("Field '%s' must be a number." % key)
    if minimum is not None and v < minimum:
        bad("Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and v > maximum:
        bad("Field '%s' must be <= %s." % (key, maximum))
    return v


def unique_check(store, field, value):
    for rec in store.values():
        if rec.get(field) == value:
            bad("Field '%s' must be unique." % field)


# ---------------------------------------------------------------------------
# Pagination & listing
# ---------------------------------------------------------------------------
def paginate(items):
    items = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    data = [serialize(r) for r in page]
    return success(data, code=200, response_type="array", pagination=pagination)


def arg_filter(items, mapping):
    """mapping: query_param -> function(rec) -> comparable string, or field name."""
    out = items
    for param, accessor in mapping.items():
        val = request.args.get(param)
        if val is None:
            continue
        if callable(accessor):
            out = [r for r in out if accessor(r, val)]
        else:
            out = [r for r in out if str(r.get(accessor)) == val]
    return out


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.route("/", methods=["GET"])
def root():
    return jsonify({"status": "ok"}), 200


# ---------------------------------------------------------------------------
# Clock (test-driving)
# ---------------------------------------------------------------------------
@app.route("/_clock/set_current_utc", methods=["POST"])
@require("PlatformAdmin")
def set_clock():
    global CLOCK
    b = body()
    v = b.get("to_iso8601")
    dt = parse_dt(v)
    if dt is None:
        bad("to_iso8601 must be a valid ISO8601 timestamp.")
    CLOCK = dt
    return success({}, code=200, response_type="object")


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------
@app.route("/customers", methods=["POST"])
@require("PlatformAdmin")
def create_customer():
    b = body()
    email = req_str(b, "email")
    full_name = req_str(b, "full_name")
    unique_check(DB["customers"], "email", email)
    rec = base_common()
    rec.update({
        "email": email,
        "full_name": full_name,
        "phone": b.get("phone", None),
    })
    DB["customers"][rec["id"]] = rec
    return obj(rec, 201)


@app.route("/customers/<cid>", methods=["GET"])
@require("Customer", "PlatformAdmin", "CustomerService")
def get_customer(cid):
    rec = DB["customers"].get(cid)
    if not rec:
        raise ApiError("ERR_NOT_FOUND", "Customer not found.")
    return obj(rec)


# ---------------------------------------------------------------------------
# Pros
# ---------------------------------------------------------------------------
@app.route("/pros", methods=["POST"])
@require("PlatformAdmin")
def create_pro():
    b = body()
    email = req_str(b, "email")
    business_name = req_str(b, "business_name")
    billing_mode = b.get("billing_mode", "PAY_PER_LEAD")
    if billing_mode not in ("PAY_PER_LEAD", "SUBSCRIPTION"):
        bad("billing_mode must be PAY_PER_LEAD or SUBSCRIPTION.")
    zips = b.get("service_zip_codes", [])
    cats = b.get("covered_category_ids", [])
    if not isinstance(zips, list) or not isinstance(cats, list):
        bad("service_zip_codes and covered_category_ids must be arrays.")
    unique_check(DB["pros"], "email", email)
    rec = base_common()
    rec.update({
        "email": email,
        "business_name": business_name,
        "phone": b.get("phone", None),
        "verification_status": "UNVERIFIED",
        "billing_mode": billing_mode,
        "subscription_plan_id": None,
        "credit_balance_cents": 0,
        "remaining_lead_credits": 0,
        "service_zip_codes": list(zips),
        "covered_category_ids": list(cats),
        "rating_avg": 0.0,
        "rating_count": 0,
        "provisional_rating": 0.0,
        "dispute_count": 0,
    })
    DB["pros"][rec["id"]] = rec
    return obj(rec, 201)


@app.route("/pros/<pid>", methods=["GET"])
@require("Pro", "Customer", "PlatformAdmin", "CustomerService")
def get_pro(pid):
    rec = DB["pros"].get(pid)
    if not rec:
        raise ApiError("ERR_NOT_FOUND", "Pro not found.")
    return obj(rec)


@app.route("/pros", methods=["GET"])
@require("PlatformAdmin", "Customer")
def list_pros():
    items = list(DB["pros"].values())
    items = arg_filter(items, {
        "subscription_plan_id": "subscription_plan_id",
        "verification_status": "verification_status",
        "category_id": lambda r, v: v in r.get("covered_category_ids", []),
        "zip_code": lambda r, v: v in r.get("service_zip_codes", []),
    })
    return paginate(items)


@app.route("/pros/<pid>/submit-verification", methods=["POST"])
@require("Pro")
def submit_verification(pid):
    rec = DB["pros"].get(pid)
    if not rec:
        raise ApiError("ERR_NOT_FOUND", "Pro not found.")
    if rec["id"] != g.uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Not the owning pro.")
    if rec["verification_status"] != "UNVERIFIED":
        raise ApiError("ERR_INVALID_STATE", "Pro is not UNVERIFIED.")
    rec["verification_status"] = "PENDING"
    touch(rec)
    return obj(rec)


@app.route("/pros/<pid>/verify", methods=["POST"])
@require("PlatformAdmin")
def verify_pro(pid):
    rec = DB["pros"].get(pid)
    if not rec:
        raise ApiError("ERR_NOT_FOUND", "Pro not found.")
    b = body()
    decision = b.get("decision")
    if decision not in ("APPROVE", "SUSPEND"):
        raise ApiError("ERR_VALIDATION_DECISION", "decision must be APPROVE or SUSPEND.")
    status = rec["verification_status"]
    if decision == "APPROVE":
        if status != "PENDING":
            raise ApiError("ERR_INVALID_STATE", "APPROVE requires PENDING pro.")
        rec["verification_status"] = "VERIFIED"
    else:  # SUSPEND
        if status not in ("PENDING", "VERIFIED"):
            raise ApiError("ERR_INVALID_STATE", "SUSPEND requires PENDING or VERIFIED pro.")
        rec["verification_status"] = "SUSPENDED"
    touch(rec)
    return obj(rec)


@app.route("/pros/<pid>/credit-topup", methods=["POST"])
@require("PlatformAdmin")
def credit_topup(pid):
    rec = DB["pros"].get(pid)
    if not rec:
        raise ApiError("ERR_NOT_FOUND", "Pro not found.")
    b = body()
    amount = req_int(b, "amount_cents")
    rec["credit_balance_cents"] += amount
    if rec["credit_balance_cents"] < 0:
        rec["credit_balance_cents"] -= amount
        bad("amount_cents would make balance negative.")
    touch(rec)
    return obj(rec)


@app.route("/pros/<pid>/subscribe", methods=["POST"])
@require("Pro")
def subscribe_pro(pid):
    rec = DB["pros"].get(pid)
    if not rec:
        raise ApiError("ERR_NOT_FOUND", "Pro not found.")
    if rec["id"] != g.uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Not the owning pro.")
    b = body()
    plan_id = b.get("subscription_plan_id")
    plan = DB["plans"].get(plan_id) if plan_id is not None else None
    if plan is None or rec["subscription_plan_id"] == plan_id:
        raise ApiError("ERR_SUBSCRIPTION_REQUIRED", "Plan does not exist or pro already on that plan.")
    rec["subscription_plan_id"] = plan_id
    rec["billing_mode"] = "SUBSCRIPTION"
    rec["remaining_lead_credits"] += plan["included_lead_credits"]
    touch(rec)
    return obj(rec)


# ---------------------------------------------------------------------------
# Service Categories
# ---------------------------------------------------------------------------
@app.route("/service-categories", methods=["POST"])
@require("PlatformAdmin")
def create_category():
    b = body()
    name = req_str(b, "name")
    base_price = req_int(b, "base_lead_price_cents", minimum=1)
    max_leads = req_int(b, "max_leads_per_request", minimum=1)
    threshold = req_int(b, "demand_high_threshold", minimum=0)
    mult = req_num(b, "demand_multiplier_high", minimum=1.0)
    refund_hours = req_int(b, "refund_window_hours", minimum=0)
    min_rating = req_num(b, "min_rating_to_receive_leads", minimum=0.0, maximum=5.0)
    unique_check(DB["categories"], "name", name)
    rec = base_config()
    rec.update({
        "name": name,
        "base_lead_price_cents": base_price,
        "max_leads_per_request": max_leads,
        "demand_high_threshold": threshold,
        "demand_multiplier_high": mult,
        "refund_window_hours": refund_hours,
        "min_rating_to_receive_leads": min_rating,
    })
    DB["categories"][rec["id"]] = rec
    return obj(rec, 201)


@app.route("/service-categories/<cid>", methods=["GET"])
@require("PlatformAdmin", "Customer", "Pro", "CustomerService")
def get_category(cid):
    rec = DB["categories"].get(cid)
    if not rec:
        raise ApiError("ERR_NOT_FOUND", "Category not found.")
    return obj(rec)


# ---------------------------------------------------------------------------
# Subscription Plans
# ---------------------------------------------------------------------------
@app.route("/subscription-plans", methods=["POST"])
@require("PlatformAdmin")
def create_plan():
    b = body()
    tier = req_str(b, "tier")
    monthly = req_int(b, "monthly_fee_cents", minimum=1)
    included = req_int(b, "included_lead_credits", minimum=0)
    overage = req_int(b, "overage_price_cents", minimum=1)
    unique_check(DB["plans"], "tier", tier)
    rec = base_config()
    rec.update({
        "tier": tier,
        "monthly_fee_cents": monthly,
        "included_lead_credits": included,
        "overage_price_cents": overage,
    })
    DB["plans"][rec["id"]] = rec
    return obj(rec, 201)


@app.route("/subscription-plans/<pid>", methods=["GET"])
@require("PlatformAdmin", "Pro")
def get_plan(pid):
    rec = DB["plans"].get(pid)
    if not rec:
        raise ApiError("ERR_NOT_FOUND", "Plan not found.")
    return obj(rec)


# ---------------------------------------------------------------------------
# Service Requests
# ---------------------------------------------------------------------------
@app.route("/service-requests", methods=["POST"])
@require("Customer")
def create_request():
    b = body()
    customer_id = b.get("customer_id")
    if customer_id != g.uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "customer_id must match the acting customer.")
    if customer_id not in DB["customers"]:
        raise ApiError("ERR_NOT_FOUND", "Customer not found.")
    category_id = b.get("category_id")
    if category_id not in DB["categories"]:
        raise ApiError("ERR_NOT_FOUND", "Category not found.")
    zip_code = req_str(b, "zip_code")
    description = b.get("description", "")
    if not isinstance(description, str):
        bad("description must be a string.")
    budget = req_int(b, "budget_cents", minimum=0)
    rec = base_common()
    rec.update({
        "customer_id": customer_id,
        "category_id": category_id,
        "zip_code": zip_code,
        "description": description,
        "budget_cents": budget,
        "status": "OPEN",
        "distributed_lead_count": 0,
    })
    DB["requests"][rec["id"]] = rec
    return obj(rec, 201)


@app.route("/service-requests/<rid>", methods=["GET"])
@require("Customer", "Pro", "PlatformAdmin", "CustomerService")
def get_request(rid):
    rec = DB["requests"].get(rid)
    if not rec:
        raise ApiError("ERR_NOT_FOUND", "Service request not found.")
    return obj(rec)


@app.route("/service-requests", methods=["GET"])
@require("Customer", "PlatformAdmin")
def list_requests():
    items = list(DB["requests"].values())
    items = arg_filter(items, {
        "customer_id": "customer_id",
        "category_id": "category_id",
        "status": "status",
    })
    return paginate(items)


def already_has_lead(request_id, pro_id):
    for l in DB["leads"].values():
        if l["request_id"] == request_id and l["pro_id"] == pro_id:
            return True
    return False


def is_eligible(pro, req, cat):
    if pro["verification_status"] != "VERIFIED":
        return False
    if req["category_id"] not in pro["covered_category_ids"]:
        return False
    if req["zip_code"] not in pro["service_zip_codes"]:
        return False
    if already_has_lead(req["id"], pro["id"]):
        return False
    if pro["rating_count"] != 0 and pro["provisional_rating"] < cat["min_rating_to_receive_leads"]:
        return False
    return True


def compute_gross(cat):
    now = now_dt()
    open_count = 0
    for l in DB["leads"].values():
        if l["category_id"] == cat["id"] and l["contact_status"] in ("DISTRIBUTED", "CONTACTED", "QUOTED"):
            cdt = parse_dt(l["created_at"])
            if cdt is not None and cdt < now:
                open_count += 1
    if open_count >= cat["demand_high_threshold"]:
        mult = cat["demand_multiplier_high"]
    else:
        mult = 1.0
    return rhu_cents(Decimal(cat["base_lead_price_cents"]) * Decimal(str(mult)))


def can_fund(pro, gross):
    if pro["billing_mode"] == "PAY_PER_LEAD":
        return pro["credit_balance_cents"] >= gross
    if pro["remaining_lead_credits"] >= 1:
        return True
    plan = DB["plans"].get(pro["subscription_plan_id"])
    if plan is None:
        return False
    return pro["credit_balance_cents"] >= plan["overage_price_cents"]


@app.route("/service-requests/<rid>/distribute", methods=["POST"])
@require("PlatformAdmin")
def distribute(rid):
    req = DB["requests"].get(rid)
    if not req:
        raise ApiError("ERR_NOT_FOUND", "Service request not found.")
    if req["status"] not in ("OPEN", "DISTRIBUTED"):
        raise ApiError("ERR_INVALID_STATE", "Request is not OPEN or DISTRIBUTED.")
    cat = DB["categories"][req["category_id"]]

    # Eligibility (priority 8) — cap reached OR no eligible pro -> ERR_NO_ELIGIBLE_PROS
    if req["distributed_lead_count"] >= cat["max_leads_per_request"]:
        raise ApiError("ERR_NO_ELIGIBLE_PROS", "Distribution cap reached.")
    eligible = [p for p in DB["pros"].values() if is_eligible(p, req, cat)]
    if not eligible:
        raise ApiError("ERR_NO_ELIGIBLE_PROS", "No eligible pro for this request.")

    gross = compute_gross(cat)

    # Funding (priority 12)
    fundable = [p for p in eligible if can_fund(p, gross)]
    if not fundable:
        raise ApiError("ERR_INSUFFICIENT_CREDIT", "No candidate pro can fund the lead.")

    # Field validity (priority 13): expected_service_request_version present & int
    b = body()
    expected = b.get("expected_service_request_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        bad("expected_service_request_version must be an integer.")

    # OCC (priority 15)
    if expected != req["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_service_request_version does not match.")

    # Select single top-ranked fundable pro
    fundable.sort(key=lambda p: (-p["provisional_rating"], p["created_at"], p["_seq"]))
    pro = fundable[0]

    # Charge
    charge_cents = 0
    credits_consumed = 0
    if pro["billing_mode"] == "PAY_PER_LEAD":
        charge_cents = gross
        pro["credit_balance_cents"] -= charge_cents
    else:
        if pro["remaining_lead_credits"] >= 1:
            charge_cents = 0
            credits_consumed = 1
            pro["remaining_lead_credits"] -= 1
        else:
            plan = DB["plans"][pro["subscription_plan_id"]]
            charge_cents = plan["overage_price_cents"]
            pro["credit_balance_cents"] -= charge_cents

    lead = base_common()
    lead.update({
        "request_id": req["id"],
        "pro_id": pro["id"],
        "category_id": req["category_id"],
        "billing_mode": pro["billing_mode"],
        "charge_cents": charge_cents,
        "credits_consumed": credits_consumed,
        "contact_status": "DISTRIBUTED",
        "billing_status": "CHARGED",
        "distributed_at": now_iso(),
    })
    DB["leads"][lead["id"]] = lead

    req["distributed_lead_count"] += 1
    if req["status"] == "OPEN":
        req["status"] = "DISTRIBUTED"
    touch(req)
    return obj(req)


@app.route("/service-requests/<rid>/close", methods=["POST"])
@require("Customer")
def close_request(rid):
    req = DB["requests"].get(rid)
    if not req:
        raise ApiError("ERR_NOT_FOUND", "Service request not found.")
    if req["customer_id"] != g.uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Not the owning customer.")
    if req["status"] not in ("OPEN", "DISTRIBUTED"):
        raise ApiError("ERR_INVALID_STATE", "Request is not OPEN or DISTRIBUTED.")
    was_distributed = req["status"] == "DISTRIBUTED"
    req["status"] = "CLOSED"
    touch(req)
    if was_distributed:
        for l in DB["leads"].values():
            if l["request_id"] == req["id"] and l["contact_status"] in ("DISTRIBUTED", "CONTACTED", "QUOTED"):
                l["contact_status"] = "CLOSED"
                touch(l)
    return obj(req)


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------
@app.route("/leads/<lid>", methods=["GET"])
@require("Pro", "Customer", "PlatformAdmin", "CustomerService")
def get_lead(lid):
    rec = DB["leads"].get(lid)
    if not rec:
        raise ApiError("ERR_NOT_FOUND", "Lead not found.")
    return obj(rec)


@app.route("/leads", methods=["GET"])
@require("Pro", "PlatformAdmin", "Customer")
def list_leads():
    items = list(DB["leads"].values())
    items = arg_filter(items, {
        "request_id": "request_id",
        "pro_id": "pro_id",
        "contact_status": "contact_status",
        "billing_status": "billing_status",
    })
    return paginate(items)


@app.route("/leads/<lid>/contact", methods=["POST"])
@require("Pro")
def contact_lead(lid):
    lead = DB["leads"].get(lid)
    if not lead:
        raise ApiError("ERR_NOT_FOUND", "Lead not found.")
    if lead["pro_id"] != g.uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Not the owning pro.")
    if lead["contact_status"] != "DISTRIBUTED":
        raise ApiError("ERR_INVALID_STATE", "Lead is not DISTRIBUTED.")
    lead["contact_status"] = "CONTACTED"
    touch(lead)
    return obj(lead)


def credit_lead_refund(lead):
    pro = DB["pros"].get(lead["pro_id"])
    if pro is not None:
        pro["credit_balance_cents"] += lead["charge_cents"]
        if lead["credits_consumed"] == 1:
            pro["remaining_lead_credits"] += 1
    return pro


@app.route("/leads/<lid>/refund-request", methods=["POST"])
@require("Pro")
def refund_lead(lid):
    lead = DB["leads"].get(lid)
    if not lead:
        raise ApiError("ERR_NOT_FOUND", "Lead not found.")
    if lead["pro_id"] != g.uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Not the owning pro.")
    if lead["billing_status"] != "CHARGED":
        raise ApiError("ERR_INVALID_STATE", "Lead billing_status is not CHARGED.")
    cat = DB["categories"].get(lead["category_id"])
    distributed_at = parse_dt(lead["distributed_at"])
    deadline = distributed_at + timedelta(hours=cat["refund_window_hours"])
    if not (now_dt() < deadline):
        raise ApiError("ERR_REFUND_WINDOW_CLOSED", "Refund window has closed.")
    lead["billing_status"] = "REFUNDED"
    touch(lead)
    pro = credit_lead_refund(lead)
    if pro is not None:
        touch(pro)
    return obj(lead)


# ---------------------------------------------------------------------------
# Quotes
# ---------------------------------------------------------------------------
@app.route("/quotes", methods=["POST"])
@require("Pro")
def create_quote():
    b = body()
    lead_id = b.get("lead_id")
    lead = DB["leads"].get(lead_id) if lead_id is not None else None
    if lead is None:
        raise ApiError("ERR_NOT_FOUND", "Lead not found.")
    if lead["contact_status"] != "CONTACTED":
        raise ApiError("ERR_INVALID_STATE", "Lead is not CONTACTED.")
    if lead["pro_id"] != g.uid:
        raise ApiError("ERR_REFERENCE_MISMATCH", "Lead does not belong to the acting pro.")
    amount = req_int(b, "amount_cents", minimum=1)
    message = b.get("message", "")
    if not isinstance(message, str):
        bad("message must be a string.")
    req = DB["requests"].get(lead["request_id"])
    rec = base_common()
    rec.update({
        "lead_id": lead_id,
        "pro_id": lead["pro_id"],
        "customer_id": req["customer_id"],
        "amount_cents": amount,
        "message": message,
        "status": "SENT",
        "revision_count": 0,
        "valid_until": b.get("valid_until", None),
    })
    DB["quotes"][rec["id"]] = rec
    # cascade lead CONTACTED -> QUOTED
    lead["contact_status"] = "QUOTED"
    touch(lead)
    return obj(rec, 201)


@app.route("/quotes/<qid>", methods=["GET"])
@require("Customer", "Pro", "PlatformAdmin")
def get_quote(qid):
    rec = DB["quotes"].get(qid)
    if not rec:
        raise ApiError("ERR_NOT_FOUND", "Quote not found.")
    return obj(rec)


@app.route("/quotes", methods=["GET"])
@require("Customer", "Pro", "PlatformAdmin")
def list_quotes():
    items = list(DB["quotes"].values())
    items = arg_filter(items, {
        "lead_id": "lead_id",
        "pro_id": "pro_id",
        "customer_id": "customer_id",
        "status": "status",
    })
    return paginate(items)


@app.route("/quotes/<qid>/send", methods=["POST"])
@require("Pro")
def send_quote(qid):
    rec = DB["quotes"].get(qid)
    if not rec:
        raise ApiError("ERR_NOT_FOUND", "Quote not found.")
    if rec["pro_id"] != g.uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Not the owning pro.")
    if rec["status"] != "REVISION_REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "Quote is not REVISION_REQUESTED.")
    b = body()
    amount = req_int(b, "amount_cents", minimum=1)
    rec["status"] = "SENT"
    rec["amount_cents"] = amount
    touch(rec)
    return obj(rec)


@app.route("/quotes/<qid>/request-revision", methods=["POST"])
@require("Customer")
def request_revision(qid):
    rec = DB["quotes"].get(qid)
    if not rec:
        raise ApiError("ERR_NOT_FOUND", "Quote not found.")
    if rec["customer_id"] != g.uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Not the owning customer.")
    if rec["status"] != "SENT":
        raise ApiError("ERR_INVALID_STATE", "Quote is not SENT.")
    rec["status"] = "REVISION_REQUESTED"
    rec["revision_count"] += 1
    touch(rec)
    return obj(rec)


# ---------------------------------------------------------------------------
# Bookings
# ---------------------------------------------------------------------------
@app.route("/bookings", methods=["POST"])
@require("Customer")
def create_booking():
    b = body()
    quote_id = b.get("quote_id")
    quote = DB["quotes"].get(quote_id) if quote_id is not None else None
    if quote is None:
        raise ApiError("ERR_NOT_FOUND", "Quote not found.")
    # ownership (priority 3): acting customer owns the quote
    if quote["customer_id"] != g.uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Not the owning customer.")
    slot_id = b.get("availability_slot_id")
    slot = DB["slots"].get(slot_id) if slot_id is not None else None
    if slot is None:
        raise ApiError("ERR_NOT_FOUND", "Availability slot not found.")
    # state (priority 5)
    if quote["status"] != "SENT":
        raise ApiError("ERR_INVALID_STATE", "Quote is not SENT.")
    if slot["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Slot is not OPEN.")
    # referential coherence (priority 6): slot belongs to quote's pro
    if slot["pro_id"] != quote["pro_id"]:
        raise ApiError("ERR_REFERENCE_MISMATCH", "Slot does not belong to the quote's pro.")
    # pro verification (priority 7)
    pro = DB["pros"].get(quote["pro_id"])
    if pro is None or pro["verification_status"] != "VERIFIED":
        raise ApiError("ERR_PRO_NOT_VERIFIED", "Quote's pro is not VERIFIED.")

    scheduled_start = b.get("scheduled_start")
    scheduled_end = b.get("scheduled_end")
    ns = parse_dt(scheduled_start)
    ne = parse_dt(scheduled_end)

    # booking conflict (priority 11)
    if ns is not None and ne is not None:
        ss = parse_dt(slot["start_utc"])
        se = parse_dt(slot["end_utc"])
        if not (ss <= ns and ne <= se):
            raise ApiError("ERR_BOOKING_CONFLICT", "Booking window does not fit the slot.")
        buffer = timedelta(minutes=30)
        for other in DB["bookings"].values():
            if other["pro_id"] == quote["pro_id"] and other["status"] == "CONFIRMED":
                bs = parse_dt(other["scheduled_start"])
                be = parse_dt(other["scheduled_end"])
                if bs is None or be is None:
                    continue
                if ns <= be + buffer and bs - buffer <= ne:
                    raise ApiError("ERR_BOOKING_CONFLICT", "Booking violates the travel buffer.")

    # field validity (priority 13)
    if ns is None or ne is None or ne <= ns:
        bad("scheduled_end must be strictly after scheduled_start.")

    rec = base_common()
    rec.update({
        "quote_id": quote_id,
        "customer_id": quote["customer_id"],
        "pro_id": quote["pro_id"],
        "availability_slot_id": slot_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "price_cents": quote["amount_cents"],
        "payout_cents": 0,
        "status": "CONFIRMED",
        "cancellation_reason": None,
    })
    DB["bookings"][rec["id"]] = rec

    # cascade: quote SENT -> ACCEPTED
    quote["status"] = "ACCEPTED"
    touch(quote)

    # cascade: winning lead QUOTED -> CONVERTED; sibling leads -> CLOSED
    lead = DB["leads"].get(quote["lead_id"])
    if lead is not None:
        lead["contact_status"] = "CONVERTED"
        touch(lead)
        req = DB["requests"].get(lead["request_id"])
        for sib in DB["leads"].values():
            if sib["id"] != lead["id"] and sib["request_id"] == lead["request_id"] \
                    and sib["contact_status"] in ("DISTRIBUTED", "CONTACTED", "QUOTED"):
                sib["contact_status"] = "CLOSED"
                touch(sib)
        # cascade: request -> BOOKED
        if req is not None and req["status"] in ("OPEN", "DISTRIBUTED"):
            req["status"] = "BOOKED"
            touch(req)

    # cascade: slot OPEN -> BOOKED
    slot["status"] = "BOOKED"
    slot["booking_id"] = rec["id"]
    touch(slot)

    return obj(rec, 201)


@app.route("/bookings/<bid>", methods=["GET"])
@require("Customer", "Pro", "PlatformAdmin")
def get_booking(bid):
    rec = DB["bookings"].get(bid)
    if not rec:
        raise ApiError("ERR_NOT_FOUND", "Booking not found.")
    return obj(rec)


@app.route("/bookings", methods=["GET"])
@require("Customer", "Pro", "PlatformAdmin")
def list_bookings():
    items = list(DB["bookings"].values())
    items = arg_filter(items, {
        "quote_id": "quote_id",
        "customer_id": "customer_id",
        "pro_id": "pro_id",
        "status": "status",
    })
    return paginate(items)


@app.route("/bookings/<bid>/complete", methods=["POST"])
@require("Pro")
def complete_booking(bid):
    rec = DB["bookings"].get(bid)
    if not rec:
        raise ApiError("ERR_NOT_FOUND", "Booking not found.")
    if rec["pro_id"] != g.uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Not the owning pro.")
    if rec["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", "Booking is not CONFIRMED.")
    start = parse_dt(rec["scheduled_start"])
    if start is not None and now_dt() < start:
        raise ApiError("ERR_INVALID_STATE", "Cannot complete before scheduled_start.")
    amount = rec["price_cents"]
    commission = rhu_cents(Decimal(amount) * Decimal("0.15"))
    processing = rhu_cents(Decimal(amount) * Decimal("0.029") + Decimal("30"))
    rec["payout_cents"] = amount - commission - processing
    rec["status"] = "COMPLETED"
    touch(rec)
    return obj(rec)


@app.route("/bookings/<bid>/cancel", methods=["POST"])
@require("Customer", "Pro")
def cancel_booking(bid):
    rec = DB["bookings"].get(bid)
    if not rec:
        raise ApiError("ERR_NOT_FOUND", "Booking not found.")
    if g.role == "Customer":
        owns = rec["customer_id"] == g.uid
    else:
        owns = rec["pro_id"] == g.uid
    if not owns:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Not a party to this booking.")
    if rec["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", "Booking is not CONFIRMED.")
    b = body()
    rec["status"] = "CANCELLED"
    rec["cancellation_reason"] = b.get("cancellation_reason", None)
    touch(rec)
    # compensation: free the slot
    slot = DB["slots"].get(rec.get("availability_slot_id"))
    if slot is None:
        for s in DB["slots"].values():
            if s.get("booking_id") == rec["id"]:
                slot = s
                break
    if slot is not None and slot["status"] == "BOOKED":
        slot["status"] = "OPEN"
        slot["booking_id"] = None
        touch(slot)
    return obj(rec)


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------
def recompute_rating(pro):
    published = [r["rating"] for r in DB["reviews"].values()
                 if r["pro_id"] == pro["id"] and r["status"] == "PUBLISHED"]
    provisional = [r["rating"] for r in DB["reviews"].values()
                   if r["pro_id"] == pro["id"] and r["status"] in ("PENDING", "PUBLISHED")]
    pro["rating_count"] = len(published)
    pro["rating_avg"] = rhu2(Decimal(sum(published)) / Decimal(len(published))) if published else 0.0
    pro["provisional_rating"] = rhu2(Decimal(sum(provisional)) / Decimal(len(provisional))) if provisional else 0.0


@app.route("/reviews", methods=["POST"])
@require("Customer")
def create_review():
    b = body()
    booking_id = b.get("booking_id")
    booking = DB["bookings"].get(booking_id) if booking_id is not None else None
    if booking is None:
        raise ApiError("ERR_NOT_FOUND", "Booking not found.")
    # coherence (priority 6): booking belongs to acting customer
    if booking["customer_id"] != g.uid:
        raise ApiError("ERR_REFERENCE_MISMATCH", "Booking does not belong to the acting customer.")
    # field validity (priority 13): rating integer 1..5
    rating = b.get("rating")
    if isinstance(rating, bool) or not isinstance(rating, int) or rating < 1 or rating > 5:
        bad("rating must be an integer between 1 and 5.")
    # uniqueness (priority 14): one review per booking
    for r in DB["reviews"].values():
        if r["booking_id"] == booking_id:
            raise ApiError("ERR_DUPLICATE_REVIEW", "A review already exists for this booking.")
    text = b.get("text", None)
    rec = base_common()
    rec.update({
        "booking_id": booking_id,
        "customer_id": booking["customer_id"],
        "pro_id": booking["pro_id"],
        "rating": rating,
        "text": text,
        "status": "PENDING",
    })
    DB["reviews"][rec["id"]] = rec
    pro = DB["pros"].get(booking["pro_id"])
    if pro is not None:
        recompute_rating(pro)
        touch(pro)
    return obj(rec, 201)


@app.route("/reviews/<rid>", methods=["GET"])
@require("Customer", "Pro", "PlatformAdmin", "CustomerService")
def get_review(rid):
    rec = DB["reviews"].get(rid)
    if not rec:
        raise ApiError("ERR_NOT_FOUND", "Review not found.")
    return obj(rec)


@app.route("/reviews", methods=["GET"])
@require("Customer", "Pro", "PlatformAdmin", "CustomerService")
def list_reviews():
    items = list(DB["reviews"].values())
    items = arg_filter(items, {
        "booking_id": "booking_id",
        "customer_id": "customer_id",
        "pro_id": "pro_id",
    })
    return paginate(items)


@app.route("/reviews/<rid>/publish", methods=["POST"])
@require("PlatformAdmin", "CustomerService")
def publish_review(rid):
    rec = DB["reviews"].get(rid)
    if not rec:
        raise ApiError("ERR_NOT_FOUND", "Review not found.")
    if rec["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "Review is not PENDING.")
    rec["status"] = "PUBLISHED"
    touch(rec)
    pro = DB["pros"].get(rec["pro_id"])
    if pro is not None:
        recompute_rating(pro)
        touch(pro)
    return obj(rec)


# ---------------------------------------------------------------------------
# Disputes
# ---------------------------------------------------------------------------
@app.route("/disputes", methods=["POST"])
@require("Pro")
def create_dispute():
    b = body()
    lead_id = b.get("lead_id")
    lead = DB["leads"].get(lead_id) if lead_id is not None else None
    if lead is None:
        raise ApiError("ERR_NOT_FOUND", "Lead not found.")
    if lead["pro_id"] != g.uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Not the owning pro.")
    if lead["billing_status"] != "CHARGED":
        raise ApiError("ERR_DISPUTE_NOT_ALLOWED", "Lead billing_status is not CHARGED.")
    reason = req_str(b, "reason")
    rec = base_common()
    rec.update({
        "lead_id": lead_id,
        "raised_by_pro_id": g.uid,
        "reason": reason,
        "status": "OPEN",
        "refund_cents": 0,
        "resolution_note": None,
        "assigned_cs_user_id": None,
    })
    DB["disputes"][rec["id"]] = rec
    # cascade lead CHARGED -> DISPUTED
    lead["billing_status"] = "DISPUTED"
    touch(lead)
    return obj(rec, 201)


@app.route("/disputes/<did>", methods=["GET"])
@require("Pro", "PlatformAdmin", "CustomerService")
def get_dispute(did):
    rec = DB["disputes"].get(did)
    if not rec:
        raise ApiError("ERR_NOT_FOUND", "Dispute not found.")
    return obj(rec)


@app.route("/disputes", methods=["GET"])
@require("Pro", "PlatformAdmin", "CustomerService")
def list_disputes():
    items = list(DB["disputes"].values())
    items = arg_filter(items, {
        "lead_id": "lead_id",
        "raised_by_pro_id": "raised_by_pro_id",
        "status": "status",
    })
    return paginate(items)


@app.route("/disputes/<did>/review", methods=["POST"])
@require("CustomerService")
def review_dispute(did):
    rec = DB["disputes"].get(did)
    if not rec:
        raise ApiError("ERR_NOT_FOUND", "Dispute not found.")
    if rec["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Dispute is not OPEN.")
    rec["status"] = "UNDER_REVIEW"
    rec["assigned_cs_user_id"] = g.uid
    touch(rec)
    return obj(rec)


@app.route("/disputes/<did>/resolve", methods=["POST"])
@require("CustomerService")
def resolve_dispute(did):
    rec = DB["disputes"].get(did)
    if not rec:
        raise ApiError("ERR_NOT_FOUND", "Dispute not found.")
    if rec["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "Dispute is not UNDER_REVIEW.")
    b = body()
    decision = b.get("decision")
    if decision not in ("REFUND", "DENY"):
        raise ApiError("ERR_VALIDATION_DECISION", "decision must be REFUND or DENY.")
    lead = DB["leads"].get(rec["lead_id"])
    if decision == "REFUND":
        if lead is None or lead["billing_status"] != "DISPUTED":
            raise ApiError("ERR_INVALID_STATE", "Disputed lead is not DISPUTED.")
        rec["status"] = "RESOLVED_REFUNDED"
        rec["refund_cents"] = lead["charge_cents"]
        rec["resolution_note"] = b.get("resolution_note", None)
        lead["billing_status"] = "REFUNDED"
        touch(lead)
        credit_lead_refund(lead)
    else:  # DENY
        rec["status"] = "RESOLVED_DENIED"
        rec["refund_cents"] = 0
        rec["resolution_note"] = b.get("resolution_note", None)
        if lead is not None and lead["billing_status"] == "DISPUTED":
            lead["billing_status"] = "CHARGED"
            touch(lead)
        pro = DB["pros"].get(lead["pro_id"]) if lead is not None else None
        if pro is not None:
            pro["dispute_count"] += 1
    touch(rec)
    return obj(rec)


# ---------------------------------------------------------------------------
# Availability Slots
# ---------------------------------------------------------------------------
@app.route("/availability-slots", methods=["POST"])
@require("Pro")
def create_slot():
    b = body()
    pro_id = b.get("pro_id")
    if pro_id != g.uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "pro_id must match the acting pro.")
    if pro_id not in DB["pros"]:
        raise ApiError("ERR_NOT_FOUND", "Pro not found.")
    start_utc = b.get("start_utc")
    end_utc = b.get("end_utc")
    s = parse_dt(start_utc)
    e = parse_dt(end_utc)
    # slot overlap (priority 10) — half-open [start, end); touching allowed
    if s is not None and e is not None and e > s:
        for other in DB["slots"].values():
            if other["pro_id"] != pro_id:
                continue
            os_ = parse_dt(other["start_utc"])
            oe = parse_dt(other["end_utc"])
            if os_ is None or oe is None:
                continue
            if s < oe and os_ < e:
                raise ApiError("ERR_SLOT_OVERLAP", "Slot overlaps an existing slot.")
    # field validity (priority 13)
    if s is None or e is None or e <= s:
        bad("end_utc must be strictly after start_utc.")
    rec = base_common()
    rec.update({
        "pro_id": pro_id,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "status": "OPEN",
        "booking_id": None,
    })
    DB["slots"][rec["id"]] = rec
    return obj(rec, 201)


@app.route("/availability-slots/<sid>", methods=["GET"])
@require("Pro", "Customer", "PlatformAdmin")
def get_slot(sid):
    rec = DB["slots"].get(sid)
    if not rec:
        raise ApiError("ERR_NOT_FOUND", "Slot not found.")
    return obj(rec)


@app.route("/availability-slots", methods=["GET"])
@require("Pro", "Customer", "PlatformAdmin")
def list_slots():
    items = list(DB["slots"].values())
    items = arg_filter(items, {
        "pro_id": "pro_id",
        "booking_id": "booking_id",
        "status": "status",
    })
    return paginate(items)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
