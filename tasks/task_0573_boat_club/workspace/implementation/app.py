"""Boat Club & Membership Boating API — Flask implementation.

Storage is in-memory only (see store.py); every collection is empty on each
process boot and nothing is ever seeded. All time-dependent behaviour is
measured against a server-held logical clock (default 2026-05-01T00:00:00Z).

Global validation gate order (PRD 2.8):
  1 auth -> 2 authz -> 3 body -> 4 existence -> 5 ownership -> 6 state ->
  7 cert/orientation -> 8 temporal -> 9 business -> 10 fiscal -> 11 OCC.
"""
import math
import os
from datetime import timedelta
from decimal import Decimal

from flask import Flask, jsonify, request

import store
from store import serialize, touch, new_common, next_seq
from util import ApiError, parse_dt, fmt_dt, now_iso, rhu, gen_request_id

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

# --- roles / enum domains ---
VALID_ROLES = {"Member", "DockStaff", "ClubAdmin"}
TIER_CODES = {"CRUISE", "SAIL", "UNLIMITED"}
BOAT_TYPES = {"PONTOON", "BOWRIDER", "DECK_BOAT", "CENTER_CONSOLE"}
SESSION_TYPES = {"ORIENTATION", "BASIC_CERT", "ADVANCED_CERT"}
SEVERITIES = {"MINOR", "MODERATE", "SEVERE"}
CERT_ORDER = {"NONE": 0, "BASIC": 1, "ADVANCED": 2}

# --- calculation constants (scaffold 1.3) ---
TAX = Decimal("1.085")
FUEL_MIN_PCT = 25
FUEL_RATE_CENTS_PER_PCT = 100
LATE_GRACE_MIN = 15
LATE_BLOCK_MIN = 30
LATE_BLOCK_CENTS = 2500
NO_SHOW_FEE_CENTS = 5000
NO_SHOW_GRACE_MIN = 30
NO_SHOW_SUSPEND_THRESHOLD = 3
CLEANING_FEE_CENTS = 4000
DEDUCTIBLE_BY_TIER = {"CRUISE": 50000, "SAIL": 30000, "UNLIMITED": 10000}
SEVERE_SURCHARGE_CENTS = 20000
FEE_BLOCK_LIMIT_CENTS = 50000
MEMBER_TURNAROUND_MIN = 60

ACTIVE_RES_STATUSES = {"REQUESTED", "CONFIRMED", "CHECKED_OUT"}
WEEK_COUNT_STATUSES = {"CONFIRMED", "CHECKED_OUT", "RETURNED", "NO_SHOW"}
NON_TERMINAL_RES = {"REQUESTED", "CONFIRMED", "CHECKED_OUT"}


# =========================================================================
# Response envelope helpers
# =========================================================================
def _meta(pagination=None):
    m = {"api_request_id": gen_request_id(), "api_request_timestamp": now_iso()}
    if pagination:
        m.update(pagination)
    return m


def ok(data, status=200, is_list=False, pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": "array" if is_list else "object",
        "data": data,
    }
    return jsonify(body), status


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.status


@app.errorhandler(404)
def handle_404(_e):
    return handle_api_error(ApiError("ERR_VALIDATION", "Unknown route"))


@app.errorhandler(405)
def handle_405(_e):
    return handle_api_error(ApiError("ERR_VALIDATION", "Method not allowed"))


# =========================================================================
# Auth / body / existence helpers
# =========================================================================
def require_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in VALID_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or unrecognized auth headers")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", "Role not permitted for this endpoint")


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", "Body must be a JSON object")
    return body


# --- body field validators (raise ERR_VALIDATION on failure) ---
def v_str(body, key, required=True):
    if key not in body or body[key] is None:
        if required:
            raise ApiError("ERR_VALIDATION", f"{key} is required")
        return None
    val = body[key]
    if not isinstance(val, str) or val == "":
        raise ApiError("ERR_VALIDATION", f"{key} must be a non-empty string")
    return val


def v_int(body, key, required=True, minimum=None):
    if key not in body or body[key] is None:
        if required:
            raise ApiError("ERR_VALIDATION", f"{key} is required")
        return None
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, int):
        raise ApiError("ERR_VALIDATION", f"{key} must be an integer")
    if minimum is not None and val < minimum:
        raise ApiError("ERR_VALIDATION", f"{key} must be >= {minimum}")
    return val


def v_num(body, key, required=True, lo=None, hi=None):
    if key not in body or body[key] is None:
        if required:
            raise ApiError("ERR_VALIDATION", f"{key} is required")
        return None
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise ApiError("ERR_VALIDATION", f"{key} must be a number")
    if lo is not None and val < lo:
        raise ApiError("ERR_VALIDATION", f"{key} must be >= {lo}")
    if hi is not None and val > hi:
        raise ApiError("ERR_VALIDATION", f"{key} must be <= {hi}")
    return val


def v_bool(body, key, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            raise ApiError("ERR_VALIDATION", f"{key} is required")
        return default
    val = body[key]
    if not isinstance(val, bool):
        raise ApiError("ERR_VALIDATION", f"{key} must be a boolean")
    return val


def v_enum(body, key, allowed, required=True):
    if key not in body or body[key] is None:
        if required:
            raise ApiError("ERR_VALIDATION", f"{key} is required")
        return None
    val = body[key]
    if not isinstance(val, str) or val not in allowed:
        raise ApiError("ERR_VALIDATION", f"{key} must be one of {sorted(allowed)}")
    return val


def v_dt(body, key, required=True):
    if key not in body or body[key] is None:
        if required:
            raise ApiError("ERR_VALIDATION", f"{key} is required")
        return None, None
    val = body[key]
    try:
        dt = parse_dt(val)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", f"{key} is not a valid ISO 8601 timestamp")
    return val, dt


def get_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def list_response(coll, filters, serializer):
    items = [e for e in coll.values()
             if all(e.get(k) == val for k, val in filters.items() if val is not None)]
    items.sort(key=lambda e: e["_seq"])
    limit, offset = get_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return ok([serializer(e) for e in page], 200, is_list=True, pagination=pagination)


# =========================================================================
# Derived-field serializers
# =========================================================================
def member_fee_totals(member_id):
    out = waived = paid = 0
    for f in store.fees.values():
        if f["member_id"] != member_id:
            continue
        if f["status"] == "ASSESSED":
            out += f["amount_cents"]
        elif f["status"] == "WAIVED":
            waived += f["amount_cents"]
        elif f["status"] == "PAID":
            paid += f["amount_cents"]
    return out, waived, paid


def iso_week_bounds(dt):
    start = dt.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=dt.weekday())
    return start, start + timedelta(days=7)


