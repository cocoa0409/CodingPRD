"""Shared parsing, validation, pagination, date and rounding helpers."""

from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import err


# --------------------------------------------------------------------------- #
# Rounding
# --------------------------------------------------------------------------- #
def round_half_up(value):
    """Round a numeric value to the nearest integer, half rounds up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------- #
# Body
# --------------------------------------------------------------------------- #
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


# --------------------------------------------------------------------------- #
# Field-level validation (priority 14 -> ERR_INVALID_REQUEST 400)
# --------------------------------------------------------------------------- #
def require(data, field):
    if field not in data or data[field] is None:
        raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
    return data[field]


def require_str(data, field):
    v = require(data, field)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a non-empty string")
    return v


def opt_str(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a string")
    return v


def require_int(data, field):
    v = require(data, field)
    return _as_int(v, field)


def opt_int(data, field, default):
    if field not in data or data[field] is None:
        return default
    return _as_int(data[field], field)


def _as_int(v, field):
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an integer")
    return v


def require_bool(data, field, default):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a boolean")
    return v


def require_enum(data, field, allowed):
    v = require_str(data, field)
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be one of {sorted(allowed)}")
    return v


def opt_enum(data, field, allowed, default):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, str) or v not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be one of {sorted(allowed)}")
    return v


def require_score(data, field):
    v = require_int(data, field)
    if v < 0 or v > 100:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be between 0 and 100")
    return v


def require_pct(data, field):
    return require_score(data, field)


def require_nonneg_int(data, field):
    v = require_int(data, field)
    if v < 0:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be non-negative")
    return v


def opt_nonneg_int(data, field, default):
    v = opt_int(data, field, default)
    if v < 0:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be non-negative")
    return v


def require_pos_int(data, field):
    v = require_int(data, field)
    if v <= 0:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be positive")
    return v


def opt_pos_int(data, field, default):
    v = opt_int(data, field, default)
    if v <= 0:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be positive")
    return v


# --------------------------------------------------------------------------- #
# Dates
# --------------------------------------------------------------------------- #
def parse_iso_date(value, field):
    """Parse an ISO YYYY-MM-DD date; raise ERR_INVALID_REQUEST on malformed."""
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an ISO date string")
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a valid ISO YYYY-MM-DD date")


def require_iso_date(data, field):
    v = require(data, field)
    parse_iso_date(v, field)  # validate
    return v


def parse_iso_datetime(value, field):
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an ISO 8601 datetime string")
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# --------------------------------------------------------------------------- #
# Pagination (PRD §2.3 -> ERR_PAGINATION_INVALID 400)
# --------------------------------------------------------------------------- #
def pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_PAGINATION_INVALID", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_PAGINATION_INVALID", "limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_PAGINATION_INVALID", "offset must be an integer")
        if offset < 0:
            raise err("ERR_PAGINATION_INVALID", "offset must be non-negative")
    return limit, offset


def paginate(items, limit, offset):
    """items already sorted; return the page slice."""
    return items[offset:offset + limit]
