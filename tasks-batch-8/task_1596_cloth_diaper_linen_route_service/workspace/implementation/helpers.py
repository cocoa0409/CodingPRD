"""Validation, auth, and domain/calculation helpers.

Every calculation follows PRD §2.6 / §3 exactly: integer cents, per-line
round-half-up before summing, Decimal arithmetic, pinned constants.
"""

import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import errors
from db import db, clock_now, clock_today, touch

# ---------------------------------------------------------------------------
# Constants (PRD §3)
# ---------------------------------------------------------------------------

SIZES = ["NEWBORN", "SMALL", "MEDIUM", "LARGE", "XL"]
WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
ROLES = {"PlatformAdmin", "Customer", "RouteDriver", "PlantOperator", "BillingAdmin"}

TARE_G = {"NEWBORN": 28, "SMALL": 34, "MEDIUM": 40, "LARGE": 46, "XL": 52}
REPLACEMENT_COST_CENTS = {"NEWBORN": 250, "SMALL": 275, "MEDIUM": 300, "LARGE": 325, "XL": 350}
SOIL_FACTOR_MILLI = 2500
VARIANCE_THRESHOLD_PCT = Decimal("10.00")
ROUTE_CAPACITY_ITEMS = 4000
STOP_BUFFER_MIN = 15
MIN_NOTICE_DAYS = 3
MAX_PAUSE_DAYS = 28
MIN_DOSE_ML = 60
MAX_DOSE_ML = 900
SOIL_MULT = {"LIGHT": Decimal("0.9"), "NORMAL": Decimal("1.0"), "HEAVY": Decimal("1.25")}
HARDNESS_MULT = {"SOFT": Decimal("0.95"), "MEDIUM": Decimal("1.0"), "HARD": Decimal("1.15")}
SURCHARGE_THRESHOLD = Decimal("0.50")
SURCHARGE_MULT = Decimal("1.10")

STOP_TERMINAL = {"COMPLETED", "SKIPPED", "FORFEITED", "RESCHEDULED"}

_MISSING = object()
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# Request body / field validation (validation pipeline stage 1: ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------

def parse_body():
    data = request.get_json(silent=True)
    if data is None:
        if request.data and request.data.strip():
            raise errors.bad_request("Malformed JSON body")
        return {}
    if not isinstance(data, dict):
        raise errors.bad_request("Body must be a JSON object")
    return data


def req_str(body, name):
    v = body.get(name, _MISSING)
    if v is _MISSING or not isinstance(v, str) or v == "":
        raise errors.bad_request("Field '%s' is required and must be a non-empty string" % name)
    return v


def opt_str(body, name, default=None):
    v = body.get(name, _MISSING)
    if v is _MISSING or v is None:
        return default
    if not isinstance(v, str):
        raise errors.bad_request("Field '%s' must be a string" % name)
    return v


def _check_int(v, name):
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.bad_request("Field '%s' must be an integer" % name)
    return v


def req_int(body, name, lo=None, hi=None):
    v = body.get(name, _MISSING)
    if v is _MISSING:
        raise errors.bad_request("Field '%s' is required" % name)
    _check_int(v, name)
    if lo is not None and v < lo:
        raise errors.bad_request("Field '%s' is below its minimum" % name)
    if hi is not None and v > hi:
        raise errors.bad_request("Field '%s' exceeds its maximum" % name)
    return v


def opt_int(body, name, default, lo=None, hi=None):
    v = body.get(name, _MISSING)
    if v is _MISSING or v is None:
        return default
    return req_int(body, name, lo, hi)


def req_enum(body, name, members):
    v = body.get(name, _MISSING)
    if v is _MISSING or not isinstance(v, str) or v not in members:
        raise errors.bad_request("Field '%s' must be one of %s" % (name, sorted(members)))
    return v


def opt_enum(body, name, members, default):
    v = body.get(name, _MISSING)
    if v is _MISSING or v is None:
        return default
    return req_enum(body, name, members)


def req_date(body, name):
    v = body.get(name, _MISSING)
    if v is _MISSING or not isinstance(v, str) or not _DATE_RE.match(v):
        raise errors.bad_request("Field '%s' must be an ISO date (YYYY-MM-DD)" % name)
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise errors.bad_request("Field '%s' must be an ISO date (YYYY-MM-DD)" % name)


def req_bool(body, name):
    v = body.get(name, _MISSING)
    if v is _MISSING or not isinstance(v, bool):
        raise errors.bad_request("Field '%s' must be a boolean" % name)
    return v


