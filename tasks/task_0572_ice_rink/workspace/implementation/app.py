"""Ice Rink & Learn-to-Skate API — in-memory Flask implementation.

Storage is in-memory only; every byte of state is wiped when the process is
restarted (start.sh re-invocation). No seeding of any entity at startup.
"""
import os
import calendar
import random
import string
import uuid
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# --------------------------------------------------------------------------
# In-memory stores (keyed by id). Empty on every boot.
# --------------------------------------------------------------------------
rinks = {}
skaters = {}
ice_slots = {}
admissions = {}
classes = {}
enrollments = {}
subscriptions = {}
leagues = {}
registrations = {}
lockers = {}
bookings = {}
sharpenings = {}

# Logical clock (server-controlled). Default at boot per PRD §2.4.
CLOCK = {"now": datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)}

_SEQ = {"n": 0}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


# --------------------------------------------------------------------------
# Roles / enums
# --------------------------------------------------------------------------
ROLES = {"RinkManager", "FrontDesk", "Skater"}

SLOT_PURPOSES = {"PUBLIC_SKATE", "LEARN_TO_SKATE", "LEAGUE", "RENTAL", "BROOMBALL", "PARTY"}
MEMBERSHIPS = {"MEMBER", "NON_MEMBER"}
BOOKING_TYPES = {"PRIVATE_RENTAL", "BROOMBALL", "PARTY"}
BOOKING_PURPOSE = {"PRIVATE_RENTAL": "RENTAL", "BROOMBALL": "BROOMBALL", "PARTY": "PARTY"}
SPORTS = {"HOCKEY", "FIGURE"}
LOCKER_SIZES = {"STANDARD", "TALL"}
SKATE_TYPES = {"HOCKEY", "FIGURE", "GOALIE"}
PRORATION_MODES = {"CALENDAR", "SESSIONS"}

# Rental-quote pricing constants (calc slot_booking_rental_quote)
PEAK_RATE = 20000
OFF_PEAK_RATE = 12000
MEMBER_DISCOUNT_PCT = Decimal("0.10")
BROOMBALL_EQUIPMENT_CENTS = 5000
RESURFACE_SURCHARGE_CENTS = 4000


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, status, message=""):
    raise ApiError(error_id, status, message)


# --------------------------------------------------------------------------
# Time / formatting helpers
# --------------------------------------------------------------------------
def real_now():
    return datetime.now(timezone.utc)


