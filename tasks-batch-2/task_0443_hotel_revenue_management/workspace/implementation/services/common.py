"""Shared helpers: body parsing, numeric coercion, pagination, mutation stamps.

Monetary precision (PRD §2.6): round-half-up, fixed decimals. Use Decimal.
"""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from flask import request

from db import db, now_iso
from errors import err, ERR_INVALID_REQUEST, ERR_NOT_FOUND


# ----------------------------------------------------------------------------
# Body parsing
# ----------------------------------------------------------------------------
def get_body():
    """Return the JSON body as a dict, or {} when absent. Malformed JSON ->
    ERR_INVALID_REQUEST."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise err(ERR_INVALID_REQUEST, "Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "Body must be a JSON object")
    return body


# ----------------------------------------------------------------------------
# Field extraction / coercion (raise ERR_INVALID_REQUEST on malformed input)
# ----------------------------------------------------------------------------
def require_str(body, key):
    if key not in body or body[key] is None:
        raise err(ERR_INVALID_REQUEST, f"Missing required field: {key}")
    v = body[key]
    if not isinstance(v, str) or v == "":
        raise err(ERR_INVALID_REQUEST, f"Field {key} must be a non-empty string")
    return v


def opt_str(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, str):
        raise err(ERR_INVALID_REQUEST, f"Field {key} must be a string")
    return v


def _as_int(v, key):
    # Reject bools (bool is subclass of int) and non-integers.
    if isinstance(v, bool):
        raise err(ERR_INVALID_REQUEST, f"Field {key} must be an integer")
    if isinstance(v, int):
        return v
    raise err(ERR_INVALID_REQUEST, f"Field {key} must be an integer")


def require_int(body, key):
    if key not in body or body[key] is None:
        raise err(ERR_INVALID_REQUEST, f"Missing required field: {key}")
    return _as_int(body[key], key)


def opt_int(body, key, default):
    if key not in body or body[key] is None:
        return default
    return _as_int(body[key], key)


def _as_number(v, key):
    if isinstance(v, bool):
        raise err(ERR_INVALID_REQUEST, f"Field {key} must be a number")
    if isinstance(v, (int, float)):
        return v
    raise err(ERR_INVALID_REQUEST, f"Field {key} must be a number")


def require_number(body, key):
    if key not in body or body[key] is None:
        raise err(ERR_INVALID_REQUEST, f"Missing required field: {key}")
    return _as_number(body[key], key)


def opt_number(body, key, default):
    if key not in body or body[key] is None:
        return default
    return _as_number(body[key], key)


def opt_bool(body, key, default):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, bool):
        raise err(ERR_INVALID_REQUEST, f"Field {key} must be a boolean")
    return v


def require_enum(body, key, choices):
    v = require_str(body, key)
    if v not in choices:
        raise err(ERR_INVALID_REQUEST, f"Field {key} must be one of {sorted(choices)}")
    return v


def require_datetime(body, key):
    """Parse an ISO 8601 datetime; normalise to UTC midnight for stay dates is
    done by the caller. Returns an aware UTC datetime."""
    v = require_str(body, key)
    return parse_iso(v, key)


def opt_datetime(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    return parse_iso(body[key], key)


def parse_iso(v, key="timestamp"):
    if not isinstance(v, str):
        raise err(ERR_INVALID_REQUEST, f"Field {key} must be an ISO 8601 string")
    s = v.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, f"Field {key} must be a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def stay_date_midnight(dt):
    """Truncate an aware UTC datetime to midnight UTC (the night key)."""
    return datetime(dt.year, dt.month, dt.day, 0, 0, 0, tzinfo=timezone.utc)


def iso_out(dt):
    """Serialize an aware UTC datetime to ISO 8601 with 3 fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ----------------------------------------------------------------------------
# Monetary / ratio rounding (round-half-up, PRD §2.6)
# ----------------------------------------------------------------------------
def round_money(value):
    """Round to 2 decimals, half-up. Returns a float for JSON output."""
    return float(_round_dec(value, 2))


def round_ratio(value):
    """Round to 4 decimals, half-up. Returns a float for JSON output."""
    return float(_round_dec(value, 4))


def _round_dec(value, places):
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        d = Decimal(0)
    q = Decimal(1).scaleb(-places)  # e.g. places=2 -> 0.01
    return d.quantize(q, rounding=ROUND_HALF_UP)


def round_half_up_int(value):
    """Round to the nearest integer, half-up."""
    d = Decimal(str(value))
    return int(d.quantize(Decimal(1), rounding=ROUND_HALF_UP))


# ----------------------------------------------------------------------------
# Mutation stamps & versioning (PRD §2.4 / §2.5)
# ----------------------------------------------------------------------------
def stamp_new(rec, mutable=True):
    """Set created_at; for mutable records also updated_at and version=1."""
    ts = now_iso()
    rec["created_at"] = ts
    if mutable:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def bump(rec):
    """Refresh updated_at and increment version by 1 (a mutation/cascade)."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 0) + 1
    return rec


# ----------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0.
# ----------------------------------------------------------------------------
def parse_pagination():
    limit = _parse_pos_int_param("limit", 10)
    offset = _parse_pos_int_param("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def _parse_pos_int_param(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def paginate(items, limit, offset):
    """Slice a list after sorting; return the page slice + total count."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


def sort_by_created(records):
    """Sort by created_at asc, with the insertion sequence as a stable
    tie-break (PRD §2.3)."""
    return sorted(records, key=lambda r: (r["created_at"], r.get("_seq", 0)))


# ----------------------------------------------------------------------------
# Lookups
# ----------------------------------------------------------------------------
def get_or_404(collection, rid):
    rec = collection.get(rid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Resource not found")
    return rec
