"""Shared input validation, pagination, and calculation helpers."""
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import err

# ----- Calculation constants (scaffold §1.3) -----
BASE_RATE_CENTS = {"LOCKOUT": 9000, "REKEY": 12000, "INSTALL": 15000, "SAFE": 20000}
LABOR_RATE_CENTS_PER_HOUR = 8000
QUEUE_PENALTY_MINUTES = 10
AFTER_HOURS_START_MINUTE = 1080   # 18:00 inclusive
AFTER_HOURS_END_MINUTE = 480      # 08:00 exclusive
AFTER_HOURS_MULTIPLIER = Decimal("1.5")
EMERGENCY_LOCKOUT_MULTIPLIER = Decimal("1.25")
BUFFER_MINUTES = 15
WARRANTY_DAYS = 90

SERVICE_TYPES = {"LOCKOUT", "REKEY", "INSTALL", "SAFE"}
AUTH_KINDS = {"KEY_DUPLICATION", "CODE_RESET", "RESTRICTED_BLANK"}


# ----- Request body access -----
def get_body():
    """Parse JSON body. Returns {} for an empty body; raises ERR_INVALID_REQUEST
    when the body is present but not a JSON object."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Request body is not valid JSON")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


# ----- Field validators (ERR_INVALID_REQUEST, 400) -----
def require_str(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
    val = body[field]
    if not isinstance(val, str) or val == "":
        raise err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string" % field)
    return val


def require_int(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)
    return val


def optional_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean" % field)
    return val


def require_number(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a number" % field)
    return val


def require_list(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
    val = body[field]
    if not isinstance(val, list):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an array" % field)
    return val


def validate_minute(value, field="minute"):
    """Time-of-day minute 0..1439 (PRD §2.7). Out of range -> ERR_INVALID_TIME_WINDOW."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)
    if value < 0 or value > 1439:
        raise err("ERR_INVALID_TIME_WINDOW", "%s must be within 0..1439" % field)
    return value


# ----- Rounding -----
def round_half_up(value):
    """Round a Decimal to a whole integer, half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ----- Surcharge multiplier (scaffold §1.3 surcharge_multiplier) -----
def surcharge_multiplier(job):
    m = Decimal("1.0")
    rm = job["requested_at_minute"]
    if rm >= AFTER_HOURS_START_MINUTE or rm < AFTER_HOURS_END_MINUTE:
        m = m * AFTER_HOURS_MULTIPLIER
    if job["is_emergency"] and job["service_type"] == "LOCKOUT":
        m = m * EMERGENCY_LOCKOUT_MULTIPLIER
    return m


def quote_estimated_total_cents(job):
    base = BASE_RATE_CENTS[job["service_type"]]
    m = surcharge_multiplier(job)
    return round_half_up(Decimal(base) * m)


def quote_final_total_cents(job, labor_hours, part_lines):
    m = surcharge_multiplier(job)
    labor_line = round_half_up(Decimal(LABOR_RATE_CENTS_PER_HOUR) * Decimal(str(labor_hours)) * m)
    parts_total = 0
    for line in part_lines:
        unit = Decimal(str(line["unit_price_cents"]))
        qty = Decimal(str(line["quantity"]))
        parts_total += round_half_up(unit * qty * m)
    return labor_line + parts_total


def promised_eta_minutes(technician, live_count):
    return technician["base_travel_minutes"] + live_count * QUEUE_PENALTY_MINUTES


def actual_response_minutes(arrived_at_minute, requested_at_minute):
    v = arrived_at_minute - requested_at_minute
    return v if v >= 0 else 0


# ----- Pagination (PRD §2.3) -----
def get_pagination():
    """Parse limit/offset query params. Returns (limit, offset)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ASC (tie-broken by creation sequence), slice, and
    build the pagination meta block."""
    ordered = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta
