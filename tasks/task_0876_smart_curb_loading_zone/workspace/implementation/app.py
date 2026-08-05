"""Smart-Curb & Loading-Zone Management API.

Single-file Flask implementation. In-memory storage only (fresh on every boot).
All timestamps derive from a settable logical clock (default 2026-05-01T00:00:00Z).
"""

import os
import re
import math
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
KNOWN_ROLES = {"Permittee", "CurbPlanner", "PermitApprover", "EnforcementOfficer", "PlatformAdmin"}

PERMITTEE_TYPES = {"CARRIER", "VALET_OPERATOR", "TNC", "MERCHANT"}
ZONE_DESIGNATIONS = {"LOADING", "VALET", "TNC", "PASSENGER", "METERED", "NO_STANDING"}
PERMIT_DESIGNATIONS = {"LOADING", "VALET", "TNC"}
VIOLATION_TYPES = {"OVERSTAY", "NO_PERMIT", "UNAUTHORIZED_ZONE", "WRONG_DESIGNATION"}
ZONE_TARGET_STATUSES = {"ACTIVE", "SUSPENDED", "RETIRED"}
ADJUDICATE_DECISIONS = {"UPHELD", "DISMISSED"}

BASE_FINE_CENTS = {"OVERSTAY": 7500, "NO_PERMIT": 15000, "UNAUTHORIZED_ZONE": 10000, "WRONG_DESIGNATION": 5000}
LATE_PENALTY_BPS = 2500
GRACE_DAYS = 14
TURNOVER_BUFFER_MINUTES = 15

DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"

# ---------------------------------------------------------------------------
# In-memory store (fresh every process start; NO seeding)
# ---------------------------------------------------------------------------
DB = {
    "permittees": {},
    "policies": {},
    "zones": {},
    "permits": {},
    "windows": {},
    "reservations": {},
    "sessions": {},
    "citations": {},
    "events": {},
    "ledger": {},
}
_SEQ = {"n": 0}
_CLOCK = {"dt": None}


def reset_state():
    for k in DB:
        DB[k].clear()
    _SEQ["n"] = 0
    _CLOCK["dt"] = parse_dt(DEFAULT_CLOCK_ISO)


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def new_id():
    return str(uuid.uuid4())


def clock_now():
    return _CLOCK["dt"]


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------
def parse_dt(s):
    """Parse an ISO-8601 string into an aware UTC datetime. Raises on bad input."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z") or txt.endswith("z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_ts(dt):
    """Format an aware datetime as ISO-8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def now_ts():
    return format_ts(clock_now())


# ---------------------------------------------------------------------------
# Errors + response envelope
# ---------------------------------------------------------------------------
class AppError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def make_meta(extra=None):
    meta = {
        "api_request_id": "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20)),
        "api_request_timestamp": now_ts(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200, response_type="object", meta_extra=None):
    body = {"meta": make_meta(meta_extra), "response_type": response_type, "data": data}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def ok_list(items, limit, offset, total_count):
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + limit) < total_count,
    }
    return ok(items, status=200, response_type="array", meta_extra=meta_extra)


@app.errorhandler(AppError)
def handle_app_error(err):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    resp = jsonify(body)
    resp.status_code = err.http_status
    return resp


@app.errorhandler(404)
def handle_404(err):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
    }
    resp = jsonify(body)
    resp.status_code = 404
    return resp


@app.errorhandler(405)
def handle_405(err):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"},
    }
    resp = jsonify(body)
    resp.status_code = 404
    return resp


@app.errorhandler(Exception)
def handle_uncaught(err):
    if isinstance(err, AppError):
        return handle_app_error(err)
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INTERNAL", "message": str(err)},
    }
    resp = jsonify(body)
    resp.status_code = 500
    return resp


@app.after_request
def add_connection_close(resp):
    # Avoid keep-alive flakiness under per-test-server isolation.
    resp.headers["Connection"] = "close"
    return resp


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------
def get_body():
    if request.method in ("POST", "PUT", "PATCH"):
        data = request.get_json(silent=True)
        if data is None:
            return {}
        if not isinstance(data, dict):
            return {}
        return data
    return {}


