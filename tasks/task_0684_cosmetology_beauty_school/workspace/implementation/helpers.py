"""Shared request-parsing, pagination, money, and date helpers."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import db
import errors


# ---------------------------------------------------------------------------
# Body parsing
# ---------------------------------------------------------------------------
def body():
    """Parse JSON body; an absent body is treated as {} (POSTs with no input)."""
    if not request.data:
        return {}
    data = request.get_json(force=True, silent=True)
    if data is None:
        if request.data.strip() == b"":
            return {}
        raise errors.invalid_request("Malformed JSON body")
    if not isinstance(data, dict):
        raise errors.invalid_request("Body must be a JSON object")
    return data


def require_fields(data, *names):
    for n in names:
        if n not in data or data[n] is None:
            raise errors.invalid_request(f"Missing required field: {n}")


def require_str(data, name):
    require_fields(data, name)
    v = data[name]
    if not isinstance(v, str) or v == "":
        raise errors.invalid_request(f"Field {name} must be a non-empty string")
    return v


def require_int(data, name):
    require_fields(data, name)
    v = data[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.invalid_request(f"Field {name} must be an integer")
    return v


def opt_int(data, name, default):
    if name not in data or data[name] is None:
        return default
    v = data[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.invalid_request(f"Field {name} must be an integer")
    return v


def require_number(data, name):
    require_fields(data, name)
    v = data[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise errors.invalid_request(f"Field {name} must be a number")
    return v


def opt_number(data, name, default):
    if name not in data or data[name] is None:
        return default
    v = data[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise errors.invalid_request(f"Field {name} must be a number")
    return v


def opt_bool(data, name, default):
    if name not in data or data[name] is None:
        return default
    v = data[name]
    if not isinstance(v, bool):
        raise errors.invalid_request(f"Field {name} must be a boolean")
    return v


def require_enum(data, name, choices):
    v = require_str(data, name)
    if v not in choices:
        raise errors.invalid_request(f"Field {name} must be one of {sorted(choices)}")
    return v


# ---------------------------------------------------------------------------
# Datetime parsing (request inputs are ISO 8601 strings)
# ---------------------------------------------------------------------------
def parse_dt(value, field="datetime"):
    if not isinstance(value, str) or not value:
        raise errors.invalid_request(f"Field {field} must be an ISO 8601 datetime string")
    raw = value
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise errors.invalid_request(f"Field {field} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def require_dt(data, name):
    require_fields(data, name)
    return parse_dt(data[name], name)


# ---------------------------------------------------------------------------
# Money / rounding (PRD 2.8: round-half-up)
# ---------------------------------------------------------------------------
def round_half_up(amount):
    """Round a numeric amount to a whole integer using round-half-up."""
    return int(Decimal(str(amount)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round2(amount):
    """Round a numeric amount to 2 decimal places (round-half-up) as a float."""
    return float(Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3: limit default 10 / min 1 / max 100; offset default 0)
# ---------------------------------------------------------------------------
def pagination():
    limit = _qint("limit", 10, lo=1, hi=100)
    offset = _qint("offset", 0, lo=0, hi=None)
    return limit, offset


def _qint(name, default, lo, hi):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        v = int(raw)
    except ValueError:
        raise errors.invalid_request(f"Query param {name} must be an integer")
    if lo is not None and v < lo:
        raise errors.invalid_request(f"Query param {name} below minimum")
    if hi is not None and v > hi:
        raise errors.invalid_request(f"Query param {name} above maximum")
    return v


def sort_created(rows):
    """PRD 2.3: list endpoints sort by created_at ASC, realized via the
    monotonic creation sequence for a stable total order even when the logical
    clock is frozen and created_at strings collide."""
    return sorted(rows, key=lambda r: r["_seq"])


def paginate(rows):
    limit, offset = pagination()
    ordered = sort_created(rows)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total
