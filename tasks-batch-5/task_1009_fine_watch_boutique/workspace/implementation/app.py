"""
Fine-Watch Boutique & Service API.

Single-file Python + Flask implementation. Storage is purely in-memory (Python
dicts keyed by id); every process start begins with an empty store and no seeded
data. See PRD.md / SCAFFOLD.yaml for the authoritative contract.
"""

import math
import os
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)
app.url_map.strict_slashes = False

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Constants (from SCAFFOLD §1.3 calculation tables and PRD §3)
# ---------------------------------------------------------------------------
ROLES = {"Associate", "Client", "Watchmaker"}

CONDITION_FACTOR = {
    "NEW": Decimal("1.00"),
    "MINT": Decimal("0.95"),
    "EXCELLENT": Decimal("0.88"),
    "GOOD": Decimal("0.78"),
    "FAIR": Decimal("0.65"),
}
CONDITION_GRADES = set(CONDITION_FACTOR.keys())
BOX_PAPERS_PREMIUM = Decimal("0.08")
TRADE_IN_RATE = Decimal("0.70")
CONSIGN_TIER1_CENTS = 500000
CONSIGN_TIER2_CENTS = 2000000

BASE_LABOR = {"BATTERY": 8000, "MOVEMENT_OVERHAUL": 60000, "WATER_RESISTANCE": 25000}
COMPLICATION_MULT = {
    "STANDARD": Decimal("1.0"),
    "CHRONOGRAPH": Decimal("1.5"),
    "GRAND_COMPLICATION": Decimal("2.5"),
}
WATER_SURCHARGE_PER_100M = 5000
MIN_QUOTE_CENTS = 12000
MAX_QUOTE_CENTS = 500000

MIN_DEPOSIT_RATE = Decimal("0.20")
DEFAULT_GRACE_DAYS = 10
RESTOCK_FEE_RATE = Decimal("0.05")

TIER_RANK = {"STANDARD": 1, "PREMIER": 2, "VIP": 3}
PRIORITY_TIERS = set(TIER_RANK.keys())
OFFER_WINDOW_DAYS = 7
BENCH_BUFFER_MINUTES = 30

SERVICE_TYPES = {"BATTERY", "MOVEMENT_OVERHAUL", "WATER_RESISTANCE"}
MOVEMENT_COMPLEXITIES = set(COMPLICATION_MULT.keys())
MODEL_LIFECYCLES = {"ACTIVE", "DISCONTINUED"}
APPRAISAL_PURPOSES = {"WARRANTY", "INSURANCE", "SALE"}
VALUATION_BASES = {"MARKET", "INSURANCE_REPLACEMENT"}
DISPOSITIONS = {"TRADE_IN", "CONSIGNMENT"}

# ---------------------------------------------------------------------------
# In-memory store (wiped on every process start; NO seeding)
# ---------------------------------------------------------------------------
customers = {}
watch_models = {}
watches = {}
watchmakers = {}
waitlist_entries = {}
service_tickets = {}
appraisals = {}
trade_in_offers = {}
layaway_plans = {}
provenance_events = {}

_seq_counter = {"n": 0}
CLOCK = {"now": datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC)}


def next_seq():
    _seq_counter["n"] += 1
    return _seq_counter["n"]


def clock_now():
    return CLOCK["now"]


# ---------------------------------------------------------------------------
# Errors + response envelope
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def _meta(pagination=None):
    rid = "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))
    m = {"api_request_id": rid, "api_request_timestamp": fmt_dt(datetime.now(UTC))}
    if pagination is not None:
        m.update(pagination)
    return m


