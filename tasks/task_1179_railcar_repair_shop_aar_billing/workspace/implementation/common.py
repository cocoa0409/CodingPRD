"""Shared helpers: logical time, response envelope, auth, validation,
serialization, and the PRD calculation rules."""
import re
import secrets
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR
from functools import wraps

from flask import request, jsonify, g

import db
from errors import ApiError

# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def iso(dt):
    """ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now():
    return db.clock_now()


def now_iso():
    return iso(db.clock_now())


def parse_dt(s):
    if not isinstance(s, str):
        raise ValueError("not a datetime string")
    s2 = s.strip()
    if s2.endswith("Z"):
        s2 = s2[:-1] + "+00:00"
    dt = datetime.fromisoformat(s2)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    if not isinstance(s, str):
        raise ValueError("not a date string")
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


def delta_seconds(a, b):
    d = b - a
    return Decimal(d.days * 86400 + d.seconds) + Decimal(d.microseconds) / Decimal(1000000)


def hours_between(a, b, places=2):
    """Fractional hours from a to b at the given decimal precision (half-up)."""
    q = Decimal(1).scaleb(-places)
    return (delta_seconds(a, b) / Decimal(3600)).quantize(q, rounding=ROUND_HALF_UP)


def rhu_cents(x):
    """Round half up to whole cents -> int."""
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Response envelope (PRD section 2.2)
# ---------------------------------------------------------------------------

def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def ok(data, code=200, rtype="object", pagination=None):
    meta = {"api_request_id": _request_id(), "api_request_timestamp": now_iso()}
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": rtype, "data": data}
    resp = jsonify(body)
    resp.status_code = code
    return resp


def error_body(error_id, message):
    return {
        "meta": {"api_request_id": _request_id(), "api_request_timestamp": now_iso()},
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# ---------------------------------------------------------------------------
# Auth (PRD section 2.1)
# ---------------------------------------------------------------------------

DECLARED_ROLES = {
    "ShopAdmin", "YardClerk", "CarInspector", "RepairForeman",
    "QualityInspector", "PartsClerk", "BillingClerk",
    "CarOwnerRep", "HandlingLineRep",
}


def auth(*allowed):
    """Validate X-User-ID / X-User-Role, then endpoint role permission."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not isinstance(uid, str) or not role or role not in DECLARED_ROLES:
                raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                               "X-User-ID and X-User-Role headers are required and the role must be declared")
            if "Any" not in allowed and role not in allowed:
                raise ApiError("ERR_FORBIDDEN_FOR_ROLE", 403,
                               "Role %s is not permitted for this endpoint" % role)
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco


# ---------------------------------------------------------------------------
# Request body validation (ERR_INVALID_REQUEST / references)
# ---------------------------------------------------------------------------

def invalid_request(msg):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def get_body(required=True):
    body = request.get_json(silent=True)
    if body is None:
        if required:
            raise invalid_request("Request body must be a JSON object")
        return {}
    if not isinstance(body, dict):
        raise invalid_request("Request body must be a JSON object")
    return body


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_field(body, name):
    if name not in body or body[name] is None:
        raise invalid_request("Missing required field: %s" % name)
    return body[name]


def req_str(body, name):
    v = req_field(body, name)
    if not isinstance(v, str):
        raise invalid_request("Field %s must be a string" % name)
    return v


