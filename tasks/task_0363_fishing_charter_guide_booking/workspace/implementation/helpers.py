"""Shared helpers: request body parsing, field validation, datetime parsing,
pagination, and serialization."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN

from flask import request

from errors import ApiError


# ---------------------------------------------------------------------------
# Body parsing
# ---------------------------------------------------------------------------
def get_body():
    """Parse JSON body; treat empty/no body as {}. Malformed JSON -> 400."""
    if request.data is None or len(request.data) == 0:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Malformed JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


# ---------------------------------------------------------------------------
# Field validation (priority 4: ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------
def require_field(body, name):
    if name not in body or body[name] is None:
        raise ApiError("ERR_INVALID_REQUEST", f"Missing required field: {name}")
    return body[name]


def require_str(body, name):
    val = require_field(body, name)
    if not isinstance(val, str) or val == "":
        raise ApiError("ERR_INVALID_REQUEST", f"Field {name} must be a non-empty string")
    return val


def opt_str(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, str):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {name} must be a string")
    return val


def _is_int(val):
    # bool is a subclass of int; reject it as an integer field value.
    return isinstance(val, int) and not isinstance(val, bool)


def require_int(body, name, minimum=None, maximum=None):
    val = require_field(body, name)
    if not _is_int(val):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {name} must be an integer")
    if minimum is not None and val < minimum:
        raise ApiError("ERR_INVALID_REQUEST", f"Field {name} below minimum {minimum}")
    if maximum is not None and val > maximum:
        raise ApiError("ERR_INVALID_REQUEST", f"Field {name} above maximum {maximum}")
    return val


def opt_int(body, name, default=None, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not _is_int(val):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {name} must be an integer")
    if minimum is not None and val < minimum:
        raise ApiError("ERR_INVALID_REQUEST", f"Field {name} below minimum {minimum}")
    if maximum is not None and val > maximum:
        raise ApiError("ERR_INVALID_REQUEST", f"Field {name} above maximum {maximum}")
    return val


def require_number(body, name, minimum=None, exclusive_min=None):
    val = require_field(body, name)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {name} must be a number")
    if minimum is not None and val < minimum:
        raise ApiError("ERR_INVALID_REQUEST", f"Field {name} below minimum {minimum}")
    if exclusive_min is not None and val <= exclusive_min:
        raise ApiError("ERR_INVALID_REQUEST", f"Field {name} must be greater than {exclusive_min}")
    return val


def require_bool(body, name):
    val = require_field(body, name)
    if not isinstance(val, bool):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {name} must be a boolean")
    return val


def opt_bool(body, name, default=False):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, bool):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {name} must be a boolean")
    return val


def require_enum(body, name, choices):
    val = require_str(body, name)
    if val not in choices:
        raise ApiError("ERR_INVALID_REQUEST", f"Field {name} must be one of {sorted(choices)}")
    return val


def opt_enum(body, name, choices, default=None):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, str) or val not in choices:
        raise ApiError("ERR_INVALID_REQUEST", f"Field {name} must be one of {sorted(choices)}")
    return val


# ---------------------------------------------------------------------------
# Datetime parsing (ISO 8601 UTC)
# ---------------------------------------------------------------------------
def parse_dt(value, field_name):
    if not isinstance(value, str) or not value:
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field_name} must be an ISO 8601 datetime string")
    raw = value.strip()
    txt = raw
    if txt.endswith("Z") or txt.endswith("z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        # Bare date like "2026-01-01"
        try:
            dt = datetime.strptime(raw, "%Y-%m-%d")
        except ValueError:
            raise ApiError("ERR_INVALID_REQUEST", f"Field {field_name} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def require_dt(body, name):
    val = require_field(body, name)
    return parse_dt(val, name)


# ---------------------------------------------------------------------------
# Rounding (PRD 2.5)
# ---------------------------------------------------------------------------
def round_half_up(numerator, denominator=1):
    """round_half_up(numerator / denominator) to integer cents."""
    q = Decimal(numerator) / Decimal(denominator)
    return int(q.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_div(numerator, denominator):
    """floor(numerator / denominator) toward zero for non-negative inputs."""
    q = Decimal(numerator) / Decimal(denominator)
    return int(q.quantize(Decimal("1"), rounding=ROUND_DOWN))


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
def get_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """items already sorted; return the page slice."""
    return items[offset:offset + limit]
