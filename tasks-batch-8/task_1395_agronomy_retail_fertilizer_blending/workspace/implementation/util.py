"""Shared helpers: ids, timestamps, Decimal rounding, validation, pagination."""

import re
import uuid
from datetime import datetime, timezone

from decimal import Decimal, ROUND_HALF_UP

from errors import validation


def new_id() -> str:
    return str(uuid.uuid4())


def now_stamp(clock) -> str:
    from response import iso8601_ms
    return iso8601_ms(clock.now())


# ---------------------------------------------------------------------------
# Decimal math
# ---------------------------------------------------------------------------

def D(x) -> Decimal:
    """Coerce int/float/str to Decimal exactly (floats via str to avoid binary noise)."""
    if isinstance(x, Decimal):
        return x
    if isinstance(x, float):
        return Decimal(str(x))
    return Decimal(x)


def round_half_up(x: Decimal, places: int = 0) -> Decimal:
    q = Decimal(1) if places == 0 else Decimal(1).scaleb(-places)
    return x.quantize(q, rounding=ROUND_HALF_UP)


def r3(x: Decimal) -> Decimal:
    return round_half_up(x, 3)


def r1(x: Decimal) -> Decimal:
    return round_half_up(x, 1)


def r0_int(x: Decimal) -> int:
    return int(round_half_up(x, 0))


# ---------------------------------------------------------------------------
# Datetime parsing — ISO 8601, whole-second granularity for comparisons
# ---------------------------------------------------------------------------

def parse_instant(value, field="instant") -> datetime:
    if not isinstance(value, str):
        raise validation(f"{field} must be an ISO 8601 string")
    s = value.strip()
    dt = None
    if s.endswith("Z"):
        try:
            dt = datetime.fromisoformat(s[:-1] + "+00:00")
        except ValueError:
            dt = None
    else:
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            dt = None
    if dt is None:
        raise validation(f"{field} must be a valid ISO 8601 instant")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_route_date(value, field="route_date") -> str:
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise validation(f"{field} must be a YYYY-MM-DD date string")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise validation(f"{field} must be a valid YYYY-MM-DD date")
    return value


# ---------------------------------------------------------------------------
# Body validation helpers
# ---------------------------------------------------------------------------

def get_body():
    from flask import request
    if not request.is_json:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise validation("Request body must be a JSON object")
    return data


def reject_unknown(body: dict, allowed):
    for k in body.keys():
        if k not in allowed:
            raise validation(f"Unknown field: {k}")


def require(body: dict, field):
    if field not in body or body[field] is None:
        raise validation(f"Missing required field: {field}")
    return body[field]


def optional(body: dict, field, default=None):
    v = body.get(field, default)
    return v


def as_string(v, field):
    if not isinstance(v, str) or not v:
        raise validation(f"{field} must be a non-empty string")
    return v


def as_int(v, field, minimum=None):
    if isinstance(v, bool) or not isinstance(v, int):
        raise validation(f"{field} must be an integer")
    if minimum is not None and v < minimum:
        raise validation(f"{field} out of range")
    return v


def as_number(v, field, minimum=None, exclusive_min=False) -> Decimal:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise validation(f"{field} must be a number")
    d = D(v)
    if minimum is not None:
        if exclusive_min:
            if d <= D(minimum):
                raise validation(f"{field} out of range")
        elif d < D(minimum):
            raise validation(f"{field} out of range")
    return d


def as_enum(v, field, members):
    if not isinstance(v, str) or v not in members:
        raise validation(f"{field} must be one of {sorted(members)}")
    return v


def as_bool(v, field):
    if not isinstance(v, bool):
        raise validation(f"{field} must be a boolean")
    return v


def one_decimal_max(d: Decimal, field) -> Decimal:
    if -d.as_tuple().exponent > 1:
        # more than 1 decimal place
        if d != round_half_up(d, 1):
            raise validation(f"{field} must carry at most one decimal place")
    return round_half_up(d, 1)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def parse_pagination():
    from flask import request
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise validation("limit must be an integer")
        if limit < 1 or limit > 100:
            raise validation("limit out of range")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise validation("offset must be an integer")
        if offset < 0:
            raise validation("offset out of range")
    return limit, offset


def paginate(items, limit, offset):
    return items[offset:offset + limit]