def require_auth(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in KNOWN_ROLES:
        raise AppError("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers")
    if role not in allowed_roles:
        raise AppError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")
    return uid, role


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise AppError("ERR_MISSING_FIELD", 422, "Missing required field: %s" % f)


def parse_pagination(args):
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise AppError("ERR_INVALID_PAGINATION", 422, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise AppError("ERR_INVALID_PAGINATION", 422, "limit out of bounds")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise AppError("ERR_INVALID_PAGINATION", 422, "offset must be an integer")
        if offset < 0:
            raise AppError("ERR_INVALID_PAGINATION", 422, "offset out of bounds")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


def sort_by_created(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


# ---------------------------------------------------------------------------
# Rounding / calculation helpers
# ---------------------------------------------------------------------------
def round_half_up_div(numerator, denominator):
    if denominator == 0:
        return 0
    return int((Decimal(numerator) / Decimal(denominator)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def surge_bps_from_ratio(policy, ratio_bps):
    if ratio_bps >= policy["surge_tier2_ratio_bps"]:
        return policy["surge_tier2_mult_bps"]
    if ratio_bps >= policy["surge_tier1_ratio_bps"]:
        return policy["surge_tier1_mult_bps"]
    return 10000


def zone_base_rate(zone, policy):
    if zone.get("base_rate_override_cents") is not None:
        return zone["base_rate_override_cents"]
    return policy["base_rate_cents_per_15min"]


def tou_bps_for(policy, start_dt):
    hour = start_dt.astimezone(timezone.utc).hour
    if policy["peak_start_hour"] <= hour < policy["peak_end_hour"]:
        return policy["peak_multiplier_bps"]
    return 10000


def intervals_overlap(a_start, a_end, b_start, b_end):
    # half-open [start, end)
    return a_start < b_end and b_start < a_end


def confirmed_overlap_count(zone_id, start_dt, end_dt, exclude_id):
    count = 0
    for r in DB["reservations"].values():
        if r["id"] == exclude_id:
            continue
        if r["zone_id"] != zone_id:
            continue
        if r["booking_status"] != "CONFIRMED":
            continue
        if intervals_overlap(start_dt, end_dt, r["_start_dt"], r["_end_dt"]):
            count += 1
    return count


def price_from_slots(base, slots, tou_bps, surge_bps):
    numerator = base * slots * tou_bps * surge_bps
    return round_half_up_div(numerator, 10000 * 10000)


# ---------------------------------------------------------------------------
# Ledger helper
# ---------------------------------------------------------------------------
def add_ledger(entry_type, amount_cents, zone_id=None, reservation_id=None, citation_id=None, memo=None):
    eid = new_id()
    entry = {
        "id": eid,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "zone_id": zone_id,
        "reservation_id": reservation_id,
        "citation_id": citation_id,
        "memo": memo,
        "created_at": now_ts(),
        "_seq": next_seq(),
    }
    DB["ledger"][eid] = entry
    return entry


def touch(entity):
    entity["version"] += 1
    entity["updated_at"] = now_ts()


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def pub(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def outstanding_fines_for(permittee_id):
    total = 0
    for c in DB["citations"].values():
        if c["permittee_id"] == permittee_id and c["status"] in ("ISSUED", "DISPUTED", "UPHELD"):
            total += c["fine_due_cents"]
    return total


def zone_revenue(zone_id):
    total = 0
    for e in DB["ledger"].values():
        if e["zone_id"] == zone_id:
            total += e["amount_cents"]
    return total


def zone_occupancy_state(zone_id):
    for s in DB["sessions"].values():
        if s["zone_id"] == zone_id and s["session_status"] == "OPEN":
            return "OCCUPIED"
    return "VACANT"


def ser_permittee(p):
    d = pub(p)
    d["outstanding_fines_cents"] = outstanding_fines_for(p["id"])
    return d


def ser_zone(z):
    d = pub(z)
    d["sensor_occupancy_state"] = zone_occupancy_state(z["id"])
    d["revenue_accrued_cents"] = zone_revenue(z["id"])
    return d


def ser_plain(e):
    return pub(e)


# ---------------------------------------------------------------------------
# Existence helpers
# ---------------------------------------------------------------------------
def get_or_404(collection, rid):
    ent = DB[collection].get(rid)
    if ent is None:
        raise AppError("ERR_NOT_FOUND", 404, "Resource not found: %s" % rid)
    return ent


# ===========================================================================
# Logical clock (test-driving)
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_auth({"PlatformAdmin"})
    body = get_body()
    require_fields(body, ["to_iso8601"])
    try:
        dt = parse_dt(body["to_iso8601"])
    except Exception:
        raise AppError("ERR_VALIDATION", 422, "Invalid to_iso8601")
    _CLOCK["dt"] = dt
    return ok({"current_utc": body["to_iso8601"]}, status=200)


# ===========================================================================
# Permittee
# ===========================================================================
@app.route("/curb/permittees", methods=["POST"])
def create_permittee():
    require_auth({"PlatformAdmin"})
    body = get_body()
    require_fields(body, ["legal_name", "contact_email", "permittee_type"])
    if body["permittee_type"] not in PERMITTEE_TYPES:
        raise AppError("ERR_INVALID_ENUM", 422, "Invalid permittee_type")
    pid = new_id()
    ts = now_ts()
    p = {
        "id": pid,
        "legal_name": body["legal_name"],
        "contact_email": body["contact_email"],
        "permittee_type": body["permittee_type"],
        "status": "ACTIVE",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    DB["permittees"][pid] = p
    return ok(ser_permittee(p), status=201)


@app.route("/curb/permittees/<rid>", methods=["GET"])
def get_permittee(rid):
    require_auth({"PlatformAdmin", "Permittee", "EnforcementOfficer", "CurbPlanner"})
    p = get_or_404("permittees", rid)
    return ok(ser_permittee(p), status=200)


# ===========================================================================
# PricingPolicy
# ===========================================================================
@app.route("/curb/pricing-policies", methods=["POST"])
def create_policy():
    require_auth({"CurbPlanner"})
    body = get_body()
    fields = ["name", "base_rate_cents_per_15min", "peak_multiplier_bps", "peak_start_hour",
              "peak_end_hour", "surge_tier1_ratio_bps", "surge_tier1_mult_bps",
              "surge_tier2_ratio_bps", "surge_tier2_mult_bps"]
    require_fields(body, fields)
    for hr in ("peak_start_hour", "peak_end_hour"):
        try:
            v = int(body[hr])
        except (ValueError, TypeError):
            raise AppError("ERR_VALIDATION", 422, "Invalid %s" % hr)
        if v < 0 or v > 23:
            raise AppError("ERR_VALIDATION", 422, "%s must be 0..23" % hr)
    pid = new_id()
    ts = now_ts()
    p = {"id": pid, "created_at": ts, "_seq": next_seq()}
    for f in fields:
        p[f] = body[f]
    DB["policies"][pid] = p
    return ok(ser_plain(p), status=201)


@app.route("/curb/pricing-policies/<rid>", methods=["GET"])
def get_policy(rid):
    require_auth({"CurbPlanner", "Permittee"})
    p = get_or_404("policies", rid)
    return ok(ser_plain(p), status=200)


# ===========================================================================
# CurbZone
# ===========================================================================
@app.route("/curb/zones", methods=["POST"])
def create_zone():
    require_auth({"CurbPlanner"})
    body = get_body()
    require_fields(body, ["name", "block_face", "length_meters", "designation", "capacity_slots", "pricing_policy_id"])
    if body["designation"] not in ZONE_DESIGNATIONS:
        raise AppError("ERR_INVALID_ENUM", 422, "Invalid designation")
    try:
        cap = int(body["capacity_slots"])
    except (ValueError, TypeError):
        raise AppError("ERR_VALIDATION", 422, "Invalid capacity_slots")
    if cap < 1:
        raise AppError("ERR_VALIDATION", 422, "capacity_slots must be >= 1")
    # referenced FK existence
    get_or_404("policies", body["pricing_policy_id"])
    override = body.get("base_rate_override_cents", None)
    zid = new_id()
    ts = now_ts()
    z = {
        "id": zid,
        "name": body["name"],
        "block_face": body["block_face"],
        "length_meters": body["length_meters"],
        "designation": body["designation"],
        "capacity_slots": cap,
        "pricing_policy_id": body["pricing_policy_id"],
        "base_rate_override_cents": override,
        "status": "ACTIVE",
        "version": 1,
        "created_at": ts,
        "updated_at": ts,
        "_seq": next_seq(),
        "_suspended_by_event": None,
    }
    DB["zones"][zid] = z
    return ok(ser_zone(z), status=201)


@app.route("/curb/zones/<rid>", methods=["GET"])
def get_zone(rid):
    require_auth({"CurbPlanner", "Permittee", "EnforcementOfficer", "PlatformAdmin"})
    z = get_or_404("zones", rid)
    return ok(ser_zone(z), status=200)


@app.route("/curb/zones", methods=["GET"])
def list_zones():
    require_auth({"CurbPlanner", "Permittee"})
    limit, offset = parse_pagination(request.args)
    items = list(DB["zones"].values())
    designation = request.args.get("designation")
    status = request.args.get("status")
    ppid = request.args.get("pricing_policy_id")
    if designation is not None:
        items = [z for z in items if z["designation"] == designation]
    if status is not None:
        items = [z for z in items if z["status"] == status]
    if ppid is not None:
        items = [z for z in items if z["pricing_policy_id"] == ppid]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_list([ser_zone(z) for z in page], limit, offset, total)


@app.route("/curb/map", methods=["GET"])
def curb_map():
    require_auth({"CurbPlanner", "Permittee", "EnforcementOfficer"})
    limit, offset = parse_pagination(request.args)
    items = list(DB["zones"].values())
    designation = request.args.get("designation")
    status = request.args.get("status")
    if designation is not None:
        items = [z for z in items if z["designation"] == designation]
    if status is not None:
        items = [z for z in items if z["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_list([ser_zone(z) for z in page], limit, offset, total)


@app.route("/curb/zones/<rid>/redesignate", methods=["POST"])
def redesignate_zone(rid):
    require_auth({"CurbPlanner"})
    z = get_or_404("zones", rid)
    body = get_body()
    require_fields(body, ["designation", "expected_zone_version"])
    if body["designation"] not in ZONE_DESIGNATIONS:
        raise AppError("ERR_INVALID_ENUM", 422, "Invalid designation")
    # OCC check is last
    try:
        expected = int(body["expected_zone_version"])
    except (ValueError, TypeError):
        raise AppError("ERR_VALIDATION", 422, "Invalid expected_zone_version")
    if expected != z["version"]:
        raise AppError("ERR_STALE_VERSION", 412, "expected_zone_version does not match")
    z["designation"] = body["designation"]
    if "base_rate_override_cents" in body:
        z["base_rate_override_cents"] = body["base_rate_override_cents"]
    touch(z)
    return ok(ser_zone(z), status=200)


@app.route("/curb/zones/<rid>/status", methods=["POST"])
def zone_status(rid):
    require_auth({"CurbPlanner"})
    z = get_or_404("zones", rid)
    body = get_body()
    require_fields(body, ["target_status"])
    target = body["target_status"]
    if target not in ZONE_TARGET_STATUSES:
        raise AppError("ERR_INVALID_ENUM", 422, "Invalid target_status")
    cur = z["status"]
    allowed = {
        ("ACTIVE", "SUSPENDED"),
        ("ACTIVE", "RETIRED"),
        ("SUSPENDED", "ACTIVE"),
        ("RETIRED", "ACTIVE"),
    }
    if (cur, target) not in allowed:
        raise AppError("ERR_INVALID_STATE", 409, "Transition %s -> %s not defined" % (cur, target))
    if cur == "ACTIVE" and target == "RETIRED":
        now = clock_now()
        for r in DB["reservations"].values():
            if r["zone_id"] == z["id"] and r["booking_status"] == "CONFIRMED" and r["_end_dt"] > now:
                raise AppError("ERR_ZONE_HAS_ACTIVE_RESERVATIONS", 409, "Zone has active reservations")
    z["status"] = target
    # manual status changes clear event-suspension provenance
    z["_suspended_by_event"] = None
    touch(z)
    return ok(ser_zone(z), status=200)


# ===========================================================================
# CurbPermit
# ===========================================================================
@app.route("/curb/permits", methods=["POST"])
def create_permit():
    uid, role = require_auth({"Permittee"})
    body = get_body()
    require_fields(body, ["permittee_id", "requested_designation", "purpose", "zone_ids"])
    # existence of permittee
    get_or_404("permittees", body["permittee_id"])
    # ownership
    if body["permittee_id"] != uid:
        raise AppError("ERR_UNAUTHORIZED", 403, "Permittee may only create own permits")
    zone_ids = body["zone_ids"]
    if not isinstance(zone_ids, list):
        raise AppError("ERR_VALIDATION", 422, "zone_ids must be a list")
    for z in zone_ids:
        get_or_404("zones", z)
    if body["requested_designation"] not in PERMIT_DESIGNATIONS:
        raise AppError("ERR_INVALID_ENUM", 422, "Invalid requested_designation")
    pid = new_id()
    ts = now_ts()
    p = {
        "id": pid,
        "permittee_id": body["permittee_id"],
        "requested_designation": body["requested_designation"],
        "purpose": body["purpose"],
        "zone_ids": list(zone_ids),
        "reviewer_user_id": None,
        "approver_user_id": None,
        "last_change_note": None,
        "status": "DRAFT",
        "version": 1,
        "created_at": ts,
        "updated_at": ts,
        "_seq": next_seq(),
    }
    DB["permits"][pid] = p
    return ok(ser_plain(p), status=201)


@app.route("/curb/permits/<rid>", methods=["GET"])
def get_permit(rid):
    require_auth({"Permittee", "CurbPlanner", "PermitApprover"})
    p = get_or_404("permits", rid)
    return ok(ser_plain(p), status=200)


@app.route("/curb/permits", methods=["GET"])
def list_permits():
    require_auth({"Permittee", "CurbPlanner", "PermitApprover"})
    limit, offset = parse_pagination(request.args)
    items = list(DB["permits"].values())
    permittee_id = request.args.get("permittee_id")
    status = request.args.get("status")
    if permittee_id is not None:
        items = [p for p in items if p["permittee_id"] == permittee_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_list([ser_plain(p) for p in page], limit, offset, total)


def _own_permit(uid, permit):
    if permit["permittee_id"] != uid:
        raise AppError("ERR_UNAUTHORIZED", 403, "Permittee does not own this permit")


@app.route("/curb/permits/<rid>/submit", methods=["POST"])
def submit_permit(rid):
    uid, role = require_auth({"Permittee"})
    p = get_or_404("permits", rid)
    _own_permit(uid, p)
    if p["status"] != "DRAFT":
        raise AppError("ERR_INVALID_STATE", 409, "Permit not in DRAFT")
    if not p["zone_ids"]:
        raise AppError("ERR_VALIDATION", 422, "Permit must name at least one zone")
    p["status"] = "SUBMITTED"
    touch(p)
    return ok(ser_plain(p), status=200)


@app.route("/curb/permits/<rid>/review", methods=["POST"])
def review_permit(rid):
    uid, role = require_auth({"CurbPlanner"})
    p = get_or_404("permits", rid)
    if p["status"] != "SUBMITTED":
        raise AppError("ERR_INVALID_STATE", 409, "Permit not SUBMITTED")
    p["status"] = "UNDER_REVIEW"
    p["reviewer_user_id"] = uid
    touch(p)
    return ok(ser_plain(p), status=200)


@app.route("/curb/permits/<rid>/request-changes", methods=["POST"])
def request_changes_permit(rid):
    uid, role = require_auth({"CurbPlanner"})
    p = get_or_404("permits", rid)
    if p["status"] != "UNDER_REVIEW":
        raise AppError("ERR_INVALID_STATE", 409, "Permit not UNDER_REVIEW")
    body = get_body()
    require_fields(body, ["note"])
    p["status"] = "DRAFT"
    p["last_change_note"] = body["note"]
    touch(p)
    return ok(ser_plain(p), status=200)


@app.route("/curb/permits/<rid>/approve", methods=["POST"])
def approve_permit(rid):
    uid, role = require_auth({"PermitApprover"})
    p = get_or_404("permits", rid)
    if p["status"] != "UNDER_REVIEW":
        raise AppError("ERR_INVALID_STATE", 409, "Permit not UNDER_REVIEW")
    if uid == p["reviewer_user_id"]:
        raise AppError("ERR_SEGREGATION_OF_DUTIES", 403, "Approver must differ from reviewer")
    for zid in p["zone_ids"]:
        z = DB["zones"].get(zid)
        if z is None or z["status"] != "ACTIVE":
            raise AppError("ERR_ZONE_NOT_ACTIVE", 409, "A referenced zone is not ACTIVE")
    p["status"] = "ACTIVE"
    p["approver_user_id"] = uid
    touch(p)
    return ok(ser_plain(p), status=200)


@app.route("/curb/permits/<rid>/deny", methods=["POST"])
def deny_permit(rid):
    uid, role = require_auth({"PermitApprover"})
    p = get_or_404("permits", rid)
    if p["status"] != "UNDER_REVIEW":
        raise AppError("ERR_INVALID_STATE", 409, "Permit not UNDER_REVIEW")
    if uid == p["reviewer_user_id"]:
        raise AppError("ERR_SEGREGATION_OF_DUTIES", 403, "Approver must differ from reviewer")
    body = get_body()
    require_fields(body, ["reason"])
    p["status"] = "DENIED"
    p["approver_user_id"] = uid
    touch(p)
    return ok(ser_plain(p), status=200)


@app.route("/curb/permits/<rid>/revoke", methods=["POST"])
def revoke_permit(rid):
    uid, role = require_auth({"CurbPlanner"})
    p = get_or_404("permits", rid)
    if p["status"] != "ACTIVE":
        raise AppError("ERR_INVALID_STATE", 409, "Permit not ACTIVE")
    body = get_body()
    require_fields(body, ["reason"])
    now = clock_now()
    p["status"] = "REVOKED"
    for r in DB["reservations"].values():
        if r["permit_id"] != p["id"]:
            continue
        if r["booking_status"] != "CONFIRMED":
            continue
        if r["_start_dt"] > now:
            r["booking_status"] = "CANCELLED"
            if r["payment_status"] == "CAPTURED":
                r["payment_status"] = "REFUNDED"
                add_ledger("REFUND", -r["estimated_price_cents"], zone_id=r["zone_id"],
                           reservation_id=r["id"], memo="Permit revocation refund")
            touch(r)
    touch(p)
    return ok(ser_plain(p), status=200)


# ===========================================================================
# ScheduleWindow
# ===========================================================================
@app.route("/curb/schedule-windows", methods=["POST"])
def create_window():
    uid, role = require_auth({"Permittee"})
    body = get_body()
    require_fields(body, ["permit_id", "zone_id", "day_of_week", "start_minute", "end_minute"])
    permit = get_or_404("permits", body["permit_id"])
    zone = get_or_404("zones", body["zone_id"])
    _own_permit(uid, permit)
    # field constraints
    try:
        dow = int(body["day_of_week"])
        start_minute = int(body["start_minute"])
        end_minute = int(body["end_minute"])
    except (ValueError, TypeError):
        raise AppError("ERR_VALIDATION", 422, "Invalid numeric field")
    if dow < 0 or dow > 6:
        raise AppError("ERR_VALIDATION", 422, "day_of_week out of bounds")
    if start_minute < 0 or start_minute > 1440 or end_minute < 0 or end_minute > 1440:
        raise AppError("ERR_VALIDATION", 422, "minute value out of bounds")
    exclusive = bool(body.get("exclusive", False))
    # temporal overlap: exclusive vs exclusive on same zone + dow, buffer check
    if exclusive:
        for w in DB["windows"].values():
            if w["zone_id"] != body["zone_id"]:
                continue
            if w["day_of_week"] != dow:
                continue
            if not w["exclusive"]:
                continue
            gap = max(start_minute - w["end_minute"], w["start_minute"] - end_minute)
            if gap < TURNOVER_BUFFER_MINUTES:
                raise AppError("ERR_SCHEDULE_WINDOW_CONFLICT", 409, "Exclusive window collides within turnover buffer")
    wid = new_id()
    ts = now_ts()
    w = {
        "id": wid,
        "permit_id": body["permit_id"],
        "zone_id": body["zone_id"],
        "day_of_week": dow,
        "start_minute": start_minute,
        "end_minute": end_minute,
        "exclusive": exclusive,
        "created_at": ts,
        "_seq": next_seq(),
    }
    DB["windows"][wid] = w
    return ok(ser_plain(w), status=201)


@app.route("/curb/schedule-windows/<rid>", methods=["GET"])
def get_window(rid):
    require_auth({"Permittee", "CurbPlanner"})
    w = get_or_404("windows", rid)
    return ok(ser_plain(w), status=200)


@app.route("/curb/schedule-windows", methods=["GET"])
def list_windows():
    require_auth({"Permittee", "CurbPlanner"})
    limit, offset = parse_pagination(request.args)
    items = list(DB["windows"].values())
    permit_id = request.args.get("permit_id")
    zone_id = request.args.get("zone_id")
    if permit_id is not None:
        items = [w for w in items if w["permit_id"] == permit_id]
    if zone_id is not None:
        items = [w for w in items if w["zone_id"] == zone_id]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_list([ser_plain(w) for w in page], limit, offset, total)


# ===========================================================================
# Reservation
# ===========================================================================
@app.route("/curb/reservations", methods=["POST"])
def create_reservation():
    uid, role = require_auth({"Permittee"})
    body = get_body()
    require_fields(body, ["permit_id", "zone_id", "start_utc", "end_utc"])
    permit = get_or_404("permits", body["permit_id"])
    zone = get_or_404("zones", body["zone_id"])
    _own_permit(uid, permit)
    try:
        start_dt = parse_dt(body["start_utc"])
        end_dt = parse_dt(body["end_utc"])
    except Exception:
        raise AppError("ERR_VALIDATION", 422, "Invalid datetime")
    if not (end_dt > start_dt):
        raise AppError("ERR_VALIDATION", 422, "end_utc must be strictly after start_utc")
    rid = new_id()
    ts = now_ts()
    r = {
        "id": rid,
        "permit_id": body["permit_id"],
        "zone_id": body["zone_id"],
        "start_utc": body["start_utc"],
        "end_utc": body["end_utc"],
        "booking_status": "PENDING",
        "payment_status": "UNPAID",
        "estimated_price_cents": None,
        "settled_price_cents": None,
        "surge_ratio_bps": None,
        "version": 1,
        "created_at": ts,
        "updated_at": ts,
        "_seq": next_seq(),
        "_start_dt": start_dt,
        "_end_dt": end_dt,
    }
    DB["reservations"][rid] = r
    return ok(ser_plain(r), status=201)


@app.route("/curb/reservations/<rid>", methods=["GET"])
def get_reservation(rid):
    require_auth({"Permittee", "CurbPlanner", "EnforcementOfficer"})
    r = get_or_404("reservations", rid)
    return ok(ser_plain(r), status=200)


@app.route("/curb/reservations", methods=["GET"])
def list_reservations():
    require_auth({"Permittee", "CurbPlanner", "EnforcementOfficer"})
    limit, offset = parse_pagination(request.args)
    items = list(DB["reservations"].values())
    permit_id = request.args.get("permit_id")
    zone_id = request.args.get("zone_id")
    booking_status = request.args.get("booking_status")
    if permit_id is not None:
        items = [r for r in items if r["permit_id"] == permit_id]
    if zone_id is not None:
        items = [r for r in items if r["zone_id"] == zone_id]
    if booking_status is not None:
        items = [r for r in items if r["booking_status"] == booking_status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_list([ser_plain(r) for r in page], limit, offset, total)


def _reservation_permittee_id(r):
    permit = DB["permits"].get(r["permit_id"])
    if permit is None:
        return None
    return permit["permittee_id"]


@app.route("/curb/reservations/<rid>/confirm", methods=["POST"])
def confirm_reservation(rid):
    uid, role = require_auth({"Permittee"})
    r = get_or_404("reservations", rid)
    # ownership via authorizing permit
    if _reservation_permittee_id(r) != uid:
        raise AppError("ERR_UNAUTHORIZED", 403, "Permittee does not own this reservation")
    if r["booking_status"] != "PENDING":
        raise AppError("ERR_INVALID_STATE", 409, "Reservation not PENDING")
    permit = DB["permits"].get(r["permit_id"])
    if permit is None or permit["status"] != "ACTIVE":
        raise AppError("ERR_PERMIT_NOT_ACTIVE", 409, "Authorizing permit not ACTIVE")
    zone = DB["zones"].get(r["zone_id"])
    if zone is None or zone["status"] != "ACTIVE":
        raise AppError("ERR_ZONE_NOT_ACTIVE", 409, "Zone not ACTIVE")
    # capacity: count CONFIRMED overlapping (excluding self)
    overlap = confirmed_overlap_count(r["zone_id"], r["_start_dt"], r["_end_dt"], r["id"])
    if overlap >= zone["capacity_slots"]:
        raise AppError("ERR_ZONE_CAPACITY_CONFLICT", 409, "Zone capacity exceeded")
    policy = DB["policies"].get(zone["pricing_policy_id"])
    base = zone_base_rate(zone, policy)
    seconds = int((r["_end_dt"] - r["_start_dt"]).total_seconds())
    slots = (seconds + 899) // 900
    tou = tou_bps_for(policy, r["_start_dt"])
    ratio_bps = (overlap * 10000) // zone["capacity_slots"]
    surge = surge_bps_from_ratio(policy, ratio_bps)
    price = price_from_slots(base, slots, tou, surge)
    r["estimated_price_cents"] = price
    r["surge_ratio_bps"] = ratio_bps
    r["booking_status"] = "CONFIRMED"
    r["payment_status"] = "CAPTURED"
    add_ledger("CHARGE", price, zone_id=r["zone_id"], reservation_id=r["id"], memo="Reservation charge")
    touch(r)
    return ok(ser_plain(r), status=200)


@app.route("/curb/reservations/<rid>/cancel", methods=["POST"])
def cancel_reservation(rid):
    uid, role = require_auth({"Permittee"})
    r = get_or_404("reservations", rid)
    if _reservation_permittee_id(r) != uid:
        raise AppError("ERR_UNAUTHORIZED", 403, "Permittee does not own this reservation")
    status = r["booking_status"]
    if status == "PENDING":
        r["booking_status"] = "CANCELLED"
        touch(r)
        return ok(ser_plain(r), status=200)
    if status == "CONFIRMED":
        if not (clock_now() < r["_start_dt"]):
            raise AppError("ERR_CANCEL_AFTER_START", 409, "Cannot cancel after window start")
        r["booking_status"] = "CANCELLED"
        if r["payment_status"] == "CAPTURED":
            r["payment_status"] = "REFUNDED"
            add_ledger("REFUND", -r["estimated_price_cents"], zone_id=r["zone_id"],
                       reservation_id=r["id"], memo="Reservation cancellation refund")
        touch(r)
        return ok(ser_plain(r), status=200)
    raise AppError("ERR_INVALID_STATE", 409, "Reservation cannot be cancelled from %s" % status)


@app.route("/curb/reservations/<rid>/fulfill", methods=["POST"])
def fulfill_reservation(rid):
    uid, role = require_auth({"Permittee", "EnforcementOfficer"})
    r = get_or_404("reservations", rid)
    if role == "Permittee" and _reservation_permittee_id(r) != uid:
        raise AppError("ERR_UNAUTHORIZED", 403, "Permittee does not own this reservation")
    if r["booking_status"] != "CONFIRMED":
        raise AppError("ERR_INVALID_STATE", 409, "Reservation not CONFIRMED")
    # find a CLOSED occupancy session matching this reservation
    matched = [s for s in DB["sessions"].values()
               if s["reservation_id"] == r["id"] and s["session_status"] == "CLOSED"]
    if not matched:
        raise AppError("ERR_NO_OCCUPANCY_SESSION", 409, "No matched closed occupancy session")
    matched.sort(key=lambda s: s["_seq"])
    session = matched[-1]
    zone = DB["zones"].get(r["zone_id"])
    policy = DB["policies"].get(zone["pricing_policy_id"])
    base = zone_base_rate(zone, policy)
    actual_minutes = session["actual_minutes"] or 0
    slots = (actual_minutes + 14) // 15
    tou = tou_bps_for(policy, r["_start_dt"])
    surge = surge_bps_from_ratio(policy, r["surge_ratio_bps"])
    settled = price_from_slots(base, slots, tou, surge)
    r["settled_price_cents"] = settled
    r["booking_status"] = "FULFILLED"
    if settled != r["estimated_price_cents"]:
        delta = settled - r["estimated_price_cents"]
        add_ledger("ADJUSTMENT", delta, zone_id=r["zone_id"], reservation_id=r["id"], memo="Settlement adjustment")
    touch(r)
    return ok(ser_plain(r), status=200)


@app.route("/curb/reservations/<rid>/no-show", methods=["POST"])
def no_show_reservation(rid):
    uid, role = require_auth({"EnforcementOfficer"})
    r = get_or_404("reservations", rid)
    if r["booking_status"] != "CONFIRMED":
        raise AppError("ERR_INVALID_STATE", 409, "Reservation not CONFIRMED")
    if not (clock_now() >= r["_end_dt"]):
        raise AppError("ERR_INVALID_STATE", 409, "Cannot mark no-show before window end")
    for s in DB["sessions"].values():
        if s["reservation_id"] == r["id"]:
            raise AppError("ERR_INVALID_STATE", 409, "Occupancy session exists for reservation")
    r["booking_status"] = "NO_SHOW"
    touch(r)
    return ok(ser_plain(r), status=200)


# ===========================================================================
# OccupancySession (sensor / system)
# ===========================================================================
@app.route("/_sensor/occupancy-enter", methods=["POST"])
def occupancy_enter():
    require_auth({"PlatformAdmin"})
    body = get_body()
    require_fields(body, ["zone_id"])
    zone = get_or_404("zones", body["zone_id"])
    reservation_id = body.get("reservation_id", None)
    if reservation_id is not None:
        get_or_404("reservations", reservation_id)
    sid = new_id()
    ts = now_ts()
    s = {
        "id": sid,
        "zone_id": body["zone_id"],
        "reservation_id": reservation_id,
        "entered_at": ts,
        "exited_at": None,
        "actual_minutes": None,
        "session_status": "OPEN",
        "version": 1,
        "created_at": ts,
        "updated_at": ts,
        "_seq": next_seq(),
        "_entered_dt": clock_now(),
    }
    DB["sessions"][sid] = s
    return ok(ser_plain(s), status=201)


@app.route("/_sensor/occupancy-exit", methods=["POST"])
def occupancy_exit():
    require_auth({"PlatformAdmin"})
    body = get_body()
    require_fields(body, ["session_id"])
    s = get_or_404("sessions", body["session_id"])
    if s["session_status"] != "OPEN":
        raise AppError("ERR_INVALID_STATE", 409, "Session not OPEN")
    now = clock_now()
    seconds = int((now - s["_entered_dt"]).total_seconds())
    if seconds < 0:
        seconds = 0
    actual_minutes = (seconds + 59) // 60
    s["exited_at"] = now_ts()
    s["actual_minutes"] = actual_minutes
    s["session_status"] = "CLOSED"
    touch(s)
    return ok(ser_plain(s), status=200)


@app.route("/curb/occupancy-sessions/<rid>", methods=["GET"])
def get_session(rid):
    require_auth({"CurbPlanner", "EnforcementOfficer"})
    s = get_or_404("sessions", rid)
    return ok(ser_plain(s), status=200)


@app.route("/curb/occupancy-sessions", methods=["GET"])
def list_sessions():
    require_auth({"CurbPlanner", "EnforcementOfficer"})
    limit, offset = parse_pagination(request.args)
    items = list(DB["sessions"].values())
    zone_id = request.args.get("zone_id")
    reservation_id = request.args.get("reservation_id")
    session_status = request.args.get("session_status")
    if zone_id is not None:
        items = [s for s in items if s["zone_id"] == zone_id]
    if reservation_id is not None:
        items = [s for s in items if s["reservation_id"] == reservation_id]
    if session_status is not None:
        items = [s for s in items if s["session_status"] == session_status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_list([ser_plain(s) for s in page], limit, offset, total)


# ===========================================================================
# Citation
# ===========================================================================
@app.route("/curb/citations", methods=["POST"])
def create_citation():
    require_auth({"EnforcementOfficer"})
    body = get_body()
    require_fields(body, ["zone_id", "permittee_id", "violation_type"])
    zone = get_or_404("zones", body["zone_id"])
    permittee = get_or_404("permittees", body["permittee_id"])
    occ_id = body.get("occupancy_session_id", None)
    res_id = body.get("reservation_id", None)
    if occ_id is not None:
        get_or_404("sessions", occ_id)
    if res_id is not None:
        get_or_404("reservations", res_id)
    if body["violation_type"] not in VIOLATION_TYPES:
        raise AppError("ERR_INVALID_ENUM", 422, "Invalid violation_type")
    cid = new_id()
    now = clock_now()
    ts = format_ts(now)
    due = format_ts(now + timedelta(days=GRACE_DAYS))
    fine = BASE_FINE_CENTS[body["violation_type"]]
    c = {
        "id": cid,
        "zone_id": body["zone_id"],
        "permittee_id": body["permittee_id"],
        "occupancy_session_id": occ_id,
        "reservation_id": res_id,
        "violation_type": body["violation_type"],
        "issued_at": ts,
        "due_at": due,
        "fine_due_cents": fine,
        "status": "ISSUED",
        "version": 1,
        "created_at": ts,
        "updated_at": ts,
        "_seq": next_seq(),
        "_due_dt": now + timedelta(days=GRACE_DAYS),
    }
    DB["citations"][cid] = c
    return ok(ser_plain(c), status=201)


@app.route("/curb/citations/<rid>", methods=["GET"])
def get_citation(rid):
    require_auth({"EnforcementOfficer", "Permittee", "CurbPlanner"})
    c = get_or_404("citations", rid)
    return ok(ser_plain(c), status=200)


@app.route("/curb/citations", methods=["GET"])
def list_citations():
    require_auth({"EnforcementOfficer", "Permittee", "CurbPlanner"})
    limit, offset = parse_pagination(request.args)
    items = list(DB["citations"].values())
    for key in ("zone_id", "reservation_id", "occupancy_session_id", "permittee_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [c for c in items if c[key] == val]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_list([ser_plain(c) for c in page], limit, offset, total)


@app.route("/curb/citations/<rid>/pay", methods=["POST"])
def pay_citation(rid):
    uid, role = require_auth({"Permittee"})
    c = get_or_404("citations", rid)
    if c["permittee_id"] != uid:
        raise AppError("ERR_UNAUTHORIZED", 403, "Permittee does not own this citation")
    if c["status"] not in ("ISSUED", "UPHELD"):
        raise AppError("ERR_INVALID_STATE", 409, "Citation not payable")
    c["status"] = "PAID"
    add_ledger("FINE", c["fine_due_cents"], zone_id=c["zone_id"], citation_id=c["id"], memo="Citation fine paid")
    touch(c)
    return ok(ser_plain(c), status=200)


@app.route("/curb/citations/<rid>/dispute", methods=["POST"])
def dispute_citation(rid):
    uid, role = require_auth({"Permittee"})
    c = get_or_404("citations", rid)
    if c["permittee_id"] != uid:
        raise AppError("ERR_UNAUTHORIZED", 403, "Permittee does not own this citation")
    if c["status"] != "ISSUED":
        raise AppError("ERR_INVALID_STATE", 409, "Citation not ISSUED")
    body = get_body()
    require_fields(body, ["reason"])
    c["status"] = "DISPUTED"
    touch(c)
    return ok(ser_plain(c), status=200)


@app.route("/curb/citations/<rid>/adjudicate", methods=["POST"])
def adjudicate_citation(rid):
    require_auth({"EnforcementOfficer"})
    c = get_or_404("citations", rid)
    body = get_body()
    require_fields(body, ["decision"])
    decision = body["decision"]
    if decision not in ADJUDICATE_DECISIONS:
        raise AppError("ERR_INVALID_ENUM", 422, "Invalid decision")
    if c["status"] != "DISPUTED":
        raise AppError("ERR_INVALID_STATE", 409, "Citation not DISPUTED")
    if decision == "UPHELD":
        base = BASE_FINE_CENTS[c["violation_type"]]
        if clock_now() > c["_due_dt"]:
            c["fine_due_cents"] = round_half_up_div(base * (10000 + LATE_PENALTY_BPS), 10000)
        else:
            c["fine_due_cents"] = base
        c["status"] = "UPHELD"
    else:
        c["status"] = "DISMISSED"
    touch(c)
    return ok(ser_plain(c), status=200)


# ===========================================================================
# CurbEvent
# ===========================================================================
@app.route("/curb/events", methods=["POST"])
def create_event():
    require_auth({"CurbPlanner"})
    body = get_body()
    require_fields(body, ["name", "start_utc", "end_utc", "zone_ids"])
    try:
        start_dt = parse_dt(body["start_utc"])
        end_dt = parse_dt(body["end_utc"])
    except Exception:
        raise AppError("ERR_VALIDATION", 422, "Invalid datetime")
    zone_ids = body["zone_ids"]
    if not isinstance(zone_ids, list):
        raise AppError("ERR_VALIDATION", 422, "zone_ids must be a list")
    for zid in zone_ids:
        get_or_404("zones", zid)
    eid = new_id()
    ts = now_ts()
    e = {
        "id": eid,
        "name": body["name"],
        "start_utc": body["start_utc"],
        "end_utc": body["end_utc"],
        "zone_ids": list(zone_ids),
        "total_refund_cents": 0,
        "status": "PLANNED",
        "version": 1,
        "created_at": ts,
        "updated_at": ts,
        "_seq": next_seq(),
        "_start_dt": start_dt,
        "_end_dt": end_dt,
    }
    DB["events"][eid] = e
    return ok(ser_plain(e), status=201)


@app.route("/curb/events/<rid>", methods=["GET"])
def get_event(rid):
    require_auth({"CurbPlanner", "Permittee"})
    e = get_or_404("events", rid)
    return ok(ser_plain(e), status=200)


@app.route("/curb/events/<rid>/activate", methods=["POST"])
def activate_event(rid):
    require_auth({"CurbPlanner"})
    e = get_or_404("events", rid)
    if e["status"] != "PLANNED":
        raise AppError("ERR_INVALID_STATE", 409, "Event not PLANNED")
    now = clock_now()
    e["status"] = "ACTIVE"
    # suspend active zones
    for zid in e["zone_ids"]:
        z = DB["zones"].get(zid)
        if z is not None and z["status"] == "ACTIVE":
            z["status"] = "SUSPENDED"
            z["_suspended_by_event"] = e["id"]
            touch(z)
    # cancel + refund overlapping confirmed reservations on those zones
    total_refund = 0
    affected = []
    for r in DB["reservations"].values():
        if r["zone_id"] not in e["zone_ids"]:
            continue
        if r["booking_status"] != "CONFIRMED":
            continue
        if intervals_overlap(r["_start_dt"], r["_end_dt"], e["_start_dt"], e["_end_dt"]):
            affected.append(r)
    affected.sort(key=lambda r: r["_seq"])
    for r in affected:
        total_seconds = int((r["_end_dt"] - r["_start_dt"]).total_seconds())
        if now <= r["_start_dt"]:
            remaining = total_seconds
        else:
            remaining = int((r["_end_dt"] - now).total_seconds())
            if remaining < 0:
                remaining = 0
        est = r["estimated_price_cents"] or 0
        r_refund = round_half_up_div(est * remaining, total_seconds) if total_seconds > 0 else 0
        r["booking_status"] = "CANCELLED_BY_EVENT"
        if r["payment_status"] == "CAPTURED":
            r["payment_status"] = "REFUNDED"
        add_ledger("REFUND", -r_refund, zone_id=r["zone_id"], reservation_id=r["id"], memo="Event reallocation refund")
        total_refund += r_refund
        touch(r)
    e["total_refund_cents"] = total_refund
    touch(e)
    return ok(ser_plain(e), status=200)


@app.route("/curb/events/<rid>/close", methods=["POST"])
def close_event(rid):
    require_auth({"CurbPlanner"})
    e = get_or_404("events", rid)
    if e["status"] != "ACTIVE":
        raise AppError("ERR_INVALID_STATE", 409, "Event not ACTIVE")
    for z in DB["zones"].values():
        if z.get("_suspended_by_event") == e["id"]:
            z["status"] = "ACTIVE"
            z["_suspended_by_event"] = None
            touch(z)
    e["status"] = "CLOSED"
    touch(e)
    return ok(ser_plain(e), status=200)


@app.route("/curb/events/<rid>/cancel", methods=["POST"])
def cancel_event(rid):
    require_auth({"CurbPlanner"})
    e = get_or_404("events", rid)
    if e["status"] != "PLANNED":
        raise AppError("ERR_INVALID_STATE", 409, "Event not PLANNED")
    e["status"] = "CANCELLED"
    touch(e)
    return ok(ser_plain(e), status=200)


# ===========================================================================
# LedgerEntry / Revenue
# ===========================================================================
@app.route("/curb/ledger-entries/<rid>", methods=["GET"])
def get_ledger_entry(rid):
    require_auth({"CurbPlanner"})
    e = get_or_404("ledger", rid)
    return ok(ser_plain(e), status=200)


@app.route("/curb/ledger-entries", methods=["GET"])
def list_ledger_entries():
    require_auth({"CurbPlanner"})
    limit, offset = parse_pagination(request.args)
    items = list(DB["ledger"].values())
    for key in ("zone_id", "reservation_id", "citation_id", "entry_type"):
        val = request.args.get(key)
        if val is not None:
            items = [e for e in items if e[key] == val]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_list([ser_plain(e) for e in page], limit, offset, total)


@app.route("/curb/revenue", methods=["GET"])
def revenue():
    require_auth({"CurbPlanner"})
    zone_id = request.args.get("zone_id")
    if zone_id is not None:
        get_or_404("zones", zone_id)
    total_charge = 0
    total_refund = 0
    total_adjustment = 0
    total_fine = 0
    for e in DB["ledger"].values():
        if zone_id is not None and e["zone_id"] != zone_id:
            continue
        if e["entry_type"] == "CHARGE":
            total_charge += e["amount_cents"]
        elif e["entry_type"] == "REFUND":
            total_refund += e["amount_cents"]
        elif e["entry_type"] == "ADJUSTMENT":
            total_adjustment += e["amount_cents"]
        elif e["entry_type"] == "FINE":
            total_fine += e["amount_cents"]
    net = total_charge + total_refund + total_adjustment + total_fine
    data = {
        "total_charge_cents": total_charge,
        "total_refund_cents": total_refund,
        "total_adjustment_cents": total_adjustment,
        "total_fine_cents": total_fine,
        "net_revenue_cents": net,
    }
    return ok(data, status=200)


# ---------------------------------------------------------------------------
# Boot
# ---------------------------------------------------------------------------
reset_state()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