def opt_str(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    if not isinstance(body[name], str):
        raise invalid_request("Field %s must be a string" % name)
    return body[name]


def req_int(body, name):
    v = req_field(body, name)
    if not _is_int(v):
        raise invalid_request("Field %s must be an integer" % name)
    return v


def opt_int(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    if not _is_int(body[name]):
        raise invalid_request("Field %s must be an integer" % name)
    return body[name]


def req_num(body, name):
    v = req_field(body, name)
    if not _is_num(v):
        raise invalid_request("Field %s must be a number" % name)
    return v


def req_bool(body, name):
    v = req_field(body, name)
    if not isinstance(v, bool):
        raise invalid_request("Field %s must be a boolean" % name)
    return v


def opt_bool(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    if not isinstance(body[name], bool):
        raise invalid_request("Field %s must be a boolean" % name)
    return body[name]


def req_enum(body, name, allowed, error=None):
    v = req_field(body, name)
    if not isinstance(v, str) or v not in allowed:
        if error is not None:
            raise error
        raise invalid_request("Field %s must be one of %s" % (name, sorted(allowed)))
    return v


# ---------------------------------------------------------------------------
# Entity access
# ---------------------------------------------------------------------------

def base_fields():
    ts = now_iso()
    return {"id": db.new_id(), "created_at": ts, "updated_at": ts,
            "version": 1, "_seq": db.next_seq()}


def touch(entity):
    entity["version"] += 1
    entity["updated_at"] = now_iso()


def get_or_404(collection, entity_id, label="Resource"):
    e = db.STORE[collection].get(entity_id)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", 404, "%s %s not found" % (label, entity_id))
    return e


def ref_or_404(collection, entity_id, label="Referenced resource"):
    e = db.STORE[collection].get(entity_id)
    if e is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", 404,
                       "%s %s does not exist" % (label, entity_id))
    return e


def public(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def sort_items(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def paginate(items):
    """limit/offset per PRD 2.3; adds pagination fields to meta."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise invalid_request("limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise invalid_request("offset must be an integer")
        if offset < 0:
            raise invalid_request("offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    meta = {"limit": limit, "offset": offset, "total_count": total,
            "has_more": (offset + limit) < total}
    return page, meta


def list_response(items):
    page, meta = paginate(items)
    return ok(page, code=200, rtype="array", pagination=meta)


# ---------------------------------------------------------------------------
# Derived fields and calculations (PRD sections 2.5-2.10, 3.x)
# ---------------------------------------------------------------------------

def part_available(p):
    return p["on_hand_qty"] - p["reserved_qty"]


def part_status(p):
    if p["on_hand_qty"] == 0:
        return "DEPLETED"
    if part_available(p) <= p["reorder_threshold"]:
        return "REORDER_NEEDED"
    return "ACTIVE"


def car_owner_status(owner):
    shop = db.STORE["shops"].get(owner["shop_id"])
    threshold = shop["owner_watch_threshold_cents"] if shop else 1000000
    return "CREDIT_WATCH" if owner["outstanding_balance_cents"] > threshold else "ACTIVE"


def shop_booked_seconds_today(shop):
    """Seconds of RESERVED/OCCUPIED slot windows overlapping the current
    logical-clock calendar day (UTC), half-open [starts_at, ends_at)."""
    n = now()
    day_start = n.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    booked = Decimal(0)
    for s in db.STORE["shop_slots"].values():
        if s["shop_id"] != shop["id"] or s["status"] not in ("RESERVED", "OCCUPIED"):
            continue
        st = parse_dt(s["starts_at"])
        en = parse_dt(s["ends_at"])
        lo = st if st > day_start else day_start
        hi = en if en < day_end else day_end
        if hi > lo:
            booked += delta_seconds(lo, hi)
    return booked


def shop_posture(shop):
    booked = shop_booked_seconds_today(shop)
    capacity = Decimal(shop["stalls"] * shop["stall_daily_hours"] * 3600)
    if booked >= capacity:
        return "FULL"
    if booked * 100 >= Decimal(85) * capacity:
        return "CONSTRAINED"
    return "OPEN"


def shop_out(shop):
    d = public(shop)
    d["current_posture"] = shop_posture(shop)
    return d


def car_owner_out(o):
    d = public(o)
    d["status"] = car_owner_status(o)
    return d


def part_out(p):
    d = public(p)
    d["available_qty"] = part_available(p)
    d["status"] = part_status(p)
    return d


def resolve_price_entry(shop_id, job_code, on_date):
    """At most one match: effective windows never overlap (PRD 2.6)."""
    target = on_date.isoformat()
    for e in db.STORE["price_entries"].values():
        if (e["shop_id"] == shop_id and e["job_code"] == job_code
                and e["effective_from"] <= target <= e["effective_to"]):
            return e
    return None


def estimate_line(line_planned_parts, entry):
    labor = rhu_cents(Decimal(str(entry["standard_labor_hours"]))
                      * Decimal(entry["labor_rate_cents_per_hour"]))
    material = 0
    for p in line_planned_parts:
        part = db.STORE["parts"][p["part_item_id"]]
        material += p["quantity"] * part["unit_price_cents"]
    return labor, material, labor + material


def final_line_pricing(line, work_order, completion_date):
    entry = resolve_price_entry_by_id_or_gap(line, work_order, completion_date)
    rate = (entry["mobile_labor_rate_cents_per_hour"]
            if work_order["routing"] == "MOBILE"
            else entry["labor_rate_cents_per_hour"])
    labor = rhu_cents(Decimal(str(line["actual_labor_hours"])) * Decimal(rate))
    material = 0
    for a in (line["actual_parts"] or []):
        part = db.STORE["parts"][a["part_item_id"]]
        material += a["quantity"] * part["unit_price_cents"]
    return labor, material, labor + material


def resolve_price_entry_by_id_or_gap(line, work_order, completion_date):
    railcar = db.STORE["railcars"][work_order["railcar_id"]]
    entry = resolve_price_entry(railcar["shop_id"], line["job_code"], completion_date)
    if entry is None:
        raise ApiError("ERR_PRICE_MASTER_GAP", 422,
                       "No price master entry effective for job_code %s at %s"
                       % (line["job_code"], completion_date.isoformat()))
    return entry


DEFECT_GROUPS = {"WHEELSET", "AIR_HOSE", "COUPLER", "SAFETY_APPLIANCE",
                 "STRUCTURAL", "BRAKE_BEAM", "DOOR", "OTHER"}
CAUSE_CODES = {"WEAR", "HANDLING_DAMAGE", "ACCIDENT", "UNKNOWN"}
SEVERITIES = {"MINOR", "MAJOR", "CONDEMNABLE"}
ROUTINGS = {"SHOP", "MOBILE"}
AAR_CODE_RE = re.compile(r"^AAR-\d{4}$")

INTERCHANGE_DAMAGE_WINDOW_HOURS = Decimal(24)
MIN_FLANGE_MM = Decimal("28.0")
MAX_TREAD_WEAR_MM = Decimal("9.5")
AGGREGATE_COUNTER_CAP_PCT = Decimal("0.60")


def determine_line_responsibility(defect, entry, railcar, inspection):
    """Ordered decision table, first match wins (PRD 2.8)."""
    if defect["cause_code"] == "HANDLING_DAMAGE":
        return "HANDLING_LINE", 0
    if entry.get("shared_split"):
        return "SHARED", 50
    group = defect["defect_group"]
    if group == "SAFETY_APPLIANCE":
        return "OWNER", 100
    if group in ("WHEELSET", "AIR_HOSE", "COUPLER"):
        return "OWNER", 100
    if group == "STRUCTURAL":
        h = hours_between(parse_dt(railcar["arrived_at"]),
                          parse_dt(inspection["completed_at"]), 3)
        if h <= INTERCHANGE_DAMAGE_WINDOW_HOURS:
            return "HANDLING_LINE", 0
    return "OWNER", 100


def compute_wo_responsibility(work_order):
    """Majority by line estimate sums; tie -> OWNER (PRD 2.8)."""
    lines = [l for l in db.STORE["repair_lines"].values()
             if l["work_order_id"] == work_order["id"]]
    total = sum(l["estimate_total_cents"] for l in lines)
    owner_sum = sum(l["estimate_total_cents"] for l in lines if (l["owner_pct"] or 0) >= 50)
    handling_sum = total - owner_sum
    party = "OWNER" if owner_sum >= handling_sum else "HANDLING_LINE"
    if total == 0:
        share = 100
    else:
        # PRD 2.8: owner_share_pct is the owner-responsible share of the
        # estimate total — each line contributes estimate * owner_pct / 100,
        # not the full estimate of majority-eligible lines.
        owner_money = sum(
            rhu_cents(Decimal(l["estimate_total_cents"]) * Decimal(l["owner_pct"] or 0) / Decimal(100))
            for l in lines)
        share = rhu_cents(Decimal(owner_money) * Decimal(100) / Decimal(total))
    return party, share


def dwell_actual(railcar, shop, end_dt):
    """Actual variant (PRD 3.6): actual hours minus free hours minus shop
    delay, floored at zero, times the dwell rate (half-up cents)."""
    actual = hours_between(parse_dt(railcar["arrived_at"]), end_dt, 2)
    delay = Decimal(str(railcar["shop_delay_hours"]))
    free = Decimal(shop["dwell_free_hours"])
    billable = actual - free - delay
    if billable < 0:
        billable = Decimal("0.00")
    charge = rhu_cents(billable * Decimal(shop["dwell_rate_cents_per_hour"]))
    return actual, billable, charge


def dwell_projected(railcar, shop, release_dt):
    """Projected variant (PRD 3.6): forward-looking, no shop-delay offset."""
    hrs = hours_between(parse_dt(railcar["arrived_at"]), release_dt, 2)
    billable = hrs - Decimal(shop["dwell_free_hours"])
    if billable < 0:
        billable = Decimal("0.00")
    return rhu_cents(billable * Decimal(shop["dwell_rate_cents_per_hour"]))


def fnum(x, places=2):
    """Serialize a Decimal as a JSON number with the given precision."""
    return float(Decimal(x).quantize(Decimal(1).scaleb(-places),
                                     rounding=ROUND_HALF_UP))