def fmt_ts(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(s):
    if not isinstance(s, str):
        err("ERR_INVALID_REQUEST", 400, "invalid datetime")
    try:
        txt = s.strip()
        if txt.endswith("Z"):
            txt = txt[:-1] + "+00:00"
        dt = datetime.fromisoformat(txt)
    except Exception:
        err("ERR_INVALID_REQUEST", 400, "invalid datetime: %s" % s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    if not isinstance(s, str):
        err("ERR_INVALID_REQUEST", 400, "invalid date")
    try:
        return date.fromisoformat(s.strip())
    except Exception:
        err("ERR_INVALID_REQUEST", 400, "invalid date: %s" % s)


def gen_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def new_id():
    return str(uuid.uuid4())


# --------------------------------------------------------------------------
# Response envelope
# --------------------------------------------------------------------------
def meta_base():
    return {"api_request_id": gen_req_id(), "api_request_timestamp": fmt_ts(real_now())}


def respond(data, response_type="object", status=200, pagination=None):
    meta = meta_base()
    if pagination:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


@app.errorhandler(ApiError)
def handle_api_error(e):
    meta = meta_base()
    body = {"meta": meta, "response_type": "error",
            "data": {"error_id": e.error_id, "message": e.message}}
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    meta = meta_base()
    body = {"meta": meta, "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "resource not found"}}
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    meta = meta_base()
    body = {"meta": meta, "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "method not allowed"}}
    return jsonify(body), 405


# --------------------------------------------------------------------------
# Common field management
# --------------------------------------------------------------------------
def stamp_new(ent):
    ts = fmt_ts(real_now())
    ent["created_at"] = ts
    ent["updated_at"] = ts
    ent["version"] = 1
    ent["_seq"] = next_seq()
    return ent


def touch(ent):
    ent["updated_at"] = fmt_ts(real_now())
    ent["version"] += 1


def charge_wallet(skater, delta):
    skater["wallet_credit_cents"] += delta
    touch(skater)


# --------------------------------------------------------------------------
# Auth / RBAC / ownership
# --------------------------------------------------------------------------
def authctx():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        err("ERR_UNAUTHENTICATED", 401, "missing or invalid auth headers")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        err("ERR_UNAUTHORIZED", 403, "role not permitted")


def check_owner(role, uid, owner_skater_id):
    """For Skater role, enforce that the acting user owns the resource."""
    if role == "Skater" and uid != owner_skater_id:
        err("ERR_UNAUTHORIZED", 403, "skater does not own this resource")


def sub_owner(sub):
    enr = enrollments.get(sub.get("enrollment_id"))
    return enr["skater_id"] if enr else None


# --------------------------------------------------------------------------
# Existence helpers
# --------------------------------------------------------------------------
def must_get(store, rid):
    ent = store.get(rid)
    if ent is None:
        err("ERR_NOT_FOUND", 404, "resource not found")
    return ent


# --------------------------------------------------------------------------
# Computed / derived figures
# --------------------------------------------------------------------------
def rink_available_rental_skates(rink):
    in_use = 0
    for a in admissions.values():
        if a["status"] == "ADMITTED" and a["rental_skate"]:
            sl = ice_slots.get(a["ice_slot_id"])
            if sl and sl["rink_id"] == rink["id"]:
                in_use += 1
    return rink["rental_skate_count"] - in_use


def rink_available_lockers(rink):
    nums = set()
    for l in lockers.values():
        if l["rink_id"] == rink["id"] and l["status"] == "ACTIVE":
            nums.add(l["locker_number"])
    return rink["locker_count"] - len(nums)


def slot_admitted_count(slot):
    return sum(1 for a in admissions.values()
               if a["ice_slot_id"] == slot["id"] and a["status"] == "ADMITTED")


def class_enrolled_count(cls):
    return sum(1 for e in enrollments.values()
               if e["class_id"] == cls["id"] and e["status"] == "ENROLLED")


def league_roster_count(lg):
    return sum(1 for r in registrations.values()
               if r["league_id"] == lg["id"] and r["status"] == "ACTIVE")


def sharpening_queue_position(order):
    if order["status"] not in ("RECEIVED", "IN_PROGRESS"):
        return None
    live = [o for o in sharpenings.values() if o["status"] in ("RECEIVED", "IN_PROGRESS")]
    live.sort(key=lambda o: o["_seq"])
    for idx, o in enumerate(live):
        if o["id"] == order["id"]:
            return idx + 1
    return None


# --------------------------------------------------------------------------
# Serializers
# --------------------------------------------------------------------------
COMMON = ["id", "created_at", "updated_at", "version"]


def _base(ent):
    return {k: ent[k] for k in COMMON}


def ser_rink(r):
    d = _base(r)
    for k in ["name", "resurface_buffer_minutes", "open_hour_utc", "close_hour_utc",
              "peak_start_hour_utc", "public_skate_capacity", "public_skate_fee_cents",
              "rental_skate_count", "locker_count", "locker_fee_cents"]:
        d[k] = r[k]
    d["available_rental_skates"] = rink_available_rental_skates(r)
    d["available_lockers"] = rink_available_lockers(r)
    return d


def ser_skater(s):
    d = _base(s)
    for k in ["full_name", "email", "membership", "wallet_credit_cents"]:
        d[k] = s[k]
    return d


def ser_slot(s):
    d = _base(s)
    for k in ["rink_id", "purpose", "start_utc", "end_utc", "status"]:
        d[k] = s[k]
    d["admitted_count"] = slot_admitted_count(s)
    rink = rinks.get(s["rink_id"])
    cap = rink["public_skate_capacity"] if rink else 0
    d["available_capacity"] = cap - d["admitted_count"]
    return d


def ser_admission(a):
    d = _base(a)
    for k in ["ice_slot_id", "skater_id", "rental_skate", "captured_cents",
              "refunded_cents", "status"]:
        d[k] = a[k]
    return d


def ser_class(c):
    d = _base(c)
    for k in ["ice_slot_id", "prerequisite_class_id", "level_name", "capacity", "status"]:
        d[k] = c[k]
    d["enrolled_count"] = class_enrolled_count(c)
    return d


def ser_enrollment(e):
    d = _base(e)
    for k in ["class_id", "skater_id", "status"]:
        d[k] = e[k]
    return d


def ser_subscription(s):
    d = _base(s)
    for k in ["enrollment_id", "monthly_fee_cents", "proration_mode", "billing_cycle_start",
              "billing_cycle_end", "total_sessions_in_cycle", "sessions_attended",
              "captured_cents", "status"]:
        d[k] = s[k]
    return d


def ser_league(l):
    d = _base(l)
    for k in ["name", "sport", "season_start", "season_end", "roster_capacity", "status"]:
        d[k] = l[k]
    d["roster_count"] = league_roster_count(l)
    return d


def ser_registration(r):
    d = _base(r)
    for k in ["league_id", "skater_id", "status"]:
        d[k] = r[k]
    return d


def ser_locker(l):
    d = _base(l)
    for k in ["rink_id", "skater_id", "league_registration_id", "locker_number",
              "season_start_date", "season_end_date", "size", "status"]:
        d[k] = l[k]
    return d


def ser_booking(b):
    d = _base(b)
    for k in ["ice_slot_id", "skater_id", "booking_type", "includes_resurface",
              "base_fee_cents", "per_guest_cents", "guest_count_booked", "guest_count_final",
              "tax_rate", "quoted_cents", "final_cents", "captured_cents", "status"]:
        d[k] = b[k]
    return d


def ser_sharpening(o):
    d = _base(o)
    for k in ["skater_id", "skate_type", "price_cents", "status"]:
        d[k] = o[k]
    d["queue_position"] = sharpening_queue_position(o)
    return d


# --------------------------------------------------------------------------
# Field parsing helpers (ERR_INVALID_REQUEST, priority 10)
# --------------------------------------------------------------------------
def body_json():
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        err("ERR_INVALID_REQUEST", 400, "body must be a JSON object")
    return data


def need(body, name):
    if name not in body or body[name] is None:
        err("ERR_INVALID_REQUEST", 400, "missing required field: %s" % name)
    return body[name]


def as_int(val, name, min_val=None, allow_neg=True):
    if isinstance(val, bool) or not isinstance(val, int):
        err("ERR_INVALID_REQUEST", 400, "%s must be an integer" % name)
    if not allow_neg and val < 0:
        err("ERR_INVALID_REQUEST", 400, "%s must be non-negative" % name)
    if min_val is not None and val < min_val:
        err("ERR_INVALID_REQUEST", 400, "%s must be >= %s" % (name, min_val))
    return val


def as_bool(val, name):
    if not isinstance(val, bool):
        err("ERR_INVALID_REQUEST", 400, "%s must be a boolean" % name)
    return val


def as_str(val, name):
    if not isinstance(val, str) or val == "":
        err("ERR_INVALID_REQUEST", 400, "%s must be a non-empty string" % name)
    return val


def as_num(val, name):
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        err("ERR_INVALID_REQUEST", 400, "%s must be a number" % name)
    return val


def as_enum(val, name, allowed):
    if val not in allowed:
        err("ERR_INVALID_REQUEST", 400, "%s must be one of %s" % (name, sorted(allowed)))
    return val


# --------------------------------------------------------------------------
# Pagination
# --------------------------------------------------------------------------
def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            err("ERR_INVALID_REQUEST", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            err("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            err("ERR_INVALID_REQUEST", 400, "offset must be an integer")
        if offset < 0:
            err("ERR_INVALID_REQUEST", 400, "offset must be non-negative")
    return limit, offset


def list_response(items, serializer):
    """items: list of entity dicts, sorted by creation order."""
    limit, offset = parse_pagination()
    items = sorted(items, key=lambda e: e["_seq"])
    total = len(items)
    page = items[offset:offset + limit]
    has_more = offset + len(page) < total
    pagination = {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}
    return respond([serializer(e) for e in page], "array", 200, pagination)


# --------------------------------------------------------------------------
# Calculations
# --------------------------------------------------------------------------
def rhu(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rental_quote(slot, rink, skater, booking_type, includes_resurface):
    seconds = (slot["_end"] - slot["_start"]).total_seconds()
    hours = Decimal(str(seconds)) / Decimal(3600)
    rate = PEAK_RATE if slot["_start"].hour >= rink["peak_start_hour_utc"] else OFF_PEAK_RATE
    base = rhu(Decimal(rate) * hours)
    discount = rhu(Decimal(base) * MEMBER_DISCOUNT_PCT) if skater["membership"] == "MEMBER" else 0
    broomball_fee = BROOMBALL_EQUIPMENT_CENTS if booking_type == "BROOMBALL" else 0
    resurface_fee = RESURFACE_SURCHARGE_CENTS if includes_resurface else 0
    return base - discount + broomball_fee + resurface_fee


def party_charge(base_fee_cents, per_guest_cents, tax_rate, headcount):
    tax_per_guest = rhu(Decimal(per_guest_cents) * Decimal(str(tax_rate)))
    guest_total = per_guest_cents + tax_per_guest
    return base_fee_cents + headcount * guest_total


def proration_refund(sub, cancel_date):
    fee = sub["monthly_fee_cents"]
    if sub["proration_mode"] == "CALENDAR":
        start = date.fromisoformat(sub["billing_cycle_start"])
        end = date.fromisoformat(sub["billing_cycle_end"])
        total = (end - start).days
        if total <= 0:
            return 0
        remaining = max(0, (end - cancel_date).days)
        return rhu(Decimal(fee * remaining) / Decimal(total))
    else:  # SESSIONS
        total = sub["total_sessions_in_cycle"]
        remaining = max(0, total - sub["sessions_attended"])
        if total <= 0:
            return 0
        return rhu(Decimal(fee * remaining) / Decimal(total))


def add_one_month(dstr):
    d = date.fromisoformat(dstr)
    m = d.month + 1
    y = d.year
    if m > 12:
        m = 1
        y += 1
    last = calendar.monthrange(y, m)[1]
    return date(y, m, min(d.day, last)).isoformat()


# --------------------------------------------------------------------------
# Cascade helpers
# --------------------------------------------------------------------------
def cancel_subscription_internal(sub):
    """Cancel an ACTIVE/PAST_DUE subscription following the tuition rules."""
    if sub["status"] == "ACTIVE":
        enr = enrollments.get(sub["enrollment_id"])
        skater = skaters.get(enr["skater_id"]) if enr else None
        refund = proration_refund(sub, CLOCK["now"].date())
        if skater is not None and refund:
            charge_wallet(skater, refund)
        elif skater is not None:
            # still credit zero (no wallet change) — but nothing to do
            pass
        sub["status"] = "CANCELLED"
        touch(sub)
        if enr is not None:
            touch(enr)  # ACTIVE cancel also bumps parent enrollment version
    elif sub["status"] == "PAST_DUE":
        sub["status"] = "CANCELLED"
        touch(sub)


def withdraw_enrollment(enr):
    enr["status"] = "WITHDRAWN"
    cls = classes.get(enr["class_id"])
    if cls is not None and cls["status"] == "FULL" and class_enrolled_count(cls) < cls["capacity"]:
        cls["status"] = "OPEN"
        touch(cls)
    for sub in list(subscriptions.values()):
        if sub["enrollment_id"] == enr["id"] and sub["status"] in ("ACTIVE", "PAST_DUE"):
            cancel_subscription_internal(sub)
    touch(enr)


def cascade_league_cancel(league):
    for reg in list(registrations.values()):
        if reg["league_id"] == league["id"] and reg["status"] == "ACTIVE":
            reg["status"] = "CANCELLED"
            touch(reg)
            for lk in list(lockers.values()):
                if lk["league_registration_id"] == reg["id"] and lk["status"] == "ACTIVE":
                    lk["status"] = "RELEASED"
                    touch(lk)


def cascade_slot_cancel(slot):
    purpose = slot["purpose"]
    if purpose == "PUBLIC_SKATE":
        for a in list(admissions.values()):
            if a["ice_slot_id"] == slot["id"] and a["status"] == "ADMITTED":
                skater = skaters.get(a["skater_id"])
                if skater is not None:
                    charge_wallet(skater, a["captured_cents"])
                a["refunded_cents"] = a["captured_cents"]
                a["captured_cents"] = 0
                a["status"] = "REFUNDED"
                touch(a)
    elif purpose == "LEARN_TO_SKATE":
        for cls in list(classes.values()):
            if cls["ice_slot_id"] == slot["id"] and cls["status"] in ("OPEN", "FULL"):
                cls["status"] = "CANCELLED"
                touch(cls)
                for enr in list(enrollments.values()):
                    if enr["class_id"] == cls["id"] and enr["status"] == "ENROLLED":
                        withdraw_enrollment(enr)
    elif purpose in ("RENTAL", "BROOMBALL", "PARTY"):
        for b in list(bookings.values()):
            if b["ice_slot_id"] == slot["id"] and b["status"] == "BOOKED":
                skater = skaters.get(b["skater_id"])
                if skater is not None:
                    charge_wallet(skater, b["captured_cents"])
                b["captured_cents"] = 0
                b["status"] = "CANCELLED"
                touch(b)


def cascade_slot_complete(slot):
    purpose = slot["purpose"]
    if purpose == "PUBLIC_SKATE":
        for a in list(admissions.values()):
            if a["ice_slot_id"] == slot["id"] and a["status"] == "ADMITTED":
                a["captured_cents"] = 0  # recognized as revenue; wallet NOT credited
                a["status"] = "EXITED"
                touch(a)
    elif purpose == "LEARN_TO_SKATE":
        for cls in list(classes.values()):
            if cls["ice_slot_id"] == slot["id"] and cls["status"] in ("OPEN", "FULL"):
                cls["status"] = "COMPLETED"
                touch(cls)
                for enr in list(enrollments.values()):
                    if enr["class_id"] == cls["id"] and enr["status"] == "ENROLLED":
                        enr["status"] = "COMPLETED"
                        touch(enr)


# ==========================================================================
# Routes
# ==========================================================================
@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


# ---- Logical clock -------------------------------------------------------
@app.route("/_clock/set_current_utc", methods=["POST"])
def clock_set():
    uid, role = authctx()
    require_role(role, {"RinkManager"})
    body = body_json()
    val = need(body, "to_iso8601")
    dt = parse_dt(val)
    CLOCK["now"] = dt
    return respond({"current_utc": fmt_ts(dt)}, "object", 200)


# ---- Rinks ---------------------------------------------------------------
@app.route("/rinks", methods=["POST"])
def create_rink():
    uid, role = authctx()
    require_role(role, {"RinkManager"})
    body = body_json()
    name = as_str(need(body, "name"), "name")
    resurface = as_int(need(body, "resurface_buffer_minutes"), "resurface_buffer_minutes", min_val=0)
    cap = as_int(need(body, "public_skate_capacity"), "public_skate_capacity", min_val=1)
    fee = as_int(need(body, "public_skate_fee_cents"), "public_skate_fee_cents", min_val=0)
    rental_count = as_int(need(body, "rental_skate_count"), "rental_skate_count", min_val=0)
    locker_count = as_int(need(body, "locker_count"), "locker_count", min_val=0)
    locker_fee = as_int(need(body, "locker_fee_cents"), "locker_fee_cents", min_val=0)
    open_hour = as_int(body.get("open_hour_utc", 6), "open_hour_utc", min_val=0)
    close_hour = as_int(body.get("close_hour_utc", 23), "close_hour_utc", min_val=0)
    peak_hour = as_int(body.get("peak_start_hour_utc", 16), "peak_start_hour_utc", min_val=0)
    for h, hn in [(open_hour, "open_hour_utc"), (close_hour, "close_hour_utc"), (peak_hour, "peak_start_hour_utc")]:
        if h > 23:
            err("ERR_INVALID_REQUEST", 400, "%s must be 0..23" % hn)
    r = {
        "id": new_id(), "name": name, "resurface_buffer_minutes": resurface,
        "open_hour_utc": open_hour, "close_hour_utc": close_hour, "peak_start_hour_utc": peak_hour,
        "public_skate_capacity": cap, "public_skate_fee_cents": fee,
        "rental_skate_count": rental_count, "locker_count": locker_count,
        "locker_fee_cents": locker_fee,
    }
    stamp_new(r)
    rinks[r["id"]] = r
    return respond(ser_rink(r), "object", 201)


@app.route("/rinks/<rid>", methods=["GET"])
def get_rink(rid):
    uid, role = authctx()
    require_role(role, ROLES)
    r = must_get(rinks, rid)
    return respond(ser_rink(r), "object", 200)


# ---- Skaters -------------------------------------------------------------
@app.route("/skaters", methods=["POST"])
def create_skater():
    uid, role = authctx()
    require_role(role, {"RinkManager", "FrontDesk"})
    body = body_json()
    full_name = as_str(need(body, "full_name"), "full_name")
    email = as_str(need(body, "email"), "email")
    membership = body.get("membership", "NON_MEMBER")
    as_enum(membership, "membership", MEMBERSHIPS)
    for s in skaters.values():
        if s["email"] == email:
            err("ERR_INVALID_REQUEST", 400, "email already in use")
    s = {"id": new_id(), "full_name": full_name, "email": email,
         "membership": membership, "wallet_credit_cents": 0}
    stamp_new(s)
    skaters[s["id"]] = s
    return respond(ser_skater(s), "object", 201)


@app.route("/skaters/<sid>", methods=["GET"])
def get_skater(sid):
    uid, role = authctx()
    require_role(role, ROLES)
    s = must_get(skaters, sid)
    check_owner(role, uid, s["id"])
    return respond(ser_skater(s), "object", 200)


@app.route("/skaters/<sid>/wallet/adjustments", methods=["POST"])
def wallet_adjust(sid):
    uid, role = authctx()
    require_role(role, {"RinkManager"})
    s = must_get(skaters, sid)
    body = body_json()
    amount = as_int(need(body, "amount_cents"), "amount_cents", allow_neg=True)
    charge_wallet(s, amount)
    return respond(ser_skater(s), "object", 200)


# ---- Ice slots -----------------------------------------------------------
@app.route("/ice-slots", methods=["POST"])
def create_slot():
    uid, role = authctx()
    require_role(role, {"RinkManager"})
    body = body_json()
    rink_id = body.get("rink_id")
    if rink_id is not None:
        rink = must_get(rinks, rink_id)
    rink_id = as_str(need(body, "rink_id"), "rink_id")
    rink = must_get(rinks, rink_id)
    purpose = as_enum(need(body, "purpose"), "purpose", SLOT_PURPOSES)
    start = parse_dt(need(body, "start_utc"))
    end = parse_dt(need(body, "end_utc"))
    if end <= start:
        err("ERR_INVALID_REQUEST", 400, "end_utc must be after start_utc")
    s = {"id": new_id(), "rink_id": rink_id, "purpose": purpose,
         "start_utc": body["start_utc"], "end_utc": body["end_utc"],
         "_start": start, "_end": end, "status": "DRAFT"}
    stamp_new(s)
    ice_slots[s["id"]] = s
    return respond(ser_slot(s), "object", 201)


@app.route("/ice-slots/<sid>", methods=["GET"])
def get_slot(sid):
    uid, role = authctx()
    require_role(role, ROLES)
    s = must_get(ice_slots, sid)
    return respond(ser_slot(s), "object", 200)


@app.route("/ice-slots", methods=["GET"])
def list_slots():
    uid, role = authctx()
    require_role(role, ROLES)
    items = list(ice_slots.values())
    rink_id = request.args.get("rink_id")
    purpose = request.args.get("purpose")
    status = request.args.get("status")
    if rink_id is not None:
        items = [x for x in items if x["rink_id"] == rink_id]
    if purpose is not None:
        items = [x for x in items if x["purpose"] == purpose]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    return list_response(items, ser_slot)


@app.route("/ice-slots/<sid>/publish", methods=["POST"])
def publish_slot(sid):
    uid, role = authctx()
    require_role(role, {"RinkManager"})
    s = must_get(ice_slots, sid)
    if s["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "slot is not DRAFT")
    rink = rinks[s["rink_id"]]
    # hours guard
    if s["_start"].hour < rink["open_hour_utc"] or s["_end"].hour > rink["close_hour_utc"]:
        err("ERR_INVALID_STATE", 409, "slot outside rink operating hours")
    # resurface-buffer overlap guard
    buffer = timedelta(minutes=rink["resurface_buffer_minutes"])
    for other in ice_slots.values():
        if other["id"] == s["id"]:
            continue
        if other["rink_id"] != s["rink_id"]:
            continue
        if other["status"] not in ("DRAFT", "SCHEDULED"):
            continue
        w_start = other["_start"] - buffer
        w_end = other["_end"] + buffer
        if s["_start"] < w_end and w_start < s["_end"]:
            err("ERR_SLOT_OVERLAP", 409, "slot collides with resurface buffer window")
    s["status"] = "SCHEDULED"
    touch(s)
    return respond(ser_slot(s), "object", 200)


@app.route("/ice-slots/<sid>/unpublish", methods=["POST"])
def unpublish_slot(sid):
    uid, role = authctx()
    require_role(role, {"RinkManager"})
    s = must_get(ice_slots, sid)
    if s["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", 409, "slot is not SCHEDULED")
    has_adm = any(a["ice_slot_id"] == s["id"] and a["status"] == "ADMITTED" for a in admissions.values())
    has_cls = any(c["ice_slot_id"] == s["id"] and c["status"] in ("OPEN", "FULL") for c in classes.values())
    has_bk = any(b["ice_slot_id"] == s["id"] and b["status"] == "BOOKED" for b in bookings.values())
    if has_adm or has_cls or has_bk:
        err("ERR_INVALID_STATE", 409, "slot has active child bookings")
    s["status"] = "DRAFT"
    touch(s)
    return respond(ser_slot(s), "object", 200)


@app.route("/ice-slots/<sid>/cancel", methods=["POST"])
def cancel_slot(sid):
    uid, role = authctx()
    require_role(role, {"RinkManager"})
    s = must_get(ice_slots, sid)
    if s["status"] not in ("DRAFT", "SCHEDULED"):
        err("ERR_INVALID_STATE", 409, "slot cannot be cancelled")
    if s["status"] == "SCHEDULED":
        cascade_slot_cancel(s)
    s["status"] = "CANCELLED"
    touch(s)
    return respond(ser_slot(s), "object", 200)


@app.route("/ice-slots/<sid>/complete", methods=["POST"])
def complete_slot(sid):
    uid, role = authctx()
    require_role(role, {"RinkManager"})
    s = must_get(ice_slots, sid)
    if s["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", 409, "slot is not SCHEDULED")
    if CLOCK["now"] < s["_end"]:
        err("ERR_INVALID_STATE", 409, "slot end time not reached")
    cascade_slot_complete(s)
    s["status"] = "COMPLETED"
    touch(s)
    return respond(ser_slot(s), "object", 200)


# ---- Public skate admissions --------------------------------------------
@app.route("/ice-slots/<sid>/admissions", methods=["POST"])
def create_admission(sid):
    uid, role = authctx()
    require_role(role, {"FrontDesk", "Skater"})
    body = body_json()
    body_skater = body.get("skater_id")
    if role == "Skater" and body_skater is not None and body_skater != uid:
        err("ERR_UNAUTHORIZED", 403, "skater may only admit self")
    slot = must_get(ice_slots, sid)
    skater_id = body.get("skater_id")
    if skater_id is not None:
        skater = must_get(skaters, skater_id)
    # state: PUBLIC_SKATE + SCHEDULED
    if slot["purpose"] != "PUBLIC_SKATE" or slot["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", 409, "slot is not a scheduled public-skate slot")
    skater_id = as_str(need(body, "skater_id"), "skater_id")
    skater = must_get(skaters, skater_id)
    rental = as_bool(body.get("rental_skate", False), "rental_skate")
    rink = rinks[slot["rink_id"]]
    # capacity
    if slot_admitted_count(slot) >= rink["public_skate_capacity"]:
        err("ERR_CAPACITY_FULL", 409, "public-skate capacity reached")
    # rental inventory
    if rental and rink_available_rental_skates(rink) < 1:
        err("ERR_NO_RENTAL_SKATES", 409, "no rental skates available")
    # fiscal
    fee = rink["public_skate_fee_cents"]
    if skater["wallet_credit_cents"] < fee:
        err("ERR_INSUFFICIENT_FUNDS", 402, "insufficient wallet credit")
    charge_wallet(skater, -fee)
    a = {"id": new_id(), "ice_slot_id": slot["id"], "skater_id": skater_id,
         "rental_skate": rental, "captured_cents": fee, "refunded_cents": 0,
         "status": "ADMITTED"}
    stamp_new(a)
    admissions[a["id"]] = a
    return respond(ser_admission(a), "object", 201)


@app.route("/admissions/<aid>", methods=["GET"])
def get_admission(aid):
    uid, role = authctx()
    require_role(role, ROLES)
    a = must_get(admissions, aid)
    check_owner(role, uid, a["skater_id"])
    return respond(ser_admission(a), "object", 200)


@app.route("/admissions", methods=["GET"])
def list_admissions():
    uid, role = authctx()
    require_role(role, ROLES)
    items = list(admissions.values())
    for key in ["ice_slot_id", "skater_id", "status"]:
        v = request.args.get(key)
        if v is not None:
            items = [x for x in items if x[key] == v]
    return list_response(items, ser_admission)


@app.route("/admissions/<aid>/refund", methods=["POST"])
def refund_admission(aid):
    uid, role = authctx()
    require_role(role, {"RinkManager", "FrontDesk"})
    a = must_get(admissions, aid)
    if a["status"] != "ADMITTED":
        err("ERR_INVALID_STATE", 409, "admission is not ADMITTED")
    skater = skaters.get(a["skater_id"])
    amount = a["captured_cents"]
    if skater is not None:
        charge_wallet(skater, amount)
    a["refunded_cents"] = amount
    a["captured_cents"] = 0
    a["status"] = "REFUNDED"
    touch(a)
    return respond(ser_admission(a), "object", 200)


# ---- Learn-to-skate classes ---------------------------------------------
@app.route("/learn-to-skate-classes", methods=["POST"])
def create_class():
    uid, role = authctx()
    require_role(role, {"RinkManager"})
    body = body_json()
    slot_id = body.get("ice_slot_id")
    if slot_id is not None:
        slot = must_get(ice_slots, slot_id)
    prereq_id = body.get("prerequisite_class_id")
    if prereq_id is not None:
        must_get(classes, prereq_id)
    slot_id = as_str(need(body, "ice_slot_id"), "ice_slot_id")
    slot = must_get(ice_slots, slot_id)
    if slot["purpose"] != "LEARN_TO_SKATE":
        err("ERR_INVALID_STATE", 409, "slot is not a LEARN_TO_SKATE slot")
    level = as_str(need(body, "level_name"), "level_name")
    capacity = as_int(need(body, "capacity"), "capacity", min_val=1)
    c = {"id": new_id(), "ice_slot_id": slot_id, "prerequisite_class_id": prereq_id,
         "level_name": level, "capacity": capacity, "status": "OPEN"}
    stamp_new(c)
    classes[c["id"]] = c
    return respond(ser_class(c), "object", 201)


@app.route("/learn-to-skate-classes/<cid>", methods=["GET"])
def get_class(cid):
    uid, role = authctx()
    require_role(role, ROLES)
    c = must_get(classes, cid)
    return respond(ser_class(c), "object", 200)


@app.route("/learn-to-skate-classes", methods=["GET"])
def list_classes():
    uid, role = authctx()
    require_role(role, ROLES)
    items = list(classes.values())
    for key in ["ice_slot_id", "prerequisite_class_id"]:
        v = request.args.get(key)
        if v is not None:
            items = [x for x in items if x[key] == v]
    return list_response(items, ser_class)


@app.route("/learn-to-skate-classes/<cid>/enrollments", methods=["POST"])
def create_enrollment(cid):
    uid, role = authctx()
    require_role(role, {"Skater", "RinkManager"})
    body = body_json()
    body_skater = body.get("skater_id")
    if role == "Skater" and body_skater is not None and body_skater != uid:
        err("ERR_UNAUTHORIZED", 403, "skater may only enroll self")
    cls = must_get(classes, cid)
    skater_id = body.get("skater_id")
    if skater_id is not None:
        skater = must_get(skaters, skater_id)
    # state: class OPEN
    if cls["status"] != "OPEN":
        err("ERR_INVALID_STATE", 409, "class is not OPEN")
    skater_id = as_str(need(body, "skater_id"), "skater_id")
    skater = must_get(skaters, skater_id)
    # prerequisite
    if cls["prerequisite_class_id"]:
        ok = any(e["class_id"] == cls["prerequisite_class_id"] and e["skater_id"] == skater_id
                 and e["status"] == "COMPLETED" for e in enrollments.values())
        if not ok:
            err("ERR_PREREQUISITE_NOT_MET", 422, "prerequisite class not completed")
    # capacity
    if class_enrolled_count(cls) >= cls["capacity"]:
        err("ERR_CAPACITY_FULL", 409, "class is full")
    e = {"id": new_id(), "class_id": cid, "skater_id": skater_id, "status": "ENROLLED"}
    stamp_new(e)
    enrollments[e["id"]] = e
    if class_enrolled_count(cls) >= cls["capacity"]:
        cls["status"] = "FULL"
        touch(cls)
    return respond(ser_enrollment(e), "object", 201)


@app.route("/enrollments/<eid>", methods=["GET"])
def get_enrollment(eid):
    uid, role = authctx()
    require_role(role, ROLES)
    e = must_get(enrollments, eid)
    check_owner(role, uid, e["skater_id"])
    return respond(ser_enrollment(e), "object", 200)


@app.route("/enrollments", methods=["GET"])
def list_enrollments():
    uid, role = authctx()
    require_role(role, ROLES)
    items = list(enrollments.values())
    for key in ["class_id", "skater_id", "status"]:
        v = request.args.get(key)
        if v is not None:
            items = [x for x in items if x[key] == v]
    return list_response(items, ser_enrollment)


@app.route("/enrollments/<eid>/withdraw", methods=["POST"])
def withdraw_enrollment_ep(eid):
    uid, role = authctx()
    require_role(role, {"Skater", "RinkManager"})
    e = must_get(enrollments, eid)
    check_owner(role, uid, e["skater_id"])
    if e["status"] != "ENROLLED":
        err("ERR_INVALID_STATE", 409, "enrollment is not ENROLLED")
    withdraw_enrollment(e)
    return respond(ser_enrollment(e), "object", 200)


@app.route("/enrollments/<eid>/complete", methods=["POST"])
def complete_enrollment(eid):
    uid, role = authctx()
    require_role(role, {"RinkManager"})
    e = must_get(enrollments, eid)
    if e["status"] != "ENROLLED":
        err("ERR_INVALID_STATE", 409, "enrollment is not ENROLLED")
    e["status"] = "COMPLETED"
    touch(e)
    return respond(ser_enrollment(e), "object", 200)


# ---- Tuition subscriptions ----------------------------------------------
@app.route("/enrollments/<eid>/tuition-subscriptions", methods=["POST"])
def create_subscription(eid):
    uid, role = authctx()
    require_role(role, {"Skater", "RinkManager"})
    e = must_get(enrollments, eid)
    check_owner(role, uid, e["skater_id"])
    body = body_json()
    skater = skaters.get(e["skater_id"])
    if skater is None:
        err("ERR_NOT_FOUND", 404, "skater not found")
    monthly = as_int(need(body, "monthly_fee_cents"), "monthly_fee_cents", min_val=0)
    cycle_start = need(body, "billing_cycle_start")
    cycle_end = need(body, "billing_cycle_end")
    parse_date(cycle_start)
    parse_date(cycle_end)
    total_sessions = as_int(need(body, "total_sessions_in_cycle"), "total_sessions_in_cycle", min_val=1)
    proration_mode = body.get("proration_mode", "CALENDAR")
    as_enum(proration_mode, "proration_mode", PRORATION_MODES)
    sessions_attended = as_int(body.get("sessions_attended", 0), "sessions_attended", min_val=0)
    # fiscal (priority 8)
    if skater["wallet_credit_cents"] < monthly:
        err("ERR_INSUFFICIENT_FUNDS", 402, "insufficient wallet credit")
    # OCC (priority 9)
    expected = body.get("expected_enrollment_version")
    if expected is not None:
        if not isinstance(expected, int) or isinstance(expected, bool):
            err("ERR_INVALID_REQUEST", 400, "expected_enrollment_version must be an integer")
        if expected != e["version"]:
            err("ERR_STALE_VERSION", 412, "enrollment version mismatch")
    else:
        err("ERR_INVALID_REQUEST", 400, "missing required field: expected_enrollment_version")
    # supersede any prior ACTIVE subscription (no refund on supersede)
    for prior in list(subscriptions.values()):
        if prior["enrollment_id"] == eid and prior["status"] == "ACTIVE":
            prior["status"] = "CANCELLED"
            touch(prior)
    charge_wallet(skater, -monthly)
    sub = {"id": new_id(), "enrollment_id": eid, "monthly_fee_cents": monthly,
           "proration_mode": proration_mode, "billing_cycle_start": cycle_start,
           "billing_cycle_end": cycle_end, "total_sessions_in_cycle": total_sessions,
           "sessions_attended": sessions_attended, "captured_cents": monthly,
           "status": "ACTIVE"}
    stamp_new(sub)
    subscriptions[sub["id"]] = sub
    touch(e)  # create increments parent enrollment version by one
    return respond(ser_subscription(sub), "object", 201)


@app.route("/tuition-subscriptions/<sid>", methods=["GET"])
def get_subscription(sid):
    uid, role = authctx()
    require_role(role, ROLES)
    sub = must_get(subscriptions, sid)
    check_owner(role, uid, sub_owner(sub))
    return respond(ser_subscription(sub), "object", 200)


@app.route("/tuition-subscriptions", methods=["GET"])
def list_subscriptions():
    uid, role = authctx()
    require_role(role, ROLES)
    items = list(subscriptions.values())
    for key in ["enrollment_id", "status"]:
        v = request.args.get(key)
        if v is not None:
            items = [x for x in items if x[key] == v]
    return list_response(items, ser_subscription)


@app.route("/tuition-subscriptions/<sid>/advance-cycle", methods=["POST"])
def advance_cycle(sid):
    uid, role = authctx()
    require_role(role, {"RinkManager"})
    sub = must_get(subscriptions, sid)
    if sub["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "subscription is not ACTIVE")
    end_dt = datetime.combine(date.fromisoformat(sub["billing_cycle_end"]),
                              datetime.min.time(), tzinfo=timezone.utc)
    if CLOCK["now"] < end_dt:
        err("ERR_INVALID_STATE", 409, "billing cycle end not reached")
    sub["billing_cycle_start"] = add_one_month(sub["billing_cycle_start"])
    sub["billing_cycle_end"] = add_one_month(sub["billing_cycle_end"])
    sub["status"] = "PAST_DUE"
    touch(sub)
    return respond(ser_subscription(sub), "object", 200)


@app.route("/tuition-subscriptions/<sid>/pay", methods=["POST"])
def pay_subscription(sid):
    uid, role = authctx()
    require_role(role, {"Skater", "RinkManager"})
    sub = must_get(subscriptions, sid)
    check_owner(role, uid, sub_owner(sub))
    if sub["status"] != "PAST_DUE":
        err("ERR_INVALID_STATE", 409, "subscription is not PAST_DUE")
    enr = enrollments.get(sub["enrollment_id"])
    skater = skaters.get(enr["skater_id"]) if enr else None
    fee = sub["monthly_fee_cents"]
    if skater is None or skater["wallet_credit_cents"] < fee:
        err("ERR_INSUFFICIENT_FUNDS", 402, "insufficient wallet credit")
    charge_wallet(skater, -fee)
    sub["captured_cents"] += fee
    sub["status"] = "ACTIVE"
    touch(sub)
    return respond(ser_subscription(sub), "object", 200)


@app.route("/tuition-subscriptions/<sid>/cancel", methods=["POST"])
def cancel_subscription(sid):
    uid, role = authctx()
    require_role(role, {"Skater", "RinkManager"})
    sub = must_get(subscriptions, sid)
    check_owner(role, uid, sub_owner(sub))
    if sub["status"] not in ("ACTIVE", "PAST_DUE"):
        err("ERR_INVALID_STATE", 409, "subscription cannot be cancelled")
    cancel_subscription_internal(sub)
    return respond(ser_subscription(sub), "object", 200)


# ---- Leagues -------------------------------------------------------------
@app.route("/leagues", methods=["POST"])
def create_league():
    uid, role = authctx()
    require_role(role, {"RinkManager"})
    body = body_json()
    name = as_str(need(body, "name"), "name")
    sport = as_enum(need(body, "sport"), "sport", SPORTS)
    season_start = need(body, "season_start")
    season_end = need(body, "season_end")
    parse_date(season_start)
    parse_date(season_end)
    roster_capacity = as_int(need(body, "roster_capacity"), "roster_capacity", min_val=1)
    l = {"id": new_id(), "name": name, "sport": sport, "season_start": season_start,
         "season_end": season_end, "roster_capacity": roster_capacity,
         "status": "REGISTRATION_OPEN"}
    stamp_new(l)
    leagues[l["id"]] = l
    return respond(ser_league(l), "object", 201)


@app.route("/leagues/<lid>", methods=["GET"])
def get_league(lid):
    uid, role = authctx()
    require_role(role, ROLES)
    l = must_get(leagues, lid)
    return respond(ser_league(l), "object", 200)


@app.route("/leagues/<lid>/start", methods=["POST"])
def start_league(lid):
    uid, role = authctx()
    require_role(role, {"RinkManager"})
    l = must_get(leagues, lid)
    if l["status"] != "REGISTRATION_OPEN":
        err("ERR_INVALID_STATE", 409, "league is not REGISTRATION_OPEN")
    l["status"] = "IN_SEASON"
    touch(l)
    return respond(ser_league(l), "object", 200)


@app.route("/leagues/<lid>/cancel", methods=["POST"])
def cancel_league(lid):
    uid, role = authctx()
    require_role(role, {"RinkManager"})
    l = must_get(leagues, lid)
    if l["status"] not in ("REGISTRATION_OPEN", "IN_SEASON"):
        err("ERR_INVALID_STATE", 409, "league cannot be cancelled")
    cascade_league_cancel(l)
    l["status"] = "CANCELLED"
    touch(l)
    return respond(ser_league(l), "object", 200)


@app.route("/leagues/<lid>/registrations", methods=["POST"])
def create_registration(lid):
    uid, role = authctx()
    require_role(role, {"Skater", "RinkManager"})
    body = body_json()
    body_skater = body.get("skater_id")
    if role == "Skater" and body_skater is not None and body_skater != uid:
        err("ERR_UNAUTHORIZED", 403, "skater may only register self")
    l = must_get(leagues, lid)
    skater_id = body.get("skater_id")
    if skater_id is not None:
        skater = must_get(skaters, skater_id)
    locker_number = body.get("locker_number")
    rink_id = body.get("rink_id")
    rink = None
    if locker_number is not None and rink_id is not None:
        rink = must_get(rinks, rink_id)
    # state: league REGISTRATION_OPEN
    if l["status"] != "REGISTRATION_OPEN":
        err("ERR_INVALID_STATE", 409, "league is not REGISTRATION_OPEN")
    skater_id = as_str(need(body, "skater_id"), "skater_id")
    skater = must_get(skaters, skater_id)
    # capacity: roster
    if league_roster_count(l) >= l["roster_capacity"]:
        err("ERR_CAPACITY_FULL", 409, "league roster is full")

    # Optional locker side effect (requires rink_id + season dates + locker_number).
    locker_ent = None
    if locker_number is not None:
        if rink_id is None:
            err("ERR_INVALID_REQUEST", 400, "rink_id required to reserve a locker")
        rink = must_get(rinks, rink_id)
        ln = as_int(locker_number, "locker_number")
        season_start_date = as_str(need(body, "season_start_date"), "season_start_date")
        season_end_date = as_str(need(body, "season_end_date"), "season_end_date")
        sd = parse_date(season_start_date)
        ed = parse_date(season_end_date)
        if ed <= sd:
            err("ERR_INVALID_REQUEST", 400, "season_end_date must be after season_start_date")
        # temporal overlap
        _check_locker_overlap(rink, ln, sd, ed)
        # capacity: index range
        if ln < 1 or ln > rink["locker_count"]:
            err("ERR_CAPACITY_FULL", 409, "locker_number out of range")
        # fiscal
        if skater["wallet_credit_cents"] < rink["locker_fee_cents"]:
            err("ERR_INSUFFICIENT_FUNDS", 402, "insufficient wallet credit for locker fee")

    reg = {"id": new_id(), "league_id": lid, "skater_id": skater_id, "status": "ACTIVE"}
    stamp_new(reg)
    registrations[reg["id"]] = reg

    if locker_number is not None:
        charge_wallet(skater, -rink["locker_fee_cents"])
        size = body.get("size", "STANDARD")
        as_enum(size, "size", LOCKER_SIZES)
        locker_ent = {"id": new_id(), "rink_id": rink["id"], "skater_id": skater_id,
                      "league_registration_id": reg["id"], "locker_number": ln,
                      "season_start_date": body["season_start_date"],
                      "season_end_date": body["season_end_date"], "size": size,
                      "status": "ACTIVE"}
        stamp_new(locker_ent)
        lockers[locker_ent["id"]] = locker_ent

    return respond(ser_registration(reg), "object", 201)


@app.route("/league-registrations/<rid>", methods=["GET"])
def get_registration(rid):
    uid, role = authctx()
    require_role(role, ROLES)
    r = must_get(registrations, rid)
    check_owner(role, uid, r["skater_id"])
    return respond(ser_registration(r), "object", 200)


@app.route("/league-registrations", methods=["GET"])
def list_registrations():
    uid, role = authctx()
    require_role(role, ROLES)
    items = list(registrations.values())
    for key in ["league_id", "skater_id", "status"]:
        v = request.args.get(key)
        if v is not None:
            items = [x for x in items if x[key] == v]
    return list_response(items, ser_registration)


# ---- Locker assignments --------------------------------------------------
def _check_locker_overlap(rink, locker_number, sd, ed):
    for l in lockers.values():
        if l["rink_id"] != rink["id"] or l["status"] != "ACTIVE":
            continue
        if l["locker_number"] != locker_number:
            continue
        e_sd = date.fromisoformat(l["season_start_date"])
        e_ed = date.fromisoformat(l["season_end_date"])
        if sd < e_ed and e_sd < ed:
            err("ERR_LOCKER_OCCUPIED", 409, "locker season range collides")


@app.route("/rinks/<rid>/locker-assignments", methods=["POST"])
def create_locker(rid):
    uid, role = authctx()
    require_role(role, {"Skater", "RinkManager"})
    body = body_json()
    body_skater = body.get("skater_id")
    if role == "Skater" and body_skater is not None and body_skater != uid:
        err("ERR_UNAUTHORIZED", 403, "skater may only assign own locker")
    rink = must_get(rinks, rid)
    skater_id = body.get("skater_id")
    if skater_id is not None:
        skater = must_get(skaters, skater_id)
    skater_id = as_str(need(body, "skater_id"), "skater_id")
    skater = must_get(skaters, skater_id)
    locker_number = as_int(need(body, "locker_number"), "locker_number")
    season_start_date = as_str(need(body, "season_start_date"), "season_start_date")
    season_end_date = as_str(need(body, "season_end_date"), "season_end_date")
    sd = parse_date(season_start_date)
    ed = parse_date(season_end_date)
    if ed <= sd:
        err("ERR_INVALID_REQUEST", 400, "season_end_date must be after season_start_date")
    size = body.get("size", "STANDARD")
    as_enum(size, "size", LOCKER_SIZES)
    # temporal overlap (priority 6)
    _check_locker_overlap(rink, locker_number, sd, ed)
    # capacity: index range (priority 7)
    if locker_number < 1 or locker_number > rink["locker_count"]:
        err("ERR_CAPACITY_FULL", 409, "locker_number out of range")
    # fiscal (priority 8)
    fee = rink["locker_fee_cents"]
    if skater["wallet_credit_cents"] < fee:
        err("ERR_INSUFFICIENT_FUNDS", 402, "insufficient wallet credit")
    charge_wallet(skater, -fee)
    l = {"id": new_id(), "rink_id": rid, "skater_id": skater_id,
         "league_registration_id": None, "locker_number": locker_number,
         "season_start_date": season_start_date, "season_end_date": season_end_date,
         "size": size, "status": "ACTIVE"}
    stamp_new(l)
    lockers[l["id"]] = l
    return respond(ser_locker(l), "object", 201)


@app.route("/locker-assignments/<lid>", methods=["GET"])
def get_locker(lid):
    uid, role = authctx()
    require_role(role, ROLES)
    l = must_get(lockers, lid)
    check_owner(role, uid, l["skater_id"])
    return respond(ser_locker(l), "object", 200)


@app.route("/locker-assignments", methods=["GET"])
def list_lockers():
    uid, role = authctx()
    require_role(role, ROLES)
    items = list(lockers.values())
    for key in ["rink_id", "skater_id", "league_registration_id", "status"]:
        v = request.args.get(key)
        if v is not None:
            items = [x for x in items if x[key] == v]
    return list_response(items, ser_locker)


@app.route("/locker-assignments/<lid>/release", methods=["POST"])
def release_locker(lid):
    uid, role = authctx()
    require_role(role, {"Skater", "RinkManager"})
    l = must_get(lockers, lid)
    check_owner(role, uid, l["skater_id"])
    if l["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "locker is not ACTIVE")
    l["status"] = "RELEASED"
    touch(l)
    return respond(ser_locker(l), "object", 200)


# ---- Slot bookings -------------------------------------------------------
@app.route("/ice-slots/<sid>/slot-bookings", methods=["POST"])
def create_booking(sid):
    uid, role = authctx()
    require_role(role, {"Skater", "RinkManager"})
    body = body_json()
    body_skater = body.get("skater_id")
    if role == "Skater" and body_skater is not None and body_skater != uid:
        err("ERR_UNAUTHORIZED", 403, "skater may only book own slots")
    slot = must_get(ice_slots, sid)
    skater_id = body.get("skater_id")
    if skater_id is not None:
        skater = must_get(skaters, skater_id)
    booking_type = need(body, "booking_type")
    as_enum(booking_type, "booking_type", BOOKING_TYPES)
    # state: booking_type must match slot purpose
    if BOOKING_PURPOSE[booking_type] != slot["purpose"]:
        err("ERR_INVALID_STATE", 409, "booking_type does not match slot purpose")
    skater_id = as_str(need(body, "skater_id"), "skater_id")
    skater = must_get(skaters, skater_id)
    rink = rinks[slot["rink_id"]]
    includes_resurface = as_bool(body.get("includes_resurface", False), "includes_resurface")
    base_fee = as_int(body.get("base_fee_cents", 0), "base_fee_cents", min_val=0)
    per_guest = as_int(body.get("per_guest_cents", 0), "per_guest_cents", min_val=0)
    guest_booked = as_int(body.get("guest_count_booked", 0), "guest_count_booked", min_val=0)
    guest_final = as_int(body.get("guest_count_final", 0), "guest_count_final", min_val=0)
    tax_rate = as_num(body.get("tax_rate", 0), "tax_rate")
    if tax_rate < 0:
        err("ERR_INVALID_REQUEST", 400, "tax_rate must be non-negative")
    # compute quote
    if booking_type == "PARTY":
        quoted = party_charge(base_fee, per_guest, tax_rate, guest_booked)
    else:
        quoted = rental_quote(slot, rink, skater, booking_type, includes_resurface)
    # fiscal
    if skater["wallet_credit_cents"] < quoted:
        err("ERR_INSUFFICIENT_FUNDS", 402, "insufficient wallet credit")
    charge_wallet(skater, -quoted)
    b = {"id": new_id(), "ice_slot_id": sid, "skater_id": skater_id,
         "booking_type": booking_type, "includes_resurface": includes_resurface,
         "base_fee_cents": base_fee, "per_guest_cents": per_guest,
         "guest_count_booked": guest_booked, "guest_count_final": guest_final,
         "tax_rate": tax_rate, "quoted_cents": quoted, "final_cents": 0,
         "captured_cents": quoted, "status": "BOOKED"}
    stamp_new(b)
    bookings[b["id"]] = b
    return respond(ser_booking(b), "object", 201)


@app.route("/slot-bookings/<bid>", methods=["GET"])
def get_booking(bid):
    uid, role = authctx()
    require_role(role, ROLES)
    b = must_get(bookings, bid)
    check_owner(role, uid, b["skater_id"])
    return respond(ser_booking(b), "object", 200)


@app.route("/slot-bookings", methods=["GET"])
def list_bookings():
    uid, role = authctx()
    require_role(role, ROLES)
    items = list(bookings.values())
    for key in ["ice_slot_id", "skater_id", "booking_type", "status"]:
        v = request.args.get(key)
        if v is not None:
            items = [x for x in items if x[key] == v]
    return list_response(items, ser_booking)


@app.route("/slot-bookings/<bid>/complete", methods=["POST"])
def complete_booking(bid):
    uid, role = authctx()
    require_role(role, {"RinkManager"})
    b = must_get(bookings, bid)
    if b["status"] != "BOOKED":
        err("ERR_INVALID_STATE", 409, "booking is not BOOKED")
    slot = ice_slots.get(b["ice_slot_id"])
    if slot is None or CLOCK["now"] < slot["_end"]:
        err("ERR_INVALID_STATE", 409, "slot end time not reached")
    body = body_json()
    if b["booking_type"] == "PARTY":
        if body.get("guest_count_final") is not None:
            b["guest_count_final"] = as_int(body["guest_count_final"], "guest_count_final", min_val=0)
        final = party_charge(b["base_fee_cents"], b["per_guest_cents"], b["tax_rate"], b["guest_count_final"])
    else:
        final = b["quoted_cents"]
    delta = final - b["captured_cents"]
    if delta != 0:
        skater = skaters.get(b["skater_id"])
        if skater is not None:
            charge_wallet(skater, -delta)
    b["final_cents"] = final
    b["captured_cents"] = final
    b["status"] = "COMPLETED"
    touch(b)
    return respond(ser_booking(b), "object", 200)


@app.route("/slot-bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    uid, role = authctx()
    require_role(role, {"Skater", "RinkManager"})
    b = must_get(bookings, bid)
    check_owner(role, uid, b["skater_id"])
    if b["status"] != "BOOKED":
        err("ERR_INVALID_STATE", 409, "booking is not BOOKED")
    skater = skaters.get(b["skater_id"])
    if skater is not None:
        charge_wallet(skater, b["captured_cents"])
    b["captured_cents"] = 0
    b["status"] = "CANCELLED"
    touch(b)
    return respond(ser_booking(b), "object", 200)


# ---- Sharpening orders ---------------------------------------------------
@app.route("/sharpening-orders", methods=["POST"])
def create_sharpening():
    uid, role = authctx()
    require_role(role, {"Skater", "FrontDesk"})
    body = body_json()
    body_skater = body.get("skater_id")
    if role == "Skater" and body_skater is not None and body_skater != uid:
        err("ERR_UNAUTHORIZED", 403, "skater may only submit own order")
    skater_id = body.get("skater_id")
    if skater_id is not None:
        skater = must_get(skaters, skater_id)
    skater_id = as_str(need(body, "skater_id"), "skater_id")
    skater = must_get(skaters, skater_id)
    skate_type = as_enum(need(body, "skate_type"), "skate_type", SKATE_TYPES)
    price = as_int(need(body, "price_cents"), "price_cents", min_val=0)
    o = {"id": new_id(), "skater_id": skater_id, "skate_type": skate_type,
         "price_cents": price, "status": "RECEIVED"}
    stamp_new(o)
    sharpenings[o["id"]] = o
    return respond(ser_sharpening(o), "object", 201)


@app.route("/sharpening-orders/<oid>", methods=["GET"])
def get_sharpening(oid):
    uid, role = authctx()
    require_role(role, ROLES)
    o = must_get(sharpenings, oid)
    check_owner(role, uid, o["skater_id"])
    return respond(ser_sharpening(o), "object", 200)


@app.route("/sharpening-orders", methods=["GET"])
def list_sharpening():
    uid, role = authctx()
    require_role(role, ROLES)
    items = list(sharpenings.values())
    for key in ["skater_id", "status"]:
        v = request.args.get(key)
        if v is not None:
            items = [x for x in items if x[key] == v]
    return list_response(items, ser_sharpening)


@app.route("/sharpening-orders/<oid>/advance", methods=["POST"])
def advance_sharpening(oid):
    uid, role = authctx()
    require_role(role, {"FrontDesk"})
    o = must_get(sharpenings, oid)
    nxt = {"RECEIVED": "IN_PROGRESS", "IN_PROGRESS": "READY", "READY": "PICKED_UP"}
    if o["status"] not in nxt:
        err("ERR_INVALID_STATE", 409, "order cannot be advanced")
    o["status"] = nxt[o["status"]]
    touch(o)
    return respond(ser_sharpening(o), "object", 200)


# --------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
