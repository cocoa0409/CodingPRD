import os
import re
import uuid
import random
import string
import functools
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# =============================================================================
# Constants (from PRD / SCAFFOLD)
# =============================================================================
PORT_FEE_PCT = Decimal("0.075")
FUEL_PCT = Decimal("0.22")
MIN_CHARGE_CENTS = 50000
VOLUME_THRESHOLD_CENTS = 100000
VOLUME_DISCOUNT_PCT = Decimal("0.10")
LEGAL_LIMIT_LBS = 80000
DRIVER_TURNAROUND_BUFFER_MIN = 60

ROLES = {"Dispatcher", "Driver", "Biller"}

DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

# =============================================================================
# In-memory store (starts empty on every boot; never seeded)
# =============================================================================
DB = {
    "terminals": {},
    "chassis": {},
    "drivers": {},
    "bookings": {},
    "appointments": {},
    "legs": {},
    "weigh_tickets": {},
    "permits": {},
    "invoices": {},
    "accessorials": {},
}

NOT_FOUND = {
    "terminals": "ERR_TERMINAL_NOT_FOUND",
    "chassis": "ERR_CHASSIS_NOT_FOUND",
    "drivers": "ERR_DRIVER_NOT_FOUND",
    "bookings": "ERR_BOOKING_NOT_FOUND",
    "appointments": "ERR_APPOINTMENT_NOT_FOUND",
    "legs": "ERR_LEG_NOT_FOUND",
    "weigh_tickets": "ERR_WEIGH_TICKET_NOT_FOUND",
    "permits": "ERR_PERMIT_NOT_FOUND",
    "invoices": "ERR_INVOICE_NOT_FOUND",
    "accessorials": "ERR_ACCESSORIAL_NOT_FOUND",
}

CLOCK = {"now": DEFAULT_CLOCK}
_SEQ = [0]


def next_seq():
    _SEQ[0] += 1
    return _SEQ[0]


