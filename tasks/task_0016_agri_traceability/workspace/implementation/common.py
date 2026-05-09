"""Common helpers: pagination, body parsing, decimal/money helpers, timestamp stamping."""

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from clock import clock
from errors import ERR_VALIDATION, raise_error


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def parse_pagination():
    args = request.args
    limit_raw = args.get("limit", "10")
    offset_raw = args.get("offset", "0")
    try:
        limit = int(limit_raw)
        offset = int(offset_raw)
    except (ValueError, TypeError):
        raise_error(ERR_VALIDATION, "limit/offset must be integers")
    if limit < 1 or limit > 100:
        raise_error(ERR_VALIDATION, "limit must be in [1,100]")
    if offset < 0:
        raise_error(ERR_VALIDATION, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


# ---------------------------------------------------------------------------
# Decimal / numeric
# ---------------------------------------------------------------------------

def to_decimal(value, fallback=None):
    if value is None:
        return fallback
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        raise_error(ERR_VALIDATION, "expected numeric value")


def round_kg(value) -> Decimal:
    """Round to 2 decimal places, half-up."""
    return to_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def kg_to_json(value):
    if value is None:
        return None
    if not isinstance(value, Decimal):
        value = to_decimal(value)
    return float(round_kg(value))


def truncate_6dp(value) -> Decimal:
    """Truncate (toward zero) to 6 decimal places — used for lab-measurement comparisons."""
    d = to_decimal(value)
    q = Decimal("0.000001")
    # Truncate toward zero
    sign, digits, exponent = d.as_tuple()
    # Use quantize with ROUND_DOWN for truncation toward zero.
    from decimal import ROUND_DOWN
    return d.quantize(q, rounding=ROUND_DOWN)


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------

def stamp_create(record):
    now = clock.now_iso()
    record["created_at"] = now
    record["updated_at"] = now
    record["version"] = 1
    return record


def stamp_create_immutable(record):
    """For append-only records (no updated_at, no version)."""
    record["created_at"] = clock.now_iso()
    return record


def stamp_update(record):
    record["updated_at"] = clock.now_iso()
    record["version"] = record.get("version", 1) + 1
    return record


def parse_iso_datetime(s, field_name="datetime"):
    """Parse an ISO-8601 datetime string. Accepts trailing 'Z' or offset."""
    if s is None:
        return None
    if isinstance(s, datetime):
        if s.tzinfo is None:
            return s.replace(tzinfo=timezone.utc)
        return s.astimezone(timezone.utc)
    if not isinstance(s, str) or not s:
        raise_error(ERR_VALIDATION, f"field {field_name} must be ISO-8601 datetime string")
    raw = s.strip()
    # Replace trailing 'Z' with '+00:00' for fromisoformat compatibility.
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except Exception:
        # Accept date-only strings as midnight UTC.
        try:
            d = datetime.strptime(s, "%Y-%m-%d")
            return d.replace(tzinfo=timezone.utc)
        except Exception:
            raise_error(ERR_VALIDATION, f"field {field_name} not valid ISO-8601: {s}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def utc_midnight_iso(dt):
    """Return ISO timestamp at UTC midnight of dt's calendar date."""
    if dt is None:
        return None
    if isinstance(dt, str):
        dt = parse_iso_datetime(dt)
    midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def add_days_utc_midnight(dt, days):
    """Add `days` whole days to dt and return UTC-midnight ISO string."""
    if isinstance(dt, str):
        dt = parse_iso_datetime(dt)
    new = dt + timedelta(days=int(days))
    return utc_midnight_iso(new)


# ---------------------------------------------------------------------------
# Body / field helpers
# ---------------------------------------------------------------------------

def get_json_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_error(ERR_VALIDATION, "JSON body must be an object")
    return body


def require_field(body, field, etype=None):
    if field not in body:
        raise_error(ERR_VALIDATION, f"missing required field {field}")
    val = body[field]
    if val is None:
        raise_error(ERR_VALIDATION, f"field {field} cannot be null")
    if etype is not None and not isinstance(val, etype):
        raise_error(ERR_VALIDATION, f"field {field} has wrong type")
    return val


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------

def sort_by_created_at(items):
    return sorted(items, key=lambda x: x.get("created_at", ""))


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

BATCH_CODE_RE = re.compile(r"^PB-[A-Z0-9]{8}$")
BIN_CODE_RE = re.compile(r"^WH-[A-Z][0-9]{3}$")
PESTICIDE_REGNO_RE = re.compile(r"^PD-[0-9]{6}$")
FERTILIZER_REGNO_RE = re.compile(r"^FT-[0-9]{6}$")
