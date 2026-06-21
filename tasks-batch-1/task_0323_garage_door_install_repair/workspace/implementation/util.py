"""Shared helpers: validation, money rounding, pagination, datetime parsing."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from flask import request

import errors


# ---------------------------------------------------------------------------
# Money rounding (PRD §2.5) — half-up to whole cents, never float for money.
# ---------------------------------------------------------------------------
def round_half_up_cents(value):
    """Round a Decimal/number to the nearest whole cent, half-up."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_places(value, places):
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    q = Decimal(1).scaleb(-places)  # 10^-places
    return float(d.quantize(q, rounding=ROUND_HALF_UP))


def ceil_int(value):
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_CEILING))


# ---------------------------------------------------------------------------
# Body parsing & validation (PRD §2.7, §2.8)
# ---------------------------------------------------------------------------
def get_body():
    """Return the JSON body as a dict (empty dict when none)."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Body must be a JSON object")
    return data


def require_fields(body, fields):
    for f in fields:
        if body.get(f) is None:
            raise errors.err(errors.ERR_INVALID_REQUEST, f"Missing required field: {f}")


def require_string(body, field):
    val = body.get(field)
    if not isinstance(val, str) or val == "":
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {field} must be a non-empty string")
    return val


def require_int(body, field):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {field} must be an integer")
    return val


def require_qty(body, field):
    """qty must be an integer >= 1 (PRD §2.7)."""
    val = require_int(body, field)
    if val < 1:
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {field} must be >= 1")
    return val


def require_enum(body, field, allowed):
    val = body.get(field)
    if val not in allowed:
        raise errors.err(errors.ERR_INVALID_REQUEST,
                         f"Field {field} must be one of {sorted(allowed)}")
    return val


def optional_bool(body, field, default):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if not isinstance(val, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {field} must be boolean")
    return val


def optional_int(body, field, default):
    if field not in body or body.get(field) is None:
        return default
    return require_int(body, field)


def optional_number(body, field, default):
    if field not in body or body.get(field) is None:
        return default
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {field} must be a number")
    return val


def optional_string(body, field, default):
    if field not in body or body.get(field) is None:
        return default
    return require_string(body, field)


# ---------------------------------------------------------------------------
# Datetime parsing (UTC instants)
# ---------------------------------------------------------------------------
def parse_dt(value, field="datetime"):
    """Parse an ISO 8601 instant into a tz-aware UTC datetime."""
    if not isinstance(value, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {field} must be an ISO8601 string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {field} is not a valid ISO8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3) — limit default 10, min 1, max 100; offset default 0.
# ---------------------------------------------------------------------------
def parse_pagination():
    limit = request.args.get("limit")
    offset = request.args.get("offset")

    if limit is None:
        limit_v = 10
    else:
        try:
            limit_v = int(limit)
        except (ValueError, TypeError):
            raise errors.err(errors.ERR_INVALID_REQUEST, "limit must be an integer")
        if limit_v < 1:
            limit_v = 1
        elif limit_v > 100:
            limit_v = 100

    if offset is None:
        offset_v = 0
    else:
        try:
            offset_v = int(offset)
        except (ValueError, TypeError):
            raise errors.err(errors.ERR_INVALID_REQUEST, "offset must be an integer")
        if offset_v < 0:
            offset_v = 0

    return limit_v, offset_v


def paginate(rows, limit, offset):
    """Sort by created_at ascending (oldest first) and apply window.

    Returns (page_rows, pagination_meta).
    """
    ordered = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return window, pagination