def member_week_usage(member_id):
    ws, we = iso_week_bounds(store.clock_dt)
    count = 0
    for r in store.reservations.values():
        if r["member_id"] != member_id:
            continue
        if r["status"] not in WEEK_COUNT_STATUSES:
            continue
        if ws <= r["_start_time"] < we:
            count += 1
    return count


def member_dues_balance(member_id):
    total = 0
    for inv in store.invoices.values():
        if inv["member_id"] != member_id:
            continue
        if inv["status"] in ("PAID", "VOID"):
            continue
        if inv["final_total_cents"] is not None:
            total += inv["final_total_cents"]
        else:
            total += inv["estimated_total_cents"]
    return total


def ser_member(m):
    d = serialize(m)
    out, waived, paid = member_fee_totals(m["id"])
    used = member_week_usage(m["id"])
    tier = store.tiers.get(m["membership_tier"])
    per_week = tier["reservations_per_week"] if tier else 0
    d["outstanding_fees_cents"] = out
    d["waived_fees_cents"] = waived
    d["paid_fees_cents"] = paid
    d["reservations_used_this_week"] = used
    d["reservations_remaining_this_week"] = max(0, per_week - used)
    d["dues_balance_cents"] = member_dues_balance(m["id"])
    return d


def enrolled_count(session_id):
    return sum(1 for e in store.enrollments.values()
               if e["session_id"] == session_id and e["status"] in ("ENROLLED", "ATTENDED"))


def ser_session(s):
    d = serialize(s)
    d["enrolled_count"] = enrolled_count(s["id"])
    return d


# =========================================================================
# Calculations
# =========================================================================
def outstanding_fees(member_id):
    return member_fee_totals(member_id)[0]


def line_taxed(amount_cents):
    return rhu(Decimal(amount_cents) * TAX)


def rolled_fee_set(member_id, eval_dt):
    """Member fees ASSESSED with assessed_at strictly before eval_dt, ordered."""
    fs = [f for f in store.fees.values()
          if f["member_id"] == member_id
          and f["status"] == "ASSESSED"
          and f["_assessed_at"] < eval_dt]
    fs.sort(key=lambda f: f["_seq"])
    return fs


def damage_fee_amount(member, severity, repair_cost_cents):
    deductible = DEDUCTIBLE_BY_TIER[member["membership_tier"]]
    surcharge = SEVERE_SURCHARGE_CENTS if severity == "SEVERE" else 0
    return min(repair_cost_cents, deductible + surcharge)


def rotation_candidates(dock_id, boat_type, start_dt, end_dt, exclude_res_id):
    cands = []
    for b in store.boats.values():
        if b["dock_id"] != dock_id or b["boat_type"] != boat_type:
            continue
        if b["status"] == "MAINTENANCE":
            continue
        if _overlaps_active(b["id"], start_dt, end_dt, exclude_res_id):
            continue
        cands.append(b)
    cands.sort(key=lambda b: (b["usage_count"], b["_seq"]))
    return cands


def _overlaps_active(boat_id, start_dt, end_dt, exclude_res_id):
    for r in store.reservations.values():
        if r["id"] == exclude_res_id:
            continue
        if r.get("boat_id") != boat_id:
            continue
        if r["status"] not in ("CONFIRMED", "CHECKED_OUT"):
            continue
        if start_dt < r["_end_time"] and r["_start_time"] < end_dt:
            return True
    return False


# =========================================================================
# Fee creation helper
# =========================================================================
def create_fee(member_id, reservation_id, fee_type, amount_cents, source_ref=None):
    f = new_common()
    f.update({
        "member_id": member_id,
        "reservation_id": reservation_id,
        "fee_type": fee_type,
        "amount_cents": amount_cents,
        "status": "ASSESSED",
        "assessed_at": store.clock_iso(),
        "_assessed_at": store.clock_dt,
        "source_ref": source_ref,
    })
    store.fees[f["id"]] = f
    return f


def ser_fee(f):
    return serialize(f)


# =========================================================================
# Shared state-transition helpers
# =========================================================================
def release_boat_from_reservation(res):
    """Clear a reservation's boat assignment (boat itself is left untouched)."""
    res["boat_id"] = None


def boat_to_maintenance(boat):
    """Send a boat to MAINTENANCE and cascade CONFIRMED reservations -> REQUESTED."""
    changed = boat["status"] != "MAINTENANCE"
    boat["status"] = "MAINTENANCE"
    if changed:
        touch(boat)
    for r in store.reservations.values():
        if r.get("boat_id") == boat["id"] and r["status"] == "CONFIRMED":
            r["status"] = "REQUESTED"
            r["boat_id"] = None
            touch(r)


def suspend_member(member):
    """ACTIVE -> SUSPENDED with cascade cancel of CONFIRMED reservations."""
    member["status"] = "SUSPENDED"
    touch(member)
    for r in store.reservations.values():
        if r["member_id"] == member["id"] and r["status"] == "CONFIRMED":
            r["status"] = "CANCELLED"
            r["boat_id"] = None
            touch(r)


