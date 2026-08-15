"""Shared request/validation/time/serialization helpers (PRD section 2)."""

import math
import re
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import db
from errors import (
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    raise_error,
)
from response import success_list

Q1 = Decimal("0.1")
Q2 = Decimal("0.01")
Q3 = Decimal("0.001")
Q4 = Decimal("0.0001")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# Rounding (round half up at every pinned step; PRD section 2.6)
# ---------------------------------------------------------------------------

def r1(x):
    return x.quantize(Q1, rounding=ROUND_HALF_UP)


def r2(x):
    return x.quantize(Q2, rounding=ROUND_HALF_UP)


def r3(x):
    return x.quantize(Q3, rounding=ROUND_HALF_UP)


def r4(x):
    return x.quantize(Q4, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Logical clock helpers
# ---------------------------------------------------------------------------

def parse_dt(value, field):
    """Parse an ISO 8601 datetime string into a naive UTC datetime."""
    if not isinstance(value, str):
        raise_error(ERR_INVALID_REQUEST, f"Field '{field}' must be an ISO 8601 datetime string")
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise_error(ERR_INVALID_REQUEST, f"Field '{field}' is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def iso_z(dt):
    """Format a naive UTC datetime as ISO 8601 with three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_dt():
    return parse_dt(db.current_utc_iso, "current_utc")


def now_ts():
    return iso_z(now_dt())


def today():
    return now_dt().date()


def parse_date(value, field):
    """Validate a strict YYYY-MM-DD date string; returns a date object."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise_error(ERR_INVALID_REQUEST, f"Field '{field}' must be an ISO date string (YYYY-MM-DD)")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise_error(ERR_INVALID_REQUEST, f"Field '{field}' is not a valid calendar date")


# ---------------------------------------------------------------------------
# Entity plumbing
# ---------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def stamp_new(entity):
    """Populate id / created_at / updated_at / version on a fresh row."""
    entity["id"] = new_id()
    ts = now_ts()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = db.next_seq()


def touch(entity):
    """Every mutation of a row refreshes updated_at and increments version."""
    entity["updated_at"] = now_ts()
    entity["version"] += 1


def public_num(value):
    """Serialize a stored Decimal (or plain number) as a JSON number."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


# ---------------------------------------------------------------------------
# Request body / field validation (PRD section 2.8 stage 3)
# ---------------------------------------------------------------------------

def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise_error(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def req_field(data, field):
    if field not in data or data[field] is None:
        raise_error(ERR_INVALID_REQUEST, f"Missing required field: {field}")
    return data[field]


def req_string(data, field):
    value = req_field(data, field)
    if not isinstance(value, str):
        raise_error(ERR_INVALID_REQUEST, f"Field '{field}' must be a string")
    return value


def opt_string(data, field):
    if field not in data or data[field] is None:
        return None
    if not isinstance(data[field], str):
        raise_error(ERR_INVALID_REQUEST, f"Field '{field}' must be a string")
    return data[field]


def _to_decimal(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise_error(ERR_INVALID_REQUEST, f"Field '{field}' must be a number")
    if isinstance(value, float) and not math.isfinite(value):
        raise_error(ERR_INVALID_REQUEST, f"Field '{field}' must be a finite number")
    return Decimal(str(value))


def req_number(data, field):
    return _to_decimal(req_field(data, field), field)


def opt_number(data, field):
    if field not in data or data[field] is None:
        return None
    return _to_decimal(data[field], field)


def _to_int(value, field):
    if isinstance(value, bool):
        raise_error(ERR_INVALID_REQUEST, f"Field '{field}' must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    raise_error(ERR_INVALID_REQUEST, f"Field '{field}' must be an integer")


def req_int(data, field):
    return _to_int(req_field(data, field), field)


def opt_int(data, field):
    if field not in data or data[field] is None:
        return None
    return _to_int(data[field], field)


def req_bool(data, field):
    value = req_field(data, field)
    if not isinstance(value, bool):
        raise_error(ERR_INVALID_REQUEST, f"Field '{field}' must be a boolean")
    return value


def opt_bool(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    if not isinstance(data[field], bool):
        raise_error(ERR_INVALID_REQUEST, f"Field '{field}' must be a boolean")
    return data[field]


def req_enum(data, field, allowed):
    value = req_field(data, field)
    if value not in allowed:
        raise_error(ERR_INVALID_REQUEST, f"Field '{field}' must be one of {sorted(allowed)}")
    return value


def opt_enum(data, field, allowed, default):
    if field not in data or data[field] is None:
        return default
    if data[field] not in allowed:
        raise_error(ERR_INVALID_REQUEST, f"Field '{field}' must be one of {sorted(allowed)}")
    return data[field]


def req_date(data, field):
    return parse_date(req_field(data, field), field)


def forbidden_fields(data, fields, context):
    for f in fields:
        if f in data and data[f] is not None:
            raise_error(ERR_INVALID_REQUEST, f"Field '{f}' is forbidden {context}")


def reject_unknown(data, allowed):
    """Strict schema: client-supplied unknown/computed fields are rejected."""
    extra = [k for k in data if k not in allowed]
    if extra:
        raise_error(ERR_INVALID_REQUEST,
                    f"Unknown field(s) in request body: {', '.join(sorted(extra))}")


# ---------------------------------------------------------------------------
# Existence / listing / pagination
# ---------------------------------------------------------------------------

def get_or_404(store, entity_id, what):
    entity = store.get(entity_id)
    if entity is None:
        raise_error(ERR_NOT_FOUND, f"{what} not found")
    return entity


def parse_pagination():
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
        offset = int(raw_offset)
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_REQUEST, "limit/offset must be integers")
    if limit < 1 or limit > 100:
        raise_error(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset < 0:
        raise_error(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def list_response(items, serializer, filters):
    """Sort by creation timestamp ascending, apply equality filters, paginate."""
    items = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    for field, value in filters.items():
        if value is not None:
            items = [e for e in items if str(e.get(field)) == value]
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serializer(e) for e in page], limit, offset, total)
