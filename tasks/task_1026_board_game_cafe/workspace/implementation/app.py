import os
import math
import uuid
import random
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

UTC = timezone.utc

# ---------------------------------------------------------------------------
# In-memory store (wiped on every process start)
# ---------------------------------------------------------------------------
ENTITY_TYPES = [
    "Table", "Membership", "Reservation", "FnbOrder", "GameCopy", "Checkout",
    "Tournament", "Registration", "Room", "PrivateBooking", "RetailOrder",
]
db = {t: {} for t in ENTITY_TYPES}
_seq_counter = {"n": 0}
_clock = {"now": datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC)}


def next_seq():
    _seq_counter["n"] += 1
    return _seq_counter["n"]


def clock_now():
    return _clock["now"]


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def fmt_ts(dt):
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=""):
    raise ApiError(error_id, http_status, message)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _meta(extra=None):
    rid = "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))
    m = {"api_request_id": rid, "api_request_timestamp": fmt_ts(clock_now())}
    if extra:
        m.update(extra)
    return m


def ok_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), code


def ok_array(items, limit, offset, total_count):
    has_more = (offset + limit) < total_count
    meta_extra = {"limit": limit, "offset": offset, "total_count": total_count, "has_more": has_more}
    body = {"meta": _meta(meta_extra), "response_type": "array", "data": items}
    return jsonify(body), 200