# =========================================================================
# Docks
# =========================================================================
def ser_dock(d):
    return serialize(d)


@app.route("/docks", methods=["POST"])
def create_dock():
    _uid, role = require_auth()
    authorize(role, {"ClubAdmin"})
    body = get_body()
    name = v_str(body, "name")
    location_code = v_str(body, "location_code")
    capacity = v_int(body, "capacity", minimum=1)
    is_reciprocal = v_bool(body, "is_reciprocal", required=False, default=False)
    ent = new_common()
    ent.update({
        "name": name,
        "location_code": location_code,
        "capacity": capacity,
        "is_reciprocal": bool(is_reciprocal),
    })
    store.docks[ent["id"]] = ent
    return ok(ser_dock(ent), 201)


@app.route("/docks/<dock_id>", methods=["GET"])
def get_dock(dock_id):
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    d = store.docks.get(dock_id)
    if d is None:
        raise ApiError("ERR_DOCK_NOT_FOUND")
    return ok(ser_dock(d))


@app.route("/docks", methods=["GET"])
def list_docks():
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    return list_response(store.docks, {}, ser_dock)


# =========================================================================
# Membership Tiers
# =========================================================================
def ser_tier(t):
    return serialize(t)


@app.route("/membership-tiers", methods=["POST"])
def create_tier():
    _uid, role = require_auth()
    authorize(role, {"ClubAdmin"})
    body = get_body()
    tier_code = v_enum(body, "tier_code", TIER_CODES)
    monthly = v_int(body, "monthly_dues_cents", minimum=0)
    max_active = v_int(body, "max_active_reservations", minimum=1)
    per_week = v_int(body, "reservations_per_week", minimum=1)
    reciprocal = v_bool(body, "reciprocal_access_allowed")
    advance_max = v_int(body, "advance_booking_days_max", minimum=1)
    if tier_code in store.tiers:
        raise ApiError("ERR_VALIDATION", "tier_code already exists")
    ent = {
        "id": tier_code,
        "tier_code": tier_code,
        "monthly_dues_cents": monthly,
        "max_active_reservations": max_active,
        "reservations_per_week": per_week,
        "reciprocal_access_allowed": reciprocal,
        "advance_booking_days_max": advance_max,
        "created_at": now_iso(),
        "_seq": next_seq(),
    }
    store.tiers[tier_code] = ent
    return ok(ser_tier(ent), 201)


@app.route("/membership-tiers/<tier_code>", methods=["GET"])
def get_tier(tier_code):
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    t = store.tiers.get(tier_code)
    if t is None:
        raise ApiError("ERR_TIER_NOT_FOUND")
    return ok(ser_tier(t))


@app.route("/membership-tiers", methods=["GET"])
def list_tiers():
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    return list_response(store.tiers, {}, ser_tier)


# =========================================================================
# Boats
# =========================================================================
def ser_boat(b):
    return serialize(b)


@app.route("/boats", methods=["POST"])
def create_boat():
    _uid, role = require_auth()
    authorize(role, {"ClubAdmin"})
    body = get_body()
    dock_id = v_str(body, "dock_id")
    boat_type = v_enum(body, "boat_type", BOAT_TYPES)
    if dock_id not in store.docks:
        raise ApiError("ERR_DOCK_NOT_FOUND")
    ent = new_common()
    ent.update({
        "dock_id": dock_id,
        "boat_type": boat_type,
        "status": "AVAILABLE",
        "fuel_level_pct": 100,
        "usage_count": 0,
        "needs_cleaning": False,
        "last_used_at": None,
    })
    store.boats[ent["id"]] = ent
    return ok(ser_boat(ent), 201)


@app.route("/boats/<boat_id>", methods=["GET"])
def get_boat(boat_id):
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    b = store.boats.get(boat_id)
    if b is None:
        raise ApiError("ERR_BOAT_NOT_FOUND")
    return ok(ser_boat(b))


@app.route("/boats", methods=["GET"])
def list_boats():
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    filters = {
        "dock_id": request.args.get("dock_id"),
        "boat_type": request.args.get("boat_type"),
        "status": request.args.get("status"),
    }
    return list_response(store.boats, filters, ser_boat)


@app.route("/boats/<boat_id>/maintenance", methods=["POST"])
def boat_maintenance(boat_id):
    _uid, role = require_auth()
    authorize(role, {"DockStaff", "ClubAdmin"})
    b = store.boats.get(boat_id)
    if b is None:
        raise ApiError("ERR_BOAT_NOT_FOUND")
    if b["status"] not in ("AVAILABLE", "OUT", "CLEANING"):
        raise ApiError("ERR_INVALID_STATE", "Boat cannot enter MAINTENANCE from its current state")
    boat_to_maintenance(b)
    return ok(ser_boat(b))


@app.route("/boats/<boat_id>/clean-complete", methods=["POST"])
def boat_clean_complete(boat_id):
    _uid, role = require_auth()
    authorize(role, {"DockStaff", "ClubAdmin"})
    b = store.boats.get(boat_id)
    if b is None:
        raise ApiError("ERR_BOAT_NOT_FOUND")
    if b["status"] not in ("CLEANING", "MAINTENANCE"):
        raise ApiError("ERR_INVALID_STATE", "Boat is not in CLEANING or MAINTENANCE")
    b["status"] = "AVAILABLE"
    b["needs_cleaning"] = False
    b["fuel_level_pct"] = 100
    touch(b)
    return ok(ser_boat(b))