def opt_bool(body, name, default):
    v = body.get(name, _MISSING)
    if v is _MISSING or v is None:
        return default
    if not isinstance(v, bool):
        raise errors.bad_request("Field '%s' must be a boolean" % name)
    return v


def parse_iso8601_to_utc(s):
    if not isinstance(s, str) or not s.strip():
        raise errors.bad_request("Field 'to_iso8601' must be an ISO 8601 timestamp")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        raise errors.bad_request("Field 'to_iso8601' must be an ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_pagination():
    """limit: default 10, min 1, max 100. offset: default 0, min 0."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise errors.bad_request("Query parameter 'limit' must be an integer")
        if str(limit_raw).strip() not in (str(limit), "+" + str(limit)):
            raise errors.bad_request("Query parameter 'limit' must be an integer")
        if limit < 1 or limit > 100:
            raise errors.bad_request("Query parameter 'limit' must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise errors.bad_request("Query parameter 'offset' must be an integer")
        if str(offset_raw).strip() not in (str(offset), "+" + str(offset)):
            raise errors.bad_request("Query parameter 'offset' must be an integer")
        if offset < 0:
            raise errors.bad_request("Query parameter 'offset' must be >= 0")
    return limit, offset


# ---------------------------------------------------------------------------
# Auth (pipeline stages 2-3)
# ---------------------------------------------------------------------------

def actor():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not uid.strip():
        raise errors.ApiError(errors.ERR_UNAUTHENTICATED, 401, "Missing or malformed X-User-ID header")
    if not role or role not in ROLES:
        raise errors.ApiError(errors.ERR_UNAUTHENTICATED, 401, "Missing or malformed X-User-Role header")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise errors.ApiError(errors.ERR_FORBIDDEN, 403, "Role %s is not permitted for this endpoint" % role)


def chain_customer_id(kind, r):
    """Resolve the owning customer id for a resource, or None if unchained."""
    if r is None:
        return None
    if kind == "customers":
        return r.get("id")
    if kind == "subscriptions":
        return r.get("customer_id")
    if kind in ("service_pauses", "starter_kits", "inventory_swaps", "lost_item_cases", "invoices"):
        sub = db["subscriptions"].get(r.get("subscription_id"))
        return sub.get("customer_id") if sub else None
    if kind == "route_stops":
        sub = db["subscriptions"].get(r.get("subscription_id"))
        return sub.get("customer_id") if sub else None
    if kind == "soiled_intakes":
        stop = db["route_stops"].get(r.get("route_stop_id"))
        sub = db["subscriptions"].get(stop.get("subscription_id")) if stop else None
        return sub.get("customer_id") if sub else None
    return None


def customer_owns_or_forbid(role, uid, owner_customer_id):
    if role == "Customer" and owner_customer_id is not None and owner_customer_id != uid:
        raise errors.ApiError(errors.ERR_FORBIDDEN, 403, "Resource is outside the caller's customer chain")


# ---------------------------------------------------------------------------
# List helper
# ---------------------------------------------------------------------------

def list_resources(kind, filters, role, uid, limit, offset):
    """filters: list of (field, value) with value None meaning 'not filtered'."""
    items = sorted(db[kind].values(), key=lambda r: (r["created_at"], r["_seq"]))
    for field, value in filters:
        if value is None:
            continue
        items = [r for r in items if r.get(field) == value]
    if role == "Customer":
        items = [r for r in items
                 if chain_customer_id(kind, r) is None or chain_customer_id(kind, r) == uid]
    total = len(items)
    return items[offset:offset + limit], total


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_or_404(kind, rid):
    r = db[kind].get(rid)
    if r is None:
        raise errors.ApiError(errors.ERR_NOT_FOUND, 404, "Resource %s not found" % rid)
    return r


def ref_or_404(kind, rid):
    r = db[kind].get(rid)
    if r is None:
        raise errors.ApiError(errors.ERR_REFERENCE_NOT_FOUND, 404, "Referenced %s id %s does not exist" % (kind, rid))
    return r


def kit_for_subscription(subscription_id):
    for k in db["starter_kits"].values():
        if k["subscription_id"] == subscription_id:
            return k
    return None


def pool_for_size(size_code):
    for p in db["inventory_pools"].values():
        if p["size_code"] == size_code:
            return p
    return None


def available_units(pool):
    return pool["on_hand_units"] - pool["reserved_units"]


# ---------------------------------------------------------------------------
# Calculations (PRD §3)
# ---------------------------------------------------------------------------

def round_half_up_int(d):
    return int(Decimal(d).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def kit_item_count(plan):
    quota = plan["weekly_quota"]
    pct = plan["kit_reserve_pct"]
    reserve = -(-(quota * pct) // 100)  # ceil on the reserve
    return quota + reserve


def per_item_soiled_g(size_code):
    # tare_g * SOIL_FACTOR_MILLI / 1000  (all sizes yield integers)
    return (TARE_G[size_code] * SOIL_FACTOR_MILLI) // 1000


def reconcile_intake(intake, stop, sub, plan):
    """Recompute expected_weight_g, variance_pct, verified_count, status."""
    per_item = per_item_soiled_g(sub["current_size_code"])
    expected = stop["clean_items_delivered"] * per_item
    scale = intake["scale_weight_g"]
    intake["expected_weight_g"] = expected
    if expected > 0:
        var = (Decimal(abs(scale - expected)) * Decimal(10000) / Decimal(expected))
        var = var.quantize(Decimal("1"), rounding=ROUND_HALF_UP) / Decimal(100)
        intake["variance_pct"] = float(var)
    else:
        var = None
        intake["variance_pct"] = None
    reconciled = (var is not None and var <= VARIANCE_THRESHOLD_PCT)
    intake["status"] = "RECONCILED" if reconciled else "DISPUTED"
    if plan["weight_policy"] == "WEIGHT_BASIS":
        intake["verified_count"] = round_half_up_int(Decimal(scale) / Decimal(per_item))
    else:  # COUNT_BASIS
        intake["verified_count"] = stop["clean_items_delivered"]


def service_days_between(zone, start, end):
    """Dates d with start <= d < end whose weekday is a zone service weekday."""
    days = []
    d = start
    while d < end:
        if WEEKDAYS[d.weekday()] in zone["service_weekdays"]:
            days.append(d)
        d += timedelta(days=1)
    return days


def billing_weeks_touched(start, end):
    """Distinct Monday-Sunday billing weeks intersecting [start, end)."""
    weeks = set()
    d = start
    while d < end:
        weeks.add(d - timedelta(days=d.weekday()))
        d += timedelta(days=1)
    return len(weeks)


def pause_final_credit_cents(pause, plan, zone):
    """FINAL proration: per paused service day, round each line, then sum."""
    per_day = round_half_up_int(
        Decimal(plan["weekly_fee_cents"]) / Decimal(zone["service_days_per_week"]))
    return per_day * len(service_days_between(zone, pause["_start_date"], pause["_end_date"]))


def pause_credit_for_period(pause, plan, zone, period_start, period_end):
    start = max(pause["_start_date"], period_start)
    end = min(pause["_end_date"], period_end)
    if start >= end:
        return 0
    per_day = round_half_up_int(
        Decimal(plan["weekly_fee_cents"]) / Decimal(zone["service_days_per_week"]))
    return per_day * len(service_days_between(zone, start, end))


def compute_invoice_lines(sub, period_start, period_end):
    plan = db["subscription_plans"][sub["subscription_plan_id"]]
    zone = db["service_zones"][sub["service_zone_id"]]
    base_fee = plan["weekly_fee_cents"]
    overage_items = 0
    for intake in db["soiled_intakes"].values():
        if intake["status"] not in ("RECONCILED", "RESOLVED"):
            continue
        stop = db["route_stops"].get(intake["route_stop_id"])
        if stop is None or stop["subscription_id"] != sub["id"]:
            continue
        route = db["routes"].get(stop["route_id"])
        if route is None:
            continue
        if period_start <= route["_route_date"] < period_end:
            over = max(intake["verified_count"] - plan["weekly_quota"], 0)
            over = min(over, plan["overage_cap_items"])
            overage_items += over
    overage_cents = overage_items * plan["overage_rate_cents"]
    pause_credit = 0
    for pause in db["service_pauses"].values():
        if pause["subscription_id"] != sub["id"]:
            continue
        if pause["status"] not in ("SCHEDULED", "ACTIVE", "COMPLETED"):
            continue
        pause_credit += pause_credit_for_period(pause, plan, zone, period_start, period_end)
    total = base_fee + overage_cents - pause_credit
    if total < 0:
        total = 0
    return {
        "base_fee_cents": base_fee,
        "overage_cents": overage_cents,
        "pause_credit_cents": pause_credit,
        "total_cents": total,
    }


def compute_case_charge(case, customer):
    pool = db["inventory_pools"].get(case["inventory_pool_id"])
    if case["case_type"] == "LOST":
        cost = REPLACEMENT_COST_CENTS[pool["size_code"]] if pool else 0
        age_days = (clock_today() - case["_first_issued_date"]).days
        if age_days <= 90:
            pct = Decimal("1.00")
        elif age_days <= 180:
            pct = Decimal("0.60")
        else:
            pct = Decimal("0.30")
        return round_half_up_int(Decimal(case["item_count"]) * Decimal(cost) * pct)
    else:  # DAMAGED
        charged = customer["deposit_charged_cents"]
        if charged == 0:
            ratio = Decimal("0")
        else:
            ratio = Decimal(customer["deposit_applied_cents"]) / Decimal(charged)
        mult = SURCHARGE_MULT if ratio > SURCHARGE_THRESHOLD else Decimal("1.00")
        return round_half_up_int(
            Decimal(case["assessed_fee_cents"]) * Decimal(case["item_count"]) * mult)


def compute_dosing(batch, formula):
    load_kg = Decimal(batch["total_load_g"]) / Decimal(1000)
    raw = (Decimal(formula["base_detergent_ml_per_kg"]) * load_kg
           * SOIL_MULT[batch["soil_level"]] * HARDNESS_MULT[batch["water_hardness"]])
    detergent = round_half_up_int(raw)
    detergent = max(MIN_DOSE_ML, min(MAX_DOSE_ML, detergent))
    sanitizer = round_half_up_int(Decimal(formula["sanitizer_ml_per_kg"]) * load_kg)
    return detergent, sanitizer


# ---------------------------------------------------------------------------
# Route manifest / cascades
# ---------------------------------------------------------------------------

def recompute_route_manifest(route):
    stops = [s for s in db["route_stops"].values() if s["route_id"] == route["id"]]
    route["planned_stop_count"] = sum(1 for s in stops if s["status"] == "PLANNED")
    route["completed_stop_count"] = sum(1 for s in stops if s["status"] == "COMPLETED")
    route["total_clean_items_delivered"] = sum(
        s["clean_items_delivered"] for s in stops if s["status"] == "COMPLETED")
    route["total_soiled_bags_collected"] = sum(
        s["soiled_bags_collected"] for s in stops if s["status"] == "COMPLETED")


def touch_route(route):
    recompute_route_manifest(route)
    touch(route)


def skip_stop(stop):
    stop["status"] = "SKIPPED"
    touch(stop)
    route = db["routes"].get(stop["route_id"])
    if route is not None:
        touch_route(route)


def window_conflicts(route_id, w_start, w_end):
    """True when the window plus the 15-minute buffer collides with any
    non-terminal stop on the route. Exactly 15 minutes of gap is allowed."""
    for s in db["route_stops"].values():
        if s["route_id"] != route_id or s["status"] in STOP_TERMINAL:
            continue
        if w_start >= s["window_end_minutes"] + STOP_BUFFER_MIN:
            continue
        if w_end + STOP_BUFFER_MIN <= s["window_start_minutes"]:
            continue
        return True
    return False


def cutoff_instant(route, zone):
    midnight = datetime.combine(route["_route_date"], datetime.min.time(), tzinfo=timezone.utc)
    return midnight - timedelta(hours=zone["stop_cutoff_hours"])


def process_clock_cascades():
    """Apply due pause transitions after a logical-clock set (PRD §2.5/§3.7)."""
    today = clock_today()
    # SCHEDULED -> ACTIVE for windows containing the new date
    for pause in sorted(db["service_pauses"].values(), key=lambda p: (p["created_at"], p["_seq"])):
        if pause["status"] != "SCHEDULED":
            continue
        if pause["_start_date"] <= today < pause["_end_date"]:
            pause["status"] = "ACTIVE"
            touch(pause)
            sub = db["subscriptions"].get(pause["subscription_id"])
            if sub is not None and sub["service_status"] == "ACTIVE":
                sub["service_status"] = "PAUSED"
                touch(sub)
                for stop in db["route_stops"].values():
                    if stop["subscription_id"] != sub["id"] or stop["status"] != "PLANNED":
                        continue
                    route = db["routes"].get(stop["route_id"])
                    if route is None:
                        continue
                    if pause["_start_date"] <= route["_route_date"] < pause["_end_date"]:
                        skip_stop(stop)
    # ACTIVE -> COMPLETED once the date reaches end_date
    for pause in sorted(db["service_pauses"].values(), key=lambda p: (p["created_at"], p["_seq"])):
        if pause["status"] != "ACTIVE":
            continue
        if today >= pause["_end_date"]:
            sub = db["subscriptions"].get(pause["subscription_id"])
            plan = db["subscription_plans"].get(sub["subscription_plan_id"]) if sub else None
            zone = db["service_zones"].get(sub["service_zone_id"]) if sub else None
            pause["status"] = "COMPLETED"
            if plan is not None and zone is not None:
                pause["final_credit_cents"] = pause_final_credit_cents(pause, plan, zone)
            touch(pause)
            if sub is not None and sub["service_status"] == "PAUSED":
                other_active = any(
                    p["subscription_id"] == sub["id"] and p["status"] == "ACTIVE"
                    for p in db["service_pauses"].values())
                if not other_active:
                    sub["service_status"] = "ACTIVE"
                    touch(sub)


def deny_swap_with_compensation(swap):
    pool = pool_for_size(swap["to_size_code"])
    if pool is not None:
        pool["reserved_units"] -= swap["quantity"]
        pool["on_hand_units"] += swap["quantity"]
        touch(pool)
    swap["status"] = "DENIED"
    touch(swap)


# ---------------------------------------------------------------------------
# Shared view helpers and endpoint constant sets
# ---------------------------------------------------------------------------

from envelope import ok, ok_list  # noqa: E402

CUSTOMER_EVENT_TYPES = {"ACTIVATE", "SUSPEND", "REINSTATE", "CLOSE"}
SUBSCRIPTION_EVENT_TYPES = {"ACTIVATE", "SUSPEND_SERVICE", "RESUME_SERVICE", "TERMINATE"}
KIT_EVENT_TYPES = {"ISSUE", "RETURN", "SETTLE"}
ROUTE_EVENT_TYPES = {"LOCK", "START", "COMPLETE", "CANCEL"}
STOP_EVENT_TYPES = {"MISS", "SKIP", "RESCHEDULE", "FORFEIT"}
INTAKE_EVENT_TYPES = {"DISPUTE", "REWEIGH", "RESOLVE"}
BATCH_EVENT_TYPES = {"START_WASH", "RECORD_SANITIZATION", "RELEASE", "REWASH", "QUARANTINE"}
SWAP_EVENT_TYPES = {"STAGE", "COMPLETE", "DENY", "CANCEL"}
CASE_EVENT_TYPES = {"CHARGE", "DISPUTE", "SETTLE", "WAIVE"}
INVOICE_EVENT_TYPES = {"ISSUE", "PAY", "MARK_PAST_DUE", "VOID", "REISSUE", "WRITE_OFF"}

ALL_ROLES = {"PlatformAdmin", "Customer", "RouteDriver", "PlantOperator", "BillingAdmin"}

SUB_TERMINAL = {"TERMINATED"}
PAUSE_TERMINAL = {"COMPLETED", "CANCELLED"}
KIT_TERMINAL = {"SETTLED"}
SWAP_TERMINAL = {"COMPLETED", "DENIED", "CANCELLED"}
ROUTE_TERMINAL = {"COMPLETED", "CANCELLED"}
INTAKE_TERMINAL = {"RESOLVED"}
BATCH_TERMINAL = {"RELEASED", "QUARANTINED"}
CASE_TERMINAL = {"SETTLED", "WAIVED"}
INVOICE_TERMINAL = {"PAID", "VOID", "WRITTEN_OFF"}


def serialize(kind, r):
    from db import public
    out = public(r)
    if kind == "inventory_pools":
        out["available_units"] = available_units(r)
    return out


def do_get_one(kind, rid):
    uid, role = actor()
    require_role(role, ALL_ROLES)
    r = get_or_404(kind, rid)
    customer_owns_or_forbid(role, uid, chain_customer_id(kind, r))
    return ok(serialize(kind, r))


def do_list(kind, filters):
    limit, offset = parse_pagination()
    uid, role = actor()
    require_role(role, ALL_ROLES)
    items, total = list_resources(kind, filters, role, uid, limit, offset)
    return ok_list([serialize(kind, r) for r in items], limit, offset, total)


def auto_lost_case(subscription_id, pool_id, size_code, count, first_issued_date):
    """Auto-created OPEN LostItemCase for kit-return / swap shortages (PRD §3.6/§3.8)."""
    from db import new_resource
    if pool_id is None:
        pool = pool_for_size(size_code)
        pool_id = pool["id"] if pool is not None else None
    case = new_resource({
        "subscription_id": subscription_id,
        "inventory_pool_id": pool_id,
        "case_type": "LOST",
        "item_count": count,
        "first_issued_date": first_issued_date,
        "assessed_fee_cents": None,
        "charge_cents": None,
        "status": "OPEN",
        "_first_issued_date": date.fromisoformat(first_issued_date),
    })
    db["lost_item_cases"][case["id"]] = case
    return case
