#!/usr/bin/env python3
"""
Indoor Playground & Kids' Café REST API implementation.

Single-process Flask app with a purely in-memory store. Every boot starts
empty; the logical clock starts at exactly 2026-05-01T00:00:00Z.
"""

import os
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, jsonify, request

# ---------------------------------------------------------------------------
# In-memory data store
# ---------------------------------------------------------------------------

db = {
    "membership_plans": {},
    "guardians": {},
    "children": {},
    "waivers": {},
    "session_slots": {},
    "visits": {},
    "party_rooms": {},
    "party_packages": {},
    "party_bookings": {},
    "cafe_menu_items": {},
    "cafe_orders": {},
    "loyalty_transactions": {},
    "staff_members": {},
    "sanitation_tasks": {},
    "incidents": {},
}

CLOCK_START_ISO = "2026-05-01T00:00:00Z"
current_utc = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Time / ID / timestamp helpers
# ---------------------------------------------------------------------------

def now():
    return current_utc


def now_ts():
    return _fmt_ts(now())


def _fmt_ts(dt):
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


def new_id():
    return str(uuid.uuid4())


def parse_iso(value):
    """Parse an ISO 8601 datetime (accepts trailing Z). Returns aware UTC datetime."""
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


def parse_date(value):
    """Parse an ISO date string (YYYY-MM-DD). Returns datetime.date or None."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

HTTP_STATUS_BY_ERROR = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_VALIDATION": 400,
    "ERR_INVALID_ENUM": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_SLOT_NOT_OPEN": 409,
    "ERR_CHECKIN_WINDOW_CLOSED": 422,
    "ERR_DUPLICATE_VISIT": 409,
    "ERR_CHILD_AGE_OUT_OF_RANGE": 422,
    "ERR_WAIVER_INVALID": 422,
    "ERR_GRIP_SOCKS_REQUIRED": 422,
    "ERR_RESERVATION_QUOTA_FULL": 409,
    "ERR_SLOT_AT_CAPACITY": 409,
    "ERR_SLOT_OVERLAP": 409,
    "ERR_CAPACITY_BELOW_OCCUPANCY": 422,
    "ERR_ROOM_TIME_CONFLICT": 409,
    "ERR_ROOM_INACTIVE": 422,
    "ERR_PACKAGE_RETIRED": 422,
    "ERR_PLAN_RETIRED": 422,
    "ERR_MENU_ITEM_RETIRED": 422,
    "ERR_ALLERGEN_CONFLICT": 422,
    "ERR_SANITATION_OVERDUE": 422,
    "ERR_RESCHEDULE_CUTOFF": 422,
    "ERR_CANCEL_CUTOFF": 422,
    "ERR_MEMBERSHIP_REQUIRED": 422,
    "ERR_INSUFFICIENT_CREDITS": 402,
    "ERR_INSUFFICIENT_POINTS": 402,
    "ERR_REDEMPTION_CAP_EXCEEDED": 422,
    "ERR_LOST_CHILD_UNRESOLVED": 409,
    "ERR_CHILD_NOT_REUNITED": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = HTTP_STATUS_BY_ERROR[error_id]
        self.message = message or error_id


def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", msg)


def err_validation(msg="Malformed payload"):
    return ApiError("ERR_VALIDATION", msg)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.url_map.strict_slashes = False


def _request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choices(alphabet, k=20))


def success_response(data, status_code=200, pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_ts(),
    }
    response_type = "object"
    if pagination is not None:
        meta.update({
            "limit": pagination["limit"],
            "offset": pagination["offset"],
            "total_count": pagination["total_count"],
            "has_more": pagination["has_more"],
        })
        response_type = "array"
    elif isinstance(data, list):
        response_type = "array"
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    return jsonify(body), status_code


def error_response(error_id, message, http_status):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": now_ts(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_404(exc):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(exc):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return handle_api_error(exc)
    return error_response("ERR_VALIDATION", str(exc) or "Internal error", 400)


# ---------------------------------------------------------------------------
# Auth & RBAC
# ---------------------------------------------------------------------------

VALID_ROLES = {"Anonymous", "Guardian", "FrontDesk", "CafeStaff", "Manager", "Admin"}
ENTITY_BACKED_ROLES = {"Guardian", "FrontDesk", "CafeStaff", "Manager"}
STAFF_ROLE_BY_NAME = {"FrontDesk": "FRONT_DESK", "CafeStaff": "CAFE_STAFF", "Manager": "MANAGER"}


def authenticate(roles, guardian_id=None):
    """
    Priority 1 + 2 auth checks.
    roles: iterable of role names permitted for this endpoint.
    guardian_id: owning guardian id (path or body) for self-service checks; None when n/a.
    Returns (role, user_id).
    """
    user_role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")

    if "Anonymous" in roles and user_role is None:
        return "Anonymous", None

    if user_role is None or user_role not in VALID_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or invalid X-User-Role")
    if user_role in ENTITY_BACKED_ROLES and not user_id:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing X-User-ID for entity-backed role")

    if user_role not in roles:
        raise ApiError("ERR_FORBIDDEN", "Role not permitted on this endpoint")

    if user_role in STAFF_ROLE_BY_NAME:
        staff = db["staff_members"].get(user_id)
        if (
            staff is None
            or staff.get("status") != "ACTIVE"
            or staff.get("role") != STAFF_ROLE_BY_NAME[user_role]
        ):
            raise ApiError("ERR_FORBIDDEN", "Staff identity invalid, inactive, or role mismatch")

    if user_role == "Guardian" and guardian_id is not None and guardian_id != user_id:
        raise ApiError("ERR_FORBIDDEN", "Guardian may only act on own resources")

    return user_role, user_id


# ---------------------------------------------------------------------------
# Payload validation helpers
# ---------------------------------------------------------------------------

ALLERGEN_CODES = {"PEANUT", "TREE_NUT", "MILK", "EGG", "WHEAT", "SOY", "FISH", "SESAME"}


def get_payload():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err_validation("JSON body must be an object")
    return data


def req_str(payload, field):
    v = payload.get(field)
    if not isinstance(v, str) or not v:
        raise err_validation(f"Missing or invalid required field: {field}")
    return v


def opt_str(payload, field, default=None):
    v = payload.get(field, default)
    if v is None:
        return None
    if not isinstance(v, str):
        raise err_validation(f"Invalid type for field: {field}")
    return v


def req_int(payload, field):
    v = payload.get(field)
    if not isinstance(v, int) or isinstance(v, bool):
        raise err_validation(f"Missing or invalid required field: {field}")
    return v


def opt_int(payload, field, default=None):
    v = payload.get(field, default)
    if v is None:
        return None
    if not isinstance(v, int) or isinstance(v, bool):
        raise err_validation(f"Invalid type for field: {field}")
    return v


def opt_bool(payload, field, default=None):
    v = payload.get(field, default)
    if v is None:
        return None
    if not isinstance(v, bool):
        raise err_validation(f"Invalid type for field: {field}")
    return v


def req_number(payload, field):
    v = payload.get(field)
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        raise err_validation(f"Missing or invalid required field: {field}")
    return v


def opt_enum(payload, field, allowed, default=None):
    v = payload.get(field, default)
    if v is None:
        return None
    if not isinstance(v, str):
        raise err_validation(f"Invalid type for field: {field}")
    if v not in allowed:
        raise ApiError("ERR_INVALID_ENUM", f"Invalid value for {field}: {v}")
    return v


def opt_str_list(payload, field, default=None):
    v = payload.get(field, default)
    if v is None:
        return None
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise err_validation(f"Invalid type for field: {field}")
    return list(v)


def opt_allergen_list(payload, field, default=None):
    v = payload.get(field, default)
    if v is None:
        return None
    if not isinstance(v, list):
        raise err_validation(f"Invalid type for field: {field}")
    for x in v:
        if not isinstance(x, str):
            raise err_validation(f"Invalid type for field: {field}")
        if x not in ALLERGEN_CODES:
            raise ApiError("ERR_INVALID_ENUM", f"Invalid allergen code: {x}")
    return list(v)


def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            limit = 10
        limit = max(1, min(100, limit))
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            offset = 0
        offset = max(0, offset)
    return limit, offset


def paginate(items, serializer):
    items_sorted = sorted(items, key=lambda r: r["created_at"])
    total = len(items_sorted)
    limit, offset = parse_pagination()
    page = items_sorted[offset:offset + limit]
    has_more = (offset + limit) < total
    return success_response(
        [serializer(r) for r in page],
        200,
        {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more},
    )


# ---------------------------------------------------------------------------
# Entity mutation helpers
# ---------------------------------------------------------------------------

def touch(entity):
    entity["updated_at"] = now_ts()
    entity["version"] += 1


def new_common_fields():
    ts = now_ts()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def round_half_up_cents(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def tiered_charge_cents(elapsed_minutes):
    m = max(0, elapsed_minutes)
    return (
        min(m, 60) * 20
        + max(0, min(m, 120) - 60) * 15
        + max(0, m - 120) * 10
    )


def elapsed_minutes(start_dt, end_dt):
    delta = (end_dt - start_dt).total_seconds()
    return int(-(-delta // 60))  # ceil


def guardian_membership_active(guardian):
    return guardian.get("membership_status") == "ACTIVE"


def guardian_plan(guardian):
    pid = guardian.get("membership_plan_id")
    if pid is None:
        return None
    return db["membership_plans"].get(pid)


def guardian_visits(guardian_id):
    return [v for v in db["visits"].values() if v["guardian_id"] == guardian_id]


def credit_counters(guardian_id):
    visits = [v for v in guardian_visits(guardian_id) if v.get("use_credit")]
    consumed = sum(1 for v in visits if v["admission_status"] in ("COMPLETED", "NO_SHOW"))
    held = sum(1 for v in visits if v["admission_status"] in ("RESERVED", "CHECKED_IN"))
    return consumed, held


def guardian_ledger(guardian_id):
    txns = sorted(
        (t for t in db["loyalty_transactions"].values() if t["guardian_id"] == guardian_id),
        key=lambda t: t["created_at"],
    )
    points_balance = 0
    lifetime = 0
    for t in txns:
        points_balance += t["points"]
        if t["kind"] in ("EARN",):
            lifetime += t["points"]
        elif t["kind"] == "ADJUSTMENT" and t["points"] > 0:
            lifetime += t["points"]
        elif t["kind"] == "REVERSAL":
            lifetime += t["points"]  # reversals reduce lifetime when negative
    lifetime = max(0, lifetime)
    return txns, points_balance, lifetime


def tier_from_lifetime(lifetime):
    if lifetime >= 5000:
        return "GOLD"
    if lifetime >= 1000:
        return "SILVER"
    return "BRONZE"


TIER_MULTIPLIER = {"BRONZE": 1, "SILVER": 2, "GOLD": 3}


def guardian_snapshot_fields(guardian):
    gid = guardian["id"]
    consumed, held = credit_counters(gid)
    granted = guardian["credits_granted"] if guardian_membership_active(guardian) else guardian["credits_granted"]
    _, points_balance, lifetime = guardian_ledger(gid)
    return {
        "credits_consumed": consumed,
        "credits_held": held,
        "credits_available": granted - consumed - held,
        "credits_statement": granted - consumed,
        "points_balance": points_balance,
        "lifetime_points": lifetime,
        "loyalty_tier": tier_from_lifetime(lifetime),
    }


def slot_counters(slot_id):
    visits = [v for v in db["visits"].values() if v["session_slot_id"] == slot_id]
    reserved = sum(1 for v in visits if v["admission_status"] == "RESERVED")
    checked_in = sum(1 for v in visits if v["admission_status"] == "CHECKED_IN")
    return reserved, checked_in


def reservation_quota(capacity):
    return (capacity * 7) // 10


# ---------------------------------------------------------------------------
# Loyalty ledger writes
# ---------------------------------------------------------------------------

def post_loyalty_txn(guardian_id, kind, points, note):
    _, balance, _ = guardian_ledger(guardian_id)
    balance_after = balance + points
    txn = {
        "id": new_id(),
        "created_at": now_ts(),
        "guardian_id": guardian_id,
        "kind": kind,
        "points": points,
        "balance_after": balance_after,
        "note": note,
    }
    db["loyalty_transactions"][txn["id"]] = txn
    return txn


def guardian_has_current_waiver(guardian_id):
    for w in db["waivers"].values():
        if (
            w["guardian_id"] == guardian_id
            and w["status"] == "SIGNED"
            and parse_iso(w["expires_at"]) is not None
            and parse_iso(w["expires_at"]) > now()
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def ser_membership_plan(p):
    return {
        "id": p["id"], "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"], "name": p["name"],
        "monthly_fee_cents": p["monthly_fee_cents"],
        "included_session_credits": p["included_session_credits"],
        "party_discount_pct": p["party_discount_pct"],
        "cafe_discount_pct": p["cafe_discount_pct"],
        "socks_included": p["socks_included"], "status": p["status"],
    }


def ser_guardian(g):
    out = {
        "id": g["id"], "created_at": g["created_at"], "updated_at": g["updated_at"],
        "version": g["version"], "full_name": g["full_name"], "email": g["email"],
        "phone": g["phone"], "membership_plan_id": g["membership_plan_id"],
        "membership_status": g["membership_status"],
        "credits_granted": g["credits_granted"],
    }
    out.update(guardian_snapshot_fields(g))
    return out


def ser_child(c):
    return {
        "id": c["id"], "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"], "guardian_id": c["guardian_id"],
        "full_name": c["full_name"], "birth_date": c["birth_date"],
        "allergies": list(c["allergies"]),
    }


def ser_waiver(w):
    return {
        "id": w["id"], "created_at": w["created_at"], "updated_at": w["updated_at"],
        "version": w["version"], "guardian_id": w["guardian_id"],
        "signed_at": w["signed_at"], "expires_at": w["expires_at"], "status": w["status"],
    }


def ser_session_slot(s):
    reserved, checked_in = slot_counters(s["id"])
    return {
        "id": s["id"], "created_at": s["created_at"], "updated_at": s["updated_at"],
        "version": s["version"], "slot_date": s["slot_date"], "start_at": s["start_at"],
        "end_at": s["end_at"], "capacity": s["capacity"],
        "reservation_quota": reservation_quota(s["capacity"]),
        "reserved_count": reserved, "checked_in_count": checked_in,
        "status": s["status"], "close_reason": s["close_reason"],
    }


def ser_visit(v):
    return {
        "id": v["id"], "created_at": v["created_at"], "updated_at": v["updated_at"],
        "version": v["version"], "session_slot_id": v["session_slot_id"],
        "child_id": v["child_id"], "guardian_id": v["guardian_id"],
        "visit_type": v["visit_type"],
        "booked_duration_minutes": v["booked_duration_minutes"],
        "use_credit": v["use_credit"],
        "admission_status": v["admission_status"],
        "payment_status": v["payment_status"],
        "sock_method": v["sock_method"],
        "grip_socks_order_id": v["grip_socks_order_id"],
        "quoted_cents": v["quoted_cents"],
        "final_charge_cents": v["final_charge_cents"],
        "refund_delta_cents": v["refund_delta_cents"],
        "checked_in_at": v["checked_in_at"],
        "checked_out_at": v["checked_out_at"],
    }


def ser_party_room(r):
    return {
        "id": r["id"], "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"], "name": r["name"],
        "capacity_children": r["capacity_children"], "status": r["status"],
    }


def ser_party_package(p):
    return {
        "id": p["id"], "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"], "name": p["name"],
        "duration_minutes": p["duration_minutes"],
        "base_price_cents": p["base_price_cents"],
        "included_children": p["included_children"],
        "extra_child_price_cents": p["extra_child_price_cents"],
        "cafe_credit_cents": p["cafe_credit_cents"], "status": p["status"],
    }


def ser_party_booking(b):
    return {
        "id": b["id"], "created_at": b["created_at"], "updated_at": b["updated_at"],
        "version": b["version"], "party_room_id": b["party_room_id"],
        "party_package_id": b["party_package_id"], "guardian_id": b["guardian_id"],
        "start_at": b["start_at"], "end_at": b["end_at"],
        "child_count": b["child_count"], "status": b["status"],
        "quoted_total_cents": b["quoted_total_cents"],
        "deposit_cents": b["deposit_cents"], "deposit_paid": b["deposit_paid"],
        "proposed_start_at": b["proposed_start_at"], "refund_cents": b["refund_cents"],
    }


def ser_cafe_menu_item(m):
    return {
        "id": m["id"], "created_at": m["created_at"], "updated_at": m["updated_at"],
        "version": m["version"], "name": m["name"], "price_cents": m["price_cents"],
        "allergen_tags": list(m["allergen_tags"]),
        "is_grip_socks": m["is_grip_socks"], "status": m["status"],
    }


def ser_cafe_order(o):
    return {
        "id": o["id"], "created_at": o["created_at"], "updated_at": o["updated_at"],
        "version": o["version"], "guardian_id": o["guardian_id"],
        "visit_id": o["visit_id"], "party_booking_id": o["party_booking_id"],
        "child_ids": list(o["child_ids"]),
        "lines": [dict(line) for line in o["lines"]],
        "points_to_redeem": o["points_to_redeem"],
        "subtotal_cents": o["subtotal_cents"],
        "points_redeemed": o["points_redeemed"],
        "total_cents": o["total_cents"],
        "points_earned": o["points_earned"],
        "status": o["status"],
    }


def ser_loyalty_transaction(t):
    return {
        "id": t["id"], "created_at": t["created_at"],
        "guardian_id": t["guardian_id"], "kind": t["kind"], "points": t["points"],
        "balance_after": t["balance_after"], "note": t["note"],
    }


def ser_staff_member(s):
    return {
        "id": s["id"], "created_at": s["created_at"], "updated_at": s["updated_at"],
        "version": s["version"], "full_name": s["full_name"],
        "role": s["role"], "status": s["status"],
    }


def ser_sanitation_task(t):
    return {
        "id": t["id"], "created_at": t["created_at"], "updated_at": t["updated_at"],
        "version": t["version"], "party_room_id": t["party_room_id"],
        "kind": t["kind"], "due_at": t["due_at"], "status": t["status"],
        "checklist_passed": t["checklist_passed"],
        "completed_at": t["completed_at"],
    }


def ser_incident(i):
    return {
        "id": i["id"], "created_at": i["created_at"], "updated_at": i["updated_at"],
        "version": i["version"], "visit_id": i["visit_id"], "kind": i["kind"],
        "severity": i["severity"], "description": i["description"],
        "status": i["status"], "child_reunited": i["child_reunited"],
        "resolution_note": i["resolution_note"], "resolved_at": i["resolved_at"],
        "reported_by_staff_id": i["reported_by_staff_id"],
    }


# ---------------------------------------------------------------------------
# Get-or-404 helpers
# ---------------------------------------------------------------------------

def get_guardian_or_404(gid):
    g = db["guardians"].get(gid)
    if g is None:
        raise err_not_found("Guardian not found")
    return g


def get_child_or_404(cid):
    c = db["children"].get(cid)
    if c is None:
        raise err_not_found("Child not found")
    return c


def get_slot_or_404(sid):
    s = db["session_slots"].get(sid)
    if s is None:
        raise err_not_found("SessionSlot not found")
    return s


def get_visit_or_404(vid):
    v = db["visits"].get(vid)
    if v is None:
        raise err_not_found("Visit not found")
    return v


def get_party_room_or_404(rid):
    r = db["party_rooms"].get(rid)
    if r is None:
        raise err_not_found("PartyRoom not found")
    return r


def get_party_package_or_404(pid):
    p = db["party_packages"].get(pid)
    if p is None:
        raise err_not_found("PartyPackage not found")
    return p


def get_party_booking_or_404(bid):
    b = db["party_bookings"].get(bid)
    if b is None:
        raise err_not_found("PartyBooking not found")
    return b


def get_cafe_order_or_404(oid):
    o = db["cafe_orders"].get(oid)
    if o is None:
        raise err_not_found("CafeOrder not found")
    return o


def get_sanitation_task_or_404(tid):
    t = db["sanitation_tasks"].get(tid)
    if t is None:
        raise err_not_found("SanitationTask not found")
    return t


def get_incident_or_404(iid):
    i = db["incidents"].get(iid)
    if i is None:
        raise err_not_found("Incident not found")
    return i


# ---------------------------------------------------------------------------
# Sock compliance
# ---------------------------------------------------------------------------

def validate_sock_compliance(guardian, sock_method, grip_socks_order_id, slot):
    if sock_method == "OWN_GRIP_SOCKS":
        return
    if sock_method == "MEMBERSHIP_PROVIDED":
        if guardian_membership_active(guardian):
            plan = guardian_plan(guardian)
            if plan is not None and plan.get("socks_included"):
                return
        raise ApiError("ERR_GRIP_SOCKS_REQUIRED", "Membership does not include grip socks")
    if sock_method == "PURCHASED":
        if not grip_socks_order_id or not isinstance(grip_socks_order_id, str):
            raise ApiError("ERR_GRIP_SOCKS_REQUIRED", "grip_socks_order_id required")
        order = db["cafe_orders"].get(grip_socks_order_id)
        if order is None:
            raise err_not_found("grip_socks_order not found")
        slot_date = parse_date(slot["slot_date"])
        order_date = parse_iso(order["created_at"]).date() if parse_iso(order["created_at"]) else None
        if (
            order["guardian_id"] == guardian["id"]
            and order["status"] == "SERVED"
            and order_date == slot_date
            and any(
                (db["cafe_menu_items"].get(line.get("menu_item_id")) or {}).get("is_grip_socks")
                for line in order["lines"]
            )
        ):
            return
        raise ApiError("ERR_GRIP_SOCKS_REQUIRED", "No qualifying grip-socks order found")
    raise ApiError("ERR_GRIP_SOCKS_REQUIRED", "Unresolvable sock method")


def child_age_at(birth_date_str, slot_date_str):
    bd = parse_date(birth_date_str)
    sd = parse_date(slot_date_str)
    if bd is None or sd is None:
        return None
    age = sd.year - bd.year - ((sd.month, sd.day) < (bd.month, bd.day))
    return age


# ---------------------------------------------------------------------------
# Visit settlement helpers
# ---------------------------------------------------------------------------

def cancel_reserved_visit(visit, slot):
    """Cancel a RESERVED visit: release credit hold, refund prepaid."""
    visit["admission_status"] = "CANCELLED"
    if visit["payment_status"] == "PREPAID":
        visit["payment_status"] = "REFUNDED"
    touch(visit)


def finalize_evacuated_visit(visit):
    """Charge 50% tiered charge, refund prepaid overpayment, restore credit."""
    checked_in_at = parse_iso(visit["checked_in_at"]) or now()
    m = elapsed_minutes(checked_in_at, now())
    tiered = tiered_charge_cents(m)
    final = round_half_up_cents(Decimal(tiered) * Decimal("0.5"))
    visit["final_charge_cents"] = final
    visit["checked_out_at"] = now_ts()
    if visit["payment_status"] == "PREPAID":
        visit["refund_delta_cents"] = (visit["quoted_cents"] or 0) - final
        visit["payment_status"] = "REFUNDED"
    visit["admission_status"] = "EVACUATED"
    touch(visit)


def close_slot_cascade(slot, reason):
    """Full §3.3 cascade for a slot close. Assumes status already validated."""
    affected_guardians = set()
    for visit in db["visits"].values():
        if visit["session_slot_id"] != slot["id"]:
            continue
        if visit["admission_status"] == "RESERVED":
            cancel_reserved_visit(visit, slot)
            affected_guardians.add(visit["guardian_id"])
        elif visit["admission_status"] == "CHECKED_IN":
            finalize_evacuated_visit(visit)
            affected_guardians.add(visit["guardian_id"])
    for gid in affected_guardians:
        post_loyalty_txn(gid, "ADJUSTMENT", 200, "Slot closure compensation")
        guardian = db["guardians"].get(gid)
        if guardian is not None:
            touch(guardian)
    slot["status"] = "CLOSED"
    slot["close_reason"] = reason
    touch(slot)


# ---------------------------------------------------------------------------
# Config endpoints: membership plans
# ---------------------------------------------------------------------------

@app.route("/membership-plans", methods=["POST"])
def create_membership_plan():
    authenticate(["Admin"])
    p = get_payload()
    name = req_str(p, "name")
    monthly_fee_cents = req_int(p, "monthly_fee_cents")
    included_session_credits = req_int(p, "included_session_credits")
    party_discount_pct = req_number(p, "party_discount_pct")
    cafe_discount_pct = req_number(p, "cafe_discount_pct")
    socks_included = p.get("socks_included")
    if not isinstance(socks_included, bool):
        raise err_validation("Missing or invalid required field: socks_included")
    plan = new_common_fields()
    plan.update({
        "name": name,
        "monthly_fee_cents": monthly_fee_cents,
        "included_session_credits": included_session_credits,
        "party_discount_pct": party_discount_pct,
        "cafe_discount_pct": cafe_discount_pct,
        "socks_included": socks_included,
        "status": "ACTIVE",
    })
    db["membership_plans"][plan["id"]] = plan
    return success_response(ser_membership_plan(plan), 201)


@app.route("/membership-plans", methods=["GET"])
def list_membership_plans():
    authenticate(["Anonymous", "Guardian", "FrontDesk", "CafeStaff", "Manager", "Admin"])
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in ("ACTIVE", "RETIRED"):
        raise ApiError("ERR_INVALID_ENUM", f"Invalid status: {status_filter}")
    plans = [p for p in db["membership_plans"].values() if status_filter is None or p["status"] == status_filter]
    return paginate(plans, ser_membership_plan)


@app.route("/membership-plans/<id>", methods=["PATCH"])
def patch_membership_plan(id):
    authenticate(["Admin"])
    plan = db["membership_plans"].get(id)
    if plan is None:
        raise err_not_found("MembershipPlan not found")
    p = get_payload()
    status = opt_enum(p, "status", ("ACTIVE", "RETIRED"))
    if status is not None:
        plan["status"] = status
    touch(plan)
    return success_response(ser_membership_plan(plan), 200)


# ---------------------------------------------------------------------------
# Config endpoints: party packages
# ---------------------------------------------------------------------------

@app.route("/party-packages", methods=["POST"])
def create_party_package():
    authenticate(["Admin"])
    p = get_payload()
    name = req_str(p, "name")
    duration_minutes = req_int(p, "duration_minutes")
    base_price_cents = req_int(p, "base_price_cents")
    included_children = req_int(p, "included_children")
    extra_child_price_cents = req_int(p, "extra_child_price_cents")
    cafe_credit_cents = req_int(p, "cafe_credit_cents")
    pkg = new_common_fields()
    pkg.update({
        "name": name,
        "duration_minutes": duration_minutes,
        "base_price_cents": base_price_cents,
        "included_children": included_children,
        "extra_child_price_cents": extra_child_price_cents,
        "cafe_credit_cents": cafe_credit_cents,
        "status": "ACTIVE",
    })
    db["party_packages"][pkg["id"]] = pkg
    return success_response(ser_party_package(pkg), 201)


@app.route("/party-packages", methods=["GET"])
def list_party_packages():
    authenticate(["Anonymous", "Guardian", "FrontDesk", "CafeStaff", "Manager", "Admin"])
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in ("ACTIVE", "RETIRED"):
        raise ApiError("ERR_INVALID_ENUM", f"Invalid status: {status_filter}")
    pkgs = [p for p in db["party_packages"].values() if status_filter is None or p["status"] == status_filter]
    return paginate(pkgs, ser_party_package)


@app.route("/party-packages/<id>", methods=["PATCH"])
def patch_party_package(id):
    authenticate(["Admin"])
    pkg = db["party_packages"].get(id)
    if pkg is None:
        raise err_not_found("PartyPackage not found")
    p = get_payload()
    status = opt_enum(p, "status", ("ACTIVE", "RETIRED"))
    if status is not None:
        pkg["status"] = status
    touch(pkg)
    return success_response(ser_party_package(pkg), 200)


# ---------------------------------------------------------------------------
# Config endpoints: party rooms
# ---------------------------------------------------------------------------

@app.route("/party-rooms", methods=["POST"])
def create_party_room():
    authenticate(["Admin"])
    p = get_payload()
    name = req_str(p, "name")
    capacity_children = req_int(p, "capacity_children")
    room = new_common_fields()
    room.update({"name": name, "capacity_children": capacity_children, "status": "ACTIVE"})
    db["party_rooms"][room["id"]] = room
    return success_response(ser_party_room(room), 201)


@app.route("/party-rooms", methods=["GET"])
def list_party_rooms():
    authenticate(["Anonymous", "Guardian", "FrontDesk", "CafeStaff", "Manager", "Admin"])
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in ("ACTIVE", "MAINTENANCE", "CLOSED"):
        raise ApiError("ERR_INVALID_ENUM", f"Invalid status: {status_filter}")
    rooms = [r for r in db["party_rooms"].values() if status_filter is None or r["status"] == status_filter]
    return paginate(rooms, ser_party_room)


@app.route("/party-rooms/<id>", methods=["GET"])
def get_party_room(id):
    authenticate(["Anonymous", "Guardian", "FrontDesk", "CafeStaff", "Manager", "Admin"])
    room = get_party_room_or_404(id)
    return success_response(ser_party_room(room), 200)


@app.route("/party-rooms/<id>", methods=["PATCH"])
def patch_party_room(id):
    authenticate(["Admin", "Manager"])
    room = db["party_rooms"].get(id)
    if room is None:
        raise err_not_found("PartyRoom not found")
    p = get_payload()
    status = opt_enum(p, "status", ("ACTIVE", "MAINTENANCE", "CLOSED"))
    if status is not None:
        room["status"] = status
    touch(room)
    return success_response(ser_party_room(room), 200)


# ---------------------------------------------------------------------------
# Config endpoints: cafe menu items
# ---------------------------------------------------------------------------

@app.route("/cafe-menu-items", methods=["POST"])
def create_cafe_menu_item():
    authenticate(["Admin"])
    p = get_payload()
    name = req_str(p, "name")
    price_cents = req_int(p, "price_cents")
    allergen_tags = opt_allergen_list(p, "allergen_tags", []) or []
    is_grip_socks = opt_bool(p, "is_grip_socks", False)
    item = new_common_fields()
    item.update({
        "name": name,
        "price_cents": price_cents,
        "allergen_tags": allergen_tags,
        "is_grip_socks": bool(is_grip_socks),
        "status": "ACTIVE",
    })
    db["cafe_menu_items"][item["id"]] = item
    return success_response(ser_cafe_menu_item(item), 201)


@app.route("/cafe-menu-items", methods=["GET"])
def list_cafe_menu_items():
    authenticate(["Anonymous", "Guardian", "FrontDesk", "CafeStaff", "Manager", "Admin"])
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in ("ACTIVE", "RETIRED"):
        raise ApiError("ERR_INVALID_ENUM", f"Invalid status: {status_filter}")
    items = [m for m in db["cafe_menu_items"].values() if status_filter is None or m["status"] == status_filter]
    return paginate(items, ser_cafe_menu_item)


@app.route("/cafe-menu-items/<id>", methods=["PATCH"])
def patch_cafe_menu_item(id):
    authenticate(["Admin"])
    item = db["cafe_menu_items"].get(id)
    if item is None:
        raise err_not_found("CafeMenuItem not found")
    p = get_payload()
    status = opt_enum(p, "status", ("ACTIVE", "RETIRED"))
    if status is not None:
        item["status"] = status
    touch(item)
    return success_response(ser_cafe_menu_item(item), 200)


# ---------------------------------------------------------------------------
# Config endpoints: staff members
# ---------------------------------------------------------------------------

STAFF_ROLES = ("FRONT_DESK", "CAFE_STAFF", "MANAGER")


@app.route("/staff-members", methods=["POST"])
def create_staff_member():
    authenticate(["Admin"])
    p = get_payload()
    full_name = req_str(p, "full_name")
    role = p.get("role")
    if role is None:
        raise err_validation("Missing or invalid required field: role")
    if not isinstance(role, str):
        raise err_validation("Invalid type for field: role")
    if role not in STAFF_ROLES:
        raise ApiError("ERR_INVALID_ENUM", f"Invalid role: {role}")
    staff = new_common_fields()
    staff.update({"full_name": full_name, "role": role, "status": "ACTIVE"})
    db["staff_members"][staff["id"]] = staff
    return success_response(ser_staff_member(staff), 201)


@app.route("/staff-members/<id>", methods=["GET"])
def get_staff_member(id):
    authenticate(["Manager", "Admin"])
    staff = db["staff_members"].get(id)
    if staff is None:
        raise err_not_found("StaffMember not found")
    return success_response(ser_staff_member(staff), 200)


@app.route("/staff-members/<id>", methods=["PATCH"])
def patch_staff_member(id):
    authenticate(["Admin"])
    staff = db["staff_members"].get(id)
    if staff is None:
        raise err_not_found("StaffMember not found")
    p = get_payload()
    status = opt_enum(p, "status", ("ACTIVE", "INACTIVE"))
    if status is not None:
        staff["status"] = status
    touch(staff)
    return success_response(ser_staff_member(staff), 200)


# ---------------------------------------------------------------------------
# Guardians
# ---------------------------------------------------------------------------

@app.route("/guardians", methods=["POST"])
def create_guardian():
    authenticate(["Anonymous"])
    p = get_payload()
    full_name = req_str(p, "full_name")
    email = req_str(p, "email")
    phone = req_str(p, "phone")
    guardian = new_common_fields()
    guardian.update({
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "membership_plan_id": None,
        "membership_status": "NONE",
        "credits_granted": 0,
    })
    db["guardians"][guardian["id"]] = guardian
    return success_response(ser_guardian(guardian), 201)


@app.route("/guardians", methods=["GET"])
def list_guardians():
    authenticate(["Manager", "Admin"])
    plan_filter = request.args.get("membership_plan_id")
    guardians = [
        g for g in db["guardians"].values()
        if plan_filter is None or g["membership_plan_id"] == plan_filter
    ]
    return paginate(guardians, ser_guardian)


@app.route("/guardians/<id>", methods=["GET"])
def get_guardian(id):
    authenticate(["Guardian", "FrontDesk", "Manager", "Admin"], guardian_id=id)
    guardian = get_guardian_or_404(id)
    return success_response(ser_guardian(guardian), 200)


@app.route("/guardians/<id>/children", methods=["POST"])
def create_child(id):
    authenticate(["Guardian", "FrontDesk"], guardian_id=id)
    guardian = get_guardian_or_404(id)
    p = get_payload()
    full_name = req_str(p, "full_name")
    birth_date = req_str(p, "birth_date")
    if parse_date(birth_date) is None:
        raise err_validation("birth_date must be an ISO date")
    allergies = opt_allergen_list(p, "allergies", []) or []
    child = new_common_fields()
    child.update({
        "guardian_id": guardian["id"],
        "full_name": full_name,
        "birth_date": birth_date,
        "allergies": allergies,
    })
    db["children"][child["id"]] = child
    return success_response(ser_child(child), 201)


@app.route("/guardians/<id>/children", methods=["GET"])
def list_children(id):
    authenticate(["Guardian", "FrontDesk", "Manager"], guardian_id=id)
    guardian = get_guardian_or_404(id)
    children = [c for c in db["children"].values() if c["guardian_id"] == guardian["id"]]
    return paginate(children, ser_child)


@app.route("/children/<id>", methods=["GET"])
def get_child(id):
    child = db["children"].get(id)
    authenticate(["Guardian", "FrontDesk", "Manager"], guardian_id=child["guardian_id"] if child else None)
    if child is None:
        raise err_not_found("Child not found")
    return success_response(ser_child(child), 200)


@app.route("/children/<id>/visits", methods=["GET"])
def list_child_visits(id):
    child = db["children"].get(id)
    authenticate(["Guardian", "FrontDesk", "Manager"], guardian_id=child["guardian_id"] if child else None)
    if child is None:
        raise err_not_found("Child not found")
    visits = [v for v in db["visits"].values() if v["child_id"] == child["id"]]
    return paginate(visits, ser_visit)


@app.route("/guardians/<id>/waivers", methods=["POST"])
def create_waiver(id):
    authenticate(["Guardian", "FrontDesk"], guardian_id=id)
    guardian = get_guardian_or_404(id)
    p = get_payload()
    expected = req_int(p, "expected_guardian_version")
    if expected != guardian["version"]:
        raise ApiError("ERR_STALE_VERSION", "Stale guardian version")
    signed = now()
    expires = signed + timedelta(days=365)
    waiver = new_common_fields()
    waiver.update({
        "guardian_id": guardian["id"],
        "signed_at": _fmt_ts(signed),
        "expires_at": _fmt_ts(expires),
        "status": "SIGNED",
    })
    for w in db["waivers"].values():
        if w["guardian_id"] == guardian["id"] and w["status"] == "SIGNED":
            w["status"] = "SUPERSEDED"
            touch(w)
    db["waivers"][waiver["id"]] = waiver
    touch(guardian)
    return success_response(ser_waiver(waiver), 201)


@app.route("/guardians/<id>/waivers", methods=["GET"])
def list_waivers(id):
    authenticate(["Guardian", "FrontDesk", "Manager"], guardian_id=id)
    guardian = get_guardian_or_404(id)
    waivers = [w for w in db["waivers"].values() if w["guardian_id"] == guardian["id"]]
    return paginate(waivers, ser_waiver)


@app.route("/guardians/<id>/membership", methods=["POST"])
def enroll_membership(id):
    authenticate(["Guardian", "Admin"], guardian_id=id)
    guardian = get_guardian_or_404(id)
    p = get_payload()
    plan_id = p.get("membership_plan_id")
    if not isinstance(plan_id, str) or not plan_id:
        raise err_validation("Missing or invalid required field: membership_plan_id")
    plan = db["membership_plans"].get(plan_id)
    if plan is None:
        raise err_not_found("MembershipPlan not found")
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_RETIRED", "Membership plan is not ACTIVE")
    guardian["membership_plan_id"] = plan["id"]
    guardian["membership_status"] = "ACTIVE"
    guardian["credits_granted"] += plan["included_session_credits"]
    touch(guardian)
    return success_response(ser_guardian(guardian), 200)


@app.route("/guardians/<id>/membership/cancel", methods=["POST"])
def cancel_membership(id):
    authenticate(["Guardian", "Admin"], guardian_id=id)
    guardian = get_guardian_or_404(id)
    guardian["membership_status"] = "CANCELLED"
    consumed, held = credit_counters(guardian["id"])
    guardian["credits_granted"] = consumed + held
    touch(guardian)
    return success_response(ser_guardian(guardian), 200)


@app.route("/guardians/<id>/visits", methods=["GET"])
def list_guardian_visits(id):
    authenticate(["Guardian", "FrontDesk", "Manager"], guardian_id=id)
    guardian = get_guardian_or_404(id)
    return paginate(guardian_visits(guardian["id"]), ser_visit)


@app.route("/guardians/<id>/cafe-orders", methods=["GET"])
def list_guardian_cafe_orders(id):
    authenticate(["Guardian", "CafeStaff", "Manager"], guardian_id=id)
    guardian = get_guardian_or_404(id)
    orders = [o for o in db["cafe_orders"].values() if o["guardian_id"] == guardian["id"]]
    return paginate(orders, ser_cafe_order)


@app.route("/guardians/<id>/party-bookings", methods=["GET"])
def list_guardian_party_bookings(id):
    authenticate(["Guardian", "FrontDesk", "Manager"], guardian_id=id)
    guardian = get_guardian_or_404(id)
    bookings = [b for b in db["party_bookings"].values() if b["guardian_id"] == guardian["id"]]
    return paginate(bookings, ser_party_booking)


@app.route("/guardians/<id>/loyalty-ledger", methods=["GET"])
def list_loyalty_ledger(id):
    authenticate(["Guardian", "Manager"], guardian_id=id)
    guardian = get_guardian_or_404(id)
    kind_filter = request.args.get("kind")
    if kind_filter is not None and kind_filter not in ("EARN", "REDEEM", "REVERSAL", "ADJUSTMENT"):
        raise ApiError("ERR_INVALID_ENUM", f"Invalid kind: {kind_filter}")
    txns = [
        t for t in db["loyalty_transactions"].values()
        if t["guardian_id"] == guardian["id"] and (kind_filter is None or t["kind"] == kind_filter)
    ]
    return paginate(txns, ser_loyalty_transaction)


@app.route("/guardians/<id>/loyalty-adjustments", methods=["POST"])
def create_loyalty_adjustment(id):
    authenticate(["Manager"])
    guardian = get_guardian_or_404(id)
    p = get_payload()
    points = req_int(p, "points")
    note = req_str(p, "note")
    txn = post_loyalty_txn(guardian["id"], "ADJUSTMENT", points, note)
    touch(guardian)
    return success_response(ser_loyalty_transaction(txn), 201)


# ---------------------------------------------------------------------------
# Session slots
# ---------------------------------------------------------------------------

@app.route("/session-slots", methods=["POST"])
def create_session_slot():
    authenticate(["Manager", "Admin"])
    p = get_payload()
    slot_date = req_str(p, "slot_date")
    if parse_date(slot_date) is None:
        raise err_validation("slot_date must be an ISO date")
    start_at_raw = req_str(p, "start_at")
    end_at_raw = req_str(p, "end_at")
    start_at = parse_iso(start_at_raw)
    end_at = parse_iso(end_at_raw)
    if start_at is None:
        raise err_validation("start_at must be an ISO datetime")
    if end_at is None:
        raise err_validation("end_at must be an ISO datetime")
    capacity = req_int(p, "capacity")
    for other in db["session_slots"].values():
        if other["slot_date"] != slot_date or other["status"] == "CLOSED":
            continue
        o_start = parse_iso(other["start_at"])
        o_end = parse_iso(other["end_at"])
        if o_start is None or o_end is None:
            continue
        if start_at < o_end and o_start < end_at:
            raise ApiError("ERR_SLOT_OVERLAP", "Slot overlaps an existing non-CLOSED slot")
    slot = new_common_fields()
    slot.update({
        "slot_date": slot_date,
        "start_at": _fmt_ts(start_at),
        "end_at": _fmt_ts(end_at),
        "capacity": capacity,
        "status": "SCHEDULED",
        "close_reason": None,
    })
    db["session_slots"][slot["id"]] = slot
    return success_response(ser_session_slot(slot), 201)


@app.route("/session-slots", methods=["GET"])
def list_session_slots():
    authenticate(["Anonymous", "Guardian", "FrontDesk", "CafeStaff", "Manager", "Admin"])
    date_filter = request.args.get("slot_date")
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in ("SCHEDULED", "OPEN", "CLOSED"):
        raise ApiError("ERR_INVALID_ENUM", f"Invalid status: {status_filter}")
    slots = [
        s for s in db["session_slots"].values()
        if (date_filter is None or s["slot_date"] == date_filter)
        and (status_filter is None or s["status"] == status_filter)
    ]
    return paginate(slots, ser_session_slot)


@app.route("/session-slots/<id>", methods=["GET"])
def get_session_slot(id):
    authenticate(["Anonymous", "Guardian", "FrontDesk", "CafeStaff", "Manager", "Admin"])
    slot = get_slot_or_404(id)
    return success_response(ser_session_slot(slot), 200)


@app.route("/session-slots/<id>", methods=["PATCH"])
def patch_session_slot(id):
    authenticate(["Manager"])
    slot = db["session_slots"].get(id)
    if slot is None:
        raise err_not_found("SessionSlot not found")
    p = get_payload()
    capacity = opt_int(p, "capacity")
    expected = req_int(p, "expected_session_slot_version")
    if expected != slot["version"]:
        raise ApiError("ERR_STALE_VERSION", "Stale session slot version")
    if capacity is not None:
        _, checked_in = slot_counters(slot["id"])
        if capacity < checked_in:
            raise ApiError("ERR_CAPACITY_BELOW_OCCUPANCY", "Capacity below current checked-in count")
        slot["capacity"] = capacity
        new_quota = reservation_quota(capacity)
        reserved, _ = slot_counters(slot["id"])
        if reserved > new_quota:
            reserved_visits = [
                v for v in db["visits"].values()
                if v["session_slot_id"] == slot["id"] and v["admission_status"] == "RESERVED"
            ]
            reserved_visits.sort(
                key=lambda v: (v["created_at"], v.get("quoted_cents") or 0), reverse=True
            )
            to_cancel = reserved - new_quota
            for v in reserved_visits[:to_cancel]:
                cancel_reserved_visit(v, slot)
    touch(slot)
    return success_response(ser_session_slot(slot), 200)


@app.route("/session-slots/<id>/open", methods=["POST"])
def open_session_slot(id):
    authenticate(["Manager"])
    slot = db["session_slots"].get(id)
    if slot is None:
        raise err_not_found("SessionSlot not found")
    if slot["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Slot is not SCHEDULED")
    slot["status"] = "OPEN"
    touch(slot)
    return success_response(ser_session_slot(slot), 200)


@app.route("/session-slots/<id>/close", methods=["POST"])
def close_session_slot(id):
    authenticate(["Manager"])
    slot = db["session_slots"].get(id)
    if slot is None:
        raise err_not_found("SessionSlot not found")
    p = get_payload()
    reason = opt_enum(p, "reason", ("MANAGER_CLOSE", "EMERGENCY"))
    if reason is None:
        raise err_validation("Missing or invalid required field: reason")
    if slot["status"] == "CLOSED":
        raise ApiError("ERR_INVALID_STATE", "Slot already CLOSED")
    close_slot_cascade(slot, reason)
    return success_response(ser_session_slot(slot), 200)


@app.route("/session-slots/<id>/visits", methods=["GET"])
def list_slot_visits(id):
    authenticate(["FrontDesk", "Manager"])
    slot = get_slot_or_404(id)
    status_filter = request.args.get("admission_status")
    allowed = ("RESERVED", "CHECKED_IN", "COMPLETED", "CANCELLED", "NO_SHOW", "EVACUATED")
    if status_filter is not None and status_filter not in allowed:
        raise ApiError("ERR_INVALID_ENUM", f"Invalid admission_status: {status_filter}")
    visits = [
        v for v in db["visits"].values()
        if v["session_slot_id"] == slot["id"]
        and (status_filter is None or v["admission_status"] == status_filter)
    ]
    return paginate(visits, ser_visit)


# ---------------------------------------------------------------------------
# Visits
# ---------------------------------------------------------------------------

VISIT_TYPES = ("RESERVATION", "WALK_IN")
SOCK_METHODS = ("OWN_GRIP_SOCKS", "PURCHASED", "MEMBERSHIP_PROVIDED")


@app.route("/visits", methods=["POST"])
def create_visit():
    p = get_payload()
    body_guardian_id = p.get("guardian_id")
    role, _ = authenticate(
        ["Guardian", "FrontDesk", "Manager"],
        guardian_id=body_guardian_id if isinstance(body_guardian_id, str) else None,
    )
    # Priority 9 shape checks for identifiers (before FK resolution).
    session_slot_id = req_str(p, "session_slot_id")
    child_id = req_str(p, "child_id")
    guardian_id = req_str(p, "guardian_id")
    visit_type = p.get("visit_type")
    if visit_type is None or not isinstance(visit_type, str):
        raise err_validation("Missing or invalid required field: visit_type")
    if visit_type not in VISIT_TYPES:
        raise ApiError("ERR_INVALID_ENUM", f"Invalid visit_type: {visit_type}")
    # Existence, left to right.
    slot = get_slot_or_404(session_slot_id)
    child = get_child_or_404(child_id)
    guardian = get_guardian_or_404(guardian_id)

    if slot["status"] != "OPEN":
        raise ApiError("ERR_SLOT_NOT_OPEN", "Session slot is not OPEN")

    booked_duration_minutes = opt_int(p, "booked_duration_minutes")
    use_credit = opt_bool(p, "use_credit", False) or False
    sock_method = p.get("sock_method")
    grip_socks_order_id = p.get("grip_socks_order_id")

    if visit_type == "RESERVATION":
        if booked_duration_minutes is None:
            raise err_validation("booked_duration_minutes is required for RESERVATION")

    if visit_type == "WALK_IN":
        # Desk admission applies full desk gate set at creation.
        if sock_method is None or not isinstance(sock_method, str):
            raise err_validation("sock_method is required for WALK_IN")
        if sock_method not in SOCK_METHODS:
            raise ApiError("ERR_INVALID_ENUM", f"Invalid sock_method: {sock_method}")
        if grip_socks_order_id is not None and not isinstance(grip_socks_order_id, str):
            raise err_validation("Invalid type for field: grip_socks_order_id")
        if not guardian_has_current_waiver(guardian["id"]):
            raise ApiError("ERR_WAIVER_INVALID", "No current signed waiver")
        validate_sock_compliance(guardian, sock_method, grip_socks_order_id, slot)

    age = child_age_at(child["birth_date"], slot["slot_date"])
    if age is None or age < 1 or age > 12:
        raise ApiError("ERR_CHILD_AGE_OUT_OF_RANGE", "Child age outside 1..12")

    for v in db["visits"].values():
        if (
            v["session_slot_id"] == slot["id"]
            and v["child_id"] == child["id"]
            and v["admission_status"] in ("RESERVED", "CHECKED_IN")
        ):
            raise ApiError("ERR_DUPLICATE_VISIT", "Child already has an active visit on this slot")

    reserved_count, checked_in_count = slot_counters(slot["id"])
    if visit_type == "RESERVATION":
        if reserved_count >= reservation_quota(slot["capacity"]):
            raise ApiError("ERR_RESERVATION_QUOTA_FULL", "Reservation quota full")
        if use_credit:
            if not guardian_membership_active(guardian):
                raise ApiError("ERR_MEMBERSHIP_REQUIRED", "use_credit requires ACTIVE membership")
            snap = guardian_snapshot_fields(guardian)
            if snap["credits_available"] < 1:
                raise ApiError("ERR_INSUFFICIENT_CREDITS", "No session credits available")
    else:  # WALK_IN
        if reserved_count + checked_in_count >= slot["capacity"]:
            raise ApiError("ERR_SLOT_AT_CAPACITY", "Slot at capacity")
        if use_credit:
            if not guardian_membership_active(guardian):
                raise ApiError("ERR_MEMBERSHIP_REQUIRED", "use_credit requires ACTIVE membership")
            snap = guardian_snapshot_fields(guardian)
            if snap["credits_available"] < 1:
                raise ApiError("ERR_INSUFFICIENT_CREDITS", "No session credits available")

    visit = new_common_fields()
    if visit_type == "RESERVATION":
        blocks = -(-booked_duration_minutes // 60)
        quoted = 1200 + (blocks - 1) * 900
        visit.update({
            "admission_status": "RESERVED",
            "payment_status": "PENDING",
            "sock_method": "NONE",
            "grip_socks_order_id": None,
            "quoted_cents": quoted,
            "checked_in_at": None,
            "checked_out_at": None,
        })
    else:
        visit.update({
            "admission_status": "CHECKED_IN",
            "payment_status": "PENDING",
            "sock_method": sock_method,
            "grip_socks_order_id": grip_socks_order_id,
            "quoted_cents": None,
            "checked_in_at": now_ts(),
            "checked_out_at": None,
        })
    visit.update({
        "session_slot_id": slot["id"],
        "child_id": child["id"],
        "guardian_id": guardian["id"],
        "visit_type": visit_type,
        "booked_duration_minutes": booked_duration_minutes,
        "use_credit": bool(use_credit),
        "final_charge_cents": None,
        "refund_delta_cents": 0,
    })
    db["visits"][visit["id"]] = visit
    return success_response(ser_visit(visit), 201)


@app.route("/visits/<id>", methods=["GET"])
def get_visit(id):
    visit = db["visits"].get(id)
    authenticate(["Guardian", "FrontDesk", "Manager"], guardian_id=visit["guardian_id"] if visit else None)
    if visit is None:
        raise err_not_found("Visit not found")
    return success_response(ser_visit(visit), 200)


@app.route("/visits/<id>/pay", methods=["POST"])
def pay_visit(id):
    visit = db["visits"].get(id)
    authenticate(["Guardian", "FrontDesk"], guardian_id=visit["guardian_id"] if visit else None)
    if visit is None:
        raise err_not_found("Visit not found")
    if visit["admission_status"] != "RESERVED" or visit["use_credit"]:
        raise ApiError("ERR_INVALID_STATE", "Visit not eligible for prepayment")
    if visit["payment_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "Visit payment already processed")
    visit["payment_status"] = "PREPAID"
    touch(visit)
    return success_response(ser_visit(visit), 200)


@app.route("/visits/<id>/check-in", methods=["POST"])
def check_in_visit(id):
    authenticate(["FrontDesk", "Manager"])
    visit = db["visits"].get(id)
    if visit is None:
        raise err_not_found("Visit not found")
    if visit["admission_status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE", "Visit is not RESERVED")
    slot = get_slot_or_404(visit["session_slot_id"])
    if slot["status"] != "OPEN":
        raise ApiError("ERR_SLOT_NOT_OPEN", "Session slot is not OPEN")
    guardian = get_guardian_or_404(visit["guardian_id"])
    if not guardian_has_current_waiver(guardian["id"]):
        raise ApiError("ERR_WAIVER_INVALID", "No current signed waiver")
    p = get_payload()
    sock_method = p.get("sock_method")
    if sock_method is None or not isinstance(sock_method, str):
        raise err_validation("Missing or invalid required field: sock_method")
    if sock_method not in SOCK_METHODS:
        raise ApiError("ERR_INVALID_ENUM", f"Invalid sock_method: {sock_method}")
    grip_socks_order_id = p.get("grip_socks_order_id")
    if grip_socks_order_id is not None and not isinstance(grip_socks_order_id, str):
        raise err_validation("Invalid type for field: grip_socks_order_id")
    validate_sock_compliance(guardian, sock_method, grip_socks_order_id, slot)
    start_at = parse_iso(slot["start_at"])
    window_open = start_at - timedelta(minutes=10)
    window_close = start_at + timedelta(minutes=15)
    if not (window_open <= now() <= window_close):
        raise ApiError("ERR_CHECKIN_WINDOW_CLOSED", "Outside check-in window")
    visit["admission_status"] = "CHECKED_IN"
    visit["checked_in_at"] = now_ts()
    visit["sock_method"] = sock_method
    visit["grip_socks_order_id"] = grip_socks_order_id
    touch(visit)
    return success_response(ser_visit(visit), 200)


@app.route("/visits/<id>/check-out", methods=["POST"])
def check_out_visit(id):
    authenticate(["FrontDesk", "Manager"])
    visit = db["visits"].get(id)
    if visit is None:
        raise err_not_found("Visit not found")
    if visit["admission_status"] != "CHECKED_IN":
        raise ApiError("ERR_INVALID_STATE", "Visit is not CHECKED_IN")
    for inc in db["incidents"].values():
        if (
            inc.get("visit_id") == visit["id"]
            and inc["kind"] == "LOST_CHILD"
            and inc["status"] in ("OPEN", "TRIAGED")
        ):
            raise ApiError("ERR_LOST_CHILD_UNRESOLVED", "Unresolved lost-child incident")
    guardian = get_guardian_or_404(visit["guardian_id"])
    checked_in_at = parse_iso(visit["checked_in_at"]) or now()
    m = elapsed_minutes(checked_in_at, now())
    tiered = tiered_charge_cents(m)
    if guardian_membership_active(guardian):
        tiered = round_half_up_cents(Decimal(tiered) * Decimal("0.9"))
    visit["final_charge_cents"] = tiered
    visit["checked_out_at"] = now_ts()
    visit["admission_status"] = "COMPLETED"
    if visit["use_credit"]:
        visit["payment_status"] = "SETTLED"
    else:
        if visit["payment_status"] == "PREPAID":
            visit["refund_delta_cents"] = max(0, (visit["quoted_cents"] or 0) - tiered)
        visit["payment_status"] = "SETTLED"
        _, _, lifetime = guardian_ledger(guardian["id"])
        multiplier = TIER_MULTIPLIER[tier_from_lifetime(lifetime)]
        points = (tiered // 100) * multiplier
        if points > 0:
            post_loyalty_txn(guardian["id"], "EARN", points, "Visit completion")
    touch(visit)
    return success_response(ser_visit(visit), 200)


@app.route("/visits/<id>/cancel", methods=["POST"])
def cancel_visit(id):
    visit = db["visits"].get(id)
    role, _ = authenticate(
        ["Guardian", "FrontDesk", "Manager"],
        guardian_id=visit["guardian_id"] if visit else None,
    )
    if visit is None:
        raise err_not_found("Visit not found")
    if visit["admission_status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE", "Visit is not RESERVED")
    if role == "Guardian":
        slot = get_slot_or_404(visit["session_slot_id"])
        start_at = parse_iso(slot["start_at"])
        if start_at is not None and not (now() < start_at):
            raise ApiError("ERR_CANCEL_CUTOFF", "Cancellation cutoff passed")
    cancel_reserved_visit(visit, None)
    return success_response(ser_visit(visit), 200)


@app.route("/visits/<id>/cafe-orders", methods=["GET"])
def list_visit_cafe_orders(id):
    visit = db["visits"].get(id)
    authenticate(["Guardian", "CafeStaff", "Manager"], guardian_id=visit["guardian_id"] if visit else None)
    if visit is None:
        raise err_not_found("Visit not found")
    orders = [o for o in db["cafe_orders"].values() if o.get("visit_id") == visit["id"]]
    return paginate(orders, ser_cafe_order)


@app.route("/visits/<id>/incidents", methods=["GET"])
def list_visit_incidents(id):
    authenticate(["FrontDesk", "Manager"])
    visit = get_visit_or_404(id)
    incidents = [i for i in db["incidents"].values() if i.get("visit_id") == visit["id"]]
    return paginate(incidents, ser_incident)


# ---------------------------------------------------------------------------
# Party bookings
# ---------------------------------------------------------------------------

def room_has_conflict(room_id, start_dt, end_dt, exclude_booking_id=None):
    """Occupied interval [start, end+30min) half-open vs other non-terminal bookings."""
    occ_start = start_dt
    occ_end = end_dt + timedelta(minutes=30)
    for b in db["party_bookings"].values():
        if b["party_room_id"] != room_id:
            continue
        if exclude_booking_id is not None and b["id"] == exclude_booking_id:
            continue
        if b["status"] in ("COMPLETED", "CANCELLED", "EXPIRED"):
            continue
        b_start = parse_iso(b["start_at"])
        b_end = parse_iso(b["end_at"])
        if b_start is None or b_end is None:
            continue
        b_occ_end = b_end + timedelta(minutes=30)
        if occ_start < b_occ_end and b_start < occ_end:
            return True
    return False


def compute_party_quote(package, guardian, child_count, start_dt):
    extra_children = max(0, child_count - package["included_children"])
    subtotal = package["base_price_cents"] + extra_children * package["extra_child_price_cents"]
    peak = 0
    if start_dt is not None and start_dt.weekday() in (5, 6):  # Sat=5, Sun=6 UTC
        peak = round_half_up_cents(Decimal(subtotal) * Decimal("0.15"))
    discount_pct = 0
    if guardian is not None and guardian_membership_active(guardian):
        plan = guardian_plan(guardian)
        if plan is not None:
            discount_pct = plan.get("party_discount_pct") or 0
    discount_pct = min(discount_pct, 0.25)
    discount = round_half_up_cents(Decimal(subtotal + peak) * Decimal(str(discount_pct)))
    quoted_total = subtotal + peak - discount
    deposit = max(5000, round_half_up_cents(Decimal(quoted_total) * Decimal("0.20")))
    return quoted_total, deposit


@app.route("/party-bookings", methods=["POST"])
def create_party_booking():
    p = get_payload()
    body_guardian_id = p.get("guardian_id")
    authenticate(["Guardian", "FrontDesk"], guardian_id=body_guardian_id if isinstance(body_guardian_id, str) else None)
    party_room_id = req_str(p, "party_room_id")
    party_package_id = req_str(p, "party_package_id")
    guardian_id = req_str(p, "guardian_id")
    start_at_raw = req_str(p, "start_at")
    start_at = parse_iso(start_at_raw)
    if start_at is None:
        raise err_validation("start_at must be an ISO datetime")
    child_count = req_int(p, "child_count")
    expected = req_int(p, "expected_party_room_version")
    room = get_party_room_or_404(party_room_id)
    package = get_party_package_or_404(party_package_id)
    guardian = get_guardian_or_404(guardian_id)
    if room["status"] != "ACTIVE":
        raise ApiError("ERR_ROOM_INACTIVE", "Party room is not ACTIVE")
    if package["status"] != "ACTIVE":
        raise ApiError("ERR_PACKAGE_RETIRED", "Party package is not ACTIVE")
    if child_count > room["capacity_children"]:
        raise ApiError("ERR_CAPACITY_BELOW_OCCUPANCY", "child_count exceeds room capacity")
    end_at = start_at + timedelta(minutes=package["duration_minutes"])
    if room_has_conflict(room["id"], start_at, end_at):
        raise ApiError("ERR_ROOM_TIME_CONFLICT", "Room time conflict")
    if expected != room["version"]:
        raise ApiError("ERR_STALE_VERSION", "Stale party room version")
    quoted_total, deposit = compute_party_quote(package, guardian, child_count, start_at)
    booking = new_common_fields()
    booking.update({
        "party_room_id": room["id"],
        "party_package_id": package["id"],
        "guardian_id": guardian["id"],
        "start_at": _fmt_ts(start_at),
        "end_at": _fmt_ts(end_at),
        "child_count": child_count,
        "status": "HELD",
        "quoted_total_cents": quoted_total,
        "deposit_cents": deposit,
        "deposit_paid": False,
        "proposed_start_at": None,
        "refund_cents": 0,
    })
    db["party_bookings"][booking["id"]] = booking
    touch(room)
    return success_response(ser_party_booking(booking), 201)


@app.route("/party-bookings", methods=["GET"])
def list_party_bookings():
    authenticate(["Manager", "Admin"])
    pkg_filter = request.args.get("party_package_id")
    status_filter = request.args.get("status")
    allowed = ("HELD", "CONFIRMED", "RESCHEDULE_REQUESTED", "COMPLETED", "CANCELLED", "EXPIRED")
    if status_filter is not None and status_filter not in allowed:
        raise ApiError("ERR_INVALID_ENUM", f"Invalid status: {status_filter}")
    bookings = [
        b for b in db["party_bookings"].values()
        if (pkg_filter is None or b["party_package_id"] == pkg_filter)
        and (status_filter is None or b["status"] == status_filter)
    ]
    return paginate(bookings, ser_party_booking)


@app.route("/party-bookings/<id>", methods=["GET"])
def get_party_booking(id):
    booking = db["party_bookings"].get(id)
    authenticate(["Guardian", "FrontDesk", "Manager"], guardian_id=booking["guardian_id"] if booking else None)
    if booking is None:
        raise err_not_found("PartyBooking not found")
    return success_response(ser_party_booking(booking), 200)


@app.route("/party-bookings/<id>/confirm", methods=["POST"])
def confirm_party_booking(id):
    booking = db["party_bookings"].get(id)
    authenticate(["Guardian"], guardian_id=booking["guardian_id"] if booking else None)
    if booking is None:
        raise err_not_found("PartyBooking not found")
    if booking["status"] != "HELD":
        raise ApiError("ERR_INVALID_STATE", "Booking is not HELD")
    room = get_party_room_or_404(booking["party_room_id"])
    if room["status"] != "ACTIVE":
        raise ApiError("ERR_ROOM_INACTIVE", "Party room is not ACTIVE")
    for t in db["sanitation_tasks"].values():
        if t["party_room_id"] == room["id"] and t["status"] == "OVERDUE":
            raise ApiError("ERR_SANITATION_OVERDUE", "Overdue sanitation task on the room")
    start_at = parse_iso(booking["start_at"])
    end_at = parse_iso(booking["end_at"])
    if start_at is not None and end_at is not None and room_has_conflict(
        room["id"], start_at, end_at, exclude_booking_id=booking["id"]
    ):
        raise ApiError("ERR_ROOM_TIME_CONFLICT", "Room time conflict")
    booking["status"] = "CONFIRMED"
    booking["deposit_paid"] = True
    touch(booking)
    return success_response(ser_party_booking(booking), 200)


@app.route("/party-bookings/<id>/request-reschedule", methods=["POST"])
def request_reschedule(id):
    booking = db["party_bookings"].get(id)
    authenticate(["Guardian"], guardian_id=booking["guardian_id"] if booking else None)
    if booking is None:
        raise err_not_found("PartyBooking not found")
    if booking["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", "Booking is not CONFIRMED")
    p = get_payload()
    proposed_raw = req_str(p, "proposed_start_at")
    proposed = parse_iso(proposed_raw)
    if proposed is None:
        raise err_validation("proposed_start_at must be an ISO datetime")
    start_at = parse_iso(booking["start_at"])
    if start_at is not None and not (now() <= start_at - timedelta(hours=48)):
        raise ApiError("ERR_RESCHEDULE_CUTOFF", "Reschedule cutoff passed")
    booking["status"] = "RESCHEDULE_REQUESTED"
    booking["proposed_start_at"] = _fmt_ts(proposed)
    touch(booking)
    return success_response(ser_party_booking(booking), 200)


@app.route("/party-bookings/<id>/approve-reschedule", methods=["POST"])
def approve_reschedule(id):
    authenticate(["Manager"])
    booking = db["party_bookings"].get(id)
    if booking is None:
        raise err_not_found("PartyBooking not found")
    if booking["status"] != "RESCHEDULE_REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "Booking is not RESCHEDULE_REQUESTED")
    proposed = parse_iso(booking["proposed_start_at"])
    if proposed is None:
        raise ApiError("ERR_INVALID_STATE", "No proposed start recorded")
    package = get_party_package_or_404(booking["party_package_id"])
    new_end = proposed + timedelta(minutes=package["duration_minutes"])
    if room_has_conflict(booking["party_room_id"], proposed, new_end, exclude_booking_id=booking["id"]):
        raise ApiError("ERR_ROOM_TIME_CONFLICT", "Room time conflict")
    guardian = get_guardian_or_404(booking["guardian_id"])
    quoted_total, deposit = compute_party_quote(package, guardian, booking["child_count"], proposed)
    booking["start_at"] = _fmt_ts(proposed)
    booking["end_at"] = _fmt_ts(new_end)
    booking["quoted_total_cents"] = quoted_total
    booking["deposit_cents"] = deposit
    booking["status"] = "CONFIRMED"
    touch(booking)
    return success_response(ser_party_booking(booking), 200)


def cancel_cafe_order_with_compensation(order):
    """Cancel a PLACED/PREPARING order and restore redeemed points via REVERSAL."""
    if order["points_redeemed"] > 0:
        post_loyalty_txn(
            order["guardian_id"], "REVERSAL", order["points_redeemed"],
            f"Points restored for cancelled order {order['id']}",
        )
    if order["points_earned"] > 0:
        post_loyalty_txn(
            order["guardian_id"], "REVERSAL", -order["points_earned"],
            f"Earned points reversed for cancelled order {order['id']}",
        )
    order["status"] = "CANCELLED"
    touch(order)


@app.route("/party-bookings/<id>/cancel", methods=["POST"])
def cancel_party_booking(id):
    booking = db["party_bookings"].get(id)
    authenticate(["Guardian", "Manager"], guardian_id=booking["guardian_id"] if booking else None)
    if booking is None:
        raise err_not_found("PartyBooking not found")
    if booking["status"] not in ("HELD", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE", "Booking cannot be cancelled from its state")
    refund = 0
    if booking["deposit_paid"]:
        start_at = parse_iso(booking["start_at"])
        if start_at is not None:
            if now() <= start_at - timedelta(days=7):
                refund = booking["deposit_cents"]
            elif now() <= start_at - timedelta(hours=48):
                refund = round_half_up_cents(Decimal(booking["deposit_cents"]) * Decimal("0.5"))
            else:
                refund = 0
    booking["status"] = "CANCELLED"
    booking["refund_cents"] = refund
    touch(booking)
    for order in db["cafe_orders"].values():
        if order.get("party_booking_id") == booking["id"] and order["status"] in ("PLACED", "PREPARING"):
            cancel_cafe_order_with_compensation(order)
    return success_response(ser_party_booking(booking), 200)


@app.route("/party-bookings/<id>/complete", methods=["POST"])
def complete_party_booking(id):
    authenticate(["Manager"])
    booking = db["party_bookings"].get(id)
    if booking is None:
        raise err_not_found("PartyBooking not found")
    if booking["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", "Booking is not CONFIRMED")
    end_at = parse_iso(booking["end_at"])
    if end_at is not None and not (now() >= end_at):
        raise ApiError("ERR_INVALID_STATE", "Party has not yet run")
    booking["status"] = "COMPLETED"
    touch(booking)
    return success_response(ser_party_booking(booking), 200)


@app.route("/party-bookings/<id>/cafe-orders", methods=["GET"])
def list_booking_cafe_orders(id):
    booking = db["party_bookings"].get(id)
    authenticate(["Guardian", "CafeStaff", "Manager"], guardian_id=booking["guardian_id"] if booking else None)
    if booking is None:
        raise err_not_found("PartyBooking not found")
    orders = [o for o in db["cafe_orders"].values() if o.get("party_booking_id") == booking["id"]]
    return paginate(orders, ser_cafe_order)


@app.route("/party-rooms/<id>/party-bookings", methods=["GET"])
def list_room_bookings(id):
    authenticate(["FrontDesk", "Manager", "Admin"])
    room = get_party_room_or_404(id)
    status_filter = request.args.get("status")
    allowed = ("HELD", "CONFIRMED", "RESCHEDULE_REQUESTED", "COMPLETED", "CANCELLED", "EXPIRED")
    if status_filter is not None and status_filter not in allowed:
        raise ApiError("ERR_INVALID_ENUM", f"Invalid status: {status_filter}")
    bookings = [
        b for b in db["party_bookings"].values()
        if b["party_room_id"] == room["id"] and (status_filter is None or b["status"] == status_filter)
    ]
    return paginate(bookings, ser_party_booking)


@app.route("/party-rooms/<id>/sanitation-tasks", methods=["GET"])
def list_room_sanitation_tasks(id):
    authenticate(["FrontDesk", "Manager", "Admin"])
    room = get_party_room_or_404(id)
    status_filter = request.args.get("status")
    allowed = ("SCHEDULED", "IN_PROGRESS", "OVERDUE", "COMPLETED")
    if status_filter is not None and status_filter not in allowed:
        raise ApiError("ERR_INVALID_ENUM", f"Invalid status: {status_filter}")
    tasks = [
        t for t in db["sanitation_tasks"].values()
        if t["party_room_id"] == room["id"] and (status_filter is None or t["status"] == status_filter)
    ]
    return paginate(tasks, ser_sanitation_task)


# ---------------------------------------------------------------------------
# Cafe orders
# ---------------------------------------------------------------------------

@app.route("/cafe-orders", methods=["POST"])
def create_cafe_order():
    p = get_payload()
    body_guardian_id = p.get("guardian_id")
    authenticate(["Guardian", "FrontDesk"], guardian_id=body_guardian_id if isinstance(body_guardian_id, str) else None)
    guardian_id = req_str(p, "guardian_id")
    guardian = get_guardian_or_404(guardian_id)

    visit_id = p.get("visit_id")
    if visit_id is not None:
        if not isinstance(visit_id, str):
            raise err_validation("Invalid type for field: visit_id")
        get_visit_or_404(visit_id)
    party_booking_id = p.get("party_booking_id")
    if party_booking_id is not None:
        if not isinstance(party_booking_id, str):
            raise err_validation("Invalid type for field: party_booking_id")
        get_party_booking_or_404(party_booking_id)

    lines_raw = p.get("lines")
    if not isinstance(lines_raw, list) or len(lines_raw) == 0:
        raise err_validation("Missing or invalid required field: lines")
    parsed_lines = []
    for line in lines_raw:
        if not isinstance(line, dict):
            raise err_validation("Each line must be an object")
        menu_item_id = line.get("menu_item_id")
        if not isinstance(menu_item_id, str) or not menu_item_id:
            raise err_validation("Missing or invalid required field: menu_item_id")
        quantity = line.get("quantity")
        if not isinstance(quantity, int) or isinstance(quantity, bool):
            raise err_validation("Missing or invalid required field: quantity")
        item = db["cafe_menu_items"].get(menu_item_id)
        if item is None:
            raise err_not_found("CafeMenuItem not found")
        parsed_lines.append({"menu_item_id": menu_item_id, "quantity": quantity, "item": item})

    child_ids = opt_str_list(p, "child_ids", []) or []
    points_to_redeem = opt_int(p, "points_to_redeem", 0)
    if points_to_redeem is None:
        points_to_redeem = 0
    if points_to_redeem < 0:
        raise err_validation("points_to_redeem must be >= 0")

    children = [get_child_or_404(cid) for cid in child_ids]

    for pl in parsed_lines:
        if pl["item"]["status"] != "ACTIVE":
            raise ApiError("ERR_MENU_ITEM_RETIRED", f"Menu item {pl['item']['name']} is not ACTIVE")

    if children:
        allergy_union = set()
        for c in children:
            allergy_union.update(c.get("allergies") or [])
        if allergy_union:
            for pl in parsed_lines:
                if allergy_union.intersection(pl["item"].get("allergen_tags") or []):
                    raise ApiError("ERR_ALLERGEN_CONFLICT", "Allergen conflict with listed children")

    cafe_discount = 0
    if guardian_membership_active(guardian):
        plan = guardian_plan(guardian)
        if plan is not None:
            cafe_discount = plan.get("cafe_discount_pct") or 0

    subtotal = 0
    final_lines = []
    for pl in parsed_lines:
        unit = pl["item"]["price_cents"]
        qty = pl["quantity"]
        line_total = round_half_up_cents(
            Decimal(unit) * Decimal(qty) * (Decimal("1") - Decimal(str(cafe_discount)))
        )
        subtotal += line_total
        final_lines.append({
            "menu_item_id": pl["menu_item_id"],
            "quantity": qty,
            "unit_price_cents": unit,
            "line_total_cents": line_total,
        })

    _, points_balance, _ = guardian_ledger(guardian["id"])
    if points_to_redeem > points_balance:
        raise ApiError("ERR_INSUFFICIENT_POINTS", "points_to_redeem exceeds points balance")
    cap = subtotal // 2
    if points_to_redeem > cap:
        raise ApiError("ERR_REDEMPTION_CAP_EXCEEDED", "points_to_redeem exceeds half of subtotal")
    points_redeemed = min(points_to_redeem, points_balance, cap)
    total = subtotal - points_redeemed

    order = new_common_fields()
    order.update({
        "guardian_id": guardian["id"],
        "visit_id": visit_id,
        "party_booking_id": party_booking_id,
        "child_ids": child_ids,
        "lines": final_lines,
        "points_to_redeem": points_to_redeem,
        "subtotal_cents": subtotal,
        "points_redeemed": points_redeemed,
        "total_cents": total,
        "points_earned": 0,
        "status": "PLACED",
    })
    db["cafe_orders"][order["id"]] = order
    if points_redeemed > 0:
        post_loyalty_txn(guardian["id"], "REDEEM", -points_redeemed, f"Redemption on order {order['id']}")
    return success_response(ser_cafe_order(order), 201)


@app.route("/cafe-orders/<id>", methods=["GET"])
def get_cafe_order(id):
    order = db["cafe_orders"].get(id)
    authenticate(["Guardian", "CafeStaff", "Manager"], guardian_id=order["guardian_id"] if order else None)
    if order is None:
        raise err_not_found("CafeOrder not found")
    return success_response(ser_cafe_order(order), 200)


@app.route("/cafe-orders/<id>/start-preparing", methods=["POST"])
def start_preparing_order(id):
    authenticate(["CafeStaff", "Manager"])
    order = db["cafe_orders"].get(id)
    if order is None:
        raise err_not_found("CafeOrder not found")
    if order["status"] != "PLACED":
        raise ApiError("ERR_INVALID_STATE", "Order is not PLACED")
    order["status"] = "PREPARING"
    touch(order)
    return success_response(ser_cafe_order(order), 200)


@app.route("/cafe-orders/<id>/serve", methods=["POST"])
def serve_order(id):
    authenticate(["CafeStaff", "Manager"])
    order = db["cafe_orders"].get(id)
    if order is None:
        raise err_not_found("CafeOrder not found")
    if order["status"] != "PREPARING":
        raise ApiError("ERR_INVALID_STATE", "Order is not PREPARING")
    guardian = get_guardian_or_404(order["guardian_id"])
    _, _, lifetime = guardian_ledger(guardian["id"])
    multiplier = TIER_MULTIPLIER[tier_from_lifetime(lifetime)]
    points = (order["total_cents"] // 100) * multiplier
    order["status"] = "SERVED"
    order["points_earned"] = points
    touch(order)
    if points > 0:
        post_loyalty_txn(guardian["id"], "EARN", points, f"Earned on order {order['id']}")
    return success_response(ser_cafe_order(order), 200)


@app.route("/cafe-orders/<id>/cancel", methods=["POST"])
def cancel_cafe_order(id):
    order = db["cafe_orders"].get(id)
    authenticate(["Guardian", "Manager"], guardian_id=order["guardian_id"] if order else None)
    if order is None:
        raise err_not_found("CafeOrder not found")
    if order["status"] not in ("PLACED", "PREPARING"):
        raise ApiError("ERR_INVALID_STATE", "Order cannot be cancelled from its state")
    cancel_cafe_order_with_compensation(order)
    return success_response(ser_cafe_order(order), 200)


# ---------------------------------------------------------------------------
# Sanitation tasks
# ---------------------------------------------------------------------------

SANITATION_KINDS = ("DEEP_CLEAN", "BALL_PIT_WASH", "SURFACE_WIPE")


@app.route("/sanitation-tasks", methods=["POST"])
def create_sanitation_task():
    authenticate(["Manager"])
    p = get_payload()
    party_room_id = req_str(p, "party_room_id")
    kind_raw = p.get("kind")
    if kind_raw is None or not isinstance(kind_raw, str):
        raise err_validation("Missing or invalid required field: kind")
    if kind_raw not in SANITATION_KINDS:
        raise ApiError("ERR_INVALID_ENUM", f"Invalid kind: {kind_raw}")
    due_at_raw = req_str(p, "due_at")
    due_at = parse_iso(due_at_raw)
    if due_at is None:
        raise err_validation("due_at must be an ISO datetime")
    room = get_party_room_or_404(party_room_id)
    task = new_common_fields()
    task.update({
        "party_room_id": room["id"],
        "kind": kind_raw,
        "due_at": _fmt_ts(due_at),
        "status": "SCHEDULED",
        "checklist_passed": None,
        "completed_at": None,
    })
    db["sanitation_tasks"][task["id"]] = task
    return success_response(ser_sanitation_task(task), 201)


@app.route("/sanitation-tasks/<id>/start", methods=["POST"])
def start_sanitation_task(id):
    authenticate(["FrontDesk", "Manager"])
    task = db["sanitation_tasks"].get(id)
    if task is None:
        raise err_not_found("SanitationTask not found")
    if task["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Task is not SCHEDULED")
    task["status"] = "IN_PROGRESS"
    touch(task)
    return success_response(ser_sanitation_task(task), 200)


@app.route("/sanitation-tasks/<id>/complete", methods=["POST"])
def complete_sanitation_task(id):
    authenticate(["FrontDesk", "Manager"])
    task = db["sanitation_tasks"].get(id)
    if task is None:
        raise err_not_found("SanitationTask not found")
    if task["status"] not in ("SCHEDULED", "IN_PROGRESS", "OVERDUE"):
        raise ApiError("ERR_INVALID_STATE", "Task cannot be completed from its state")
    p = get_payload()
    checklist_passed = p.get("checklist_passed")
    if checklist_passed is not True:
        raise err_validation("checklist_passed must be true")
    task["checklist_passed"] = True
    task["status"] = "COMPLETED"
    task["completed_at"] = now_ts()
    touch(task)
    return success_response(ser_sanitation_task(task), 200)


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------

INCIDENT_KINDS = ("LOST_CHILD", "INJURY", "PROPERTY_DAMAGE", "BEHAVIOR")
INCIDENT_SEVERITIES = ("LOW", "MEDIUM", "CRITICAL")


@app.route("/incidents", methods=["POST"])
def create_incident():
    role, user_id = authenticate(["FrontDesk", "Manager"])
    p = get_payload()
    kind = p.get("kind")
    if kind is None or not isinstance(kind, str):
        raise err_validation("Missing or invalid required field: kind")
    if kind not in INCIDENT_KINDS:
        raise ApiError("ERR_INVALID_ENUM", f"Invalid kind: {kind}")
    severity = p.get("severity")
    if severity is None or not isinstance(severity, str):
        raise err_validation("Missing or invalid required field: severity")
    if severity not in INCIDENT_SEVERITIES:
        raise ApiError("ERR_INVALID_ENUM", f"Invalid severity: {severity}")
    description = req_str(p, "description")
    visit_id = p.get("visit_id")
    if visit_id is not None and not isinstance(visit_id, str):
        raise err_validation("Invalid type for field: visit_id")
    if kind == "LOST_CHILD":
        if visit_id is None:
            raise err_validation("visit_id is required for LOST_CHILD")
        get_visit_or_404(visit_id)
    elif visit_id is not None:
        get_visit_or_404(visit_id)
    incident = new_common_fields()
    incident.update({
        "visit_id": visit_id,
        "kind": kind,
        "severity": severity,
        "description": description,
        "status": "OPEN",
        "child_reunited": None,
        "resolution_note": None,
        "resolved_at": None,
        "reported_by_staff_id": user_id,
    })
    db["incidents"][incident["id"]] = incident
    return success_response(ser_incident(incident), 201)


@app.route("/incidents/<id>", methods=["GET"])
def get_incident(id):
    authenticate(["FrontDesk", "Manager"])
    incident = get_incident_or_404(id)
    return success_response(ser_incident(incident), 200)


@app.route("/incidents/<id>/triage", methods=["POST"])
def triage_incident(id):
    authenticate(["Manager"])
    incident = db["incidents"].get(id)
    if incident is None:
        raise err_not_found("Incident not found")
    if incident["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Incident is not OPEN")
    incident["status"] = "TRIAGED"
    touch(incident)
    return success_response(ser_incident(incident), 200)


@app.route("/incidents/<id>/resolve", methods=["POST"])
def resolve_incident(id):
    authenticate(["Manager"])
    incident = db["incidents"].get(id)
    if incident is None:
        raise err_not_found("Incident not found")
    if incident["status"] != "TRIAGED":
        raise ApiError("ERR_INVALID_STATE", "Incident is not TRIAGED")
    p = get_payload()
    child_reunited = p.get("child_reunited")
    resolution_note = p.get("resolution_note")
    if child_reunited is not None and not isinstance(child_reunited, bool):
        raise err_validation("Invalid type for field: child_reunited")
    if resolution_note is not None and not isinstance(resolution_note, str):
        raise err_validation("Invalid type for field: resolution_note")
    if incident["kind"] == "LOST_CHILD" and child_reunited is not True:
        raise ApiError("ERR_CHILD_NOT_REUNITED", "child_reunited must be true for LOST_CHILD")
    if child_reunited is not None:
        incident["child_reunited"] = child_reunited
    if resolution_note is not None:
        incident["resolution_note"] = resolution_note
    incident["status"] = "RESOLVED"
    incident["resolved_at"] = now_ts()
    touch(incident)
    return success_response(ser_incident(incident), 200)


@app.route("/incidents/<id>/reopen", methods=["POST"])
def reopen_incident(id):
    authenticate(["Manager"])
    incident = db["incidents"].get(id)
    if incident is None:
        raise err_not_found("Incident not found")
    if incident["status"] != "RESOLVED":
        raise ApiError("ERR_INVALID_STATE", "Incident is not RESOLVED")
    incident["status"] = "TRIAGED"
    incident["resolved_at"] = None
    touch(incident)
    return success_response(ser_incident(incident), 200)


@app.route("/incidents/<id>/close", methods=["POST"])
def close_incident(id):
    authenticate(["Manager"])
    incident = db["incidents"].get(id)
    if incident is None:
        raise err_not_found("Incident not found")
    if incident["status"] != "RESOLVED":
        raise ApiError("ERR_INVALID_STATE", "Incident is not RESOLVED")
    incident["status"] = "CLOSED"
    touch(incident)
    return success_response(ser_incident(incident), 200)


# ---------------------------------------------------------------------------
# Ops
# ---------------------------------------------------------------------------

@app.route("/ops-runs", methods=["POST"])
def ops_run():
    authenticate(["Manager", "Admin"])
    counts = {
        "no_shows_marked": 0,
        "holds_expired": 0,
        "sanitations_flagged": 0,
        "slots_closed": 0,
        "waivers_expired": 0,
        "tiers_recomputed": 0,
    }
    # No-show marking.
    for visit in list(db["visits"].values()):
        if visit["admission_status"] != "RESERVED":
            continue
        slot = db["session_slots"].get(visit["session_slot_id"])
        if slot is None:
            continue
        start_at = parse_iso(slot["start_at"])
        if start_at is None:
            continue
        if now() >= start_at + timedelta(minutes=15):
            visit["admission_status"] = "NO_SHOW"
            touch(visit)
            counts["no_shows_marked"] += 1
    # HELD party booking expiry.
    for booking in list(db["party_bookings"].values()):
        if booking["status"] != "HELD":
            continue
        created = parse_iso(booking["created_at"])
        if created is None:
            continue
        if now() >= created + timedelta(hours=24):
            booking["status"] = "EXPIRED"
            touch(booking)
            counts["holds_expired"] += 1
    # Sanitation overdue flagging.
    for task in list(db["sanitation_tasks"].values()):
        if task["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        due_at = parse_iso(task["due_at"])
        if due_at is None:
            continue
        if due_at <= now():
            task["status"] = "OVERDUE"
            touch(task)
            counts["sanitations_flagged"] += 1
    # Slot auto-close past end_at.
    for slot in list(db["session_slots"].values()):
        if slot["status"] == "CLOSED":
            continue
        end_at = parse_iso(slot["end_at"])
        if end_at is None:
            continue
        if end_at <= now():
            close_slot_cascade(slot, "OPS_ENDED")
            counts["slots_closed"] += 1
    # Waiver expiry.
    for waiver in list(db["waivers"].values()):
        if waiver["status"] != "SIGNED":
            continue
        expires = parse_iso(waiver["expires_at"])
        if expires is None:
            continue
        if expires <= now():
            waiver["status"] = "EXPIRED"
            touch(waiver)
            counts["waivers_expired"] += 1
    # Loyalty tier recompute.
    for guardian in list(db["guardians"].values()):
        _, _, lifetime = guardian_ledger(guardian["id"])
        guardian["loyalty_tier"] = tier_from_lifetime(lifetime)
        counts["tiers_recomputed"] += 1
    return success_response(counts, 200)


@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate(["Admin"])
    global current_utc
    p = get_payload()
    raw = req_str(p, "to_iso8601")
    dt = parse_iso(raw)
    if dt is None:
        raise err_validation("to_iso8601 must be an ISO 8601 datetime")
    current_utc = dt
    return success_response({"current_utc": _fmt_ts(current_utc)}, 200)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