# =========================================================================
# Members
# =========================================================================
@app.route("/members", methods=["POST"])
def create_member():
    _uid, role = require_auth()
    authorize(role, {"ClubAdmin"})
    body = get_body()
    full_name = v_str(body, "full_name")
    email = v_str(body, "email")
    membership_tier = v_enum(body, "membership_tier", TIER_CODES)
    home_dock_id = v_str(body, "home_dock_id")
    # existence, left-to-right in input order (tier before dock)
    if membership_tier not in store.tiers:
        raise ApiError("ERR_TIER_NOT_FOUND")
    if home_dock_id not in store.docks:
        raise ApiError("ERR_DOCK_NOT_FOUND")
    ent = new_common()
    ent.update({
        "full_name": full_name,
        "email": email,
        "membership_tier": membership_tier,
        "home_dock_id": home_dock_id,
        "status": "PENDING_ORIENTATION",
        "orientation_completed": False,
        "certification_level": "NONE",
        "no_show_strikes": 0,
        "last_reinstated_at": None,
    })
    store.members[ent["id"]] = ent
    return ok(ser_member(ent), 201)


@app.route("/members/<member_id>", methods=["GET"])
def get_member(member_id):
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    m = store.members.get(member_id)
    if m is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND")
    return ok(ser_member(m))


@app.route("/members", methods=["GET"])
def list_members():
    _uid, role = require_auth()
    authorize(role, {"DockStaff", "ClubAdmin"})
    filters = {
        "home_dock_id": request.args.get("home_dock_id"),
        "status": request.args.get("status"),
        "membership_tier": request.args.get("membership_tier"),
    }
    return list_response(store.members, filters, ser_member)


@app.route("/members/<member_id>/suspend", methods=["POST"])
def suspend_member_ep(member_id):
    _uid, role = require_auth()
    authorize(role, {"ClubAdmin"})
    m = store.members.get(member_id)
    if m is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND")
    if m["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE member can be suspended")
    suspend_member(m)
    return ok(ser_member(m))


@app.route("/members/<member_id>/reinstate", methods=["POST"])
def reinstate_member_ep(member_id):
    _uid, role = require_auth()
    authorize(role, {"ClubAdmin"})
    m = store.members.get(member_id)
    if m is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND")
    if m["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", "Only a SUSPENDED member can be reinstated")
    if outstanding_fees(m["id"]) != 0:
        raise ApiError("ERR_OUTSTANDING_FEES", "Outstanding fees must be zero to reinstate")
    m["status"] = "ACTIVE"
    m["no_show_strikes"] = 0
    m["last_reinstated_at"] = store.clock_iso()
    touch(m)
    return ok(ser_member(m))


@app.route("/members/<member_id>/dues-invoices", methods=["POST"])
def issue_invoice(member_id):
    _uid, role = require_auth()
    authorize(role, {"ClubAdmin"})
    body = get_body()
    ps_raw, ps_dt = v_dt(body, "period_start")
    pe_raw, pe_dt = v_dt(body, "period_end")
    expected_version = v_int(body, "expected_member_version")
    if pe_dt <= ps_dt:
        raise ApiError("ERR_VALIDATION", "period_end must be after period_start")
    m = store.members.get(member_id)
    if m is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND")
    # OCC (priority 11)
    if expected_version != m["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_member_version does not match member version")

    tier = store.tiers.get(m["membership_tier"])
    base = tier["monthly_dues_cents"] if tier else 0
    issued_at_dt = store.clock_dt
    rolled = rolled_fee_set(m["id"], issued_at_dt)
    fees_rolled = sum(line_taxed(f["amount_cents"]) for f in rolled)
    estimated_total = base + fees_rolled

    inv = new_common()
    inv.update({
        "member_id": m["id"],
        "period_start": ps_raw,
        "_period_start": ps_dt,
        "period_end": pe_raw,
        "_period_end": pe_dt,
        "base_dues_cents": base,
        "fees_rolled_cents": fees_rolled,
        "estimated_total_cents": estimated_total,
        "final_total_cents": None,
        "rolled_fee_ids": [],
        "status": "ISSUED",
        "issued_at": store.clock_iso(),
        "paid_at": None,
    })
    # supersede prior unpaid invoices for this member
    for other in store.invoices.values():
        if other["member_id"] == m["id"] and other["status"] in ("ISSUED", "OVERDUE"):
            other["status"] = "VOID"
            touch(other)
    store.invoices[inv["id"]] = inv
    # issuing bumps member.version by one
    touch(m)
    return ok(serialize(inv), 201)


# =========================================================================
# Reservations
# =========================================================================
def ser_reservation(r):
    return serialize(r)


def _cert_orientation_check(member, boat_type):
    if not member["orientation_completed"]:
        raise ApiError("ERR_ORIENTATION_REQUIRED", "Orientation must be completed first")
    required = "ADVANCED" if boat_type == "CENTER_CONSOLE" else "BASIC"
    if CERT_ORDER[member["certification_level"]] < CERT_ORDER[required]:
        raise ApiError("ERR_CERT_INSUFFICIENT", "Certification level insufficient for boat type")


def _booking_window_check(member, start_dt):
    if start_dt <= store.clock_dt:
        raise ApiError("ERR_BOOKING_WINDOW", "start_time must be in the future")
    tier = store.tiers.get(member["membership_tier"])
    horizon = store.clock_dt + timedelta(days=tier["advance_booking_days_max"])
    if start_dt > horizon:
        raise ApiError("ERR_BOOKING_WINDOW", "start_time beyond advance booking horizon")


def _schedule_conflict_check(member_id, start_dt, end_dt, exclude_res_id):
    gap = timedelta(minutes=MEMBER_TURNAROUND_MIN)
    for r in store.reservations.values():
        if r["id"] == exclude_res_id or r["member_id"] != member_id:
            continue
        if r["status"] not in NON_TERMINAL_RES:
            continue
        if start_dt >= r["_end_time"]:
            if start_dt - r["_end_time"] < gap:
                raise ApiError("ERR_MEMBER_SCHEDULE_CONFLICT", "Too close to another reservation")
        elif r["_start_time"] >= end_dt:
            if r["_start_time"] - end_dt < gap:
                raise ApiError("ERR_MEMBER_SCHEDULE_CONFLICT", "Too close to another reservation")
        else:
            raise ApiError("ERR_MEMBER_SCHEDULE_CONFLICT", "Overlaps another reservation")