def success(data, response_type="object", status=200, pagination=None):
    body = {"meta": _meta(pagination), "response_type": response_type, "data": data}
    return jsonify(body), status


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(_e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(_e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"},
    }
    return jsonify(body), 404


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def fmt_dt(dt):
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_str():
    return fmt_dt(datetime.now(UTC))


def rhu(value):
    """Round a real (Decimal/number) to the nearest whole cent, half away from zero."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_dt(value):
    if not isinstance(value, str):
        raise ApiError("ERR_VALIDATION", 400, "Invalid datetime")
    try:
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except Exception:
        raise ApiError("ERR_VALIDATION", 400, "Invalid datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def new_common():
    ts = now_str()
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(entity, bump_version=True):
    entity["updated_at"] = now_str()
    if bump_version:
        entity["version"] += 1


def public(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def check_auth(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid auth headers")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this endpoint")
    return uid, role


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", 400, "Body must be a JSON object")
    return data


def require(data, field):
    if field not in data or data[field] is None:
        raise ApiError("ERR_VALIDATION", 400, f"Missing required field: {field}")
    return data[field]


def check_nonneg_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_VALIDATION", 400, f"{field} must be an integer")
    if value < 0:
        raise ApiError("ERR_VALIDATION", 400, f"{field} must be non-negative")
    return value


def opt_nonneg_int(data, field, default=0):
    if field not in data or data[field] is None:
        return default
    return check_nonneg_int(data[field], field)


def req_nonneg_int(data, field):
    return check_nonneg_int(require(data, field), field)


def check_enum(value, allowed, field):
    if value not in allowed:
        raise ApiError("ERR_VALIDATION", 400, f"{field} has an invalid value")
    return value


def opt_bool(data, field, default=False):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", 400, f"{field} must be a boolean")
    return v


def get_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", 400, "limit must be between 1 and 100")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 400, "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", 400, "offset must be non-negative")
    return limit, offset


def paginate(rows):
    limit, offset = get_pagination()
    rows = sorted(rows, key=lambda e: e["_seq"])
    total = len(rows)
    page = rows[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return [public(r) for r in page], pagination


def get_or_404(store, rid):
    ent = store.get(rid)
    if ent is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found")
    return ent


def add_provenance(watch_id, event_type, detail, actor_role):
    ev = {
        "id": str(uuid.uuid4()),
        "created_at": now_str(),
        "_seq": next_seq(),
        "watch_id": watch_id,
        "event_type": event_type,
        "detail": detail,
        "actor_role": actor_role,
    }
    provenance_events[ev["id"]] = ev
    return ev


def add_store_credit(customer, delta):
    customer["store_credit_cents"] = max(0, customer["store_credit_cents"] + delta)
    touch(customer)


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def appraisal_valuation(model, condition_grade, has_box_papers, valuation_basis):
    factor = CONDITION_FACTOR[condition_grade]
    box_premium = BOX_PAPERS_PREMIUM if has_box_papers else Decimal("0")
    market = rhu(Decimal(model["msrp_cents"]) * factor * (Decimal("1") + box_premium))
    premium_bps = Decimal(model.get("market_premium_bps", 0))
    replacement = rhu(Decimal(model["msrp_cents"]) * (Decimal("1") + premium_bps / Decimal("10000")))
    appraised = market if valuation_basis == "MARKET" else replacement
    return market, replacement, appraised


def trade_in_valuation(msrp_cents, condition_grade, has_box_papers, disposition):
    factor = CONDITION_FACTOR[condition_grade]
    box_premium = BOX_PAPERS_PREMIUM if has_box_papers else Decimal("0")
    appraised_market = rhu(Decimal(msrp_cents) * factor * (Decimal("1") + box_premium))
    if disposition == "TRADE_IN":
        commission_rate_bps = None
        quoted_credit = rhu(Decimal(appraised_market) * TRADE_IN_RATE)
    else:  # CONSIGNMENT
        if appraised_market <= CONSIGN_TIER1_CENTS:
            commission_rate_bps = 2000
        elif appraised_market <= CONSIGN_TIER2_CENTS:
            commission_rate_bps = 1500
        else:
            commission_rate_bps = 1000
        quoted_credit = rhu(
            Decimal(appraised_market) * (Decimal("1") - Decimal(commission_rate_bps) / Decimal("10000"))
        )
    return appraised_market, commission_rate_bps, quoted_credit


def service_quote(ticket):
    labor = Decimal(BASE_LABOR[ticket["service_type"]]) * COMPLICATION_MULT[ticket["movement_complexity"]]
    if ticket["service_type"] == "WATER_RESISTANCE":
        target = ticket.get("water_resistance_target_m") or 0
        blocks = math.ceil(target / 100.0)
        water_surcharge = blocks * WATER_SURCHARGE_PER_100M
    else:
        water_surcharge = 0
    raw = labor + Decimal(ticket["parts_cost_cents"]) + Decimal(water_surcharge)
    quoted = rhu(raw)
    quoted = min(MAX_QUOTE_CENTS, max(MIN_QUOTE_CENTS, quoted))
    return quoted


# ---------------------------------------------------------------------------
# Waitlist allocation selector
# ---------------------------------------------------------------------------
def select_waitlist_entry(model_id):
    candidates = [
        w for w in waitlist_entries.values()
        if w["status"] == "WAITING"
        and w["model_id"] == model_id
        and watch_models.get(model_id, {}).get("lifecycle") == "ACTIVE"
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda w: (-TIER_RANK[w["priority_tier"]], -w["deposit_cents"], w["_seq"])
    )
    return candidates[0]


def do_offer(watch, entry, actor_role):
    entry["status"] = "OFFERED"
    entry["allocated_watch_id"] = watch["id"]
    entry["offer_expires_at"] = fmt_dt(clock_now() + timedelta(days=OFFER_WINDOW_DAYS))
    touch(entry)
    watch["status"] = "OFFERED"
    touch(watch, bump_version=False)
    add_provenance(watch["id"], "ALLOCATED", "Watch allocated to waitlist entry", actor_role)


def auto_offer_after_free(watch, actor_role="system"):
    """CASCADE hop3: when an allocation-controlled watch is freed, auto-offer it."""
    model = watch_models.get(watch["model_id"]) if watch.get("model_id") else None
    if not model or not model.get("allocation_controlled"):
        return
    if watch["status"] != "IN_STOCK":
        return
    entry = select_waitlist_entry(watch["model_id"])
    if entry is not None:
        do_offer(watch, entry, actor_role)


# ===========================================================================
# Customers
# ===========================================================================
@app.route("/customers", methods=["POST"])
def create_customer():
    check_auth({"Associate"})
    data = body()
    full_name = require(data, "full_name")
    email = require(data, "email")
    phone = data.get("phone")
    kyc = opt_bool(data, "kyc_verified", False)
    ent = new_common()
    ent.update({
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "kyc_verified": kyc,
        "store_credit_cents": 0,
    })
    customers[ent["id"]] = ent
    return success(public(ent), "object", 201)


@app.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    check_auth({"Associate", "Client"})
    return success(public(get_or_404(customers, cid)), "object", 200)


# ===========================================================================
# Watch models
# ===========================================================================
@app.route("/watch-models", methods=["POST"])
def create_watch_model():
    check_auth({"Associate"})
    data = body()
    brand = require(data, "brand")
    reference_number = require(data, "reference_number")
    display_name = require(data, "display_name")
    msrp_cents = req_nonneg_int(data, "msrp_cents")
    market_premium_bps = opt_nonneg_int(data, "market_premium_bps", 0)
    allocation_controlled = opt_bool(data, "allocation_controlled", False)
    lifecycle = data.get("lifecycle") or "ACTIVE"
    check_enum(lifecycle, MODEL_LIFECYCLES, "lifecycle")
    ent = new_common()
    ent.update({
        "brand": brand,
        "reference_number": reference_number,
        "display_name": display_name,
        "msrp_cents": msrp_cents,
        "market_premium_bps": market_premium_bps,
        "allocation_controlled": allocation_controlled,
        "lifecycle": lifecycle,
    })
    watch_models[ent["id"]] = ent
    return success(public(ent), "object", 201)


@app.route("/watch-models/<mid>", methods=["GET"])
def get_watch_model(mid):
    check_auth({"Associate", "Client"})
    return success(public(get_or_404(watch_models, mid)), "object", 200)


# ===========================================================================
# Watchmakers
# ===========================================================================
@app.route("/watchmakers", methods=["POST"])
def create_watchmaker():
    check_auth({"Associate"})
    data = body()
    display_name = require(data, "display_name")
    specialties = data.get("specialties")
    if specialties is None:
        specialties = []
    if not isinstance(specialties, list):
        raise ApiError("ERR_VALIDATION", 400, "specialties must be an array")
    active = opt_bool(data, "active", True)
    ent = new_common()
    ent.update({"display_name": display_name, "specialties": specialties, "active": active})
    watchmakers[ent["id"]] = ent
    return success(public(ent), "object", 201)


@app.route("/watchmakers/<wid>", methods=["GET"])
def get_watchmaker(wid):
    check_auth({"Associate", "Client", "Watchmaker"})
    return success(public(get_or_404(watchmakers, wid)), "object", 200)


# ===========================================================================
# Watches
# ===========================================================================
def serial_exists(serial):
    return any(w["serial_number"] == serial for w in watches.values())


@app.route("/watches", methods=["POST"])
def create_watch():
    _uid, role = check_auth({"Associate"})
    data = body()
    model_id = require(data, "model_id")
    serial_number = require(data, "serial_number")
    condition_grade = check_enum(require(data, "condition_grade"), CONDITION_GRADES, "condition_grade")
    list_price_cents = req_nonneg_int(data, "list_price_cents")
    has_box_papers = opt_bool(data, "has_box_papers", False)
    acquisition_cost_cents = data.get("acquisition_cost_cents")
    if acquisition_cost_cents is not None:
        check_nonneg_int(acquisition_cost_cents, "acquisition_cost_cents")
    is_loaner = opt_bool(data, "is_loaner", False)
    # existence of FK
    if model_id not in watch_models:
        raise ApiError("ERR_NOT_FOUND", 404, "model_id not found")
    # serial uniqueness
    if serial_exists(serial_number):
        raise ApiError("ERR_SERIAL_DUPLICATE", 409, "serial_number already exists")
    ent = new_common()
    ent.update({
        "model_id": model_id,
        "serial_number": serial_number,
        "condition_grade": condition_grade,
        "has_box_papers": has_box_papers,
        "list_price_cents": list_price_cents,
        "acquisition_cost_cents": acquisition_cost_cents,
        "is_loaner": is_loaner,
        "source": "PURCHASE",
        "authentication_status": "UNVERIFIED",
        "status": "IN_STOCK",
        "current_appraisal_id": None,
    })
    watches[ent["id"]] = ent
    add_provenance(ent["id"], "INTAKE", "Watch taken into inventory", role)
    return success(public(ent), "object", 201)


@app.route("/watches/<wid>", methods=["GET"])
def get_watch(wid):
    check_auth({"Associate", "Client"})
    return success(public(get_or_404(watches, wid)), "object", 200)


@app.route("/watches", methods=["GET"])
def list_watches():
    check_auth({"Associate", "Client"})
    args = request.args
    rows = list(watches.values())
    if "model_id" in args:
        rows = [w for w in rows if w["model_id"] == args.get("model_id")]
    if "status" in args:
        rows = [w for w in rows if w["status"] == args.get("status")]
    if "authentication_status" in args:
        rows = [w for w in rows if w["authentication_status"] == args.get("authentication_status")]
    if "is_loaner" in args:
        want = args.get("is_loaner").lower() == "true"
        rows = [w for w in rows if w["is_loaner"] == want]
    page, pagination = paginate(rows)
    return success(page, "array", 200, pagination)


@app.route("/watches/<wid>/authenticate", methods=["POST"])
def authenticate_watch(wid):
    _uid, role = check_auth({"Associate"})
    watch = get_or_404(watches, wid)
    if watch["authentication_status"] != "UNVERIFIED":
        raise ApiError("ERR_INVALID_STATE", 409, "Watch is not UNVERIFIED")
    watch["authentication_status"] = "AUTHENTICATED"
    add_provenance(watch["id"], "AUTHENTICATED", "Watch authenticated", role)
    touch(watch, bump_version=True)
    return success(public(watch), "object", 200)


@app.route("/watches/<wid>/flag-inauthentic", methods=["POST"])
def flag_watch(wid):
    _uid, role = check_auth({"Associate"})
    watch = get_or_404(watches, wid)
    data = body()
    if watch["authentication_status"] not in ("UNVERIFIED", "AUTHENTICATED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Watch cannot be flagged")
    reason = data.get("reason")
    # Primary transition -> FLAGGED
    watch["authentication_status"] = "FLAGGED"
    detail = "Watch flagged inauthentic" + (f": {reason}" if reason else "")
    add_provenance(watch["id"], "FLAGGED", detail, role)
    touch(watch, bump_version=True)

    # CASCADE-B: void ACTIVE layaways on this watch (refund paid_cents)
    for plan in layaway_plans.values():
        if plan["watch_id"] == watch["id"] and plan["status"] == "ACTIVE":
            plan["status"] = "VOIDED"
            touch(plan)
            cust = customers.get(plan["customer_id"])
            if cust is not None:
                add_store_credit(cust, plan["paid_cents"])

    # CASCADE-B: reverse a settled TRADE_IN intake for this watch (clawback)
    if watch["source"] == "TRADE_IN":
        for offer in trade_in_offers.values():
            if offer["status"] == "SETTLED" and offer["resulting_watch_id"] == watch["id"]:
                offer["status"] = "REVERSED"
                touch(offer)
                cust = customers.get(offer["customer_id"])
                if cust is not None:
                    add_store_credit(cust, -offer["quoted_credit_cents"])

    # CASCADE-B: cancel open service tickets (RECEIVED/DIAGNOSED) on this watch
    for ticket in service_tickets.values():
        if ticket["watch_id"] == watch["id"] and ticket["status"] in ("RECEIVED", "DIAGNOSED"):
            ticket["status"] = "CANCELLED"
            touch(ticket)
            if watch["status"] == "IN_SERVICE":
                watch["status"] = "IN_STOCK"
                touch(watch, bump_version=False)

    return success(public(watch), "object", 200)


@app.route("/watches/<wid>/provenance", methods=["GET"])
def get_provenance(wid):
    check_auth({"Associate", "Client"})
    get_or_404(watches, wid)
    rows = [e for e in provenance_events.values() if e["watch_id"] == wid]
    page, pagination = paginate(rows)
    return success(page, "array", 200, pagination)


@app.route("/watches/<wid>/appraisals", methods=["POST"])
def create_appraisal(wid):
    _uid, role = check_auth({"Associate"})
    watch = get_or_404(watches, wid)
    data = body()
    purpose = check_enum(require(data, "purpose"), APPRAISAL_PURPOSES, "purpose")
    valuation_basis = check_enum(require(data, "valuation_basis"), VALUATION_BASES, "valuation_basis")
    # OCC: expected_watch_version is required
    if "expected_watch_version" not in data or data["expected_watch_version"] is None:
        raise ApiError("ERR_VERSION_REQUIRED", 400, "expected_watch_version is required")
    expected = data["expected_watch_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError("ERR_VALIDATION", 400, "expected_watch_version must be an integer")
    if expected != watch["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Watch version has advanced")

    model = watch_models.get(watch["model_id"], {})
    market, replacement, appraised = appraisal_valuation(
        model, watch["condition_grade"], watch["has_box_papers"], valuation_basis
    )
    ent = new_common()
    ent.update({
        "watch_id": watch["id"],
        "purpose": purpose,
        "valuation_basis": valuation_basis,
        "condition_grade_snapshot": watch["condition_grade"],
        "market_value_cents": market,
        "replacement_value_cents": replacement,
        "appraised_value_cents": appraised,
    })
    appraisals[ent["id"]] = ent
    watch["current_appraisal_id"] = ent["id"]
    add_provenance(watch["id"], "APPRAISED", "Watch appraised", role)
    touch(watch, bump_version=True)
    return success(public(ent), "object", 201)


@app.route("/watches/<wid>/appraisals", methods=["GET"])
def list_appraisals(wid):
    check_auth({"Associate", "Client"})
    get_or_404(watches, wid)
    rows = [a for a in appraisals.values() if a["watch_id"] == wid]
    page, pagination = paginate(rows)
    return success(page, "array", 200, pagination)


@app.route("/watches/<wid>/offer", methods=["POST"])
def offer_watch(wid):
    _uid, role = check_auth({"Associate"})
    watch = get_or_404(watches, wid)
    # priority 10: authenticated
    if watch["authentication_status"] != "AUTHENTICATED":
        raise ApiError("ERR_WATCH_NOT_AUTHENTICATED", 409, "Watch is not AUTHENTICATED")
    # priority 15: eligible waitlist candidate
    entry = select_waitlist_entry(watch["model_id"])
    if entry is None:
        raise ApiError("ERR_NO_ELIGIBLE_WAITLIST", 409, "No eligible waitlist entry")
    # priority 16: watch must be IN_STOCK
    if watch["status"] != "IN_STOCK":
        raise ApiError("ERR_WATCH_UNAVAILABLE", 409, "Watch is not IN_STOCK")
    do_offer(watch, entry, role)
    return success(public(entry), "object", 200)


# ===========================================================================
# Waitlist
# ===========================================================================
@app.route("/waitlist-entries", methods=["POST"])
def create_waitlist_entry():
    check_auth({"Associate", "Client"})
    data = body()
    customer_id = require(data, "customer_id")
    model_id = require(data, "model_id")
    priority_tier = data.get("priority_tier") or "STANDARD"
    check_enum(priority_tier, PRIORITY_TIERS, "priority_tier")
    deposit_cents = opt_nonneg_int(data, "deposit_cents", 0)
    if customer_id not in customers:
        raise ApiError("ERR_NOT_FOUND", 404, "customer_id not found")
    if model_id not in watch_models:
        raise ApiError("ERR_NOT_FOUND", 404, "model_id not found")
    # priority 6: duplicate non-terminal entry
    for w in waitlist_entries.values():
        if w["customer_id"] == customer_id and w["model_id"] == model_id and w["status"] in ("WAITING", "OFFERED"):
            raise ApiError("ERR_DUPLICATE_WAITLIST", 409, "Customer already holds a non-terminal entry")
    # priority 9: model lifecycle ACTIVE
    if watch_models[model_id]["lifecycle"] != "ACTIVE":
        raise ApiError("ERR_MODEL_DISCONTINUED", 409, "Model is DISCONTINUED")
    ent = new_common()
    ent.update({
        "customer_id": customer_id,
        "model_id": model_id,
        "priority_tier": priority_tier,
        "deposit_cents": deposit_cents,
        "allocated_watch_id": None,
        "offer_expires_at": None,
        "status": "WAITING",
    })
    waitlist_entries[ent["id"]] = ent
    return success(public(ent), "object", 201)


@app.route("/waitlist-entries/<eid>", methods=["GET"])
def get_waitlist_entry(eid):
    check_auth({"Associate", "Client"})
    return success(public(get_or_404(waitlist_entries, eid)), "object", 200)


@app.route("/waitlist-entries", methods=["GET"])
def list_waitlist_entries():
    check_auth({"Associate", "Client"})
    args = request.args
    rows = list(waitlist_entries.values())
    for key in ("customer_id", "model_id", "allocated_watch_id", "status"):
        if key in args:
            rows = [w for w in rows if w[key] == args.get(key)]
    page, pagination = paginate(rows)
    return success(page, "array", 200, pagination)


@app.route("/waitlist-entries/<eid>/accept", methods=["POST"])
def accept_waitlist_entry(eid):
    check_auth({"Associate", "Client"})
    entry = get_or_404(waitlist_entries, eid)
    if entry["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_STATE", 409, "Entry is not OFFERED")
    watch = watches.get(entry["allocated_watch_id"])
    expires = parse_dt(entry["offer_expires_at"]) if entry.get("offer_expires_at") else None
    if expires is None or clock_now() >= expires:
        # lazy expiry
        entry["status"] = "EXPIRED"
        entry["allocated_watch_id"] = None
        touch(entry)
        if watch is not None and watch["status"] == "OFFERED":
            watch["status"] = "IN_STOCK"
            touch(watch, bump_version=False)
        raise ApiError("ERR_OFFER_EXPIRED", 409, "Offer has expired")
    entry["status"] = "ALLOCATED"
    touch(entry)
    if watch is not None:
        watch["status"] = "RESERVED"
        touch(watch, bump_version=False)
    return success(public(entry), "object", 200)


@app.route("/waitlist-entries/<eid>/decline", methods=["POST"])
def decline_waitlist_entry(eid):
    check_auth({"Associate", "Client"})
    entry = get_or_404(waitlist_entries, eid)
    if entry["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_STATE", 409, "Entry is not OFFERED")
    watch = watches.get(entry["allocated_watch_id"])
    entry["status"] = "DECLINED"
    entry["allocated_watch_id"] = None
    touch(entry)
    if watch is not None and watch["status"] == "OFFERED":
        watch["status"] = "IN_STOCK"
        touch(watch, bump_version=False)
    return success(public(entry), "object", 200)


# ===========================================================================
# Service tickets
# ===========================================================================
def bench_conflict(watchmaker_id, new_start, new_end, exclude_id=None):
    buffer = timedelta(minutes=BENCH_BUFFER_MINUTES)
    for t in service_tickets.values():
        if t["id"] == exclude_id:
            continue
        if t["watchmaker_id"] != watchmaker_id:
            continue
        if t["status"] in ("COLLECTED", "CANCELLED"):
            continue
        es = parse_dt(t["appt_start"])
        ee = parse_dt(t["appt_end"])
        if not (new_start >= ee + buffer or es >= new_end + buffer):
            return True
    return False


def loaner_conflict(loaner_id, new_start, new_end, exclude_id=None):
    for t in service_tickets.values():
        if t["id"] == exclude_id:
            continue
        if t.get("loaner_watch_id") != loaner_id:
            continue
        if t["status"] in ("COLLECTED", "CANCELLED"):
            continue
        if not t.get("loan_start") or not t.get("loan_end"):
            continue
        ls = parse_dt(t["loan_start"])
        le = parse_dt(t["loan_end"])
        if new_start < le and ls < new_end:
            return True
    return False


@app.route("/service-tickets", methods=["POST"])
def create_service_ticket():
    check_auth({"Associate", "Client"})
    data = body()
    watch_id = require(data, "watch_id")
    customer_id = require(data, "customer_id")
    watchmaker_id = require(data, "watchmaker_id")
    service_type = check_enum(require(data, "service_type"), SERVICE_TYPES, "service_type")
    appt_start_raw = require(data, "appt_start")
    appt_end_raw = require(data, "appt_end")
    movement_complexity = data.get("movement_complexity") or "STANDARD"
    check_enum(movement_complexity, MOVEMENT_COMPLEXITIES, "movement_complexity")
    water_target = data.get("water_resistance_target_m")
    if water_target is not None:
        check_nonneg_int(water_target, "water_resistance_target_m")
    parts_cost_cents = opt_nonneg_int(data, "parts_cost_cents", 0)
    loaner_watch_id = data.get("loaner_watch_id")
    loan_start_raw = data.get("loan_start")
    loan_end_raw = data.get("loan_end")

    # existence (path/FK left-to-right)
    watch = watches.get(watch_id)
    if watch is None:
        raise ApiError("ERR_NOT_FOUND", 404, "watch_id not found")
    if customer_id not in customers:
        raise ApiError("ERR_NOT_FOUND", 404, "customer_id not found")
    if watchmaker_id not in watchmakers:
        raise ApiError("ERR_NOT_FOUND", 404, "watchmaker_id not found")
    if loaner_watch_id is not None and loaner_watch_id not in watches:
        raise ApiError("ERR_NOT_FOUND", 404, "loaner_watch_id not found")

    appt_start = parse_dt(appt_start_raw)
    appt_end = parse_dt(appt_end_raw)

    loan_start = loan_end = None
    if loaner_watch_id is not None:
        if loan_start_raw is None or loan_end_raw is None:
            raise ApiError("ERR_VALIDATION", 400, "loan_start and loan_end required with a loaner")
        loan_start = parse_dt(loan_start_raw)
        loan_end = parse_dt(loan_end_raw)

    # priority 7: watch must be IN_STOCK for service
    if watch["status"] != "IN_STOCK":
        raise ApiError("ERR_INVALID_STATE", 409, "Watch is not IN_STOCK")
    # priority 10: watch AUTHENTICATED
    if watch["authentication_status"] != "AUTHENTICATED":
        raise ApiError("ERR_WATCH_NOT_AUTHENTICATED", 409, "Watch is not AUTHENTICATED")
    # priority 12: bench availability
    if bench_conflict(watchmaker_id, appt_start, appt_end):
        raise ApiError("ERR_WATCHMAKER_UNAVAILABLE", 409, "Watchmaker bench unavailable")
    # priority 13: loaner availability
    if loaner_watch_id is not None and loaner_conflict(loaner_watch_id, loan_start, loan_end):
        raise ApiError("ERR_LOANER_UNAVAILABLE", 409, "Loaner unavailable")
    # priority 14: appt not in the past
    if appt_start < clock_now():
        raise ApiError("ERR_APPOINTMENT_IN_PAST", 422, "Appointment is back-dated")

    ent = new_common()
    ent.update({
        "watch_id": watch_id,
        "customer_id": customer_id,
        "watchmaker_id": watchmaker_id,
        "service_type": service_type,
        "movement_complexity": movement_complexity,
        "water_resistance_target_m": water_target,
        "parts_cost_cents": parts_cost_cents,
        "appt_start": fmt_dt(appt_start),
        "appt_end": fmt_dt(appt_end),
        "loaner_watch_id": loaner_watch_id,
        "loan_start": fmt_dt(loan_start) if loan_start else None,
        "loan_end": fmt_dt(loan_end) if loan_end else None,
        "quoted_cents": None,
        "amount_paid_cents": 0,
        "payment_status": "UNPAID",
        "status": "RECEIVED",
    })
    service_tickets[ent["id"]] = ent
    watch["status"] = "IN_SERVICE"
    touch(watch, bump_version=False)
    return success(public(ent), "object", 201)


@app.route("/service-tickets/<tid>", methods=["GET"])
def get_service_ticket(tid):
    check_auth({"Associate", "Client", "Watchmaker"})
    return success(public(get_or_404(service_tickets, tid)), "object", 200)


@app.route("/service-tickets", methods=["GET"])
def list_service_tickets():
    check_auth({"Associate", "Client", "Watchmaker"})
    args = request.args
    rows = list(service_tickets.values())
    for key in ("watch_id", "customer_id", "watchmaker_id", "loaner_watch_id", "status"):
        if key in args:
            rows = [t for t in rows if t.get(key) == args.get(key)]
    page, pagination = paginate(rows)
    return success(page, "array", 200, pagination)


@app.route("/service-tickets/<tid>/diagnose", methods=["POST"])
def diagnose_ticket(tid):
    check_auth({"Watchmaker"})
    ticket = get_or_404(service_tickets, tid)
    if ticket["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Ticket is not RECEIVED")
    ticket["quoted_cents"] = service_quote(ticket)
    ticket["status"] = "DIAGNOSED"
    touch(ticket)
    return success(public(ticket), "object", 200)


@app.route("/service-tickets/<tid>/finish", methods=["POST"])
def finish_ticket(tid):
    _uid, role = check_auth({"Watchmaker"})
    ticket = get_or_404(service_tickets, tid)
    if ticket["status"] != "DIAGNOSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Ticket is not DIAGNOSED")
    ticket["status"] = "READY"
    touch(ticket)
    add_provenance(ticket["watch_id"], "SERVICED", "Service completed", role)
    return success(public(ticket), "object", 200)


@app.route("/service-tickets/<tid>/collect", methods=["POST"])
def collect_ticket(tid):
    check_auth({"Associate", "Client"})
    ticket = get_or_404(service_tickets, tid)
    if ticket["status"] != "READY":
        raise ApiError("ERR_INVALID_STATE", 409, "Ticket is not READY")
    if ticket["payment_status"] != "PAID":
        raise ApiError("ERR_PAYMENT_NOT_COMPLETE", 409, "Payment is not complete")
    ticket["status"] = "COLLECTED"
    touch(ticket)
    watch = watches.get(ticket["watch_id"])
    if watch is not None and watch["status"] == "IN_SERVICE":
        watch["status"] = "IN_STOCK"
        touch(watch, bump_version=False)
    return success(public(ticket), "object", 200)


@app.route("/service-tickets/<tid>/payments", methods=["POST"])
def pay_ticket(tid):
    check_auth({"Associate", "Client"})
    ticket = get_or_404(service_tickets, tid)
    data = body()
    amount = req_nonneg_int(data, "amount_cents")
    if ticket["status"] not in ("DIAGNOSED", "READY"):
        raise ApiError("ERR_INVALID_STATE", 409, "Ticket must be quoted before payment")
    quoted = ticket["quoted_cents"] or 0
    if ticket["amount_paid_cents"] + amount > quoted:
        raise ApiError("ERR_OVERPAYMENT", 422, "Payment exceeds the quoted amount")
    ticket["amount_paid_cents"] += amount
    if ticket["amount_paid_cents"] == quoted:
        ticket["payment_status"] = "PAID"
    else:
        ticket["payment_status"] = "PARTIALLY_PAID"
    touch(ticket)
    return success(public(ticket), "object", 200)


# ===========================================================================
# Layaway plans
# ===========================================================================
@app.route("/layaway-plans", methods=["POST"])
def create_layaway_plan():
    check_auth({"Associate", "Client"})
    data = body()
    customer_id = require(data, "customer_id")
    watch_id = require(data, "watch_id")
    deposit_cents = req_nonneg_int(data, "deposit_cents")
    term_months = req_nonneg_int(data, "term_months")
    if term_months < 1:
        raise ApiError("ERR_VALIDATION", 400, "term_months must be at least 1")
    first_due_raw = require(data, "first_due_at")
    use_store_credit = opt_bool(data, "use_store_credit", False)

    customer = customers.get(customer_id)
    if customer is None:
        raise ApiError("ERR_NOT_FOUND", 404, "customer_id not found")
    watch = watches.get(watch_id)
    if watch is None:
        raise ApiError("ERR_NOT_FOUND", 404, "watch_id not found")
    first_due_at = parse_dt(first_due_raw)

    # priority 10: watch AUTHENTICATED
    if watch["authentication_status"] != "AUTHENTICATED":
        raise ApiError("ERR_WATCH_NOT_AUTHENTICATED", 409, "Watch is not AUTHENTICATED")
    # priority 16: watch IN_STOCK
    if watch["status"] != "IN_STOCK":
        raise ApiError("ERR_WATCH_UNAVAILABLE", 409, "Watch is not IN_STOCK")

    total_price_cents = watch["list_price_cents"]
    # priority 17: deposit floor
    deposit_floor = rhu(Decimal(total_price_cents) * MIN_DEPOSIT_RATE)
    if deposit_cents < deposit_floor:
        raise ApiError("ERR_DEPOSIT_TOO_LOW", 422, "Deposit below minimum")
    # priority 18: sufficient store credit when funding from balance
    if use_store_credit and customer["store_credit_cents"] < deposit_cents:
        raise ApiError("ERR_INSUFFICIENT_STORE_CREDIT", 422, "Insufficient store credit")

    financed = total_price_cents - deposit_cents
    per_installment = financed // term_months
    final_installment = financed - per_installment * (term_months - 1)
    paid_cents = deposit_cents

    ent = new_common()
    ent.update({
        "customer_id": customer_id,
        "watch_id": watch_id,
        "deposit_cents": deposit_cents,
        "use_store_credit": use_store_credit,
        "term_months": term_months,
        "first_due_at": fmt_dt(first_due_at),
        "total_price_cents": total_price_cents,
        "per_installment_cents": per_installment,
        "final_installment_cents": final_installment,
        "paid_cents": paid_cents,
        "remaining_cents": max(0, total_price_cents - paid_cents),
        "status": "ACTIVE",
    })
    layaway_plans[ent["id"]] = ent

    watch["status"] = "RESERVED"
    touch(watch, bump_version=False)
    if use_store_credit:
        add_store_credit(customer, -deposit_cents)
    add_provenance(watch_id, "LAYAWAY_RESERVED", "Watch reserved for layaway", request.headers.get("X-User-Role"))
    return success(public(ent), "object", 201)


@app.route("/layaway-plans/<pid>", methods=["GET"])
def get_layaway_plan(pid):
    check_auth({"Associate", "Client"})
    return success(public(get_or_404(layaway_plans, pid)), "object", 200)


@app.route("/layaway-plans", methods=["GET"])
def list_layaway_plans():
    check_auth({"Associate", "Client"})
    args = request.args
    rows = list(layaway_plans.values())
    for key in ("customer_id", "watch_id", "status"):
        if key in args:
            rows = [p for p in rows if p[key] == args.get(key)]
    page, pagination = paginate(rows)
    return success(page, "array", 200, pagination)


@app.route("/layaway-plans/<pid>/payments", methods=["POST"])
def pay_layaway_plan(pid):
    check_auth({"Associate", "Client"})
    plan = get_or_404(layaway_plans, pid)
    data = body()
    amount = req_nonneg_int(data, "amount_cents")
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Plan is not ACTIVE")
    if plan["paid_cents"] + amount > plan["total_price_cents"]:
        raise ApiError("ERR_OVERPAYMENT", 422, "Payment exceeds the total price")
    plan["paid_cents"] += amount
    plan["remaining_cents"] = max(0, plan["total_price_cents"] - plan["paid_cents"])
    if plan["paid_cents"] == plan["total_price_cents"]:
        plan["status"] = "PAID_OFF"
        plan["remaining_cents"] = 0
        # auto-fulfill
        plan["status"] = "FULFILLED"
        watch = watches.get(plan["watch_id"])
        if watch is not None and watch["status"] == "RESERVED":
            watch["status"] = "SOLD"
            touch(watch, bump_version=False)
    touch(plan)
    return success(public(plan), "object", 200)


@app.route("/layaway-plans/<pid>/default", methods=["POST"])
def default_layaway_plan(pid):
    check_auth({"Associate"})
    plan = get_or_404(layaway_plans, pid)
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Plan is not ACTIVE")
    grace_deadline = parse_dt(plan["first_due_at"]) + timedelta(days=DEFAULT_GRACE_DAYS)
    if clock_now() < grace_deadline:
        raise ApiError("ERR_INVALID_STATE", 409, "Grace period has not lapsed")
    plan["status"] = "DEFAULTED"
    touch(plan)
    # paid_cents forfeited (no refund). Free the watch.
    watch = watches.get(plan["watch_id"])
    if watch is not None and watch["status"] == "RESERVED":
        watch["status"] = "IN_STOCK"
        touch(watch, bump_version=False)
        auto_offer_after_free(watch, actor_role="system")
    return success(public(plan), "object", 200)


@app.route("/layaway-plans/<pid>/cancel", methods=["POST"])
def cancel_layaway_plan(pid):
    check_auth({"Associate", "Client"})
    plan = get_or_404(layaway_plans, pid)
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Plan is not ACTIVE")
    plan["status"] = "CANCELLED"
    touch(plan)
    watch = watches.get(plan["watch_id"])
    if watch is not None and watch["status"] == "RESERVED":
        watch["status"] = "IN_STOCK"
        touch(watch, bump_version=False)
    restock_fee = rhu(Decimal(plan["total_price_cents"]) * RESTOCK_FEE_RATE)
    refund = max(0, plan["paid_cents"] - restock_fee)
    customer = customers.get(plan["customer_id"])
    if customer is not None and refund > 0:
        add_store_credit(customer, refund)
    return success(public(plan), "object", 200)


# ===========================================================================
# Trade-in / consignment offers
# ===========================================================================
@app.route("/trade-in-offers", methods=["POST"])
def create_trade_in_offer():
    check_auth({"Associate"})
    data = body()
    customer_id = require(data, "customer_id")
    incoming_brand = require(data, "incoming_brand")
    incoming_reference = require(data, "incoming_reference")
    serial_number = require(data, "serial_number")
    est_model_msrp_cents = req_nonneg_int(data, "est_model_msrp_cents")
    condition_grade = check_enum(require(data, "condition_grade"), CONDITION_GRADES, "condition_grade")
    disposition = check_enum(require(data, "disposition"), DISPOSITIONS, "disposition")
    has_box_papers = opt_bool(data, "has_box_papers", False)
    if customer_id not in customers:
        raise ApiError("ERR_NOT_FOUND", 404, "customer_id not found")

    appraised_market, commission_rate_bps, quoted_credit = trade_in_valuation(
        est_model_msrp_cents, condition_grade, has_box_papers, disposition
    )
    ent = new_common()
    ent.update({
        "customer_id": customer_id,
        "incoming_brand": incoming_brand,
        "incoming_reference": incoming_reference,
        "serial_number": serial_number,
        "est_model_msrp_cents": est_model_msrp_cents,
        "condition_grade": condition_grade,
        "has_box_papers": has_box_papers,
        "disposition": disposition,
        "appraised_market_cents": appraised_market,
        "commission_rate_bps": commission_rate_bps,
        "quoted_credit_cents": quoted_credit,
        "resulting_watch_id": None,
        "status": "QUOTED",
    })
    trade_in_offers[ent["id"]] = ent
    return success(public(ent), "object", 201)


@app.route("/trade-in-offers/<oid>", methods=["GET"])
def get_trade_in_offer(oid):
    check_auth({"Associate", "Client"})
    return success(public(get_or_404(trade_in_offers, oid)), "object", 200)


@app.route("/trade-in-offers", methods=["GET"])
def list_trade_in_offers():
    check_auth({"Associate", "Client"})
    args = request.args
    rows = list(trade_in_offers.values())
    for key in ("customer_id", "resulting_watch_id", "status"):
        if key in args:
            rows = [o for o in rows if o.get(key) == args.get(key)]
    page, pagination = paginate(rows)
    return success(page, "array", 200, pagination)


@app.route("/trade-in-offers/<oid>/accept", methods=["POST"])
def accept_trade_in_offer(oid):
    check_auth({"Associate", "Client"})
    offer = get_or_404(trade_in_offers, oid)
    if offer["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Offer is not QUOTED")
    offer["status"] = "ACCEPTED"
    touch(offer)
    return success(public(offer), "object", 200)


@app.route("/trade-in-offers/<oid>/settle", methods=["POST"])
def settle_trade_in_offer(oid):
    _uid, role = check_auth({"Associate"})
    offer = get_or_404(trade_in_offers, oid)
    if offer["status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Offer is not ACCEPTED")
    customer = customers.get(offer["customer_id"])
    if offer["disposition"] == "CONSIGNMENT":
        if customer is None or not customer["kyc_verified"]:
            raise ApiError("ERR_KYC_REQUIRED", 409, "Consignment settlement requires KYC")
    # serial uniqueness against all watches
    if serial_exists(offer["serial_number"]):
        raise ApiError("ERR_SERIAL_DUPLICATE", 409, "serial_number already exists")

    is_trade_in = offer["disposition"] == "TRADE_IN"
    watch = new_common()
    watch.update({
        "model_id": None,
        "serial_number": offer["serial_number"],
        "condition_grade": offer["condition_grade"],
        "has_box_papers": offer["has_box_papers"],
        "list_price_cents": offer["appraised_market_cents"],
        "acquisition_cost_cents": None,
        "is_loaner": False,
        "source": "TRADE_IN" if is_trade_in else "CONSIGNMENT",
        "authentication_status": "UNVERIFIED",
        "status": "IN_STOCK" if is_trade_in else "CONSIGNED",
        "current_appraisal_id": None,
    })
    watches[watch["id"]] = watch
    offer["resulting_watch_id"] = watch["id"]
    offer["status"] = "SETTLED"
    touch(offer)
    if customer is not None:
        add_store_credit(customer, offer["quoted_credit_cents"])
    add_provenance(watch["id"], "TRADE_IN_INTAKE", "Watch minted from trade-in/consignment settlement", role)
    return success(public(offer), "object", 200)


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    check_auth({"Associate"})
    data = body()
    to_iso = require(data, "to_iso8601")
    CLOCK["now"] = parse_dt(to_iso)
    return success({}, "object", 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