# =============================================================================
# Errors
# =============================================================================
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# =============================================================================
# Time helpers
# =============================================================================
def now_iso_ms():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def iso_ms(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    m = re.match(r"^(.*T\d{2}:\d{2}:\d{2})(\.\d+)?(.*)$", t)
    if m:
        base, frac, tail = m.group(1), m.group(2), m.group(3)
        if frac:
            digits = (frac[1:] + "000000")[:6]
            frac = "." + digits
        else:
            frac = ""
        t = base + frac + tail
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# =============================================================================
# Rounding / calculations
# =============================================================================
def round_half_up(dec_value):
    return int(Decimal(dec_value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def demurrage_amount(booking, basis):
    term = DB["terminals"][booking["origin_terminal_id"]]
    per_day = round_half_up(Decimal(term["demurrage_daily_rate_cents"]) * (Decimal(1) + PORT_FEE_PCT))
    days = max(0, (basis.date() - booking["last_free_day"].date()).days)
    return per_day * days


def per_diem_amount(chassis, basis):
    if chassis["assigned_out_at"] is None:
        return 0
    days_out = max(0, (basis.date() - chassis["assigned_out_at"].date()).days)
    chargeable = max(0, days_out - chassis["free_days"])
    return chassis["per_diem_rate_cents"] * chargeable


# =============================================================================
# Response envelope
# =============================================================================
def _meta(extra=None):
    m = {
        "api_request_id": "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20)),
        "api_request_timestamp": now_iso_ms(),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, code=200, response_type="object", meta_extra=None):
    body = {"meta": _meta(meta_extra), "response_type": response_type, "data": data}
    return jsonify(body), code


@app.errorhandler(ApiError)
def _handle_api_error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# =============================================================================
# Auth / RBAC
# =============================================================================
def require_auth(allowed_roles):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **k):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role or role not in ROLES:
                raise ApiError("ERR_UNAUTHENTICATED", 401)
            if role not in allowed_roles:
                raise ApiError("ERR_UNAUTHORIZED", 403)
            g.user_id = uid
            g.role = role
            return fn(*a, **k)
        return wrapper
    return deco


READ_ROLES = ("Dispatcher", "Biller", "Driver")


# =============================================================================
# Common field helpers
# =============================================================================
def new_common(with_version=True):
    now = now_iso_ms()
    d = {"id": str(uuid.uuid4()), "created_at": now, "_seq": next_seq()}
    if with_version:
        d["updated_at"] = now
        d["version"] = 1
    return d


def touch(entity):
    entity["updated_at"] = now_iso_ms()
    entity["version"] += 1


# =============================================================================
# Body / validation helpers
# =============================================================================
def body():
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


def v_str(b, field, required=True):
    if field not in b or b[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", 400, f"{field} is required")
        return None
    if not isinstance(b[field], str):
        raise ApiError("ERR_VALIDATION", 400, f"{field} must be a string")
    return b[field]


def v_int_nonneg(b, field, required=True):
    if field not in b or b[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", 400, f"{field} is required")
        return None
    val = b[field]
    if isinstance(val, bool) or not isinstance(val, int) or val < 0:
        raise ApiError("ERR_VALIDATION", 400, f"{field} must be a non-negative integer")
    return val


def v_int(b, field, required=True):
    if field not in b or b[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", 400, f"{field} is required")
        return None
    val = b[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise ApiError("ERR_VALIDATION", 400, f"{field} must be an integer")
    return val


def v_enum(b, field, allowed, required=True, default=None):
    if field not in b or b[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", 400, f"{field} is required")
        return default
    if b[field] not in allowed:
        raise ApiError("ERR_VALIDATION", 400, f"{field} is invalid")
    return b[field]


def v_dt(b, field, required=True):
    if field not in b or b[field] is None:
        if required:
            raise ApiError("ERR_VALIDATION", 400, f"{field} is required")
        return None
    try:
        return parse_iso(b[field])
    except Exception:
        raise ApiError("ERR_VALIDATION", 400, f"{field} must be a valid ISO8601 datetime")


def get_or_404(coll, id_):
    if id_ is None:
        raise ApiError(NOT_FOUND[coll], 404)
    e = DB[coll].get(id_)
    if e is None:
        raise ApiError(NOT_FOUND[coll], 404)
    return e


# =============================================================================
# Pagination
# =============================================================================
def paginate(items):
    items = sorted(items, key=lambda x: x["_seq"])
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = 10
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            offset = 0
        if offset < 0:
            offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta


def list_response(coll_items, serializer, extra_meta=None):
    page, pmeta = paginate(coll_items)
    if extra_meta:
        pmeta.update(extra_meta)
    return ok([serializer(x) for x in page], code=200, response_type="array", meta_extra=pmeta)


# =============================================================================
# Serializers
# =============================================================================
def ser_terminal(t):
    return {
        "id": t["id"],
        "name": t["name"],
        "code": t["code"],
        "demurrage_daily_rate_cents": t["demurrage_daily_rate_cents"],
        "slot_capacity_per_window": t["slot_capacity_per_window"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def ser_chassis(c):
    provisional = 0
    if c["status"] == "OUT":
        provisional = per_diem_amount(c, CLOCK["now"])
    return {
        "id": c["id"],
        "chassis_number": c["chassis_number"],
        "pool_scac": c["pool_scac"],
        "per_diem_rate_cents": c["per_diem_rate_cents"],
        "free_days": c["free_days"],
        "status": c["status"],
        "assigned_out_at": iso_ms(c["assigned_out_at"]),
        "returned_at": iso_ms(c["returned_at"]),
        "per_diem_provisional_cents": provisional,
        "per_diem_final_cents": c["per_diem_final_cents"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_driver(d):
    return {
        "id": d["id"],
        "name": d["name"],
        "license_number": d["license_number"],
        "status": d["status"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def ser_booking(b):
    return {
        "id": b["id"],
        "container_number": b["container_number"],
        "direction": b["direction"],
        "container_size": b["container_size"],
        "origin_terminal_id": b["origin_terminal_id"],
        "chassis_id": b["chassis_id"],
        "last_free_day": iso_ms(b["last_free_day"]),
        "linehaul_base_cents": b["linehaul_base_cents"],
        "gross_weight_lbs": b["gross_weight_lbs"],
        "requires_permit": b["requires_permit"],
        "scheduled_pickup_at": iso_ms(b["scheduled_pickup_at"]),
        "actual_pickup_at": iso_ms(b["actual_pickup_at"]),
        "demurrage_estimate_cents": b["demurrage_estimate_cents"],
        "demurrage_actual_cents": b["demurrage_actual_cents"],
        "per_diem_final_cents": b["per_diem_final_cents"],
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def ser_appointment(a):
    return {
        "id": a["id"],
        "booking_id": a["booking_id"],
        "terminal_id": a["terminal_id"],
        "purpose": a["purpose"],
        "window_start": iso_ms(a["window_start"]),
        "window_end": iso_ms(a["window_end"]),
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_leg(l):
    return {
        "id": l["id"],
        "booking_id": l["booking_id"],
        "driver_id": l["driver_id"],
        "appointment_id": l["appointment_id"],
        "linked_export_booking_id": l["linked_export_booking_id"],
        "leg_type": l["leg_type"],
        "window_start": iso_ms(l["window_start"]),
        "window_end": iso_ms(l["window_end"]),
        "status": l["status"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def ser_weigh_ticket(w):
    return {
        "id": w["id"],
        "booking_id": w["booking_id"],
        "gross_weight_lbs": w["gross_weight_lbs"],
        "is_overweight": w["is_overweight"],
        "weighed_at": iso_ms(w["weighed_at"]),
        "created_at": w["created_at"],
    }


def ser_permit(p):
    return {
        "id": p["id"],
        "booking_id": p["booking_id"],
        "permit_number": p["permit_number"],
        "max_gross_weight_lbs": p["max_gross_weight_lbs"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_invoice(inv):
    return {
        "id": inv["id"],
        "booking_id": inv["booking_id"],
        "linehaul_base_cents": inv["linehaul_base_cents"],
        "effective_linehaul_cents": inv["effective_linehaul_cents"],
        "fuel_surcharge_cents": inv["fuel_surcharge_cents"],
        "accessorials_total_cents": inv["accessorials_total_cents"],
        "demurrage_cents": inv["demurrage_cents"],
        "per_diem_cents": inv["per_diem_cents"],
        "total_charge_cents": inv["total_charge_cents"],
        "status": inv["status"],
        "created_at": inv["created_at"],
        "updated_at": inv["updated_at"],
        "version": inv["version"],
    }


def ser_accessorial(a):
    return {
        "id": a["id"],
        "invoice_id": a["invoice_id"],
        "kind": a["kind"],
        "amount_cents": a["amount_cents"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


# =============================================================================
# Invoice computation
# =============================================================================
def compute_invoice_at_generation(inv, booking):
    base = booking["linehaul_base_cents"]
    inv["linehaul_base_cents"] = base
    if base >= VOLUME_THRESHOLD_CENTS:
        eff = round_half_up(Decimal(base) * (Decimal(1) - VOLUME_DISCOUNT_PCT))
    else:
        eff = base
    inv["effective_linehaul_cents"] = eff
    inv["fuel_surcharge_cents"] = round_half_up(Decimal(eff) * FUEL_PCT)
    inv["demurrage_cents"] = booking["demurrage_actual_cents"]
    inv["per_diem_cents"] = booking["per_diem_final_cents"]
    recompute_invoice_totals(inv)


def recompute_invoice_totals(inv):
    acc_total = sum(
        a["amount_cents"]
        for a in DB["accessorials"].values()
        if a["invoice_id"] == inv["id"] and a["status"] == "ACTIVE"
    )
    inv["accessorials_total_cents"] = acc_total
    subtotal = (
        inv["effective_linehaul_cents"]
        + inv["fuel_surcharge_cents"]
        + acc_total
        + inv["demurrage_cents"]
        + inv["per_diem_cents"]
    )
    inv["total_charge_cents"] = max(subtotal, MIN_CHARGE_CENTS)


# =============================================================================
# Shared business helpers
# =============================================================================
def check_driver_available(driver_id, ws, we, exclude_leg_id=None):
    buf = timedelta(minutes=DRIVER_TURNAROUND_BUFFER_MIN)
    for l in DB["legs"].values():
        if l["driver_id"] != driver_id:
            continue
        if l["status"] not in ("PLANNED", "DISPATCHED"):
            continue
        if exclude_leg_id is not None and l["id"] == exclude_leg_id:
            continue
        a = l["window_start"] - buf
        b = l["window_end"] + buf
        # closed-interval overlap of [a,b] and [ws,we]
        if a <= we and ws <= b:
            raise ApiError("ERR_DRIVER_UNAVAILABLE", 409)


def check_slot_capacity(terminal, ws, we):
    cap = terminal["slot_capacity_per_window"]
    count = 0
    for ap in DB["appointments"].values():
        if ap["terminal_id"] != terminal["id"]:
            continue
        if ap["status"] != "BOOKED":
            continue
        # half-open [ws,we) intersection
        if ap["window_start"] < we and ws < ap["window_end"]:
            count += 1
    if count >= cap:
        raise ApiError("ERR_APPOINTMENT_SLOT_FULL", 409)


def release_chassis_finalize(chassis):
    """OUT -> AVAILABLE, stamp returned_at, finalize per-diem. No booking cascade."""
    chassis["status"] = "AVAILABLE"
    chassis["returned_at"] = CLOCK["now"]
    chassis["per_diem_final_cents"] = per_diem_amount(chassis, CLOCK["now"])
    touch(chassis)


def cancel_leg_internal(leg):
    """Cancel a non-terminal leg; release an OUT chassis it took out."""
    if leg["leg_type"] == "PICKUP" and leg["status"] == "DISPATCHED":
        booking = DB["bookings"].get(leg["booking_id"])
        if booking and booking["chassis_id"]:
            ch = DB["chassis"].get(booking["chassis_id"])
            if ch and ch["status"] == "OUT":
                release_chassis_finalize(ch)
    leg["status"] = "CANCELED"
    touch(leg)


BOOKING_TERMINAL = ("EMPTY_RETURNED", "CANCELED")


# =============================================================================
# Health
# =============================================================================
@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


# =============================================================================
# Logical clock
# =============================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
@require_auth(("Dispatcher",))
def set_clock():
    b = body()
    dt = v_dt(b, "to_iso8601")
    CLOCK["now"] = dt
    return ok({}, code=200)


# =============================================================================
# Terminals
# =============================================================================
@app.route("/terminals", methods=["POST"])
@require_auth(("Dispatcher",))
def create_terminal():
    b = body()
    name = v_str(b, "name")
    code = v_str(b, "code")
    rate = v_int_nonneg(b, "demurrage_daily_rate_cents")
    cap = v_int(b, "slot_capacity_per_window", required=False)
    if cap is None:
        cap = 1
    elif cap < 1:
        raise ApiError("ERR_VALIDATION", 400, "slot_capacity_per_window must be >= 1")
    t = new_common()
    t.update({
        "name": name,
        "code": code,
        "demurrage_daily_rate_cents": rate,
        "slot_capacity_per_window": cap,
    })
    DB["terminals"][t["id"]] = t
    return ok(ser_terminal(t), code=201)


@app.route("/terminals/<tid>", methods=["GET"])
@require_auth(READ_ROLES)
def get_terminal(tid):
    return ok(ser_terminal(get_or_404("terminals", tid)))


# =============================================================================
# Chassis
# =============================================================================
@app.route("/chassis", methods=["POST"])
@require_auth(("Dispatcher",))
def create_chassis():
    b = body()
    number = v_str(b, "chassis_number")
    scac = v_str(b, "pool_scac")
    rate = v_int_nonneg(b, "per_diem_rate_cents")
    free_days = v_int_nonneg(b, "free_days", required=False)
    if free_days is None:
        free_days = 4
    c = new_common()
    c.update({
        "chassis_number": number,
        "pool_scac": scac,
        "per_diem_rate_cents": rate,
        "free_days": free_days,
        "status": "AVAILABLE",
        "assigned_out_at": None,
        "returned_at": None,
        "per_diem_final_cents": 0,
    })
    DB["chassis"][c["id"]] = c
    return ok(ser_chassis(c), code=201)


@app.route("/chassis/<cid>", methods=["GET"])
@require_auth(READ_ROLES)
def get_chassis(cid):
    return ok(ser_chassis(get_or_404("chassis", cid)))


# =============================================================================
# Drivers
# =============================================================================
@app.route("/drivers", methods=["POST"])
@require_auth(("Dispatcher",))
def create_driver():
    b = body()
    name = v_str(b, "name")
    lic = v_str(b, "license_number")
    status = v_enum(b, "status", ("ACTIVE", "INACTIVE"), required=False, default="ACTIVE")
    d = new_common()
    d.update({"name": name, "license_number": lic, "status": status})
    DB["drivers"][d["id"]] = d
    return ok(ser_driver(d), code=201)


@app.route("/drivers/<did>", methods=["GET"])
@require_auth(READ_ROLES)
def get_driver(did):
    return ok(ser_driver(get_or_404("drivers", did)))


# =============================================================================
# Bookings
# =============================================================================
@app.route("/bookings", methods=["POST"])
@require_auth(("Dispatcher",))
def create_booking():
    b = body()
    container_number = v_str(b, "container_number")
    direction = v_enum(b, "direction", ("IMPORT", "EXPORT"))
    origin_terminal_id = v_str(b, "origin_terminal_id")
    last_free_day = v_dt(b, "last_free_day")
    linehaul_base_cents = v_int_nonneg(b, "linehaul_base_cents")
    container_size = v_enum(b, "container_size", ("D20", "D40", "HC40"), required=False, default="D40")
    # existence of FK
    get_or_404("terminals", origin_terminal_id)
    bk = new_common()
    bk.update({
        "container_number": container_number,
        "direction": direction,
        "container_size": container_size,
        "origin_terminal_id": origin_terminal_id,
        "chassis_id": None,
        "last_free_day": last_free_day,
        "linehaul_base_cents": linehaul_base_cents,
        "gross_weight_lbs": None,
        "requires_permit": False,
        "scheduled_pickup_at": None,
        "actual_pickup_at": None,
        "demurrage_estimate_cents": 0,
        "demurrage_actual_cents": 0,
        "per_diem_final_cents": 0,
        "status": "DRAFT",
    })
    DB["bookings"][bk["id"]] = bk
    return ok(ser_booking(bk), code=201)


@app.route("/bookings/<bid>", methods=["GET"])
@require_auth(READ_ROLES)
def get_booking(bid):
    return ok(ser_booking(get_or_404("bookings", bid)))


@app.route("/bookings", methods=["GET"])
@require_auth(READ_ROLES)
def list_bookings():
    items = list(DB["bookings"].values())
    origin = request.args.get("origin_terminal_id")
    chassis_id = request.args.get("chassis_id")
    status = request.args.get("status")
    if origin is not None:
        items = [x for x in items if x["origin_terminal_id"] == origin]
    if chassis_id is not None:
        items = [x for x in items if x["chassis_id"] == chassis_id]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    return list_response(items, ser_booking)


@app.route("/bookings/<bid>/confirm", methods=["POST"])
@require_auth(("Dispatcher",))
def confirm_booking(bid):
    bk = get_or_404("bookings", bid)
    if bk["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409)
    bk["status"] = "CONFIRMED"
    touch(bk)
    return ok(ser_booking(bk))


@app.route("/bookings/<bid>/assign-chassis", methods=["POST"])
@require_auth(("Dispatcher",))
def assign_chassis(bid):
    bk = get_or_404("bookings", bid)  # existence (path)
    b = body()
    chassis_id = b.get("chassis_id")
    # existence of body FK (left-to-right, after path) when present
    if isinstance(chassis_id, str):
        get_or_404("chassis", chassis_id)
    # body well-formedness
    chassis_id = v_str(b, "chassis_id")
    expected = v_int(b, "expected_booking_version")
    target = DB["chassis"].get(chassis_id)
    if target is None:
        raise ApiError("ERR_CHASSIS_NOT_FOUND", 404)
    # state validity (6)
    if bk["status"] not in ("CONFIRMED", "CHASSIS_ASSIGNED"):
        raise ApiError("ERR_INVALID_STATE", 409)
    # referenced-entity state (8): target chassis AVAILABLE
    if target["status"] != "AVAILABLE":
        raise ApiError("ERR_CHASSIS_UNAVAILABLE", 409)
    # OCC (13)
    if expected != bk["version"]:
        raise ApiError("ERR_STALE_BOOKING_VERSION", 412)
    # apply
    if bk["status"] == "CHASSIS_ASSIGNED" and bk["chassis_id"]:
        prev = DB["chassis"].get(bk["chassis_id"])
        if prev and prev["status"] == "ASSIGNED":
            prev["status"] = "AVAILABLE"
            touch(prev)
    bk["chassis_id"] = target["id"]
    target["status"] = "ASSIGNED"
    touch(target)
    bk["status"] = "CHASSIS_ASSIGNED"
    touch(bk)
    return ok(ser_booking(bk))


@app.route("/bookings/<bid>/release-chassis", methods=["POST"])
@require_auth(("Dispatcher",))
def release_chassis(bid):
    bk = get_or_404("bookings", bid)
    if bk["status"] != "CHASSIS_ASSIGNED":
        raise ApiError("ERR_INVALID_STATE", 409)
    ch = DB["chassis"].get(bk["chassis_id"]) if bk["chassis_id"] else None
    if ch is None or ch["status"] != "ASSIGNED":
        raise ApiError("ERR_INVALID_STATE", 409)
    ch["status"] = "AVAILABLE"
    touch(ch)
    bk["chassis_id"] = None
    bk["status"] = "CONFIRMED"
    touch(bk)
    return ok(ser_booking(bk))


@app.route("/bookings/<bid>/cancel", methods=["POST"])
@require_auth(("Dispatcher",))
def cancel_booking(bid):
    bk = get_or_404("bookings", bid)
    if bk["status"] in BOOKING_TERMINAL:
        raise ApiError("ERR_INVALID_STATE", 409)
    for leg in list(DB["legs"].values()):
        if leg["booking_id"] == bk["id"] and leg["status"] in ("PLANNED", "DISPATCHED"):
            cancel_leg_internal(leg)
    bk["status"] = "CANCELED"
    touch(bk)
    return ok(ser_booking(bk))


# =============================================================================
# Weigh tickets
# =============================================================================
@app.route("/weigh-tickets", methods=["POST"])
@require_auth(("Dispatcher",))
def create_weigh_ticket():
    b = body()
    booking_id = b.get("booking_id")
    if isinstance(booking_id, str):
        get_or_404("bookings", booking_id)
    booking_id = v_str(b, "booking_id")
    gross = v_int_nonneg(b, "gross_weight_lbs")
    booking = DB["bookings"].get(booking_id)
    if booking is None:
        raise ApiError("ERR_BOOKING_NOT_FOUND", 404)
    overweight = gross > LEGAL_LIMIT_LBS
    w = new_common(with_version=False)
    w.update({
        "booking_id": booking_id,
        "gross_weight_lbs": gross,
        "is_overweight": overweight,
        "weighed_at": CLOCK["now"],
    })
    DB["weigh_tickets"][w["id"]] = w
    booking["gross_weight_lbs"] = gross
    if overweight:
        booking["requires_permit"] = True
    touch(booking)
    return ok(ser_weigh_ticket(w), code=201)


@app.route("/weigh-tickets/<wid>", methods=["GET"])
@require_auth(READ_ROLES)
def get_weigh_ticket(wid):
    return ok(ser_weigh_ticket(get_or_404("weigh_tickets", wid)))


@app.route("/weigh-tickets", methods=["GET"])
@require_auth(READ_ROLES)
def list_weigh_tickets():
    items = list(DB["weigh_tickets"].values())
    booking_id = request.args.get("booking_id")
    if booking_id is not None:
        items = [x for x in items if x["booking_id"] == booking_id]
    return list_response(items, ser_weigh_ticket)


# =============================================================================
# Appointments
# =============================================================================
@app.route("/appointments", methods=["POST"])
@require_auth(("Dispatcher",))
def create_appointment():
    b = body()
    booking_id = b.get("booking_id")
    terminal_id = b.get("terminal_id")
    # existence left-to-right (present references)
    if isinstance(booking_id, str):
        get_or_404("bookings", booking_id)
    if isinstance(terminal_id, str):
        get_or_404("terminals", terminal_id)
    # body well-formedness
    booking_id = v_str(b, "booking_id")
    terminal_id = v_str(b, "terminal_id")
    purpose = v_enum(b, "purpose", ("PICKUP", "RETURN"))
    ws = v_dt(b, "window_start")
    we = v_dt(b, "window_end")
    if ws >= we:
        raise ApiError("ERR_VALIDATION", 400, "window_start must be before window_end")
    booking = DB["bookings"].get(booking_id)
    if booking is None:
        raise ApiError("ERR_BOOKING_NOT_FOUND", 404)
    terminal = DB["terminals"].get(terminal_id)
    if terminal is None:
        raise ApiError("ERR_TERMINAL_NOT_FOUND", 404)
    # slot capacity (10)
    check_slot_capacity(terminal, ws, we)
    ap = new_common()
    ap.update({
        "booking_id": booking_id,
        "terminal_id": terminal_id,
        "purpose": purpose,
        "window_start": ws,
        "window_end": we,
        "status": "BOOKED",
    })
    DB["appointments"][ap["id"]] = ap
    # booking advance for PICKUP when CHASSIS_ASSIGNED
    if purpose == "PICKUP" and booking["status"] == "CHASSIS_ASSIGNED":
        booking["scheduled_pickup_at"] = ws
        booking["demurrage_estimate_cents"] = demurrage_amount(booking, ws)
        booking["status"] = "APPOINTED"
        touch(booking)
    return ok(ser_appointment(ap), code=201)


@app.route("/appointments/<aid>", methods=["GET"])
@require_auth(READ_ROLES)
def get_appointment(aid):
    return ok(ser_appointment(get_or_404("appointments", aid)))


@app.route("/appointments", methods=["GET"])
@require_auth(READ_ROLES)
def list_appointments():
    items = list(DB["appointments"].values())
    booking_id = request.args.get("booking_id")
    terminal_id = request.args.get("terminal_id")
    if booking_id is not None:
        items = [x for x in items if x["booking_id"] == booking_id]
    if terminal_id is not None:
        items = [x for x in items if x["terminal_id"] == terminal_id]
    return list_response(items, ser_appointment)


@app.route("/appointments/<aid>/cancel", methods=["POST"])
@require_auth(("Dispatcher",))
def cancel_appointment(aid):
    ap = get_or_404("appointments", aid)
    if ap["status"] != "BOOKED":
        raise ApiError("ERR_INVALID_STATE", 409)
    # no non-terminal PICKUP leg references this appointment
    for leg in DB["legs"].values():
        if (
            leg["appointment_id"] == ap["id"]
            and leg["leg_type"] == "PICKUP"
            and leg["status"] in ("PLANNED", "DISPATCHED")
        ):
            raise ApiError("ERR_INVALID_STATE", 409)
    ap["status"] = "CANCELED"
    touch(ap)
    if ap["purpose"] == "PICKUP":
        booking = DB["bookings"].get(ap["booking_id"])
        if booking and booking["status"] == "APPOINTED":
            booking["scheduled_pickup_at"] = None
            booking["status"] = "CHASSIS_ASSIGNED"
            touch(booking)
    return ok(ser_appointment(ap))


# =============================================================================
# Legs
# =============================================================================
@app.route("/legs", methods=["POST"])
@require_auth(("Dispatcher",))
def create_leg():
    b = body()
    booking_id = b.get("booking_id")
    driver_id = b.get("driver_id")
    appointment_id = b.get("appointment_id")
    linked_export_booking_id = b.get("linked_export_booking_id")
    # existence left-to-right (present references)
    if isinstance(booking_id, str):
        get_or_404("bookings", booking_id)
    if isinstance(driver_id, str):
        get_or_404("drivers", driver_id)
    if isinstance(appointment_id, str):
        get_or_404("appointments", appointment_id)
    if isinstance(linked_export_booking_id, str):
        get_or_404("bookings", linked_export_booking_id)
    # body well-formedness
    booking_id = v_str(b, "booking_id")
    driver_id = v_str(b, "driver_id")
    leg_type = v_enum(b, "leg_type", ("PICKUP", "RETURN", "STREET_TURN"))
    ws = v_dt(b, "window_start")
    we = v_dt(b, "window_end")
    if ws >= we:
        raise ApiError("ERR_VALIDATION", 400, "window_start must be before window_end")
    if leg_type == "PICKUP" and not appointment_id:
        raise ApiError("ERR_VALIDATION", 400, "appointment_id required for PICKUP leg")
    if leg_type == "STREET_TURN" and not linked_export_booking_id:
        raise ApiError("ERR_VALIDATION", 400, "linked_export_booking_id required for STREET_TURN leg")
    # ensure referenced entities resolved
    if booking_id not in DB["bookings"]:
        raise ApiError("ERR_BOOKING_NOT_FOUND", 404)
    if driver_id not in DB["drivers"]:
        raise ApiError("ERR_DRIVER_NOT_FOUND", 404)
    # driver availability (11)
    check_driver_available(driver_id, ws, we)
    leg = new_common()
    leg.update({
        "booking_id": booking_id,
        "driver_id": driver_id,
        "appointment_id": appointment_id if isinstance(appointment_id, str) else None,
        "linked_export_booking_id": linked_export_booking_id if isinstance(linked_export_booking_id, str) else None,
        "leg_type": leg_type,
        "window_start": ws,
        "window_end": we,
        "status": "PLANNED",
    })
    DB["legs"][leg["id"]] = leg
    return ok(ser_leg(leg), code=201)


@app.route("/legs/<lid>", methods=["GET"])
@require_auth(READ_ROLES)
def get_leg(lid):
    return ok(ser_leg(get_or_404("legs", lid)))


@app.route("/legs", methods=["GET"])
@require_auth(READ_ROLES)
def list_legs():
    items = list(DB["legs"].values())
    for key in ("booking_id", "driver_id", "appointment_id", "linked_export_booking_id"):
        val = request.args.get(key)
        if val is not None:
            items = [x for x in items if x[key] == val]
    return list_response(items, ser_leg)


@app.route("/legs/<lid>/dispatch", methods=["POST"])
@require_auth(("Dispatcher",))
def dispatch_leg(lid):
    leg = get_or_404("legs", lid)
    # state (6)
    if leg["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", 409)
    booking = DB["bookings"].get(leg["booking_id"])
    driver = DB["drivers"].get(leg["driver_id"])

    if leg["leg_type"] == "PICKUP":
        # permit gate (7)
        if booking and booking["requires_permit"]:
            has_permit = any(
                p["booking_id"] == booking["id"] and p["status"] == "APPROVED"
                for p in DB["permits"].values()
            )
            if not has_permit:
                raise ApiError("ERR_PERMIT_REQUIRED", 422)
        # referenced-entity states (8): chassis, appointment, driver (in order)
        ch = DB["chassis"].get(booking["chassis_id"]) if (booking and booking["chassis_id"]) else None
        if ch is None or ch["status"] != "ASSIGNED":
            raise ApiError("ERR_CHASSIS_NOT_ASSIGNED", 409)
        appt = DB["appointments"].get(leg["appointment_id"]) if leg["appointment_id"] else None
        if appt is None or appt["status"] != "BOOKED":
            raise ApiError("ERR_APPOINTMENT_NOT_BOOKED", 409)
        if driver is None or driver["status"] != "ACTIVE":
            raise ApiError("ERR_DRIVER_INACTIVE", 409)
        # appointment temporal (9)
        if not (CLOCK["now"] < appt["window_end"]):
            raise ApiError("ERR_APPOINTMENT_EXPIRED", 422)
        # apply
        leg["status"] = "DISPATCHED"
        touch(leg)
        appt["status"] = "USED"
        touch(appt)
        ch["status"] = "OUT"
        ch["assigned_out_at"] = CLOCK["now"]
        touch(ch)
        booking["actual_pickup_at"] = CLOCK["now"]
        booking["demurrage_actual_cents"] = demurrage_amount(booking, CLOCK["now"])
        booking["status"] = "DISPATCHED"
        touch(booking)
        return ok(ser_leg(leg))

    # RETURN / STREET_TURN dispatch: driver must be ACTIVE
    if driver is None or driver["status"] != "ACTIVE":
        raise ApiError("ERR_DRIVER_INACTIVE", 409)
    leg["status"] = "DISPATCHED"
    touch(leg)
    return ok(ser_leg(leg))


@app.route("/legs/<lid>/complete", methods=["POST"])
@require_auth(("Dispatcher", "Driver"))
def complete_leg(lid):
    leg = get_or_404("legs", lid)
    # ownership (5)
    if g.role == "Driver" and leg["driver_id"] != g.user_id:
        raise ApiError("ERR_LEG_NOT_OWNED", 403)
    # state (6)
    if leg["status"] != "DISPATCHED":
        raise ApiError("ERR_INVALID_STATE", 409)
    booking = DB["bookings"].get(leg["booking_id"])

    if leg["leg_type"] == "PICKUP":
        if booking is None or booking["status"] != "DISPATCHED":
            raise ApiError("ERR_INVALID_STATE", 409)
        leg["status"] = "COMPLETED"
        touch(leg)
        booking["status"] = "DELIVERED"
        touch(booking)
        return ok(ser_leg(leg))

    if leg["leg_type"] == "RETURN":
        if booking is None or booking["status"] != "DELIVERED":
            raise ApiError("ERR_INVALID_STATE", 409)
        ch = DB["chassis"].get(booking["chassis_id"]) if booking["chassis_id"] else None
        if ch is None or ch["status"] != "OUT":
            raise ApiError("ERR_INVALID_STATE", 409)
        # empty-return chain
        release_chassis_finalize(ch)
        booking["per_diem_final_cents"] = ch["per_diem_final_cents"]
        booking["status"] = "EMPTY_RETURNED"
        touch(booking)
        leg["status"] = "COMPLETED"
        touch(leg)
        return ok(ser_leg(leg))

    # STREET_TURN
    if booking is None or booking["status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_STATE", 409)
    export_booking = DB["bookings"].get(leg["linked_export_booking_id"])
    if export_booking is None:
        raise ApiError("ERR_BOOKING_NOT_FOUND", 404)
    if export_booking["direction"] != "EXPORT" or export_booking["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", 409)
    ch = DB["chassis"].get(booking["chassis_id"]) if booking["chassis_id"] else None
    if ch is None or ch["status"] != "OUT":
        raise ApiError("ERR_INVALID_STATE", 409)
    # per-diem snapshot as of current clock; chassis stays OUT
    booking["per_diem_final_cents"] = per_diem_amount(ch, CLOCK["now"])
    booking["status"] = "EMPTY_RETURNED"
    touch(booking)
    # reassign chassis to export booking (chassis not returned)
    export_booking["chassis_id"] = ch["id"]
    export_booking["status"] = "CHASSIS_ASSIGNED"
    touch(export_booking)
    leg["status"] = "COMPLETED"
    touch(leg)
    return ok(ser_leg(leg))


@app.route("/legs/<lid>/cancel", methods=["POST"])
@require_auth(("Dispatcher",))
def cancel_leg(lid):
    leg = get_or_404("legs", lid)
    if leg["status"] not in ("PLANNED", "DISPATCHED"):
        raise ApiError("ERR_INVALID_STATE", 409)
    cancel_leg_internal(leg)
    return ok(ser_leg(leg))


# =============================================================================
# Permits
# =============================================================================
@app.route("/permits", methods=["POST"])
@require_auth(("Dispatcher",))
def create_permit():
    b = body()
    booking_id = b.get("booking_id")
    if isinstance(booking_id, str):
        get_or_404("bookings", booking_id)
    booking_id = v_str(b, "booking_id")
    permit_number = v_str(b, "permit_number")
    max_gross = v_int_nonneg(b, "max_gross_weight_lbs")
    if booking_id not in DB["bookings"]:
        raise ApiError("ERR_BOOKING_NOT_FOUND", 404)
    p = new_common()
    p.update({
        "booking_id": booking_id,
        "permit_number": permit_number,
        "max_gross_weight_lbs": max_gross,
        "status": "REQUESTED",
    })
    DB["permits"][p["id"]] = p
    return ok(ser_permit(p), code=201)


@app.route("/permits/<pid>", methods=["GET"])
@require_auth(READ_ROLES)
def get_permit(pid):
    return ok(ser_permit(get_or_404("permits", pid)))


@app.route("/permits", methods=["GET"])
@require_auth(READ_ROLES)
def list_permits():
    items = list(DB["permits"].values())
    booking_id = request.args.get("booking_id")
    if booking_id is not None:
        items = [x for x in items if x["booking_id"] == booking_id]
    return list_response(items, ser_permit)


@app.route("/permits/<pid>/approve", methods=["POST"])
@require_auth(("Dispatcher",))
def approve_permit(pid):
    p = get_or_404("permits", pid)
    if p["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409)
    p["status"] = "APPROVED"
    touch(p)
    return ok(ser_permit(p))


# =============================================================================
# Invoices
# =============================================================================
@app.route("/invoices", methods=["POST"])
@require_auth(("Biller",))
def create_invoice():
    b = body()
    booking_id = b.get("booking_id")
    if isinstance(booking_id, str):
        get_or_404("bookings", booking_id)
    booking_id = v_str(b, "booking_id")
    booking = DB["bookings"].get(booking_id)
    if booking is None:
        raise ApiError("ERR_BOOKING_NOT_FOUND", 404)
    # invoiceability (12)
    if booking["status"] not in ("DELIVERED", "EMPTY_RETURNED"):
        raise ApiError("ERR_NOT_INVOICEABLE", 409)
    if any(inv["booking_id"] == booking_id for inv in DB["invoices"].values()):
        raise ApiError("ERR_NOT_INVOICEABLE", 409)
    inv = new_common()
    inv.update({
        "booking_id": booking_id,
        "linehaul_base_cents": 0,
        "effective_linehaul_cents": 0,
        "fuel_surcharge_cents": 0,
        "accessorials_total_cents": 0,
        "demurrage_cents": 0,
        "per_diem_cents": 0,
        "total_charge_cents": 0,
        "status": "DRAFT",
    })
    compute_invoice_at_generation(inv, booking)
    DB["invoices"][inv["id"]] = inv
    return ok(ser_invoice(inv), code=201)


@app.route("/invoices/<iid>", methods=["GET"])
@require_auth(READ_ROLES)
def get_invoice(iid):
    return ok(ser_invoice(get_or_404("invoices", iid)))


@app.route("/invoices", methods=["GET"])
@require_auth(READ_ROLES)
def list_invoices():
    items = list(DB["invoices"].values())
    booking_id = request.args.get("booking_id")
    if booking_id is not None:
        items = [x for x in items if x["booking_id"] == booking_id]
    return list_response(items, ser_invoice)


@app.route("/invoices/<iid>/issue", methods=["POST"])
@require_auth(("Biller",))
def issue_invoice(iid):
    inv = get_or_404("invoices", iid)
    if inv["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409)
    inv["status"] = "ISSUED"
    touch(inv)
    return ok(ser_invoice(inv))


@app.route("/invoices/<iid>/accessorials", methods=["POST"])
@require_auth(("Biller",))
def add_accessorial(iid):
    inv = get_or_404("invoices", iid)
    b = body()
    kind = v_enum(b, "kind", ("CHASSIS_RENTAL", "PRE_PULL", "STORAGE", "HAZMAT", "REEFER"))
    amount = v_int_nonneg(b, "amount_cents")
    # invoiceability (12): parent DRAFT
    if inv["status"] != "DRAFT":
        raise ApiError("ERR_NOT_INVOICEABLE", 409)
    a = new_common()
    a.update({
        "invoice_id": inv["id"],
        "kind": kind,
        "amount_cents": amount,
        "status": "ACTIVE",
    })
    DB["accessorials"][a["id"]] = a
    recompute_invoice_totals(inv)
    touch(inv)
    return ok(ser_accessorial(a), code=201)


@app.route("/invoices/<iid>/accessorials", methods=["GET"])
@require_auth(READ_ROLES)
def list_accessorials(iid):
    inv = get_or_404("invoices", iid)
    items = [a for a in DB["accessorials"].values() if a["invoice_id"] == inv["id"]]
    return list_response(items, ser_accessorial)


@app.route("/invoices/<iid>/accessorials/<aid>/void", methods=["POST"])
@require_auth(("Biller",))
def void_accessorial(iid, aid):
    inv = get_or_404("invoices", iid)
    a = DB["accessorials"].get(aid)
    if a is None or a["invoice_id"] != inv["id"]:
        raise ApiError("ERR_ACCESSORIAL_NOT_FOUND", 404)
    # state (6): accessorial ACTIVE
    if a["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409)
    # invoiceability (12): parent DRAFT
    if inv["status"] != "DRAFT":
        raise ApiError("ERR_NOT_INVOICEABLE", 409)
    a["status"] = "VOIDED"
    touch(a)
    recompute_invoice_totals(inv)
    touch(inv)
    return ok(ser_accessorial(a))


# =============================================================================
# Entrypoint
# =============================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