@app.route("/reservations", methods=["POST"])
def create_reservation():
    uid, role = require_auth()
    authorize(role, {"Member"})
    body = get_body()
    member_id = v_str(body, "member_id")
    dock_id = v_str(body, "dock_id")
    boat_type = v_enum(body, "boat_type", BOAT_TYPES)
    st_raw, st_dt = v_dt(body, "start_time")
    et_raw, et_dt = v_dt(body, "end_time")
    if et_dt <= st_dt:
        raise ApiError("ERR_VALIDATION", "end_time must be after start_time")
    # existence (member, dock)
    member = store.members.get(member_id)
    if member is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND")
    dock = store.docks.get(dock_id)
    if dock is None:
        raise ApiError("ERR_DOCK_NOT_FOUND")
    # ownership
    if member_id != uid:
        raise ApiError("ERR_FORBIDDEN", "Members may only act on their own reservations")
    # cert / orientation (7)
    _cert_orientation_check(member, boat_type)
    # temporal (8): window, schedule conflict, rotation-eligible boat exists
    _booking_window_check(member, st_dt)
    _schedule_conflict_check(member_id, st_dt, et_dt, None)
    if not rotation_candidates(dock_id, boat_type, st_dt, et_dt, None):
        raise ApiError("ERR_NO_BOAT_AVAILABLE", "No rotation-eligible boat for the window")
    # business (9): reciprocal, max active
    tier = store.tiers.get(member["membership_tier"])
    if dock["is_reciprocal"] and not tier["reciprocal_access_allowed"]:
        raise ApiError("ERR_RECIPROCAL_NOT_ALLOWED", "Tier lacks reciprocal access")
    active = sum(1 for r in store.reservations.values()
                 if r["member_id"] == member_id and r["status"] in ACTIVE_RES_STATUSES)
    if active >= tier["max_active_reservations"]:
        raise ApiError("ERR_MAX_ACTIVE_RESERVATIONS", "Max active reservations reached")
    # fiscal (10)
    if outstanding_fees(member_id) > FEE_BLOCK_LIMIT_CENTS:
        raise ApiError("ERR_OUTSTANDING_FEES", "Outstanding fees exceed reservation block limit")

    ent = new_common()
    ent.update({
        "member_id": member_id,
        "dock_id": dock_id,
        "boat_type": boat_type,
        "boat_id": None,
        "start_time": st_raw,
        "_start_time": st_dt,
        "end_time": et_raw,
        "_end_time": et_dt,
        "status": "REQUESTED",
        "fuel_at_checkout": None,
        "fuel_at_return": None,
        "checkout_time": None,
        "return_time": None,
        "provisional_fuel_fee_cents": None,
    })
    store.reservations[ent["id"]] = ent
    return ok(ser_reservation(ent), 201)


@app.route("/reservations/<reservation_id>", methods=["GET"])
def get_reservation(reservation_id):
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    r = store.reservations.get(reservation_id)
    if r is None:
        raise ApiError("ERR_RESERVATION_NOT_FOUND")
    return ok(ser_reservation(r))


@app.route("/reservations", methods=["GET"])
def list_reservations():
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    filters = {
        "member_id": request.args.get("member_id"),
        "dock_id": request.args.get("dock_id"),
        "boat_id": request.args.get("boat_id"),
        "status": request.args.get("status"),
    }
    return list_response(store.reservations, filters, ser_reservation)


def _load_owned_reservation(reservation_id, uid):
    r = store.reservations.get(reservation_id)
    if r is None:
        raise ApiError("ERR_RESERVATION_NOT_FOUND")
    if r["member_id"] != uid:
        raise ApiError("ERR_FORBIDDEN", "Members may only act on their own reservations")
    return r


