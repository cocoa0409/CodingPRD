"""Pool & Billiards Hall API — Flask entry point, routes, and business logic."""
import os
from datetime import timedelta
from decimal import Decimal

from flask import Flask, request, jsonify, g

import calc
from common import (
    ApiError, ROLES, gen_id, gen_request_id, format_dt, parse_dt, serialize,
    TABLE_TYPES, TIERS, TIER_RANK, FORMATS, HANDICAP_MODES, PRODUCT_CATEGORIES,
    SERVICE_TYPES, CYCLE_DAYS, NO_SHOW_GRACE_MINUTES, NO_SHOW_SUSPEND_THRESHOLD,
    CHECKIN_EARLY_MINUTES, TURNOVER_BUFFER_MINUTES, MIN_TOURNAMENT_ENTRIES,
    MIN_BILLED_MINUTES,
)
from store import db

app = Flask(__name__)


# ==========================================================================
# Response envelope
# ==========================================================================
def _meta(extra=None):
    m = {
        "api_request_id": gen_request_id(),
        "api_request_timestamp": format_dt(db.clock),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, response_type="object", meta_extra=None):
    body = {
        "meta": _meta(meta_extra),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def ok_list(items, limit, offset, total):
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return ok([serialize(i) for i in items], 200, "array", meta_extra)


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
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"}}
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(_e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"}}
    return jsonify(body), 404


# ==========================================================================
# Auth / RBAC
# ==========================================================================
def authenticate(allowed_roles, anonymous_ok=False):
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    role = role.strip() if role else role
    uid = uid.strip() if uid else uid
    if not role and not uid:
        if anonymous_ok:
            return None, "Anonymous"
        raise ApiError("ERR_UNAUTHENTICATED", "Missing authentication headers")
    if not role or not uid:
        if anonymous_ok:
            # A partially-supplied header set on an anonymous-capable endpoint.
            raise ApiError("ERR_UNAUTHENTICATED", "Malformed authentication headers")
        raise ApiError("ERR_UNAUTHENTICATED", "Missing authentication headers")
    if role not in ROLES:
        raise ApiError("ERR_FORBIDDEN", "Role not permitted")
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN", "Role not permitted for this operation")
    return uid, role


def require_owner(role, uid, owner_id):
    if role == "Member" and owner_id != uid:
        raise ApiError("ERR_FORBIDDEN", "Member may only act on its own resources")


# ==========================================================================
# Body parsing / validation helpers
# ==========================================================================
def get_body():
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise ApiError("ERR_VALIDATION", "Request body must be valid JSON")
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object")
    return body


def v_error(msg):
    raise ApiError("ERR_VALIDATION", msg)


def req_str(body, field):
    val = body.get(field)
    if not isinstance(val, str) or not val.strip():
        v_error(f"'{field}' must be a non-empty string")
    return val


def opt_str(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if not isinstance(val, str):
        v_error(f"'{field}' must be a string")
    return val


def req_int(body, field, minimum=None, maximum=None):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        v_error(f"'{field}' must be an integer")
    if minimum is not None and val < minimum:
        v_error(f"'{field}' must be >= {minimum}")
    if maximum is not None and val > maximum:
        v_error(f"'{field}' must be <= {maximum}")
    return val


def opt_int(body, field, default=None, minimum=None, maximum=None):
    if field not in body or body.get(field) is None:
        return default
    return req_int(body, field, minimum, maximum)


def req_number(body, field, minimum=None, maximum=None):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        v_error(f"'{field}' must be a number")
    if minimum is not None and val < minimum:
        v_error(f"'{field}' must be >= {minimum}")
    if maximum is not None and val > maximum:
        v_error(f"'{field}' must be <= {maximum}")
    return val


def req_enum(body, field, choices):
    val = req_str(body, field)
    if val not in choices:
        v_error(f"'{field}' must be one of {sorted(choices)}")
    return val


def opt_enum(body, field, choices, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_enum(body, field, choices)


# ==========================================================================
# Record lifecycle helpers
# ==========================================================================
def base_record():
    now = db.clock
    return {
        "id": gen_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(record):
    record["version"] += 1
    record["updated_at"] = db.clock


def paginate_args():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    try:
        limit = 10 if limit is None else int(limit)
        offset = 0 if offset is None else int(offset)
    except (TypeError, ValueError):
        raise ApiError("ERR_PAGINATION", "limit/offset must be integers")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_PAGINATION", "limit out of range")
    if offset < 0:
        raise ApiError("ERR_PAGINATION", "offset out of range")
    return limit, offset


def sorted_records(coll):
    return sorted(coll.values(), key=lambda r: (r["created_at"], r["_seq"]))


def list_response(records, limit, offset):
    total = len(records)
    page = records[offset:offset + limit]
    return ok_list(page, limit, offset, total)


# ==========================================================================
# Fetch-with-existence helpers
# ==========================================================================
def get_plan(pid):
    r = db.plans.get(pid)
    if r is None:
        raise ApiError("ERR_NOT_FOUND", "Plan not found")
    return r


def get_member(mid, apply_expiry=True):
    r = db.members.get(mid)
    if r is None:
        raise ApiError("ERR_NOT_FOUND", "Member not found")
    if apply_expiry:
        _apply_expiry(r)
    return r


def get_table(tid):
    r = db.tables.get(tid)
    if r is None:
        raise ApiError("ERR_NOT_FOUND", "Table not found")
    return r


def get_reservation(rid):
    r = db.reservations.get(rid)
    if r is None:
        raise ApiError("ERR_NOT_FOUND", "Reservation not found")
    return r


def get_session(sid):
    r = db.sessions.get(sid)
    if r is None:
        raise ApiError("ERR_NOT_FOUND", "Session not found")
    return r


def get_fnb(oid):
    r = db.fnb_orders.get(oid)
    if r is None:
        raise ApiError("ERR_NOT_FOUND", "Fnb order not found")
    return r


def get_tournament(tid):
    r = db.tournaments.get(tid)
    if r is None:
        raise ApiError("ERR_NOT_FOUND", "Tournament not found")
    return r


def get_entry(eid):
    r = db.entries.get(eid)
    if r is None:
        raise ApiError("ERR_NOT_FOUND", "Entry not found")
    return r


def get_product(pid):
    r = db.products.get(pid)
    if r is None:
        raise ApiError("ERR_NOT_FOUND", "Product not found")
    return r


def get_repair(rid):
    r = db.repairs.get(rid)
    if r is None:
        raise ApiError("ERR_NOT_FOUND", "Repair order not found")
    return r


def get_event(eid):
    r = db.events.get(eid)
    if r is None:
        raise ApiError("ERR_NOT_FOUND", "Event not found")
    return r


# ==========================================================================
# Wallet helpers (zero-floor). These do NOT touch() — caller bumps version.
# ==========================================================================
def check_and_debit(member, amount):
    if member["wallet_credit_cents"] - amount < 0:
        raise ApiError("ERR_INSUFFICIENT_FUNDS", "Wallet balance too low")
    member["wallet_credit_cents"] -= amount


def apply_adjustment(member, delta):
    new_balance = member["wallet_credit_cents"] + delta
    if new_balance < 0:
        raise ApiError("ERR_INSUFFICIENT_FUNDS", "Adjustment would drive balance below zero")
    member["wallet_credit_cents"] = new_balance


# ==========================================================================
# Lazy membership expiry (PRD §2.5, §3.1)
# ==========================================================================
def _apply_expiry(member):
    if member["membership_status"] == "ACTIVE" and db.clock >= member["membership_expires_at"]:
        member["membership_status"] = "EXPIRED"
        if member.get("pending_plan_id"):
            member["plan_id"] = member["pending_plan_id"]
            member["pending_plan_id"] = None


# ==========================================================================
# Reservation / table / event helpers & cascades
# ==========================================================================
def _windows_conflict(a_start, a_end, b_start, b_end):
    """True when [a_start,a_end) and [b_start,b_end) sit within the turnover buffer."""
    buffer = timedelta(minutes=TURNOVER_BUFFER_MINUTES)
    if b_start >= a_end + buffer:
        return False
    if a_start >= b_end + buffer:
        return False
    return True


def _turnover_conflict(table_id, start, end, exclude_id=None):
    for r in db.reservations.values():
        if r["table_id"] != table_id:
            continue
        if exclude_id is not None and r["id"] == exclude_id:
            continue
        if r["status"] not in ("PENDING", "CONFIRMED", "CHECKED_IN"):
            continue
        if _windows_conflict(start, end, r["start_at"], r["end_at"]):
            return True
    return False


def _table_overlap_reservations(table_id, start, end, statuses):
    for r in db.reservations.values():
        if r["table_id"] != table_id:
            continue
        if r["status"] not in statuses:
            continue
        if r["start_at"] < end and start < r["end_at"]:
            return True
    return False


def _free_active_tables(start, end):
    """ACTIVE tables with no CONFIRMED/CHECKED_IN reservation overlapping [start,end)."""
    result = []
    for t in sorted_records(db.tables):
        if t["status"] != "ACTIVE":
            continue
        if _table_overlap_reservations(t["id"], start, end, ("CONFIRMED", "CHECKED_IN")):
            continue
        result.append(t)
    return result


def _open_session_for_table(table_id):
    for s in db.sessions.values():
        if s["table_id"] == table_id and s["status"] == "OPEN":
            return s
    return None


def _open_session_for_reservation(res_id):
    for s in db.sessions.values():
        if s.get("reservation_id") == res_id and s["status"] == "OPEN":
            return s
    return None


def cancel_reservation(res, cascade_event=True):
    """Move a {PENDING,CONFIRMED} reservation to CANCELLED, with optional event cascade."""
    prior = res["status"]
    if prior not in ("PENDING", "CONFIRMED"):
        return
    res["status"] = "CANCELLED"
    touch(res)
    if cascade_event and prior == "CONFIRMED" and res.get("event_id"):
        ev = db.events.get(res["event_id"])
        if ev and ev["booking_status"] in ("BOOKED", "CONFIRMED"):
            cancel_event(ev)


def cancel_event(ev):
    """Event cancellation cascade (PRD §3.7)."""
    if ev["booking_status"] in ("COMPLETED", "CANCELLED"):
        return
    ev["booking_status"] = "CANCELLED"
    touch(ev)
    # Cancel this event's still-CONFIRMED reservations; void their open sessions.
    for r in list(db.reservations.values()):
        if r.get("event_id") == ev["id"] and r["status"] == "CONFIRMED":
            sess = _open_session_for_reservation(r["id"])
            if sess is not None:
                sess["status"] = "VOIDED"
                sess["ended_at"] = db.clock
                sess["final_charge_cents"] = 0
                touch(sess)
            r["status"] = "CANCELLED"
            touch(r)
    # Deposit refund (money-conserving compensation).
    if ev["payment_status"] == "DEPOSIT_PAID":
        host = db.members.get(ev["host_member_id"])
        if host is not None:
            host["wallet_credit_cents"] += ev["deposit_paid_cents"]
            touch(host)
        ev["payment_status"] = "REFUNDED"
        touch(ev)


def cancel_table_future_reservations(table_id):
    for r in list(db.reservations.values()):
        if r["table_id"] != table_id:
            continue
        if r["status"] not in ("PENDING", "CONFIRMED"):
            continue
        if r["start_at"] >= db.clock:
            cancel_reservation(r, cascade_event=True)


def apply_no_show_suspension(member):
    if member["no_show_strikes"] >= NO_SHOW_SUSPEND_THRESHOLD and member["membership_status"] == "ACTIVE":
        member["membership_status"] = "SUSPENDED"
        touch(member)
        for r in list(db.reservations.values()):
            if r["member_id"] == member["id"] and r["status"] in ("PENDING", "CONFIRMED"):
                cancel_reservation(r, cascade_event=True)


# ==========================================================================
# Window validation (reservations)
# ==========================================================================
def _parse_window(body):
    try:
        start = parse_dt(body.get("start_at"))
        end = parse_dt(body.get("end_at"))
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_WINDOW", "start_at/end_at must be valid datetimes")
    return start, end


def _validate_reservation_window(start, end, horizon_days):
    if start.second or start.microsecond or end.second or end.microsecond:
        raise ApiError("ERR_INVALID_WINDOW", "times must be aligned to whole minutes")
    if start >= end:
        raise ApiError("ERR_INVALID_WINDOW", "start_at must be before end_at")
    horizon = db.clock + timedelta(days=horizon_days)
    if end > horizon:
        raise ApiError("ERR_INVALID_WINDOW", "window exceeds reservation horizon")


# ==========================================================================
# MembershipPlan endpoints
# ==========================================================================
@app.route("/v1/plans", methods=["POST"])
def create_plan():
    authenticate(["Manager"])
    body = get_body()
    tier = req_enum(body, "tier", TIERS)
    monthly_fee = req_int(body, "monthly_fee_cents", minimum=0)
    discount = req_number(body, "table_discount_pct", minimum=0.0, maximum=0.5)
    included = opt_int(body, "included_hours_per_month", default=0, minimum=0)
    horizon = opt_int(body, "reservation_horizon_days", default=14, minimum=0)
    # Uniqueness: tier unique across active plans (all plans are active here).
    for p in db.plans.values():
        if p["tier"] == tier:
            raise ApiError("ERR_DUPLICATE", "tier already exists")
    rec = base_record()
    rec.update({
        "tier": tier,
        "monthly_fee_cents": monthly_fee,
        "table_discount_pct": discount,
        "included_hours_per_month": included,
        "reservation_horizon_days": horizon,
    })
    db.plans[rec["id"]] = rec
    return ok(serialize(rec), 201)


@app.route("/v1/plans", methods=["GET"])
def list_plans():
    authenticate(["Manager", "FrontDesk", "Member"])
    limit, offset = paginate_args()
    tier = request.args.get("tier")
    records = sorted_records(db.plans)
    if tier:
        records = [r for r in records if r["tier"] == tier]
    return list_response(records, limit, offset)


@app.route("/v1/plans/<pid>", methods=["GET"])
def get_plan_ep(pid):
    authenticate(["Manager", "FrontDesk", "Member"])
    return ok(serialize(get_plan(pid)))


# ==========================================================================
# Member endpoints
# ==========================================================================
@app.route("/v1/members", methods=["POST"])
def register_member():
    _, role = authenticate(["Manager"], anonymous_ok=True)
    body = get_body()
    email = req_str(body, "email")
    full_name = req_str(body, "full_name")
    plan_id = req_str(body, "plan_id")
    handicap = opt_int(body, "handicap_rating", default=5, minimum=1, maximum=9)
    plan = get_plan(plan_id)  # existence
    for m in db.members.values():
        if m["email"] == email:
            raise ApiError("ERR_DUPLICATE", "email already registered")
    rec = base_record()
    rec.update({
        "email": email,
        "full_name": full_name,
        "plan_id": plan_id,
        "pending_plan_id": None,
        "membership_status": "ACTIVE",
        "membership_expires_at": rec["created_at"] + timedelta(days=CYCLE_DAYS),
        "handicap_rating": handicap,
        "wallet_credit_cents": 0,
        "no_show_strikes": 0,
    })
    db.members[rec["id"]] = rec
    return ok(serialize(rec), 201)


@app.route("/v1/members", methods=["GET"])
def list_members():
    authenticate(["Manager", "FrontDesk"])
    limit, offset = paginate_args()
    plan_id = request.args.get("plan_id")
    status = request.args.get("membership_status")
    records = sorted_records(db.members)
    for r in records:
        _apply_expiry(r)
    if plan_id:
        records = [r for r in records if r["plan_id"] == plan_id]
    if status:
        records = [r for r in records if r["membership_status"] == status]
    return list_response(records, limit, offset)


@app.route("/v1/members/<mid>", methods=["GET"])
def get_member_ep(mid):
    _, role = authenticate(["Manager", "FrontDesk", "Member"])
    uid = request.headers.get("X-User-ID", "").strip()
    member = get_member(mid)
    require_owner(role, uid, member["id"])
    return ok(serialize(member))


@app.route("/v1/members/<mid>/plan-change", methods=["POST"])
def plan_change(mid):
    uid, role = authenticate(["Member"])
    member = get_member(mid)
    require_owner(role, uid, member["id"])
    body = get_body()
    target_id = req_str(body, "target_plan_id")
    if "expected_member_version" not in body:
        v_error("expected_member_version is required")
    expected = req_int(body, "expected_member_version")
    target = get_plan(target_id)  # existence
    if expected != member["version"]:
        raise ApiError("ERR_STALE_VERSION", "member version mismatch")
    current = get_plan(member["plan_id"])
    if TIER_RANK[target["tier"]] >= TIER_RANK[current["tier"]]:
        # upgrade (or same tier): immediate
        member["plan_id"] = target_id
        member["pending_plan_id"] = None
    else:
        # downgrade: deferred to next expiry
        member["pending_plan_id"] = target_id
    touch(member)
    return ok(serialize(member))


@app.route("/v1/members/<mid>/renew", methods=["POST"])
def renew_member(mid):
    authenticate(["Member", "FrontDesk"])
    uid = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    member = get_member(mid)
    require_owner(role, uid, member["id"])
    plan = get_plan(member["plan_id"])
    fee = plan["monthly_fee_cents"]
    check_and_debit(member, fee)  # funds check (may raise before any mutation)
    prior_status = member["membership_status"]
    if prior_status == "EXPIRED":
        member["membership_expires_at"] = db.clock + timedelta(days=CYCLE_DAYS)
    else:
        member["membership_expires_at"] = member["membership_expires_at"] + timedelta(days=CYCLE_DAYS)
    member["no_show_strikes"] = 0
    member["membership_status"] = "ACTIVE"
    touch(member)
    return ok(serialize(member))


@app.route("/v1/members/<mid>/wallet/adjustments", methods=["POST"])
def wallet_adjustment(mid):
    authenticate(["Manager", "FrontDesk"])
    member = get_member(mid)
    body = get_body()
    amount = req_int(body, "amount_cents")
    opt_str(body, "reason")
    apply_adjustment(member, amount)
    touch(member)
    return ok(serialize(member))


# ==========================================================================
# PoolTable endpoints
# ==========================================================================
@app.route("/v1/tables", methods=["POST"])
def create_table():
    authenticate(["Manager"])
    body = get_body()
    number = req_int(body, "table_number", minimum=1)
    ttype = req_enum(body, "table_type", TABLE_TYPES)
    capacity = req_int(body, "seat_capacity", minimum=1)
    rate = req_int(body, "hourly_rate_cents", minimum=0)
    for t in db.tables.values():
        if t["table_number"] == number:
            raise ApiError("ERR_DUPLICATE", "table_number already exists")
    rec = base_record()
    rec.update({
        "table_number": number,
        "table_type": ttype,
        "seat_capacity": capacity,
        "hourly_rate_cents": rate,
        "status": "ACTIVE",
    })
    db.tables[rec["id"]] = rec
    return ok(serialize(rec), 201)


@app.route("/v1/tables", methods=["GET"])
def list_tables():
    authenticate(["Manager", "FrontDesk", "Member"])
    limit, offset = paginate_args()
    status = request.args.get("status")
    ttype = request.args.get("table_type")
    records = sorted_records(db.tables)
    if status:
        records = [r for r in records if r["status"] == status]
    if ttype:
        records = [r for r in records if r["table_type"] == ttype]
    return list_response(records, limit, offset)


@app.route("/v1/tables/<tid>", methods=["GET"])
def get_table_ep(tid):
    authenticate(["Manager", "FrontDesk", "Member"])
    return ok(serialize(get_table(tid)))


@app.route("/v1/tables/<tid>/maintenance", methods=["POST"])
def table_maintenance(tid):
    authenticate(["Manager"])
    table = get_table(tid)
    if table["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "table not ACTIVE")
    if _open_session_for_table(tid) is not None:
        raise ApiError("ERR_DEPENDENT_STATE", "table has an OPEN session")
    table["status"] = "MAINTENANCE"
    touch(table)
    cancel_table_future_reservations(tid)
    return ok(serialize(table))


@app.route("/v1/tables/<tid>/activate", methods=["POST"])
def table_activate(tid):
    authenticate(["Manager"])
    table = get_table(tid)
    if table["status"] != "MAINTENANCE":
        raise ApiError("ERR_INVALID_STATE", "table not in MAINTENANCE")
    table["status"] = "ACTIVE"
    touch(table)
    return ok(serialize(table))


@app.route("/v1/tables/<tid>/retire", methods=["POST"])
def table_retire(tid):
    authenticate(["Manager"])
    table = get_table(tid)
    if table["status"] not in ("ACTIVE", "MAINTENANCE"):
        raise ApiError("ERR_INVALID_STATE", "table already retired")
    if table["status"] == "ACTIVE" and _open_session_for_table(tid) is not None:
        raise ApiError("ERR_DEPENDENT_STATE", "table has an OPEN session")
    table["status"] = "RETIRED"
    touch(table)
    cancel_table_future_reservations(tid)
    return ok(serialize(table))


# ==========================================================================
# Reservation endpoints
# ==========================================================================
@app.route("/v1/reservations", methods=["POST"])
def create_reservation():
    uid, role = authenticate(["Member", "FrontDesk"])
    body = get_body()
    member_id = req_str(body, "member_id")
    table_id = req_str(body, "table_id")
    require_owner(role, uid, member_id)
    member = get_member(member_id)   # existence + lazy expiry
    table = get_table(table_id)      # existence
    party_size = req_int(body, "party_size", minimum=1)
    start, end = _parse_window(body)
    plan = get_plan(member["plan_id"])
    # Priority 8: turnover conflict
    if start < end and not (start.second or start.microsecond or end.second or end.microsecond):
        if _turnover_conflict(table_id, start, end):
            raise ApiError("ERR_TABLE_TIME_CONFLICT", "window conflicts with another reservation")
    # Priority 10: party capacity
    if party_size > table["seat_capacity"]:
        raise ApiError("ERR_CAPACITY_EXCEEDED", "party_size exceeds seat_capacity")
    # Priority 11: window validity
    _validate_reservation_window(start, end, plan["reservation_horizon_days"])
    # Priority 15: member standing
    if member["membership_status"] == "SUSPENDED":
        raise ApiError("ERR_MEMBER_SUSPENDED", "member is suspended")
    rec = base_record()
    rec.update({
        "member_id": member_id,
        "table_id": table_id,
        "event_id": None,
        "start_at": start,
        "end_at": end,
        "party_size": party_size,
        "status": "PENDING",
    })
    db.reservations[rec["id"]] = rec
    return ok(serialize(rec), 201)


@app.route("/v1/reservations", methods=["GET"])
def list_reservations():
    uid, role = authenticate(["Manager", "FrontDesk", "Member"])
    limit, offset = paginate_args()
    records = sorted_records(db.reservations)
    if role == "Member":
        records = [r for r in records if r["member_id"] == uid]
    for key in ("member_id", "table_id", "event_id", "status"):
        val = request.args.get(key)
        if val is not None:
            records = [r for r in records if r.get(key) == val]
    return list_response(records, limit, offset)


@app.route("/v1/reservations/<rid>", methods=["GET"])
def get_reservation_ep(rid):
    uid, role = authenticate(["Manager", "FrontDesk", "Member"])
    res = get_reservation(rid)
    require_owner(role, uid, res["member_id"])
    return ok(serialize(res))


@app.route("/v1/reservations/<rid>/confirm", methods=["POST"])
def confirm_reservation(rid):
    authenticate(["FrontDesk"])
    res = get_reservation(rid)
    if res["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "reservation not PENDING")
    table = get_table(res["table_id"])
    if table["status"] != "ACTIVE":
        raise ApiError("ERR_TABLE_NOT_ACTIVE", "table not ACTIVE")
    res["status"] = "CONFIRMED"
    touch(res)
    return ok(serialize(res))


@app.route("/v1/reservations/<rid>/reschedule", methods=["POST"])
def reschedule_reservation(rid):
    uid, role = authenticate(["Member", "FrontDesk"])
    res = get_reservation(rid)
    require_owner(role, uid, res["member_id"])
    body = get_body()
    if "expected_reservation_version" not in body:
        v_error("expected_reservation_version is required")
    expected = req_int(body, "expected_reservation_version")
    # Priority 4: state
    if res["status"] not in ("PENDING", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE", "reservation cannot be rescheduled")
    # Priority 5: OCC
    if expected != res["version"]:
        raise ApiError("ERR_STALE_VERSION", "reservation version mismatch")
    table = get_table(res["table_id"])
    member = get_member(res["member_id"])
    plan = get_plan(member["plan_id"])
    # Priority 6: table active
    if table["status"] != "ACTIVE":
        raise ApiError("ERR_TABLE_NOT_ACTIVE", "table not ACTIVE")
    start, end = _parse_window(body)
    # Priority 8: turnover conflict
    if start < end and not (start.second or start.microsecond or end.second or end.microsecond):
        if _turnover_conflict(res["table_id"], start, end, exclude_id=res["id"]):
            raise ApiError("ERR_TABLE_TIME_CONFLICT", "window conflicts with another reservation")
    # Priority 10: party capacity
    if res["party_size"] > table["seat_capacity"]:
        raise ApiError("ERR_CAPACITY_EXCEEDED", "party_size exceeds seat_capacity")
    # Priority 11: window validity
    _validate_reservation_window(start, end, plan["reservation_horizon_days"])
    res["start_at"] = start
    res["end_at"] = end
    touch(res)
    return ok(serialize(res))


@app.route("/v1/reservations/<rid>/cancel", methods=["POST"])
def cancel_reservation_ep(rid):
    uid, role = authenticate(["Member", "FrontDesk"])
    res = get_reservation(rid)
    require_owner(role, uid, res["member_id"])
    if res["status"] not in ("PENDING", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE", "reservation cannot be cancelled")
    cancel_reservation(res, cascade_event=True)
    return ok(serialize(res))


@app.route("/v1/reservations/<rid>/check-in", methods=["POST"])
def checkin_reservation(rid):
    authenticate(["FrontDesk"])
    res = get_reservation(rid)
    if res["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", "reservation not CONFIRMED")
    table = get_table(res["table_id"])
    if table["status"] != "ACTIVE":
        raise ApiError("ERR_TABLE_NOT_ACTIVE", "table not ACTIVE")
    earliest = res["start_at"] - timedelta(minutes=CHECKIN_EARLY_MINUTES)
    if db.clock < earliest:
        raise ApiError("ERR_INVALID_STATE", "too early to check in")
    res["status"] = "CHECKED_IN"
    touch(res)
    # Cascade link 1: open a TableSession with provisional charge.
    reserved_minutes = calc.whole_minutes(res["start_at"], res["end_at"])
    provisional = calc.provisional_charge(reserved_minutes, table["hourly_rate_cents"])
    sess = base_record()
    sess.update({
        "reservation_id": res["id"],
        "table_id": table["id"],
        "member_id": res["member_id"],
        "started_at": db.clock,
        "ended_at": None,
        "provisional_charge_cents": provisional,
        "final_charge_cents": 0,
        "status": "OPEN",
    })
    db.sessions[sess["id"]] = sess
    return ok(serialize(sess), 201)


@app.route("/v1/reservations/<rid>/no-show", methods=["POST"])
def no_show_reservation(rid):
    authenticate(["FrontDesk"])
    res = get_reservation(rid)
    if res["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", "reservation not CONFIRMED")
    threshold = res["start_at"] + timedelta(minutes=NO_SHOW_GRACE_MINUTES)
    if db.clock < threshold:
        raise ApiError("ERR_INVALID_STATE", "grace period not elapsed")
    res["status"] = "NO_SHOW"
    touch(res)
    member = get_member(res["member_id"])
    member["no_show_strikes"] += 1
    touch(member)
    apply_no_show_suspension(member)
    return ok(serialize(res))


# ==========================================================================
# TableSession endpoints
# ==========================================================================
@app.route("/v1/sessions", methods=["POST"])
def open_session():
    authenticate(["FrontDesk"])
    body = get_body()
    table_id = req_str(body, "table_id")
    member_id = opt_str(body, "member_id")
    table = get_table(table_id)
    member = None
    if member_id is not None:
        member = get_member(member_id)
    if table["status"] != "ACTIVE":
        raise ApiError("ERR_TABLE_NOT_ACTIVE", "table not ACTIVE")
    provisional = calc.provisional_charge(MIN_BILLED_MINUTES, table["hourly_rate_cents"])
    sess = base_record()
    sess.update({
        "reservation_id": None,
        "table_id": table_id,
        "member_id": member_id,
        "started_at": db.clock,
        "ended_at": None,
        "provisional_charge_cents": provisional,
        "final_charge_cents": 0,
        "status": "OPEN",
    })
    db.sessions[sess["id"]] = sess
    return ok(serialize(sess), 201)


@app.route("/v1/sessions", methods=["GET"])
def list_sessions():
    uid, role = authenticate(["Manager", "FrontDesk", "Member"])
    limit, offset = paginate_args()
    records = sorted_records(db.sessions)
    if role == "Member":
        records = [r for r in records if r.get("member_id") == uid]
    for key in ("reservation_id", "table_id", "member_id", "status"):
        val = request.args.get(key)
        if val is not None:
            records = [r for r in records if r.get(key) == val]
    return list_response(records, limit, offset)


@app.route("/v1/sessions/<sid>", methods=["GET"])
def get_session_ep(sid):
    uid, role = authenticate(["Manager", "FrontDesk", "Member"])
    sess = get_session(sid)
    require_owner(role, uid, sess.get("member_id"))
    return ok(serialize(sess))


@app.route("/v1/sessions/<sid>/close", methods=["POST"])
def close_session(sid):
    authenticate(["FrontDesk"])
    sess = get_session(sid)
    if sess["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "session not OPEN")
    table = get_table(sess["table_id"])
    ended_at = db.clock
    discount = 0.0
    member = None
    if sess.get("member_id"):
        member = get_member(sess["member_id"])
        plan = get_plan(member["plan_id"])
        discount = plan["table_discount_pct"]
    final = calc.final_charge(sess["started_at"], ended_at, table["hourly_rate_cents"], discount)
    if member is not None:
        check_and_debit(member, final)  # funds check before any mutation
    sess["ended_at"] = ended_at
    sess["final_charge_cents"] = final
    sess["status"] = "CLOSED"
    touch(sess)
    if member is not None:
        touch(member)
    if sess.get("reservation_id"):
        res = db.reservations.get(sess["reservation_id"])
        if res is not None and res["status"] == "CHECKED_IN":
            res["status"] = "COMPLETED"
            touch(res)
    return ok(serialize(sess))


@app.route("/v1/sessions/<sid>/void", methods=["POST"])
def void_session(sid):
    authenticate(["FrontDesk", "Manager"])
    sess = get_session(sid)
    if sess["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "session not OPEN")
    sess["ended_at"] = db.clock
    sess["final_charge_cents"] = 0
    sess["status"] = "VOIDED"
    touch(sess)
    if sess.get("reservation_id"):
        res = db.reservations.get(sess["reservation_id"])
        if res is not None and res["status"] == "CHECKED_IN":
            res["status"] = "CANCELLED"
            touch(res)
    return ok(serialize(sess))


# ==========================================================================
# FnbOrder endpoints
# ==========================================================================
def _validate_line_items(body):
    items = body.get("line_items")
    if not isinstance(items, list) or len(items) == 0:
        v_error("line_items must be a non-empty array")
    clean = []
    for li in items:
        if not isinstance(li, dict):
            v_error("each line item must be an object")
        name = li.get("name")
        if not isinstance(name, str) or not name.strip():
            v_error("line item name must be a non-empty string")
        price = li.get("unit_price_cents")
        if isinstance(price, bool) or not isinstance(price, int) or price < 0:
            v_error("line item unit_price_cents must be a non-negative integer")
        qty = li.get("qty")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            v_error("line item qty must be a positive integer")
        clean.append({"name": name, "unit_price_cents": price, "qty": qty})
    return clean


@app.route("/v1/fnb-orders", methods=["POST"])
def create_fnb():
    uid, role = authenticate(["Member", "FrontDesk"])
    body = get_body()
    session_id = req_str(body, "session_id")
    member_id = opt_str(body, "member_id")
    if role == "Member" and member_id is not None:
        require_owner(role, uid, member_id)
    sess = get_session(session_id)
    if member_id is not None:
        get_member(member_id)
    line_items = _validate_line_items(body)
    rec = base_record()
    rec.update({
        "session_id": session_id,
        "member_id": member_id,
        "line_items": line_items,
        "subtotal_cents": 0,
        "tax_cents": 0,
        "total_cents": 0,
        "status": "OPEN",
    })
    db.fnb_orders[rec["id"]] = rec
    return ok(serialize(rec), 201)


@app.route("/v1/fnb-orders", methods=["GET"])
def list_fnb():
    uid, role = authenticate(["Manager", "FrontDesk", "Member"])
    limit, offset = paginate_args()
    records = sorted_records(db.fnb_orders)
    if role == "Member":
        records = [r for r in records if r.get("member_id") == uid]
    for key in ("session_id", "member_id", "status"):
        val = request.args.get(key)
        if val is not None:
            records = [r for r in records if r.get(key) == val]
    return list_response(records, limit, offset)


@app.route("/v1/fnb-orders/<oid>", methods=["GET"])
def get_fnb_ep(oid):
    uid, role = authenticate(["Manager", "FrontDesk", "Member"])
    order = get_fnb(oid)
    require_owner(role, uid, order.get("member_id"))
    return ok(serialize(order))


@app.route("/v1/fnb-orders/<oid>/submit", methods=["POST"])
def submit_fnb(oid):
    authenticate(["FrontDesk"])
    order = get_fnb(oid)
    if order["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "order not OPEN")
    sess = get_session(order["session_id"])
    if sess["status"] != "OPEN":
        raise ApiError("ERR_DEPENDENT_STATE", "parent session not OPEN")
    subtotal, tax, total = calc.fnb_totals(order["line_items"])
    member = None
    if order.get("member_id"):
        member = get_member(order["member_id"])
        check_and_debit(member, total)
    order["subtotal_cents"] = subtotal
    order["tax_cents"] = tax
    order["total_cents"] = total
    order["status"] = "SUBMITTED"
    touch(order)
    if member is not None:
        touch(member)
    return ok(serialize(order))


@app.route("/v1/fnb-orders/<oid>/void", methods=["POST"])
def void_fnb(oid):
    authenticate(["FrontDesk"])
    order = get_fnb(oid)
    if order["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "order not OPEN")
    order["status"] = "VOIDED"
    touch(order)
    return ok(serialize(order))


# ==========================================================================
# Tournament endpoints
# ==========================================================================
@app.route("/v1/tournaments", methods=["POST"])
def create_tournament():
    authenticate(["Manager"])
    body = get_body()
    name = req_str(body, "name")
    fmt = req_enum(body, "format", FORMATS)
    handicap_mode = opt_enum(body, "handicap_mode", HANDICAP_MODES, default="CAPPED")
    entry_fee = req_int(body, "entry_fee_cents", minimum=0)
    max_entries = req_int(body, "max_entries", minimum=MIN_TOURNAMENT_ENTRIES)
    rec = base_record()
    rec.update({
        "name": name,
        "format": fmt,
        "handicap_mode": handicap_mode,
        "entry_fee_cents": entry_fee,
        "max_entries": max_entries,
        "open_slots": max_entries,
        "prize_pool_cents": 0,
        "status": "SCHEDULED",
    })
    db.tournaments[rec["id"]] = rec
    return ok(serialize(rec), 201)


@app.route("/v1/tournaments", methods=["GET"])
def list_tournaments():
    authenticate(["Manager", "FrontDesk", "Member"])
    limit, offset = paginate_args()
    records = sorted_records(db.tournaments)
    for key in ("status", "format"):
        val = request.args.get(key)
        if val is not None:
            records = [r for r in records if r.get(key) == val]
    return list_response(records, limit, offset)


@app.route("/v1/tournaments/<tid>", methods=["GET"])
def get_tournament_ep(tid):
    authenticate(["Manager", "FrontDesk", "Member"])
    return ok(serialize(get_tournament(tid)))


@app.route("/v1/tournaments/<tid>/open", methods=["POST"])
def open_tournament(tid):
    authenticate(["Manager"])
    t = get_tournament(tid)
    if t["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "tournament not SCHEDULED")
    t["status"] = "REGISTRATION_OPEN"
    touch(t)
    return ok(serialize(t))


def _captured_entries(tid):
    return [e for e in db.entries.values()
            if e["tournament_id"] == tid and e["status"] in ("ENTERED", "CHECKED_IN")]


@app.route("/v1/tournaments/<tid>/seed", methods=["POST"])
def seed_tournament(tid):
    authenticate(["Manager"])
    t = get_tournament(tid)
    if t["status"] != "REGISTRATION_OPEN":
        raise ApiError("ERR_INVALID_STATE", "tournament not REGISTRATION_OPEN")
    entries = _captured_entries(tid)
    if len(entries) < MIN_TOURNAMENT_ENTRIES:
        raise ApiError("ERR_PRECONDITION_NOT_MET", "not enough captured entries to seed")
    top_rating = max(db.members[e["member_id"]]["handicap_rating"] for e in entries)
    for e in entries:
        rating = db.members[e["member_id"]]["handicap_rating"]
        e["handicap_spot"] = calc.handicap_spot(t["handicap_mode"], top_rating, rating)
        touch(e)
    t["status"] = "SEEDED"
    touch(t)
    return ok(serialize(t))


@app.route("/v1/tournaments/<tid>/start", methods=["POST"])
def start_tournament(tid):
    authenticate(["Manager"])
    t = get_tournament(tid)
    if t["status"] != "SEEDED":
        raise ApiError("ERR_INVALID_STATE", "tournament not SEEDED")
    t["status"] = "IN_PROGRESS"
    touch(t)
    return ok(serialize(t))


@app.route("/v1/tournaments/<tid>/complete", methods=["POST"])
def complete_tournament(tid):
    authenticate(["Manager"])
    t = get_tournament(tid)
    if t["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "tournament not IN_PROGRESS")
    for e in db.entries.values():
        if e["tournament_id"] == tid and e["status"] == "CHECKED_IN":
            e["status"] = "ELIMINATED"
            touch(e)
    t["status"] = "COMPLETED"
    touch(t)
    return ok(serialize(t))


@app.route("/v1/tournaments/<tid>/cancel", methods=["POST"])
def cancel_tournament(tid):
    authenticate(["Manager"])
    t = get_tournament(tid)
    if t["status"] not in ("SCHEDULED", "REGISTRATION_OPEN", "SEEDED"):
        raise ApiError("ERR_INVALID_STATE", "tournament cannot be cancelled")
    for e in db.entries.values():
        if e["tournament_id"] == tid and e["status"] in ("ENTERED", "CHECKED_IN"):
            e["status"] = "WITHDRAWN"
            touch(e)
            member = db.members.get(e["member_id"])
            if member is not None:
                member["wallet_credit_cents"] += e["entry_fee_cents"]
                touch(member)
            t["prize_pool_cents"] -= e["entry_fee_cents"]
            t["open_slots"] += 1
    t["status"] = "CANCELLED"
    touch(t)
    return ok(serialize(t))


# ==========================================================================
# TournamentEntry endpoints
# ==========================================================================
@app.route("/v1/tournament-entries", methods=["POST"])
def create_entry():
    uid, role = authenticate(["Member"])
    body = get_body()
    tournament_id = req_str(body, "tournament_id")
    member_id = req_str(body, "member_id")
    require_owner(role, uid, member_id)
    t = get_tournament(tournament_id)
    member = get_member(member_id)
    if t["status"] != "REGISTRATION_OPEN":
        raise ApiError("ERR_DEPENDENT_STATE", "tournament registration not open")
    if t["open_slots"] <= 0:
        raise ApiError("ERR_PRECONDITION_NOT_MET", "bracket is full")
    if member["membership_status"] == "SUSPENDED":
        raise ApiError("ERR_MEMBER_SUSPENDED", "member is suspended")
    fee = t["entry_fee_cents"]
    check_and_debit(member, fee)
    touch(member)
    rec = base_record()
    rec.update({
        "tournament_id": tournament_id,
        "member_id": member_id,
        "entry_fee_cents": fee,
        "handicap_spot": None,
        "status": "ENTERED",
    })
    db.entries[rec["id"]] = rec
    t["prize_pool_cents"] += fee
    t["open_slots"] -= 1
    touch(t)
    return ok(serialize(rec), 201)


@app.route("/v1/tournament-entries", methods=["GET"])
def list_entries():
    uid, role = authenticate(["Manager", "FrontDesk", "Member"])
    limit, offset = paginate_args()
    records = sorted_records(db.entries)
    if role == "Member":
        records = [r for r in records if r["member_id"] == uid]
    for key in ("tournament_id", "member_id", "status"):
        val = request.args.get(key)
        if val is not None:
            records = [r for r in records if r.get(key) == val]
    return list_response(records, limit, offset)


@app.route("/v1/tournament-entries/<eid>", methods=["GET"])
def get_entry_ep(eid):
    uid, role = authenticate(["Manager", "FrontDesk", "Member"])
    entry = get_entry(eid)
    require_owner(role, uid, entry["member_id"])
    return ok(serialize(entry))


@app.route("/v1/tournament-entries/<eid>/check-in", methods=["POST"])
def checkin_entry(eid):
    authenticate(["FrontDesk"])
    entry = get_entry(eid)
    if entry["status"] != "ENTERED":
        raise ApiError("ERR_INVALID_STATE", "entry not ENTERED")
    t = get_tournament(entry["tournament_id"])
    if t["status"] != "SEEDED":
        raise ApiError("ERR_DEPENDENT_STATE", "tournament not SEEDED")
    entry["status"] = "CHECKED_IN"
    touch(entry)
    return ok(serialize(entry))


@app.route("/v1/tournament-entries/<eid>/withdraw", methods=["POST"])
def withdraw_entry(eid):
    uid, role = authenticate(["Member"])
    entry = get_entry(eid)
    require_owner(role, uid, entry["member_id"])
    if entry["status"] != "ENTERED":
        raise ApiError("ERR_INVALID_STATE", "entry not ENTERED")
    t = get_tournament(entry["tournament_id"])
    if t["status"] not in ("REGISTRATION_OPEN", "SEEDED"):
        raise ApiError("ERR_DEPENDENT_STATE", "tournament not accepting withdrawals")
    entry["status"] = "WITHDRAWN"
    touch(entry)
    member = get_member(entry["member_id"])
    member["wallet_credit_cents"] += entry["entry_fee_cents"]
    touch(member)
    t["prize_pool_cents"] -= entry["entry_fee_cents"]
    t["open_slots"] += 1
    touch(t)
    return ok(serialize(entry))


# ==========================================================================
# ProShopProduct endpoints
# ==========================================================================
@app.route("/v1/products", methods=["POST"])
def create_product():
    authenticate(["ProShopStaff", "Manager"])
    body = get_body()
    sku = req_str(body, "sku")
    name = req_str(body, "name")
    category = req_enum(body, "category", PRODUCT_CATEGORIES)
    price = req_int(body, "unit_price_cents", minimum=0)
    stock = req_int(body, "stock_qty", minimum=0)
    for p in db.products.values():
        if p["sku"] == sku:
            raise ApiError("ERR_DUPLICATE", "sku already exists")
    rec = base_record()
    rec.update({
        "sku": sku,
        "name": name,
        "category": category,
        "unit_price_cents": price,
        "stock_qty": stock,
    })
    db.products[rec["id"]] = rec
    return ok(serialize(rec), 201)


@app.route("/v1/products", methods=["GET"])
def list_products():
    authenticate(["Manager", "FrontDesk", "ProShopStaff", "Member"])
    limit, offset = paginate_args()
    records = sorted_records(db.products)
    category = request.args.get("category")
    if category:
        records = [r for r in records if r["category"] == category]
    return list_response(records, limit, offset)


@app.route("/v1/products/<pid>", methods=["GET"])
def get_product_ep(pid):
    authenticate(["Manager", "FrontDesk", "ProShopStaff", "Member"])
    return ok(serialize(get_product(pid)))


@app.route("/v1/products/<pid>/restock", methods=["POST"])
def restock_product(pid):
    authenticate(["ProShopStaff", "Manager"])
    product = get_product(pid)
    body = get_body()
    qty = req_int(body, "qty")
    if qty <= 0:
        raise ApiError("ERR_STOCK_NEGATIVE", "qty must be positive")
    product["stock_qty"] += qty
    touch(product)
    return ok(serialize(product))


@app.route("/v1/products/<pid>/sell", methods=["POST"])
def sell_product(pid):
    authenticate(["ProShopStaff", "Manager"])
    product = get_product(pid)
    body = get_body()
    qty = req_int(body, "qty")
    member_id = opt_str(body, "member_id")
    member = None
    if member_id is not None:
        member = get_member(member_id)
    if qty <= 0:
        raise ApiError("ERR_STOCK_NEGATIVE", "qty must be positive")
    if qty > product["stock_qty"]:
        raise ApiError("ERR_PRECONDITION_NOT_MET", "insufficient stock")
    charge = product["unit_price_cents"] * qty
    if member is not None:
        check_and_debit(member, charge)
    product["stock_qty"] -= qty
    touch(product)
    if member is not None:
        touch(member)
    return ok(serialize(product))


# ==========================================================================
# RepairOrder endpoints
# ==========================================================================
@app.route("/v1/repair-orders", methods=["POST"])
def create_repair():
    uid, role = authenticate(["Member", "ProShopStaff"])
    body = get_body()
    member_id = req_str(body, "member_id")
    service_type = req_enum(body, "service_type", SERVICE_TYPES)
    quote = req_int(body, "quote_cents", minimum=0)
    product_id = opt_str(body, "product_id")
    table_id = opt_str(body, "table_id")
    require_owner(role, uid, member_id)
    get_member(member_id)
    if product_id is not None:
        get_product(product_id)
    if table_id is not None:
        get_table(table_id)
    rec = base_record()
    rec.update({
        "member_id": member_id,
        "product_id": product_id,
        "table_id": table_id,
        "service_type": service_type,
        "quote_cents": quote,
        "status": "RECEIVED",
    })
    db.repairs[rec["id"]] = rec
    return ok(serialize(rec), 201)


@app.route("/v1/repair-orders", methods=["GET"])
def list_repairs():
    uid, role = authenticate(["Manager", "FrontDesk", "ProShopStaff", "Member"])
    limit, offset = paginate_args()
    records = sorted_records(db.repairs)
    if role == "Member":
        records = [r for r in records if r["member_id"] == uid]
    for key in ("member_id", "product_id", "table_id", "status"):
        val = request.args.get(key)
        if val is not None:
            records = [r for r in records if r.get(key) == val]
    return list_response(records, limit, offset)


@app.route("/v1/repair-orders/<rid>", methods=["GET"])
def get_repair_ep(rid):
    uid, role = authenticate(["Manager", "FrontDesk", "ProShopStaff", "Member"])
    repair = get_repair(rid)
    require_owner(role, uid, repair["member_id"])
    return ok(serialize(repair))


@app.route("/v1/repair-orders/<rid>/start", methods=["POST"])
def start_repair(rid):
    authenticate(["ProShopStaff"])
    repair = get_repair(rid)
    if repair["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE", "repair not RECEIVED")
    repair["status"] = "IN_PROGRESS"
    touch(repair)
    return ok(serialize(repair))


@app.route("/v1/repair-orders/<rid>/ready", methods=["POST"])
def ready_repair(rid):
    authenticate(["ProShopStaff"])
    repair = get_repair(rid)
    if repair["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "repair not IN_PROGRESS")
    if repair["service_type"] == "TABLE_RECOVER":
        table = get_table(repair["table_id"]) if repair.get("table_id") else None
        if table is None or table["status"] != "MAINTENANCE":
            raise ApiError("ERR_DEPENDENT_STATE", "table must be in MAINTENANCE")
    repair["status"] = "READY"
    touch(repair)
    return ok(serialize(repair))


@app.route("/v1/repair-orders/<rid>/pickup", methods=["POST"])
def pickup_repair(rid):
    authenticate(["FrontDesk"])
    repair = get_repair(rid)
    if repair["status"] != "READY":
        raise ApiError("ERR_INVALID_STATE", "repair not READY")
    member = get_member(repair["member_id"])
    check_and_debit(member, repair["quote_cents"])
    touch(member)
    repair["status"] = "PICKED_UP"
    touch(repair)
    return ok(serialize(repair))


@app.route("/v1/repair-orders/<rid>/cancel", methods=["POST"])
def cancel_repair(rid):
    uid, role = authenticate(["Member", "ProShopStaff"])
    repair = get_repair(rid)
    require_owner(role, uid, repair["member_id"])
    if repair["status"] not in ("RECEIVED", "IN_PROGRESS"):
        raise ApiError("ERR_INVALID_STATE", "repair cannot be cancelled")
    repair["status"] = "CANCELLED"
    touch(repair)
    return ok(serialize(repair))


# ==========================================================================
# Event endpoints
# ==========================================================================
@app.route("/v1/events", methods=["POST"])
def create_event():
    uid, role = authenticate(["Member", "Manager"])
    body = get_body()
    host_member_id = req_str(body, "host_member_id")
    table_count = req_int(body, "table_count", minimum=1)
    require_owner(role, uid, host_member_id)
    host = get_member(host_member_id)
    start, end = _parse_window(body)
    if start >= end:
        raise ApiError("ERR_INVALID_WINDOW", "start_at must be before end_at")
    if host["membership_status"] == "SUSPENDED":
        raise ApiError("ERR_MEMBER_SUSPENDED", "host is suspended")
    rec = base_record()
    rec.update({
        "host_member_id": host_member_id,
        "table_count": table_count,
        "start_at": start,
        "end_at": end,
        "quote_cents": 0,
        "deposit_cents": 0,
        "deposit_paid_cents": 0,
        "booking_status": "INQUIRY",
        "payment_status": "UNPAID",
    })
    db.events[rec["id"]] = rec
    return ok(serialize(rec), 201)


@app.route("/v1/events", methods=["GET"])
def list_events():
    uid, role = authenticate(["Manager", "FrontDesk", "Member"])
    limit, offset = paginate_args()
    records = sorted_records(db.events)
    if role == "Member":
        records = [r for r in records if r["host_member_id"] == uid]
    host = request.args.get("host_member_id")
    booking = request.args.get("booking_status")
    if host is not None:
        records = [r for r in records if r["host_member_id"] == host]
    if booking is not None:
        records = [r for r in records if r["booking_status"] == booking]
    return list_response(records, limit, offset)


@app.route("/v1/events/<eid>", methods=["GET"])
def get_event_ep(eid):
    uid, role = authenticate(["Manager", "FrontDesk", "Member"])
    ev = get_event(eid)
    require_owner(role, uid, ev["host_member_id"])
    return ok(serialize(ev))


@app.route("/v1/events/<eid>/quote", methods=["POST"])
def quote_event(eid):
    authenticate(["Manager"])
    ev = get_event(eid)
    if ev["booking_status"] != "INQUIRY":
        raise ApiError("ERR_INVALID_STATE", "event not INQUIRY")
    free = _free_active_tables(ev["start_at"], ev["end_at"])
    if len(free) < ev["table_count"]:
        raise ApiError("ERR_EVENT_CAPACITY_UNAVAILABLE", "not enough free tables")
    quote, deposit = calc.event_quote(ev["table_count"], ev["start_at"], ev["end_at"])
    ev["quote_cents"] = quote
    ev["deposit_cents"] = deposit
    ev["booking_status"] = "QUOTED"
    touch(ev)
    return ok(serialize(ev))


@app.route("/v1/events/<eid>/pay-deposit", methods=["POST"])
def pay_deposit(eid):
    uid, role = authenticate(["Member"])
    ev = get_event(eid)
    require_owner(role, uid, ev["host_member_id"])
    if ev["payment_status"] != "UNPAID" or ev["booking_status"] not in ("QUOTED", "BOOKED"):
        raise ApiError("ERR_INVALID_STATE", "deposit cannot be paid in current state")
    host = get_member(ev["host_member_id"])
    check_and_debit(host, ev["deposit_cents"])
    touch(host)
    ev["deposit_paid_cents"] = ev["deposit_cents"]
    ev["payment_status"] = "DEPOSIT_PAID"
    touch(ev)
    return ok(serialize(ev))


@app.route("/v1/events/<eid>/book", methods=["POST"])
def book_event(eid):
    uid, role = authenticate(["Member"])
    ev = get_event(eid)
    require_owner(role, uid, ev["host_member_id"])
    if ev["booking_status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE", "event not QUOTED")
    free = _free_active_tables(ev["start_at"], ev["end_at"])
    if len(free) < ev["table_count"]:
        raise ApiError("ERR_EVENT_CAPACITY_UNAVAILABLE", "not enough free tables")
    selected = free[:ev["table_count"]]
    for table in selected:
        rec = base_record()
        rec.update({
            "member_id": ev["host_member_id"],
            "table_id": table["id"],
            "event_id": ev["id"],
            "start_at": ev["start_at"],
            "end_at": ev["end_at"],
            "party_size": 1,
            "status": "CONFIRMED",
        })
        db.reservations[rec["id"]] = rec
    ev["booking_status"] = "BOOKED"
    touch(ev)
    return ok(serialize(ev))


@app.route("/v1/events/<eid>/confirm", methods=["POST"])
def confirm_event(eid):
    authenticate(["Manager"])
    ev = get_event(eid)
    if ev["booking_status"] != "BOOKED":
        raise ApiError("ERR_INVALID_STATE", "event not BOOKED")
    if ev["payment_status"] not in ("DEPOSIT_PAID", "PAID_IN_FULL"):
        raise ApiError("ERR_DEPENDENT_STATE", "deposit not paid")
    ev["booking_status"] = "CONFIRMED"
    touch(ev)
    return ok(serialize(ev))


@app.route("/v1/events/<eid>/complete", methods=["POST"])
def complete_event(eid):
    authenticate(["Manager"])
    ev = get_event(eid)
    if ev["booking_status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", "event not CONFIRMED")
    ev["booking_status"] = "COMPLETED"
    if ev["payment_status"] != "REFUNDED":
        ev["payment_status"] = "PAID_IN_FULL"
    touch(ev)
    return ok(serialize(ev))


@app.route("/v1/events/<eid>/cancel", methods=["POST"])
def cancel_event_ep(eid):
    uid, role = authenticate(["Member", "Manager"])
    ev = get_event(eid)
    require_owner(role, uid, ev["host_member_id"])
    if ev["booking_status"] in ("COMPLETED", "CANCELLED"):
        raise ApiError("ERR_INVALID_STATE", "event cannot be cancelled")
    cancel_event(ev)
    return ok(serialize(ev))


# ==========================================================================
# Logical clock
# ==========================================================================
@app.route("/v1/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate(["Manager"])
    body = get_body()
    value = body.get("to_iso8601")
    try:
        new_clock = parse_dt(value)
    except (ValueError, TypeError):
        v_error("to_iso8601 must be a valid ISO 8601 datetime")
    db.clock = new_clock
    return ok({})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