@app.errorhandler(ApiError)
def _handle_api_error(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def _handle_404(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def _handle_405(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"},
    }
    return jsonify(body), 404


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------
def round_half_up(amount_cents, pct_str):
    val = (Decimal(int(amount_cents)) * Decimal(pct_str)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(val)


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
VALID_ROLES = {"Manager", "Staff", "Member"}


def authctx(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in VALID_ROLES:
        err("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers")
    effective = set(allowed_roles)
    if "Staff" in effective:
        effective.add("Manager")
    if role not in effective:
        err("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")
    return uid, role


def owner_body(role, uid, membership_id):
    if role == "Member" and membership_id != uid:
        err("ERR_UNAUTHORIZED", 403, "Member may only act on its own resources")


def owner_path(role, uid, path_id):
    if role == "Member" and path_id != uid:
        err("ERR_UNAUTHORIZED", 403, "Member may only act on its own resources")


def owner_resource(role, uid, rec):
    if role == "Member" and rec.get("membership_id") != uid:
        err("ERR_UNAUTHORIZED", 403, "Member may only act on its own resources")


# ---------------------------------------------------------------------------
# Body / field validation helpers (raise ERR_VALIDATION 400)
# ---------------------------------------------------------------------------
def get_body():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        err("ERR_VALIDATION", 400, "Request body must be a JSON object")
    return b


def v_req_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v == "":
        err("ERR_VALIDATION", 400, "Field '%s' must be a non-empty string" % name)
    return v


def v_req_int(body, name, minv=None):
    v = body.get(name)
    if not isinstance(v, int) or isinstance(v, bool):
        err("ERR_VALIDATION", 400, "Field '%s' must be an integer" % name)
    if minv is not None and v < minv:
        err("ERR_VALIDATION", 400, "Field '%s' must be >= %d" % (name, minv))
    return v


def v_opt_int(body, name, minv=None, default=None):
    if name not in body or body.get(name) is None:
        return default
    return v_req_int(body, name, minv)


def v_req_enum(body, name, allowed):
    v = body.get(name)
    if not isinstance(v, str) or v not in allowed:
        err("ERR_VALIDATION", 400, "Field '%s' must be one of %s" % (name, sorted(allowed)))
    return v


def v_opt_enum(body, name, allowed, default=None):
    if name not in body or body.get(name) is None:
        return default
    return v_req_enum(body, name, allowed)


def v_req_dt(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v == "":
        err("ERR_VALIDATION", 400, "Field '%s' must be an ISO-8601 datetime string" % name)
    try:
        dt = parse_dt(v)
    except Exception:
        err("ERR_VALIDATION", 400, "Field '%s' is not a valid datetime" % name)
    return v, dt


def resolve(entity_type, id_val):
    """Return record if id present and exists; None if id absent/None; raise 404 if present but missing."""
    if id_val is None:
        return None
    rec = db[entity_type].get(id_val)
    if rec is None:
        err("ERR_NOT_FOUND", 404, "%s '%s' not found" % (entity_type, id_val))
    return rec


def must_get(entity_type, id_val):
    rec = db[entity_type].get(id_val)
    if rec is None:
        err("ERR_NOT_FOUND", 404, "%s '%s' not found" % (entity_type, id_val))
    return rec


# ---------------------------------------------------------------------------
# Record lifecycle
# ---------------------------------------------------------------------------
def new_record(entity_type, fields):
    now = fmt_ts(clock_now())
    rec = {
        "_type": entity_type,
        "_seq": next_seq(),
        "id": uuid.uuid4().hex,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    rec.update(fields)
    db[entity_type][rec["id"]] = rec
    return rec


def touch(rec):
    rec["version"] += 1
    rec["updated_at"] = fmt_ts(clock_now())


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def get_pagination():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            err("ERR_VALIDATION", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            err("ERR_VALIDATION", 400, "limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            err("ERR_VALIDATION", 400, "offset must be an integer")
        if offset < 0:
            err("ERR_VALIDATION", 400, "offset must be >= 0")
    return limit, offset


def paginate_and_respond(records, limit, offset):
    records = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(records)
    page = records[offset:offset + limit]
    items = [serialize(r) for r in page]
    return ok_array(items, limit, offset, total)


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
DISCOUNT_PCT = {"BRONZE": "0.00", "SILVER": "0.10", "GOLD": "0.20"}
CONDITION_ORD = {"MINT": 0, "GOOD": 1, "WORN": 2, "DAMAGED": 3, "LOST": 4}
TIME_BLOCK_MINUTES = 30
CANCEL_CUTOFF_MINUTES = 120
NO_SHOW_SUSPEND_THRESHOLD = 3
TABLE_TURNOVER_BUFFER_MINUTES = 15
POINTS_PER_CENT_DIVISOR = 100
TIER_SILVER_THRESHOLD = 500
TIER_GOLD_THRESHOLD = 2000
HOUSE_CUT_PCT = "0.20"
CONDITION_STEP_CENTS = 800
PER_HEAD_CATERING_CENTS = 1500
SERVICE_FEE_PCT = "0.18"
DEPOSIT_PCT = "0.25"


def compute_tier(lifetime_points):
    if lifetime_points >= TIER_GOLD_THRESHOLD:
        return "GOLD"
    if lifetime_points >= TIER_SILVER_THRESHOLD:
        return "SILVER"
    return "BRONZE"


def fnb_subtotal_for(reservation_id):
    return sum(
        o["total_cents"] for o in db["FnbOrder"].values()
        if o["reservation_id"] == reservation_id and o["status"] != "VOID"
    )


def compute_bill(res, end_instant):
    table = db["Table"][res["table_id"]]
    seated = parse_dt(res["seated_at"])
    minutes = int((end_instant - seated).total_seconds() // 60)
    if minutes < 0:
        minutes = 0
    blocks = math.ceil(minutes / TIME_BLOCK_MINUTES)
    raw = blocks * table["half_hour_rate_cents"]
    time_charge = min(raw, table["day_pass_cents"])
    cover = res["party_size"] * table["cover_fee_cents"]
    gaming = time_charge + cover
    tier = res.get("tier_at_seating") or "BRONZE"
    discount = round_half_up(gaming, DISCOUNT_PCT[tier])
    discounted_gaming = gaming - discount
    fnb = fnb_subtotal_for(res["id"])
    shortfall = max(0, table["min_spend_cents"] - fnb)
    bill_total = discounted_gaming + fnb + shortfall
    return {
        "time_charge_cents": time_charge,
        "cover_charge_cents": cover,
        "member_discount_cents": discount,
        "fnb_subtotal_cents": fnb,
        "minimum_shortfall_cents": shortfall,
        "bill_total_cents": bill_total,
    }


def compute_points_earned(reservation_id):
    total = 0
    for o in db["FnbOrder"].values():
        if o["reservation_id"] == reservation_id and o["status"] != "VOID":
            total += o["total_cents"] // POINTS_PER_CENT_DIVISOR
    return total


def prize_pool(count, entry_fee):
    gross = count * entry_fee
    house = round_half_up(gross, HOUSE_CUT_PCT)
    return gross - house, house


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def serialize(rec):
    out = {k: v for k, v in rec.items() if not k.startswith("_")}
    t = rec["_type"]
    if t == "Reservation":
        if rec["status"] == "SEATED":
            bill = compute_bill(rec, clock_now())
            out["provisional_bill_total_cents"] = bill["bill_total_cents"]
        else:
            out["provisional_bill_total_cents"] = 0
    elif t == "Tournament":
        regs = [r for r in db["Registration"].values() if r["tournament_id"] == rec["id"]]
        reg_count = sum(1 for r in regs if r["status"] in ("REGISTERED", "CHECKED_IN"))
        ci_count = sum(1 for r in regs if r["status"] == "CHECKED_IN")
        out["registered_count"] = reg_count
        out["checked_in_count"] = ci_count
        if rec["status"] == "OPEN":
            pool, _ = prize_pool(reg_count, rec["entry_fee_cents"])
            out["provisional_prize_pool_cents"] = pool
        else:
            out["provisional_prize_pool_cents"] = 0
    return out


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authctx(["Manager"])
    body = get_body()
    _, dt = v_req_dt(body, "to_iso8601")
    _clock["now"] = dt.astimezone(UTC)
    return ok_object({}, 200)


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------
TABLE_ZONES = {"MAIN", "QUIET", "PATIO"}
TABLE_STATUSES = {"AVAILABLE", "OUT_OF_SERVICE"}


@app.route("/tables", methods=["POST"])
def create_table():
    authctx(["Manager"])
    body = get_body()
    label = v_req_str(body, "label")
    seats = v_req_int(body, "seats", 1)
    hhr = v_req_int(body, "half_hour_rate_cents", 0)
    dp = v_req_int(body, "day_pass_cents", 0)
    cover = v_req_int(body, "cover_fee_cents", 0)
    minspend = v_req_int(body, "min_spend_cents", 0)
    zone = v_opt_enum(body, "zone", TABLE_ZONES, "MAIN")
    rec = new_record("Table", {
        "label": label, "zone": zone, "seats": seats,
        "half_hour_rate_cents": hhr, "day_pass_cents": dp,
        "cover_fee_cents": cover, "min_spend_cents": minspend,
        "status": "AVAILABLE",
    })
    return ok_object(serialize(rec), 201)


@app.route("/tables/<id>", methods=["GET"])
def get_table(id):
    authctx(["Manager", "Staff", "Member"])
    return ok_object(serialize(must_get("Table", id)), 200)


@app.route("/tables", methods=["GET"])
def list_tables():
    authctx(["Manager", "Staff", "Member"])
    limit, offset = get_pagination()
    zone = request.args.get("zone")
    status = request.args.get("status")
    recs = [r for r in db["Table"].values()
            if (zone is None or r["zone"] == zone) and (status is None or r["status"] == status)]
    return paginate_and_respond(recs, limit, offset)


@app.route("/tables/<id>", methods=["PATCH"])
def patch_table(id):
    authctx(["Manager"])
    rec = must_get("Table", id)
    body = get_body()
    if "status" in body and body["status"] is not None:
        rec["status"] = v_req_enum(body, "status", TABLE_STATUSES)
    for f in ("half_hour_rate_cents", "cover_fee_cents", "min_spend_cents", "day_pass_cents"):
        if f in body and body[f] is not None:
            rec[f] = v_req_int(body, f, 0)
    touch(rec)
    return ok_object(serialize(rec), 200)


# ---------------------------------------------------------------------------
# Memberships
# ---------------------------------------------------------------------------
MEMBERSHIP_STATUSES = {"ACTIVE", "SUSPENDED", "CANCELLED"}


@app.route("/memberships", methods=["POST"])
def create_membership():
    authctx(["Manager", "Staff"])
    body = get_body()
    email = v_req_str(body, "email")
    full_name = v_req_str(body, "full_name")
    for m in db["Membership"].values():
        if m["email"] == email:
            err("ERR_VALIDATION", 400, "email must be unique")
    rec = new_record("Membership", {
        "email": email, "full_name": full_name, "tier": "BRONZE",
        "points_balance": 0, "lifetime_points": 0, "no_show_strikes": 0,
        "status": "ACTIVE", "last_redemption_id": None,
        "last_redemption_points": 0, "last_redemption_status": "NONE",
    })
    return ok_object(serialize(rec), 201)


@app.route("/memberships/<id>", methods=["GET"])
def get_membership(id):
    authctx(["Manager", "Staff", "Member"])
    return ok_object(serialize(must_get("Membership", id)), 200)


@app.route("/memberships", methods=["GET"])
def list_memberships():
    authctx(["Manager", "Staff"])
    limit, offset = get_pagination()
    tier = request.args.get("tier")
    status = request.args.get("status")
    recs = [r for r in db["Membership"].values()
            if (tier is None or r["tier"] == tier) and (status is None or r["status"] == status)]
    return paginate_and_respond(recs, limit, offset)


@app.route("/memberships/<id>", methods=["PATCH"])
def patch_membership(id):
    authctx(["Manager"])
    rec = must_get("Membership", id)
    body = get_body()
    new_status = v_req_enum(body, "status", MEMBERSHIP_STATUSES)
    cur = rec["status"]
    if new_status == "SUSPENDED":
        if cur != "ACTIVE":
            err("ERR_INVALID_STATE", 409, "Only ACTIVE memberships can be suspended")
        rec["status"] = "SUSPENDED"
    elif new_status == "ACTIVE":
        if cur != "SUSPENDED":
            err("ERR_INVALID_STATE", 409, "Only SUSPENDED memberships can be reinstated")
        rec["status"] = "ACTIVE"
        rec["no_show_strikes"] = 0
    elif new_status == "CANCELLED":
        if cur not in ("ACTIVE", "SUSPENDED"):
            err("ERR_INVALID_STATE", 409, "Membership cannot be cancelled from its current state")
        rec["status"] = "CANCELLED"
    touch(rec)
    return ok_object(serialize(rec), 200)


@app.route("/memberships/<id>/loyalty-adjustments", methods=["POST"])
def loyalty_adjustment(id):
    authctx(["Manager"])
    rec = must_get("Membership", id)
    body = get_body()
    delta = v_req_int(body, "points_delta")
    v_req_str(body, "reason")
    if delta > 0:
        rec["points_balance"] += delta
        rec["lifetime_points"] += delta
        rec["tier"] = compute_tier(rec["lifetime_points"])
    elif delta < 0:
        rec["points_balance"] = max(0, rec["points_balance"] + delta)
    touch(rec)
    return ok_object(serialize(rec), 200)


@app.route("/memberships/<id>/redemptions", methods=["POST"])
def redemption(id):
    uid, role = authctx(["Member", "Staff"])
    owner_path(role, uid, id)
    rec = must_get("Membership", id)
    body = get_body()
    points_cost = v_req_int(body, "points_cost", 0)
    v_req_str(body, "reward_description")
    if rec["status"] == "SUSPENDED":
        err("ERR_MEMBERSHIP_SUSPENDED", 409, "Suspended member cannot redeem points")
    if points_cost > rec["points_balance"]:
        err("ERR_INSUFFICIENT_POINTS", 409, "points_cost exceeds points_balance")
    rec["points_balance"] -= points_cost
    rec["last_redemption_id"] = uuid.uuid4().hex
    rec["last_redemption_points"] = points_cost
    rec["last_redemption_status"] = "APPLIED"
    touch(rec)
    return ok_object(serialize(rec), 200)


@app.route("/memberships/<id>/redemptions/<redemption_id>/reverse", methods=["POST"])
def reverse_redemption(id, redemption_id):
    authctx(["Manager", "Staff"])
    rec = must_get("Membership", id)
    if (rec["last_redemption_id"] is None
            or rec["last_redemption_id"] != redemption_id
            or rec["last_redemption_status"] != "APPLIED"):
        err("ERR_REDEMPTION_ALREADY_REVERSED", 409,
            "Redemption is not the most recent APPLIED redemption")
    rec["points_balance"] += rec["last_redemption_points"]
    rec["last_redemption_status"] = "REVERSED"
    touch(rec)
    return ok_object(serialize(rec), 200)


# ---------------------------------------------------------------------------
# Reservations
# ---------------------------------------------------------------------------
def table_time_conflict(table_id, start_dt, end_dt, exclude_id=None):
    buf = TABLE_TURNOVER_BUFFER_MINUTES * 60
    for r in db["Reservation"].values():
        if r["table_id"] != table_id:
            continue
        if exclude_id is not None and r["id"] == exclude_id:
            continue
        if r["status"] not in ("BOOKED", "SEATED"):
            continue
        ex_start = parse_dt(r["start_at"])
        ex_end = parse_dt(r["end_at"])
        # conflict iff requested.start < existing.end + buf AND requested.end + buf > existing.start
        if start_dt < ex_end + _sec(buf) and end_dt + _sec(buf) > ex_start:
            return True
    return False


def _sec(seconds):
    from datetime import timedelta
    return timedelta(seconds=seconds)


@app.route("/reservations", methods=["POST"])
def create_reservation():
    uid, role = authctx(["Manager", "Staff", "Member"])
    body = get_body()
    membership_id = body.get("membership_id")
    owner_body(role, uid, membership_id)
    # existence
    table = resolve("Table", body.get("table_id"))
    resolve("Membership", membership_id)
    # validation
    table_id = v_req_str(body, "table_id")
    party_size = v_req_int(body, "party_size", 1)
    start_s, start_dt = v_req_dt(body, "start_at")
    end_s, end_dt = v_req_dt(body, "end_at")
    if end_dt <= start_dt:
        err("ERR_VALIDATION", 400, "end_at must be after start_at")
    deposit = v_opt_int(body, "deposit_cents", 0, 0)
    if membership_id is not None and not isinstance(membership_id, str):
        err("ERR_VALIDATION", 400, "membership_id must be a string")
    table = db["Table"][table_id]
    # business checks
    if party_size > table["seats"]:
        err("ERR_TABLE_CAPACITY_EXCEEDED", 409, "party_size exceeds table seats")
    if table["status"] == "OUT_OF_SERVICE":
        err("ERR_TABLE_OUT_OF_SERVICE", 409, "table is out of service")
    if table_time_conflict(table_id, start_dt, end_dt):
        err("ERR_TABLE_TIME_CONFLICT", 409, "requested window conflicts with an existing reservation")
    rec = new_record("Reservation", {
        "table_id": table_id, "membership_id": membership_id, "party_size": party_size,
        "start_at": start_s, "end_at": end_s, "deposit_cents": deposit,
        "deposit_forfeited": False, "status": "BOOKED",
        "seated_at": None, "closed_at": None, "tier_at_seating": None,
        "time_charge_cents": 0, "cover_charge_cents": 0, "member_discount_cents": 0,
        "fnb_subtotal_cents": 0, "minimum_shortfall_cents": 0, "bill_total_cents": 0,
        "points_earned": 0,
    })
    return ok_object(serialize(rec), 201)


@app.route("/reservations/<id>", methods=["GET"])
def get_reservation(id):
    authctx(["Manager", "Staff", "Member"])
    return ok_object(serialize(must_get("Reservation", id)), 200)


@app.route("/reservations", methods=["GET"])
def list_reservations():
    authctx(["Manager", "Staff", "Member"])
    limit, offset = get_pagination()
    table_id = request.args.get("table_id")
    membership_id = request.args.get("membership_id")
    status = request.args.get("status")
    recs = [r for r in db["Reservation"].values()
            if (table_id is None or r["table_id"] == table_id)
            and (membership_id is None or r["membership_id"] == membership_id)
            and (status is None or r["status"] == status)]
    return paginate_and_respond(recs, limit, offset)


@app.route("/reservations/<id>/seat", methods=["POST"])
def seat_reservation(id):
    authctx(["Manager", "Staff"])
    rec = must_get("Reservation", id)
    body = get_body()
    if rec["status"] != "BOOKED":
        err("ERR_INVALID_STATE", 409, "Reservation is not BOOKED")
    party_size = rec["party_size"]
    if "party_size" in body and body["party_size"] is not None:
        party_size = v_req_int(body, "party_size", 1)
    table = db["Table"][rec["table_id"]]
    if party_size > table["seats"]:
        err("ERR_TABLE_CAPACITY_EXCEEDED", 409, "party_size exceeds table seats")
    if table["status"] == "OUT_OF_SERVICE":
        err("ERR_TABLE_OUT_OF_SERVICE", 409, "table is out of service")
    rec["party_size"] = party_size
    rec["status"] = "SEATED"
    rec["seated_at"] = fmt_ts(clock_now())
    if rec["membership_id"] is not None:
        m = db["Membership"].get(rec["membership_id"])
        rec["tier_at_seating"] = m["tier"] if m else None
    else:
        rec["tier_at_seating"] = None
    touch(rec)
    return ok_object(serialize(rec), 200)


@app.route("/reservations/<id>/close", methods=["POST"])
def close_reservation(id):
    authctx(["Manager", "Staff"])
    rec = must_get("Reservation", id)
    if rec["status"] != "SEATED":
        err("ERR_INVALID_STATE", 409, "Reservation is not SEATED")
    for c in db["Checkout"].values():
        if c["reservation_id"] == id and c["status"] == "ACTIVE":
            err("ERR_SESSION_HAS_OPEN_CHECKOUTS", 409, "Session has open checkouts")
    closed_at = clock_now()
    rec["closed_at"] = fmt_ts(closed_at)
    bill = compute_bill(rec, closed_at)
    rec.update(bill)
    points = compute_points_earned(id)
    rec["points_earned"] = points
    rec["status"] = "COMPLETED"
    touch(rec)
    if rec["membership_id"] is not None:
        m = db["Membership"].get(rec["membership_id"])
        if m is not None:
            m["lifetime_points"] += points
            m["points_balance"] += points
            m["tier"] = compute_tier(m["lifetime_points"])
            touch(m)
    return ok_object(serialize(rec), 200)


@app.route("/reservations/<id>/cancel", methods=["POST"])
def cancel_reservation(id):
    uid, role = authctx(["Manager", "Staff", "Member"])
    rec = must_get("Reservation", id)
    owner_resource(role, uid, rec)
    if rec["status"] != "BOOKED":
        err("ERR_INVALID_STATE", 409, "Reservation is not BOOKED")
    start_dt = parse_dt(rec["start_at"])
    if clock_now() > start_dt - _sec(CANCEL_CUTOFF_MINUTES * 60):
        err("ERR_CANCEL_TOO_LATE", 409, "Cancellation past the cutoff")
    rec["status"] = "CANCELLED"
    touch(rec)
    return ok_object(serialize(rec), 200)


@app.route("/reservations/<id>/no-show", methods=["POST"])
def no_show_reservation(id):
    authctx(["Manager", "Staff"])
    rec = must_get("Reservation", id)
    if rec["status"] != "BOOKED":
        err("ERR_INVALID_STATE", 409, "Reservation is not BOOKED")
    start_dt = parse_dt(rec["start_at"])
    if clock_now() < start_dt:
        err("ERR_INVALID_STATE", 409, "No-show cannot be marked before start_at")
    rec["status"] = "NO_SHOW"
    rec["deposit_forfeited"] = True
    touch(rec)
    if rec["membership_id"] is not None:
        m = db["Membership"].get(rec["membership_id"])
        if m is not None:
            m["no_show_strikes"] += 1
            if m["no_show_strikes"] >= NO_SHOW_SUSPEND_THRESHOLD and m["status"] == "ACTIVE":
                m["status"] = "SUSPENDED"
            touch(m)
    return ok_object(serialize(rec), 200)


# ---------------------------------------------------------------------------
# F&B orders
# ---------------------------------------------------------------------------
@app.route("/fnb-orders", methods=["POST"])
def create_fnb():
    authctx(["Manager", "Staff"])
    body = get_body()
    resolve("Reservation", body.get("reservation_id"))
    reservation_id = v_req_str(body, "reservation_id")
    description = v_req_str(body, "description")
    total = v_req_int(body, "total_cents", 0)
    rec = new_record("FnbOrder", {
        "reservation_id": reservation_id, "description": description,
        "total_cents": total, "status": "OPEN",
    })
    return ok_object(serialize(rec), 201)


@app.route("/fnb-orders/<id>", methods=["GET"])
def get_fnb(id):
    authctx(["Manager", "Staff"])
    return ok_object(serialize(must_get("FnbOrder", id)), 200)


@app.route("/fnb-orders", methods=["GET"])
def list_fnb():
    authctx(["Manager", "Staff"])
    limit, offset = get_pagination()
    reservation_id = request.args.get("reservation_id")
    status = request.args.get("status")
    recs = [r for r in db["FnbOrder"].values()
            if (reservation_id is None or r["reservation_id"] == reservation_id)
            and (status is None or r["status"] == status)]
    return paginate_and_respond(recs, limit, offset)


@app.route("/fnb-orders/<id>/void", methods=["POST"])
def void_fnb(id):
    authctx(["Manager", "Staff"])
    rec = must_get("FnbOrder", id)
    if rec["status"] != "OPEN":
        err("ERR_INVALID_STATE", 409, "F&B order is not OPEN")
    rec["status"] = "VOID"
    touch(rec)
    return ok_object(serialize(rec), 200)


# ---------------------------------------------------------------------------
# Game copies
# ---------------------------------------------------------------------------
GAME_CONDITIONS = {"MINT", "GOOD", "WORN", "DAMAGED", "LOST"}
GAME_STATUSES = {"AVAILABLE", "CHECKED_OUT", "RETIRED"}
LENDABLE_CONDITIONS = {"MINT", "GOOD", "WORN"}


@app.route("/game-copies", methods=["POST"])
def create_game_copy():
    authctx(["Manager"])
    body = get_body()
    title = v_req_str(body, "title")
    barcode = v_req_str(body, "barcode")
    rv = v_req_int(body, "replacement_value_cents", 0)
    condition = v_opt_enum(body, "condition", GAME_CONDITIONS, "GOOD")
    for g in db["GameCopy"].values():
        if g["barcode"] == barcode:
            err("ERR_VALIDATION", 400, "barcode must be unique")
    rec = new_record("GameCopy", {
        "title": title, "barcode": barcode, "replacement_value_cents": rv,
        "condition": condition, "status": "AVAILABLE",
    })
    return ok_object(serialize(rec), 201)


@app.route("/game-copies/<id>", methods=["GET"])
def get_game_copy(id):
    authctx(["Manager", "Staff", "Member"])
    return ok_object(serialize(must_get("GameCopy", id)), 200)


@app.route("/game-copies", methods=["GET"])
def list_game_copies():
    authctx(["Manager", "Staff", "Member"])
    limit, offset = get_pagination()
    title = request.args.get("title")
    status = request.args.get("status")
    condition = request.args.get("condition")
    recs = [r for r in db["GameCopy"].values()
            if (title is None or r["title"] == title)
            and (status is None or r["status"] == status)
            and (condition is None or r["condition"] == condition)]
    return paginate_and_respond(recs, limit, offset)


@app.route("/game-copies/<id>", methods=["PATCH"])
def patch_game_copy(id):
    authctx(["Manager"])
    rec = must_get("GameCopy", id)
    body = get_body()
    new_condition = None
    new_status = None
    if "condition" in body and body["condition"] is not None:
        new_condition = v_req_enum(body, "condition", GAME_CONDITIONS)
    if "status" in body and body["status"] is not None:
        new_status = v_req_enum(body, "status", GAME_STATUSES)
    if new_status == "RETIRED" and rec["status"] == "RETIRED":
        err("ERR_INVALID_STATE", 409, "Copy is already RETIRED")
    if new_condition is not None:
        rec["condition"] = new_condition
    if new_status is not None:
        rec["status"] = new_status
    touch(rec)
    return ok_object(serialize(rec), 200)


# ---------------------------------------------------------------------------
# Checkouts
# ---------------------------------------------------------------------------
RETURN_CONDITIONS = {"MINT", "GOOD", "WORN", "DAMAGED"}


@app.route("/checkouts", methods=["POST"])
def create_checkout():
    authctx(["Manager", "Staff"])
    body = get_body()
    game = resolve("GameCopy", body.get("game_copy_id"))
    res = resolve("Reservation", body.get("reservation_id"))
    game_copy_id = v_req_str(body, "game_copy_id")
    reservation_id = v_req_str(body, "reservation_id")
    game = db["GameCopy"][game_copy_id]
    res = db["Reservation"][reservation_id]
    if res["status"] != "SEATED":
        err("ERR_INVALID_STATE", 409, "Reservation is not SEATED")
    if game["status"] != "AVAILABLE" or game["condition"] not in LENDABLE_CONDITIONS:
        err("ERR_GAME_NOT_AVAILABLE", 409, "Game copy is not lendable")
    game["status"] = "CHECKED_OUT"
    touch(game)
    rec = new_record("Checkout", {
        "game_copy_id": game_copy_id, "reservation_id": reservation_id,
        "checkout_condition": game["condition"], "return_condition": None,
        "condition_fee_cents": 0, "status": "ACTIVE",
        "checked_out_at": fmt_ts(clock_now()), "returned_at": None,
    })
    return ok_object(serialize(rec), 201)


@app.route("/checkouts/<id>", methods=["GET"])
def get_checkout(id):
    authctx(["Manager", "Staff"])
    return ok_object(serialize(must_get("Checkout", id)), 200)


@app.route("/checkouts", methods=["GET"])
def list_checkouts():
    authctx(["Manager", "Staff"])
    limit, offset = get_pagination()
    game_copy_id = request.args.get("game_copy_id")
    reservation_id = request.args.get("reservation_id")
    status = request.args.get("status")
    recs = [r for r in db["Checkout"].values()
            if (game_copy_id is None or r["game_copy_id"] == game_copy_id)
            and (reservation_id is None or r["reservation_id"] == reservation_id)
            and (status is None or r["status"] == status)]
    return paginate_and_respond(recs, limit, offset)


@app.route("/checkouts/<id>/return", methods=["POST"])
def return_checkout(id):
    authctx(["Manager", "Staff"])
    rec = must_get("Checkout", id)
    body = get_body()
    if rec["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Checkout is not ACTIVE")
    return_condition = v_req_enum(body, "return_condition", RETURN_CONDITIONS)
    ord_ret = CONDITION_ORD[return_condition]
    ord_base = CONDITION_ORD[rec["checkout_condition"]]
    if ord_ret <= ord_base:
        fee = 0
    else:
        fee = (ord_ret - ord_base) * CONDITION_STEP_CENTS
    rec["return_condition"] = return_condition
    rec["condition_fee_cents"] = fee
    rec["returned_at"] = fmt_ts(clock_now())
    rec["status"] = "RETURNED"
    touch(rec)
    game = db["GameCopy"].get(rec["game_copy_id"])
    if game is not None:
        game["status"] = "AVAILABLE"
        game["condition"] = return_condition
        touch(game)
    return ok_object(serialize(rec), 200)


@app.route("/checkouts/<id>/report-lost", methods=["POST"])
def report_lost(id):
    authctx(["Manager", "Staff"])
    rec = must_get("Checkout", id)
    if rec["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Checkout is not ACTIVE")
    game = db["GameCopy"].get(rec["game_copy_id"])
    rec["condition_fee_cents"] = game["replacement_value_cents"] if game else 0
    rec["status"] = "LOST"
    touch(rec)
    if game is not None:
        game["condition"] = "LOST"
        game["status"] = "RETIRED"
        touch(game)
    return ok_object(serialize(rec), 200)


# ---------------------------------------------------------------------------
# Tournaments
# ---------------------------------------------------------------------------
TOURNAMENT_FORMATS = {"SINGLE_ELIM", "LEAGUE", "CASUAL"}


@app.route("/tournaments", methods=["POST"])
def create_tournament():
    authctx(["Manager"])
    body = get_body()
    name = v_req_str(body, "name")
    game_title = v_req_str(body, "game_title")
    fmt = v_req_enum(body, "format", TOURNAMENT_FORMATS)
    capacity = v_req_int(body, "capacity", 1)
    entry_fee = v_req_int(body, "entry_fee_cents", 0)
    start_s, _ = v_req_dt(body, "start_at")
    rec = new_record("Tournament", {
        "name": name, "game_title": game_title, "format": fmt,
        "capacity": capacity, "entry_fee_cents": entry_fee, "start_at": start_s,
        "status": "SCHEDULED", "house_cut_cents": 0, "prize_pool_cents": 0,
    })
    return ok_object(serialize(rec), 201)


@app.route("/tournaments/<id>", methods=["GET"])
def get_tournament(id):
    authctx(["Manager", "Staff", "Member"])
    return ok_object(serialize(must_get("Tournament", id)), 200)


@app.route("/tournaments", methods=["GET"])
def list_tournaments():
    authctx(["Manager", "Staff", "Member"])
    limit, offset = get_pagination()
    status = request.args.get("status")
    fmt = request.args.get("format")
    recs = [r for r in db["Tournament"].values()
            if (status is None or r["status"] == status)
            and (fmt is None or r["format"] == fmt)]
    return paginate_and_respond(recs, limit, offset)


@app.route("/tournaments/<id>/open", methods=["POST"])
def open_tournament(id):
    authctx(["Manager"])
    rec = must_get("Tournament", id)
    if rec["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", 409, "Tournament is not SCHEDULED")
    rec["status"] = "OPEN"
    touch(rec)
    return ok_object(serialize(rec), 200)


@app.route("/tournaments/<id>/start", methods=["POST"])
def start_tournament(id):
    authctx(["Manager"])
    rec = must_get("Tournament", id)
    if rec["status"] != "OPEN":
        err("ERR_INVALID_STATE", 409, "Tournament is not OPEN")
    ci_count = sum(1 for r in db["Registration"].values()
                   if r["tournament_id"] == id and r["status"] == "CHECKED_IN")
    pool, house = prize_pool(ci_count, rec["entry_fee_cents"])
    rec["prize_pool_cents"] = pool
    rec["house_cut_cents"] = house
    rec["status"] = "RUNNING"
    touch(rec)
    return ok_object(serialize(rec), 200)


@app.route("/tournaments/<id>/cancel", methods=["POST"])
def cancel_tournament(id):
    authctx(["Manager"])
    rec = must_get("Tournament", id)
    if rec["status"] not in ("SCHEDULED", "OPEN"):
        err("ERR_INVALID_STATE", 409, "Tournament cannot be cancelled from its current state")
    for r in db["Registration"].values():
        if r["tournament_id"] == id and r["status"] in ("REGISTERED", "CHECKED_IN"):
            r["status"] = "REFUNDED"
            r["refunded_cents"] = r["fee_paid_cents"]
            touch(r)
    rec["status"] = "CANCELLED"
    touch(rec)
    return ok_object(serialize(rec), 200)


# ---------------------------------------------------------------------------
# Registrations
# ---------------------------------------------------------------------------
@app.route("/registrations", methods=["POST"])
def create_registration():
    uid, role = authctx(["Manager", "Staff", "Member"])
    body = get_body()
    membership_id = body.get("membership_id")
    owner_body(role, uid, membership_id)
    tour = resolve("Tournament", body.get("tournament_id"))
    member = resolve("Membership", membership_id)
    tournament_id = v_req_str(body, "tournament_id")
    membership_id = v_req_str(body, "membership_id")
    tour = db["Tournament"][tournament_id]
    member = db["Membership"][membership_id]
    # business checks, PRD §3.6 order: suspended -> not_open -> full -> duplicate
    if member["status"] == "SUSPENDED":
        err("ERR_MEMBERSHIP_SUSPENDED", 409, "Suspended member cannot register")
    if tour["status"] != "OPEN":
        err("ERR_TOURNAMENT_NOT_OPEN", 409, "Tournament is not OPEN")
    active = [r for r in db["Registration"].values()
              if r["tournament_id"] == tournament_id and r["status"] in ("REGISTERED", "CHECKED_IN")]
    if len(active) >= tour["capacity"]:
        err("ERR_TOURNAMENT_FULL", 409, "Tournament is full")
    for r in active:
        if r["membership_id"] == membership_id:
            err("ERR_DUPLICATE_REGISTRATION", 409, "Member already registered")
    rec = new_record("Registration", {
        "tournament_id": tournament_id, "membership_id": membership_id,
        "status": "REGISTERED", "fee_paid_cents": tour["entry_fee_cents"],
        "refunded_cents": 0,
    })
    return ok_object(serialize(rec), 201)


@app.route("/registrations/<id>", methods=["GET"])
def get_registration(id):
    authctx(["Manager", "Staff", "Member"])
    return ok_object(serialize(must_get("Registration", id)), 200)


@app.route("/registrations", methods=["GET"])
def list_registrations():
    authctx(["Manager", "Staff", "Member"])
    limit, offset = get_pagination()
    tournament_id = request.args.get("tournament_id")
    membership_id = request.args.get("membership_id")
    status = request.args.get("status")
    recs = [r for r in db["Registration"].values()
            if (tournament_id is None or r["tournament_id"] == tournament_id)
            and (membership_id is None or r["membership_id"] == membership_id)
            and (status is None or r["status"] == status)]
    return paginate_and_respond(recs, limit, offset)


@app.route("/registrations/<id>/check-in", methods=["POST"])
def checkin_registration(id):
    authctx(["Manager", "Staff"])
    rec = must_get("Registration", id)
    if rec["status"] != "REGISTERED":
        err("ERR_INVALID_STATE", 409, "Registration is not REGISTERED")
    tour = db["Tournament"].get(rec["tournament_id"])
    if tour is None or tour["status"] != "OPEN":
        err("ERR_INVALID_STATE", 409, "Tournament is not OPEN")
    rec["status"] = "CHECKED_IN"
    touch(rec)
    return ok_object(serialize(rec), 200)


@app.route("/registrations/<id>/withdraw", methods=["POST"])
def withdraw_registration(id):
    uid, role = authctx(["Manager", "Staff", "Member"])
    rec = must_get("Registration", id)
    owner_resource(role, uid, rec)
    if rec["status"] != "REGISTERED":
        err("ERR_INVALID_STATE", 409, "Registration is not REGISTERED")
    tour = db["Tournament"].get(rec["tournament_id"])
    if tour is None or tour["status"] not in ("OPEN", "SCHEDULED"):
        err("ERR_INVALID_STATE", 409, "Tournament does not allow withdrawal")
    rec["status"] = "WITHDRAWN"
    rec["refunded_cents"] = rec["fee_paid_cents"]
    touch(rec)
    return ok_object(serialize(rec), 200)


# ---------------------------------------------------------------------------
# Rooms
# ---------------------------------------------------------------------------
ROOM_STATUSES = {"AVAILABLE", "OUT_OF_SERVICE"}


@app.route("/rooms", methods=["POST"])
def create_room():
    authctx(["Manager"])
    body = get_body()
    name = v_req_str(body, "name")
    capacity = v_req_int(body, "capacity", 1)
    hourly = v_req_int(body, "hourly_rate_cents", 0)
    rec = new_record("Room", {
        "name": name, "capacity": capacity, "hourly_rate_cents": hourly,
        "status": "AVAILABLE",
    })
    return ok_object(serialize(rec), 201)


@app.route("/rooms/<id>", methods=["GET"])
def get_room(id):
    authctx(["Manager", "Staff", "Member"])
    return ok_object(serialize(must_get("Room", id)), 200)


@app.route("/rooms", methods=["GET"])
def list_rooms():
    authctx(["Manager", "Staff", "Member"])
    limit, offset = get_pagination()
    status = request.args.get("status")
    recs = [r for r in db["Room"].values() if (status is None or r["status"] == status)]
    return paginate_and_respond(recs, limit, offset)


@app.route("/rooms/<id>", methods=["PATCH"])
def patch_room(id):
    authctx(["Manager"])
    rec = must_get("Room", id)
    body = get_body()
    if "status" in body and body["status"] is not None:
        rec["status"] = v_req_enum(body, "status", ROOM_STATUSES)
    if "hourly_rate_cents" in body and body["hourly_rate_cents"] is not None:
        rec["hourly_rate_cents"] = v_req_int(body, "hourly_rate_cents", 0)
    if "capacity" in body and body["capacity"] is not None:
        rec["capacity"] = v_req_int(body, "capacity", 1)
    touch(rec)
    return ok_object(serialize(rec), 200)


# ---------------------------------------------------------------------------
# Private bookings
# ---------------------------------------------------------------------------
def room_time_conflict(room_id, start_dt, end_dt):
    for b in db["PrivateBooking"].values():
        if b["room_id"] != room_id:
            continue
        if b["status"] != "CONFIRMED":
            continue
        ex_start = parse_dt(b["start_at"])
        ex_end = parse_dt(b["end_at"])
        if start_dt < ex_end and end_dt > ex_start:
            return True
    return False


@app.route("/private-bookings", methods=["POST"])
def create_private_booking():
    authctx(["Manager", "Staff"])
    body = get_body()
    room = resolve("Room", body.get("room_id"))
    room_id = v_req_str(body, "room_id")
    start_s, start_dt = v_req_dt(body, "start_at")
    end_s, end_dt = v_req_dt(body, "end_at")
    if end_dt <= start_dt:
        err("ERR_VALIDATION", 400, "end_at must be after start_at")
    headcount = v_req_int(body, "headcount", 1)
    expected_version = v_req_int(body, "expected_room_version")
    room = db["Room"][room_id]
    # business checks per priority: conflict(15) -> unavailable(16) -> OCC(19)
    if room_time_conflict(room_id, start_dt, end_dt):
        err("ERR_ROOM_TIME_CONFLICT", 409, "requested window overlaps a confirmed booking")
    if room["status"] == "OUT_OF_SERVICE":
        err("ERR_ROOM_UNAVAILABLE", 409, "room is out of service")
    if expected_version != room["version"]:
        err("ERR_STALE_VERSION", 412, "expected_room_version does not match room version")
    # supersede prior HELD bookings and bump room version
    for b in db["PrivateBooking"].values():
        if b["room_id"] == room_id and b["status"] == "HELD":
            b["status"] = "SUPERSEDED"
            touch(b)
    room["version"] += 1
    room["updated_at"] = fmt_ts(clock_now())
    # quote
    minutes = int((end_dt - start_dt).total_seconds() // 60)
    room_hours = math.ceil(minutes / 60)
    room_charge = room_hours * room["hourly_rate_cents"]
    catering = headcount * PER_HEAD_CATERING_CENTS
    service_fee = round_half_up(room_charge + catering, SERVICE_FEE_PCT)
    quoted = room_charge + catering + service_fee
    deposit = round_half_up(quoted, DEPOSIT_PCT)
    rec = new_record("PrivateBooking", {
        "room_id": room_id, "start_at": start_s, "end_at": end_s,
        "headcount": headcount, "status": "HELD",
        "quoted_total_cents": quoted, "deposit_cents": deposit,
    })
    return ok_object(serialize(rec), 201)


@app.route("/private-bookings/<id>", methods=["GET"])
def get_private_booking(id):
    authctx(["Manager", "Staff", "Member"])
    return ok_object(serialize(must_get("PrivateBooking", id)), 200)


@app.route("/private-bookings", methods=["GET"])
def list_private_bookings():
    authctx(["Manager", "Staff", "Member"])
    limit, offset = get_pagination()
    room_id = request.args.get("room_id")
    status = request.args.get("status")
    recs = [r for r in db["PrivateBooking"].values()
            if (room_id is None or r["room_id"] == room_id)
            and (status is None or r["status"] == status)]
    return paginate_and_respond(recs, limit, offset)


@app.route("/private-bookings/<id>/confirm", methods=["POST"])
def confirm_private_booking(id):
    authctx(["Manager", "Staff"])
    rec = must_get("PrivateBooking", id)
    if rec["status"] != "HELD":
        err("ERR_INVALID_STATE", 409, "Booking is not HELD")
    room = db["Room"].get(rec["room_id"])
    if room is not None and rec["headcount"] > room["capacity"]:
        err("ERR_INVALID_STATE", 409, "headcount exceeds room capacity")
    rec["status"] = "CONFIRMED"
    touch(rec)
    return ok_object(serialize(rec), 200)


@app.route("/private-bookings/<id>/cancel", methods=["POST"])
def cancel_private_booking(id):
    authctx(["Manager", "Staff"])
    rec = must_get("PrivateBooking", id)
    if rec["status"] not in ("HELD", "CONFIRMED"):
        err("ERR_INVALID_STATE", 409, "Booking cannot be cancelled from its current state")
    rec["status"] = "CANCELLED"
    touch(rec)
    return ok_object(serialize(rec), 200)


# ---------------------------------------------------------------------------
# Retail orders
# ---------------------------------------------------------------------------
FULFILLMENT_TYPES = {"IN_STOCK", "PREORDER"}


@app.route("/retail-orders", methods=["POST"])
def create_retail_order():
    uid, role = authctx(["Manager", "Staff", "Member"])
    body = get_body()
    membership_id = body.get("membership_id")
    owner_body(role, uid, membership_id)
    resolve("Membership", membership_id)
    product_title = v_req_str(body, "product_title")
    fulfillment_type = v_req_enum(body, "fulfillment_type", FULFILLMENT_TYPES)
    quantity = v_req_int(body, "quantity", 1)
    unit_price = v_req_int(body, "unit_price_cents", 0)
    if membership_id is not None and not isinstance(membership_id, str):
        err("ERR_VALIDATION", 400, "membership_id must be a string")
    total = quantity * unit_price
    status = "READY" if fulfillment_type == "IN_STOCK" else "AWAITING_STOCK"
    rec = new_record("RetailOrder", {
        "membership_id": membership_id, "product_title": product_title,
        "fulfillment_type": fulfillment_type, "quantity": quantity,
        "unit_price_cents": unit_price, "total_cents": total, "status": status,
    })
    return ok_object(serialize(rec), 201)


@app.route("/retail-orders/<id>", methods=["GET"])
def get_retail_order(id):
    authctx(["Manager", "Staff", "Member"])
    return ok_object(serialize(must_get("RetailOrder", id)), 200)


@app.route("/retail-orders", methods=["GET"])
def list_retail_orders():
    authctx(["Manager", "Staff", "Member"])
    limit, offset = get_pagination()
    membership_id = request.args.get("membership_id")
    status = request.args.get("status")
    fulfillment_type = request.args.get("fulfillment_type")
    recs = [r for r in db["RetailOrder"].values()
            if (membership_id is None or r["membership_id"] == membership_id)
            and (status is None or r["status"] == status)
            and (fulfillment_type is None or r["fulfillment_type"] == fulfillment_type)]
    return paginate_and_respond(recs, limit, offset)


@app.route("/retail-orders/<id>/fulfill", methods=["POST"])
def fulfill_retail_order(id):
    authctx(["Manager", "Staff"])
    rec = must_get("RetailOrder", id)
    if rec["status"] not in ("READY", "AWAITING_STOCK"):
        err("ERR_INVALID_STATE", 409, "Order cannot be fulfilled from its current state")
    rec["status"] = "FULFILLED"
    touch(rec)
    return ok_object(serialize(rec), 200)


@app.route("/retail-orders/<id>/cancel", methods=["POST"])
def cancel_retail_order(id):
    uid, role = authctx(["Manager", "Staff", "Member"])
    rec = must_get("RetailOrder", id)
    owner_resource(role, uid, rec)
    if rec["status"] not in ("READY", "AWAITING_STOCK"):
        err("ERR_INVALID_STATE", 409, "Order cannot be cancelled from its current state")
    rec["status"] = "CANCELLED"
    touch(rec)
    return ok_object(serialize(rec), 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