@app.route("/reservations/<reservation_id>/confirm", methods=["POST"])
def confirm_reservation(reservation_id):
    uid, role = require_auth()
    authorize(role, {"Member"})
    r = _load_owned_reservation(reservation_id, uid)
    # state (6): reservation REQUESTED, then member ACTIVE
    if r["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "Reservation is not REQUESTED")
    member = store.members[r["member_id"]]
    if member["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE", "Member is not ACTIVE")
    # cert/orientation (7)
    _cert_orientation_check(member, r["boat_type"])
    # temporal (8): window, schedule conflict, rotation
    _booking_window_check(member, r["_start_time"])
    _schedule_conflict_check(member["id"], r["_start_time"], r["_end_time"], r["id"])
    cands = rotation_candidates(r["dock_id"], r["boat_type"], r["_start_time"], r["_end_time"], r["id"])
    if not cands:
        raise ApiError("ERR_NO_BOAT_AVAILABLE", "No rotation-eligible boat for the window")
    # weekly quota (9)
    tier = store.tiers.get(member["membership_tier"])
    ws, we = iso_week_bounds(store.clock_dt)
    used = 0
    for other in store.reservations.values():
        if other["member_id"] == member["id"] and other["id"] != r["id"] \
                and other["status"] in WEEK_COUNT_STATUSES and ws <= other["_start_time"] < we:
            used += 1
    counts_this = ws <= r["_start_time"] < we
    if counts_this and used + 1 > tier["reservations_per_week"]:
        raise ApiError("ERR_WEEKLY_QUOTA_EXCEEDED", "Weekly reservation quota exceeded")
    # commit
    selected = cands[0]
    r["status"] = "CONFIRMED"
    r["boat_id"] = selected["id"]
    touch(r)
    return ok(ser_reservation(r))


@app.route("/reservations/<reservation_id>/checkout", methods=["POST"])
def checkout_reservation(reservation_id):
    uid, role = require_auth()
    authorize(role, {"Member"})
    body = get_body()
    fuel = v_num(body, "fuel_at_checkout", lo=0, hi=100)
    r = _load_owned_reservation(reservation_id, uid)
    if r["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", "Reservation is not CONFIRMED")
    boat = store.boats.get(r["boat_id"]) if r.get("boat_id") else None
    if boat is None or boat["status"] != "AVAILABLE":
        raise ApiError("ERR_BOAT_NOT_AVAILABLE", "Assigned boat is not AVAILABLE")
    # commit
    r["status"] = "CHECKED_OUT"
    r["fuel_at_checkout"] = fuel
    r["checkout_time"] = store.clock_iso()
    if fuel > FUEL_MIN_PCT:
        prov = rhu(Decimal(FUEL_RATE_CENTS_PER_PCT) * Decimal(str(fuel - FUEL_MIN_PCT)))
    else:
        prov = 0
    r["provisional_fuel_fee_cents"] = prov
    touch(r)
    boat["status"] = "OUT"
    touch(boat)
    return ok(ser_reservation(r))


@app.route("/reservations/<reservation_id>/return", methods=["POST"])
def return_reservation(reservation_id):
    uid, role = require_auth()
    authorize(role, {"Member"})
    body = get_body()
    fuel = v_num(body, "fuel_at_return", lo=0, hi=100)
    cleaning_state = v_str(body, "cleaning_state", required=False)
    r = _load_owned_reservation(reservation_id, uid)
    if r["status"] != "CHECKED_OUT":
        raise ApiError("ERR_INVALID_STATE", "Reservation is not CHECKED_OUT")
    # commit reservation + boat
    r["status"] = "RETURNED"
    r["fuel_at_return"] = fuel
    r["return_time"] = store.clock_iso()
    touch(r)
    boat = store.boats.get(r["boat_id"]) if r.get("boat_id") else None
    if boat is not None:
        boat["status"] = "CLEANING"
        boat["needs_cleaning"] = True
        boat["usage_count"] += 1
        boat["last_used_at"] = store.clock_iso()
        boat["fuel_level_pct"] = fuel
        touch(boat)
    # fees
    # late return
    minutes_late = max(0, math.ceil((store.clock_dt - r["_end_time"]).total_seconds() / 60.0))
    if minutes_late > LATE_GRACE_MIN:
        blocks = math.ceil(minutes_late / LATE_BLOCK_MIN)
        create_fee(r["member_id"], r["id"], "LATE_RETURN", LATE_BLOCK_CENTS * blocks)
    # fuel
    if fuel < FUEL_MIN_PCT:
        checkout_fuel = r["fuel_at_checkout"] if r["fuel_at_checkout"] is not None else fuel
        amount = rhu(Decimal(FUEL_RATE_CENTS_PER_PCT) * Decimal(str(checkout_fuel - fuel)))
        create_fee(r["member_id"], r["id"], "FUEL", amount)
    # cleaning
    if cleaning_state == "SOILED":
        create_fee(r["member_id"], r["id"], "CLEANING", CLEANING_FEE_CENTS)
    return ok(ser_reservation(r))


@app.route("/reservations/<reservation_id>/cancel", methods=["POST"])
def cancel_reservation(reservation_id):
    uid, role = require_auth()
    authorize(role, {"Member"})
    r = _load_owned_reservation(reservation_id, uid)
    if r["status"] not in ("REQUESTED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE", "Reservation cannot be cancelled from its current state")
    r["status"] = "CANCELLED"
    r["boat_id"] = None
    touch(r)
    return ok(ser_reservation(r))


# =========================================================================
# Training Sessions
# =========================================================================
@app.route("/training-sessions", methods=["POST"])
def create_session():
    _uid, role = require_auth()
    authorize(role, {"ClubAdmin"})
    body = get_body()
    dock_id = v_str(body, "dock_id")
    session_type = v_enum(body, "session_type", SESSION_TYPES)
    st_raw, st_dt = v_dt(body, "start_time")
    et_raw, et_dt = v_dt(body, "end_time")
    capacity = v_int(body, "capacity", minimum=1)
    instructor = v_str(body, "instructor_name")
    if et_dt <= st_dt:
        raise ApiError("ERR_VALIDATION", "end_time must be after start_time")
    if dock_id not in store.docks:
        raise ApiError("ERR_DOCK_NOT_FOUND")
    ent = new_common()
    ent.update({
        "dock_id": dock_id,
        "session_type": session_type,
        "start_time": st_raw,
        "_start_time": st_dt,
        "end_time": et_raw,
        "_end_time": et_dt,
        "capacity": capacity,
        "instructor_name": instructor,
        "status": "SCHEDULED",
    })
    store.sessions[ent["id"]] = ent
    return ok(ser_session(ent), 201)


@app.route("/training-sessions/<session_id>", methods=["GET"])
def get_session(session_id):
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    s = store.sessions.get(session_id)
    if s is None:
        raise ApiError("ERR_SESSION_NOT_FOUND")
    return ok(ser_session(s))


@app.route("/training-sessions", methods=["GET"])
def list_sessions():
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    filters = {
        "dock_id": request.args.get("dock_id"),
        "session_type": request.args.get("session_type"),
        "status": request.args.get("status"),
    }
    return list_response(store.sessions, filters, ser_session)


# =========================================================================
# Enrollments
# =========================================================================
def ser_enrollment(e):
    return serialize(e)


@app.route("/enrollments", methods=["POST"])
def create_enrollment():
    uid, role = require_auth()
    authorize(role, {"Member"})
    body = get_body()
    member_id = v_str(body, "member_id")
    session_id = v_str(body, "session_id")
    # existence (member, session)
    member = store.members.get(member_id)
    if member is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND")
    session = store.sessions.get(session_id)
    if session is None:
        raise ApiError("ERR_SESSION_NOT_FOUND")
    # ownership
    if member_id != uid:
        raise ApiError("ERR_FORBIDDEN", "Members may only enroll themselves")
    # business (9): duplicate then session full
    for e in store.enrollments.values():
        if e["member_id"] == member_id and e["session_id"] == session_id and e["status"] == "ENROLLED":
            raise ApiError("ERR_DUPLICATE_ENROLLMENT", "Member already enrolled in this session")
    if enrolled_count(session_id) >= session["capacity"]:
        raise ApiError("ERR_SESSION_FULL", "Session is at capacity")
    ent = new_common()
    ent.update({
        "member_id": member_id,
        "session_id": session_id,
        "status": "ENROLLED",
    })
    store.enrollments[ent["id"]] = ent
    # session may reach capacity -> FULL
    if session["status"] == "SCHEDULED" and enrolled_count(session_id) >= session["capacity"]:
        session["status"] = "FULL"
        touch(session)
    return ok(ser_enrollment(ent), 201)


@app.route("/enrollments/<enrollment_id>", methods=["GET"])
def get_enrollment(enrollment_id):
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    e = store.enrollments.get(enrollment_id)
    if e is None:
        raise ApiError("ERR_ENROLLMENT_NOT_FOUND")
    return ok(ser_enrollment(e))


@app.route("/enrollments", methods=["GET"])
def list_enrollments():
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    filters = {
        "member_id": request.args.get("member_id"),
        "session_id": request.args.get("session_id"),
        "status": request.args.get("status"),
    }
    return list_response(store.enrollments, filters, ser_enrollment)


@app.route("/enrollments/<enrollment_id>/mark-attendance", methods=["POST"])
def mark_attendance(enrollment_id):
    _uid, role = require_auth()
    authorize(role, {"DockStaff", "ClubAdmin"})
    body = get_body()
    attended = v_bool(body, "attended")
    e = store.enrollments.get(enrollment_id)
    if e is None:
        raise ApiError("ERR_ENROLLMENT_NOT_FOUND")
    # state (6)
    if e["status"] != "ENROLLED":
        raise ApiError("ERR_INVALID_STATE", "Enrollment is not ENROLLED")
    session = store.sessions[e["session_id"]]
    if session["status"] not in ("SCHEDULED", "FULL"):
        raise ApiError("ERR_INVALID_STATE", "Session is not open for attendance")
    member = store.members[e["member_id"]]
    if attended:
        # cert / orientation prerequisites (7)
        if session["session_type"] == "BASIC_CERT" and not member["orientation_completed"]:
            raise ApiError("ERR_ORIENTATION_REQUIRED", "Orientation required before BASIC certification")
        if session["session_type"] == "ADVANCED_CERT" and member["certification_level"] != "BASIC":
            raise ApiError("ERR_CERT_INSUFFICIENT", "BASIC certification required before ADVANCED")
        e["status"] = "ATTENDED"
        touch(e)
        # grants
        st = session["session_type"]
        if st == "ORIENTATION":
            member["orientation_completed"] = True
            if member["status"] == "PENDING_ORIENTATION":
                member["status"] = "ACTIVE"
            touch(member)
        elif st == "BASIC_CERT":
            member["certification_level"] = "BASIC"
            touch(member)
        elif st == "ADVANCED_CERT":
            member["certification_level"] = "ADVANCED"
            touch(member)
    else:
        e["status"] = "NO_SHOW"
        touch(e)
    _reconcile_session_status(session)
    return ok(ser_enrollment(e))


def _reconcile_session_status(session):
    sess_enrollments = [e for e in store.enrollments.values() if e["session_id"] == session["id"]]
    if sess_enrollments and all(e["status"] in ("ATTENDED", "NO_SHOW") for e in sess_enrollments):
        if session["status"] != "COMPLETED":
            session["status"] = "COMPLETED"
            touch(session)
        return
    cnt = enrolled_count(session["id"])
    if session["status"] == "FULL" and cnt < session["capacity"]:
        session["status"] = "SCHEDULED"
        touch(session)
    elif session["status"] == "SCHEDULED" and cnt >= session["capacity"]:
        session["status"] = "FULL"
        touch(session)


# =========================================================================
# Damage Reports
# =========================================================================
def ser_damage(d):
    return serialize(d)


@app.route("/damage-reports", methods=["POST"])
def create_damage_report():
    _uid, role = require_auth()
    authorize(role, {"DockStaff", "ClubAdmin"})
    body = get_body()
    reservation_id = v_str(body, "reservation_id")
    boat_id = v_str(body, "boat_id")
    severity = v_enum(body, "severity", SEVERITIES)
    repair_cost = v_int(body, "repair_cost_cents", minimum=0)
    if reservation_id not in store.reservations:
        raise ApiError("ERR_RESERVATION_NOT_FOUND")
    if boat_id not in store.boats:
        raise ApiError("ERR_BOAT_NOT_FOUND")
    ent = new_common()
    ent.update({
        "reservation_id": reservation_id,
        "boat_id": boat_id,
        "severity": severity,
        "repair_cost_cents": repair_cost,
        "assessed_fee_cents": None,
        "status": "FILED",
    })
    store.damage_reports[ent["id"]] = ent
    return ok(ser_damage(ent), 201)


@app.route("/damage-reports/<report_id>", methods=["GET"])
def get_damage_report(report_id):
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    d = store.damage_reports.get(report_id)
    if d is None:
        raise ApiError("ERR_DAMAGE_REPORT_NOT_FOUND")
    return ok(ser_damage(d))


@app.route("/damage-reports", methods=["GET"])
def list_damage_reports():
    _uid, role = require_auth()
    authorize(role, {"DockStaff", "ClubAdmin"})
    filters = {
        "reservation_id": request.args.get("reservation_id"),
        "boat_id": request.args.get("boat_id"),
        "status": request.args.get("status"),
    }
    return list_response(store.damage_reports, filters, ser_damage)


@app.route("/damage-reports/<report_id>/assess", methods=["POST"])
def assess_damage_report(report_id):
    _uid, role = require_auth()
    authorize(role, {"DockStaff", "ClubAdmin"})
    d = store.damage_reports.get(report_id)
    if d is None:
        raise ApiError("ERR_DAMAGE_REPORT_NOT_FOUND")
    if d["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", "Damage report is not FILED")
    reservation = store.reservations[d["reservation_id"]]
    member = store.members[reservation["member_id"]]
    fee_amount = damage_fee_amount(member, d["severity"], d["repair_cost_cents"])
    d["assessed_fee_cents"] = fee_amount
    d["status"] = "ASSESSED"
    touch(d)
    create_fee(member["id"], reservation["id"], "DAMAGE", fee_amount, source_ref=d["id"])
    boat = store.boats.get(d["boat_id"])
    if boat is not None:
        boat_to_maintenance(boat)
    return ok(ser_damage(d))


# =========================================================================
# Fees
# =========================================================================
@app.route("/fees/<fee_id>", methods=["GET"])
def get_fee(fee_id):
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    f = store.fees.get(fee_id)
    if f is None:
        raise ApiError("ERR_FEE_NOT_FOUND")
    return ok(ser_fee(f))


@app.route("/fees", methods=["GET"])
def list_fees():
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    filters = {
        "member_id": request.args.get("member_id"),
        "reservation_id": request.args.get("reservation_id"),
        "status": request.args.get("status"),
        "fee_type": request.args.get("fee_type"),
    }
    return list_response(store.fees, filters, ser_fee)


@app.route("/fees/<fee_id>/waive", methods=["POST"])
def waive_fee(fee_id):
    _uid, role = require_auth()
    authorize(role, {"DockStaff", "ClubAdmin"})
    f = store.fees.get(fee_id)
    if f is None:
        raise ApiError("ERR_FEE_NOT_FOUND")
    if f["status"] != "ASSESSED":
        raise ApiError("ERR_FEE_NOT_ASSESSED", "Only an ASSESSED fee can be waived")
    f["status"] = "WAIVED"
    touch(f)
    return ok(ser_fee(f))


# =========================================================================
# Dues Invoices
# =========================================================================
@app.route("/dues-invoices/<invoice_id>", methods=["GET"])
def get_invoice(invoice_id):
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    inv = store.invoices.get(invoice_id)
    if inv is None:
        raise ApiError("ERR_INVOICE_NOT_FOUND")
    return ok(serialize(inv))


@app.route("/dues-invoices", methods=["GET"])
def list_invoices():
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    filters = {
        "member_id": request.args.get("member_id"),
        "status": request.args.get("status"),
    }
    return list_response(store.invoices, filters, serialize)


@app.route("/dues-invoices/<invoice_id>/pay", methods=["POST"])
def pay_invoice(invoice_id):
    uid, role = require_auth()
    authorize(role, {"Member"})
    inv = store.invoices.get(invoice_id)
    if inv is None:
        raise ApiError("ERR_INVOICE_NOT_FOUND")
    if inv["member_id"] != uid:
        raise ApiError("ERR_FORBIDDEN", "Members may only pay their own invoices")
    if inv["status"] not in ("ISSUED", "OVERDUE"):
        raise ApiError("ERR_INVALID_STATE", "Invoice is not payable")
    paid_at_dt = store.clock_dt
    rolled = rolled_fee_set(inv["member_id"], paid_at_dt)
    fees_rolled = sum(line_taxed(f["amount_cents"]) for f in rolled)
    inv["fees_rolled_cents"] = fees_rolled
    inv["final_total_cents"] = inv["base_dues_cents"] + fees_rolled
    inv["rolled_fee_ids"] = [f["id"] for f in rolled]
    inv["paid_at"] = store.clock_iso()
    inv["status"] = "PAID"
    touch(inv)
    for f in rolled:
        f["status"] = "PAID"
        touch(f)
    return ok(serialize(inv))


# =========================================================================
# Test-driving operations
# =========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _uid, role = require_auth()
    authorize(role, {"ClubAdmin"})
    body = get_body()
    _raw, dt = v_dt(body, "to_iso8601")
    store.clock_dt = dt
    return ok({})


@app.route("/_ops/run-no-show-sweep", methods=["POST"])
def run_no_show_sweep():
    _uid, role = require_auth()
    authorize(role, {"ClubAdmin"})
    grace = timedelta(minutes=NO_SHOW_GRACE_MIN)
    # deterministic order over currently-confirmed reservations
    candidates = sorted(
        [r for r in store.reservations.values() if r["status"] == "CONFIRMED"],
        key=lambda r: r["_seq"],
    )
    for r in candidates:
        if r["status"] != "CONFIRMED":
            continue  # may have been cancelled by a suspension cascade
        if store.clock_dt > r["_start_time"] + grace:
            r["status"] = "NO_SHOW"
            r["boat_id"] = None
            touch(r)
            member = store.members[r["member_id"]]
            create_fee(member["id"], r["id"], "NO_SHOW", NO_SHOW_FEE_CENTS)
            member["no_show_strikes"] += 1
            touch(member)
            if member["no_show_strikes"] >= NO_SHOW_SUSPEND_THRESHOLD and member["status"] == "ACTIVE":
                suspend_member(member)
    # overdue invoices
    for inv in store.invoices.values():
        if inv["status"] == "ISSUED" and store.clock_dt >= inv["_period_end"]:
            inv["status"] = "OVERDUE"
            touch(inv)
    return ok({})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
