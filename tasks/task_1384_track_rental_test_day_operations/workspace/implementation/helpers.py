"""Auth, body validation, path resolution, and shared domain logic."""

from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from flask import request

import db
import errors

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
ROLES = {"TrackOps", "SafetyOfficer", "Organizer", "Coach"}

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
CERT_LEVELS = {"BASIC", "INTERMEDIATE", "RACE"}
TRACK_DAY_STATUSES = {"SCHEDULED", "OPEN", "WEATHER_HOLD", "RUNNING", "STOPPED", "CLOSED", "CANCELLED"}
RUN_GROUP_CLASSES = {"NOVICE", "INTERMEDIATE", "ADVANCED", "RACE"}
SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
INCIDENT_STATUSES = {"OPEN", "INVESTIGATING", "CLEARED"}
SESSION_STATUSES = {"GREEN", "RED", "BLACK", "CHECKERED"}
BOOKING_APPROVAL_STATUSES = {"PENDING", "APPROVED", "REJECTED", "CANCELLED"}
LICENSE_CLASSES = {"STREET", "CLUB", "PRO"}
CANCEL_REASONS = {"CUSTOMER", "WEATHER", "SAFETY"}
ASSIGNMENT_STATUSES = {"ACTIVE", "RELEASED"}
BLOCK_STATUSES = {"OPEN", "FULL", "CLOSED"}
PAYMENT_OUTCOMES = {"AUTHORIZE", "CAPTURE", "VOID", "REFUND"}

# ---------------------------------------------------------------------------
# Domain constants
# ---------------------------------------------------------------------------
NOISE_BREACH_CAUTION_THRESHOLD = 1
NOISE_BREACH_SUSPENSION_THRESHOLD = 3
NOISE_WINDOW_MINUTES = 60
WAIVER_TTL_HOURS = 24 * 365
MIN_LAPS_FOR_CHECKERED = 1
FULL_REFUND_HOURS = 72
HALF_REFUND_HOURS = 24
WEATHER_FACILITY_FEE_CENTS = 5000
FEE_PER_DRIVER_CENTS = 35000
GARAGE_BASE_FEE_CENTS = 15000
POWER_TIER1_CENTS = 2500
POWER_TIER2_CENTS = 4000
WATER_FLAT_CENTS = 3000
MAX_BOOKINGS_PER_COACH = 3


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def now_str():
    return db.CURRENT_UTC


def parse_dt(s):
    if not isinstance(s, str):
        raise errors.invalid_request("expected an ISO-8601 timestamp string")
    text = s
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise errors.invalid_request("malformed ISO-8601 timestamp: %r" % s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:23] + "Z"


def validate_date(s, field):
    if not isinstance(s, str):
        raise errors.invalid_request("field %r must be a YYYY-MM-DD date string" % field)
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        raise errors.invalid_request("field %r must be a YYYY-MM-DD date string" % field)
    return s


# ---------------------------------------------------------------------------
# Auth (PRD §2.1, §2.9 checks 1-2)
# ---------------------------------------------------------------------------
def caller_role():
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        raise errors.unauthenticated()
    return role


def caller_id():
    return request.headers.get("X-User-ID")


def require_roles(*roles):
    role = caller_role()
    if role not in roles:
        raise errors.forbidden_role()
    return role


# ---------------------------------------------------------------------------
# Request body validation (PRD §2.9 check 4)
# ---------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise errors.invalid_request("request body must be a JSON object")
    return data


def req_string(data, field, allow_empty=False):
    if field not in data or not isinstance(data[field], str):
        raise errors.invalid_request("field %r is required and must be a string" % field)
    if not allow_empty and data[field] == "":
        raise errors.invalid_request("field %r must be a non-empty string" % field)
    return data[field]


def opt_string(data, field, allow_empty=True):
    if field not in data or data[field] is None:
        return None
    if not isinstance(data[field], str):
        raise errors.invalid_request("field %r must be a string" % field)
    if not allow_empty and data[field] == "":
        raise errors.invalid_request("field %r must be a non-empty string" % field)
    return data[field]


def req_int(data, field):
    if field not in data or isinstance(data[field], bool) or not isinstance(data[field], int):
        raise errors.invalid_request("field %r is required and must be an integer" % field)
    return data[field]


def opt_int(data, field):
    if field not in data or data[field] is None:
        return None
    if isinstance(data[field], bool) or not isinstance(data[field], int):
        raise errors.invalid_request("field %r must be an integer" % field)
    return data[field]


def req_bool(data, field):
    if field not in data or not isinstance(data[field], bool):
        raise errors.invalid_request("field %r is required and must be a boolean" % field)
    return data[field]


def opt_bool(data, field):
    if field not in data or data[field] is None:
        return None
    if not isinstance(data[field], bool):
        raise errors.invalid_request("field %r must be a boolean" % field)
    return data[field]


def req_enum(data, field, allowed):
    value = req_string(data, field)
    if value not in allowed:
        raise errors.invalid_request("field %r must be one of %s" % (field, sorted(allowed)))
    return value


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def pagination():
    args = request.args
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.invalid_request("limit must be between 1 and 100")
    else:
        limit = 10
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("offset must be an integer")
        if offset < 0:
            raise errors.invalid_request("offset must be at least 0")
    else:
        offset = 0
    return limit, offset


def parse_bool_param(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    lowered = raw.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    raise errors.invalid_request("query parameter %r must be true or false" % name)


def query_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in allowed:
        raise errors.invalid_request("query parameter %r must be one of %s" % (name, sorted(allowed)))
    return raw


def query_string(name):
    return request.args.get(name)


# ---------------------------------------------------------------------------
# Path resolution (PRD §2.5: strict left-to-right existence + ownership)
# ---------------------------------------------------------------------------
def resolve_track(tid):
    track = db.tracks.get(tid)
    if track is None:
        raise errors.not_found("track %s not found" % tid)
    return track


def resolve_coach(tid, cid):
    track = resolve_track(tid)
    coach = db.coaches.get(cid)
    if coach is None or coach["track_id"] != track["id"]:
        raise errors.not_found("coach %s not found" % cid)
    return track, coach


def resolve_track_day(tid, tdid):
    track = resolve_track(tid)
    day = db.track_days.get(tdid)
    if day is None or day["track_id"] != track["id"]:
        raise errors.not_found("track day %s not found" % tdid)
    return track, day


def resolve_rental_block(tid, tdid, rbid):
    track, day = resolve_track_day(tid, tdid)
    block = db.rental_blocks.get(rbid)
    if block is None or block["track_day_id"] != day["id"]:
        raise errors.not_found("rental block %s not found" % rbid)
    return track, day, block


def resolve_booking(tid, tdid, rbid, bid):
    track, day, block = resolve_rental_block(tid, tdid, rbid)
    booking = db.bookings.get(bid)
    if booking is None or booking["rental_block_id"] != block["id"]:
        raise errors.not_found("booking %s not found" % bid)
    return track, day, block, booking


def resolve_driver(tid, tdid, rbid, bid, did):
    track, day, block, booking = resolve_booking(tid, tdid, rbid, bid)
    driver = db.drivers.get(did)
    if driver is None or driver["booking_id"] != booking["id"]:
        raise errors.not_found("driver %s not found" % did)
    return track, day, block, booking, driver


def resolve_session(tid, tdid, sid):
    track, day = resolve_track_day(tid, tdid)
    session = db.sessions.get(sid)
    if session is None or session["track_day_id"] != day["id"]:
        raise errors.not_found("session %s not found" % sid)
    return track, day, session


def resolve_incident(tid, tdid, iid):
    track, day = resolve_track_day(tid, tdid)
    incident = db.incidents.get(iid)
    if incident is None or incident["track_day_id"] != day["id"]:
        raise errors.not_found("incident %s not found" % iid)
    return track, day, incident


def resolve_garage_assignment(tid, tdid, gid):
    track, day = resolve_track_day(tid, tdid)
    assignment = db.garage_assignments.get(gid)
    if assignment is None or assignment["track_day_id"] != day["id"]:
        raise errors.not_found("garage assignment %s not found" % gid)
    return track, day, assignment


def resolve_paddock_assignment(tid, tdid, pid):
    track, day = resolve_track_day(tid, tdid)
    assignment = db.paddock_assignments.get(pid)
    if assignment is None or assignment["track_day_id"] != day["id"]:
        raise errors.not_found("paddock assignment %s not found" % pid)
    return track, day, assignment


# ---------------------------------------------------------------------------
# Derived / computed state
# ---------------------------------------------------------------------------
def recompute_noise_breach_count(day):
    """Count breaching readings on this day within the trailing 60-minute window."""
    window_start = parse_dt(now_str()) - timedelta(minutes=NOISE_WINDOW_MINUTES)
    count = 0
    for reading in db.noise_readings.values():
        if reading["track_day_id"] != day["id"] or not reading["breach"]:
            continue
        if parse_dt(reading["recorded_at_utc"]) >= window_start:
            count += 1
    day["noise_breach_count"] = count


def recompute_posture(day):
    """Posture ladder (PRD §3.6), evaluated in exactly this order.

    The breach count is window-relative to the logical clock, so refresh it
    first (PRD §3.7: readings at least as recent as sixty minutes before the
    current logical time count; older ones fall out).
    """
    recompute_noise_breach_count(day)
    if day["weather_flag"] == "STOP":
        day["posture"] = "SUSPENDED"
        return
    open_incidents = [
        i for i in db.incidents.values()
        if i["track_day_id"] == day["id"] and i["status"] == "OPEN"
    ]
    if open_incidents and any(i["severity"] in ("HIGH", "CRITICAL") for i in open_incidents):
        day["posture"] = "SUSPENDED"
        return
    if day["noise_breach_count"] >= NOISE_BREACH_SUSPENSION_THRESHOLD:
        day["posture"] = "SUSPENDED"
        return
    if (open_incidents
            or day["noise_breach_count"] >= NOISE_BREACH_CAUTION_THRESHOLD
            or day["weather_flag"] == "WATCH"):
        day["posture"] = "CAUTION"
        return
    day["posture"] = "NORMAL"


def recompute_block_seats(block):
    """Seats aggregation + FULL/OPEN derivation (PRD §3.2)."""
    reserved = sum(
        b["driver_count"]
        for b in db.bookings.values()
        if b["rental_block_id"] == block["id"] and b["approval_status"] == "APPROVED"
    )
    block["seats_reserved"] = reserved
    available = block["max_group_size"] - reserved
    block["seats_available"] = available if available > 0 else 0
    if block["status"] != "CLOSED":
        block["status"] = "FULL" if reserved == block["max_group_size"] else "OPEN"


def recompute_driver_cleared(driver):
    booking = db.bookings.get(driver["booking_id"])
    driver["cleared_to_run"] = bool(
        driver["waiver_status"] == "SIGNED"
        and driver["safety_status"] == "PASSED"
        and booking is not None
        and booking["approval_status"] == "APPROVED"
        and booking["payment_status"] == "CAPTURED"
    )


def coach_assigned_booking_ids(coach_id):
    return [
        b["id"]
        for b in db.bookings.values()
        if b.get("coach_id") == coach_id and b["approval_status"] == "APPROVED"
    ]


def coach_load_on_day(coach_id, track_day_id):
    """Bookings referencing this coach, APPROVED, on blocks of the given day."""
    count = 0
    for b in db.bookings.values():
        if b.get("coach_id") != coach_id or b["approval_status"] != "APPROVED":
            continue
        block = db.rental_blocks.get(b["rental_block_id"])
        if block is not None and block["track_day_id"] == track_day_id:
            count += 1
    return count


def recompute_coaches_for_booking(booking):
    """Refresh computed assigned_booking_ids is done at read time; nothing stored."""
    return None


# ---------------------------------------------------------------------------
# Cancellation / refunds (PRD §3.9)
# ---------------------------------------------------------------------------
def fee_cents_for(booking):
    return FEE_PER_DRIVER_CENTS * booking["driver_count"]


def compute_refund_cents(reason, booking, block, day):
    """Refund per cancel policy. AUTHORIZED (never CAPTURED) -> 0 (auth voided)."""
    if booking["payment_status"] == "AUTHORIZED":
        return 0
    fee = fee_cents_for(booking)
    if reason == "WEATHER":
        refund = int((Decimal(fee) * Decimal("0.75")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        refund -= WEATHER_FACILITY_FEE_CENTS
        return refund if refund > 0 else 0
    if reason == "SAFETY":
        return fee
    # CUSTOMER — chronological variant
    block_start = datetime.strptime(day["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    block_start += timedelta(minutes=block["start_minute"])
    delta_seconds = (block_start - parse_dt(now_str())).total_seconds()
    hours_until = int(delta_seconds // 3600)  # whole hours, floor
    if hours_until >= FULL_REFUND_HOURS:
        pct = Decimal("1.00")
    elif hours_until >= HALF_REFUND_HOURS:
        pct = Decimal("0.50")
    else:
        pct = Decimal("0.00")
    return int((Decimal(fee) * pct).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def cancel_booking_effects(booking, block, reason, day):
    """Shared unwind for single-booking cancel and day-cancel cascade."""
    booking["approval_status"] = "CANCELLED"
    recompute_block_seats(block)
    for assignment in db.garage_assignments.values():
        if assignment["booking_id"] == booking["id"] and assignment["status"] == "ACTIVE":
            assignment["status"] = "RELEASED"
            assignment["updated_at"] = now_str()
            assignment["version"] += 1
    for assignment in db.paddock_assignments.values():
        if assignment["booking_id"] == booking["id"] and assignment["status"] == "ACTIVE":
            assignment["status"] = "RELEASED"
            assignment["updated_at"] = now_str()
            assignment["version"] += 1
    booking["coach_id"] = None
    booking["refund_cents"] = compute_refund_cents(reason, booking, block, day)
    booking["updated_at"] = now_str()
    booking["version"] += 1
    for driver in db.drivers.values():
        if driver["booking_id"] == booking["id"]:
            recompute_driver_cleared(driver)


# ---------------------------------------------------------------------------
# Garage utility fee (PRD §3.8)
# ---------------------------------------------------------------------------
def garage_utility_fee_cents(power_hookups, water_hookup):
    if power_hookups <= 2:
        power_fee = power_hookups * POWER_TIER1_CENTS
    else:
        power_fee = 2 * POWER_TIER1_CENTS + (power_hookups - 2) * POWER_TIER2_CENTS
    water_fee = WATER_FLAT_CENTS if water_hookup else 0
    return GARAGE_BASE_FEE_CENTS + power_fee + water_fee


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def serialize_track(t):
    return {
        "id": t["id"],
        "name": t["name"],
        "noise_limit_db": t["noise_limit_db"],
        "run_group_capacity": t["run_group_capacity"],
        "garage_bay_count": t["garage_bay_count"],
        "paddock_stall_count": t["paddock_stall_count"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def serialize_coach(c):
    return {
        "id": c["id"],
        "track_id": c["track_id"],
        "full_name": c["full_name"],
        "cert_level": c["cert_level"],
        "active": c["active"],
        "assigned_booking_ids": coach_assigned_booking_ids(c["id"]),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_track_day(d):
    return {
        "id": d["id"],
        "track_id": d["track_id"],
        "date": d["date"],
        "status": d["status"],
        "posture": d["posture"],
        "weather_flag": d["weather_flag"],
        "open_incident_count": d["open_incident_count"],
        "noise_breach_count": d["noise_breach_count"],
        "ops_run_index": d["ops_run_index"],
        "cancelled_reason": d["cancelled_reason"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def serialize_rental_block(b):
    return {
        "id": b["id"],
        "track_day_id": b["track_day_id"],
        "block_index": b["block_index"],
        "start_minute": b["start_minute"],
        "end_minute": b["end_minute"],
        "max_group_size": b["max_group_size"],
        "seats_reserved": b["seats_reserved"],
        "seats_available": b["seats_available"],
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def serialize_booking(b):
    return {
        "id": b["id"],
        "rental_block_id": b["rental_block_id"],
        "organizer_user_id": b["organizer_user_id"],
        "group_name": b["group_name"],
        "run_group_class": b["run_group_class"],
        "driver_count": b["driver_count"],
        "insurance_policy_ref": b["insurance_policy_ref"],
        "approval_status": b["approval_status"],
        "payment_status": b["payment_status"],
        "cancel_policy_snapshot": b["cancel_policy_snapshot"],
        "refund_cents": b["refund_cents"],
        "coach_id": b["coach_id"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def serialize_driver(d):
    return {
        "id": d["id"],
        "booking_id": d["booking_id"],
        "full_name": d["full_name"],
        "license_class": d["license_class"],
        "waiver_status": d["waiver_status"],
        "safety_status": d["safety_status"],
        "cleared_to_run": d["cleared_to_run"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def serialize_waiver(w):
    return {
        "id": w["id"],
        "driver_id": w["driver_id"],
        "signed_at_utc": w["signed_at_utc"],
        "expires_at_utc": w["expires_at_utc"],
        "signature_payload_hash": w["signature_payload_hash"],
        "created_at": w["created_at"],
    }


def serialize_inspection(i):
    return {
        "id": i["id"],
        "driver_id": i["driver_id"],
        "inspector_user_id": i["inspector_user_id"],
        "helmet_ok": i["helmet_ok"],
        "harness_ok": i["harness_ok"],
        "result": i["result"],
        "inspected_at_utc": i["inspected_at_utc"],
        "created_at": i["created_at"],
    }


def serialize_session(s):
    return {
        "id": s["id"],
        "track_day_id": s["track_day_id"],
        "rental_block_id": s["rental_block_id"],
        "run_group_class": s["run_group_class"],
        "status": s["status"],
        "started_at_utc": s["started_at_utc"],
        "ended_at_utc": s["ended_at_utc"],
        "lap_count": s["lap_count"],
        "max_db_observed": s["max_db_observed"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_incident(i):
    return {
        "id": i["id"],
        "track_day_id": i["track_day_id"],
        "session_id": i["session_id"],
        "severity": i["severity"],
        "status": i["status"],
        "reported_by_user_id": i["reported_by_user_id"],
        "cleared_by_user_id": i["cleared_by_user_id"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def serialize_noise_reading(n):
    return {
        "id": n["id"],
        "track_day_id": n["track_day_id"],
        "session_id": n["session_id"],
        "db_level": n["db_level"],
        "recorded_at_utc": n["recorded_at_utc"],
        "breach": n["breach"],
        "created_at": n["created_at"],
    }


def serialize_garage_assignment(g):
    return {
        "id": g["id"],
        "track_day_id": g["track_day_id"],
        "booking_id": g["booking_id"],
        "bay_number": g["bay_number"],
        "power_hookups": g["power_hookups"],
        "water_hookup": g["water_hookup"],
        "garage_utility_fee_cents": g["garage_utility_fee_cents"],
        "status": g["status"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def serialize_paddock_assignment(p):
    return {
        "id": p["id"],
        "track_day_id": p["track_day_id"],
        "booking_id": p["booking_id"],
        "stall_number": p["stall_number"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }
