"""Time, decimal, and request-body validation helpers."""

import math
from datetime import datetime, timezone

from decimal import Decimal, ROUND_HALF_UP
from flask import request

from errors import bad_request


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def iso3(dt):
    """ISO 8601 UTC timestamp with exactly three fractional digits (PRD §2.4)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def wall_iso3():
    """Wall-clock UTC timestamp with three fractional digits (meta envelope)."""
    return iso3(datetime.now(timezone.utc))


def parse_datetime(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Returns None when the value is not a valid datetime string.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    # Normalise a trailing Z for fromisoformat.
    candidate = s[:-1] + "+00:00" if s.endswith(("Z", "z")) else s
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_months(dt, months):
    """Add calendar months, landing on the same day-of-month (clamped)."""
    total = dt.year * 12 + (dt.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    if month == 12:
        last_day = 31
    elif month in (4, 6, 9, 11):
        last_day = 30
    else:
        if year % 400 == 0 or (year % 4 == 0 and year % 100 != 0):
            last_day = 29
        else:
            last_day = 28
    day = min(dt.day, last_day)
    return dt.replace(year=year, month=month, day=day)


# ---------------------------------------------------------------------------
# Decimal helpers — round-half-up only, at pinned rounding points (PRD §2.5)
# ---------------------------------------------------------------------------
def dec(value):
    """Decimal from an int/float/str without binary-float artefacts."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round2(value):
    """Round half-up to exactly 2 decimal places; returned as Decimal."""
    return dec(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round0(value):
    """Round half-up to a whole unit; returned as int."""
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def to_json_number(d):
    """Serialize a Decimal micron quantity as a JSON number."""
    if isinstance(d, Decimal):
        return float(d)
    return d


# ---------------------------------------------------------------------------
# Request body extraction and field validation (gate 3: ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------
def get_body():
    """Return the JSON request body as a dict; {} when absent.

    Malformed JSON or a non-object JSON value is a 400.
    """
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        # Body present but not parseable JSON (or literal 'null').
        stripped = request.data.strip()
        if stripped in (b"null", b""):
            return {}
        raise bad_request("request body must be a JSON object")
    if not isinstance(data, dict):
        raise bad_request("request body must be a JSON object")
    return data


def _present(body, name):
    return name in body and body[name] is not None


def req_str(body, name, non_empty=True):
    if not _present(body, name):
        raise bad_request(f"missing required field: {name}")
    value = body[name]
    if not isinstance(value, str):
        raise bad_request(f"field {name} must be a string")
    if non_empty and value.strip() == "":
        raise bad_request(f"field {name} must be a non-empty string")
    return value


def opt_str(body, name, default=None):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, str):
        raise bad_request(f"field {name} must be a string")
    return value


def req_int(body, name, minimum=None, maximum=None):
    if not _present(body, name):
        raise bad_request(f"missing required field: {name}")
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_request(f"field {name} must be an integer")
    if minimum is not None and value < minimum:
        raise bad_request(f"field {name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise bad_request(f"field {name} must be <= {maximum}")
    return value


def opt_int(body, name, minimum=None, maximum=None, default=None):
    if not _present(body, name):
        return default
    return req_int(body, name, minimum=minimum, maximum=maximum)


def req_number(body, name, minimum=None):
    if not _present(body, name):
        raise bad_request(f"missing required field: {name}")
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad_request(f"field {name} must be a number")
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise bad_request(f"field {name} must be a finite number")
    if minimum is not None and value < minimum:
        raise bad_request(f"field {name} must be >= {minimum}")
    return value


def req_enum(body, name, allowed):
    if not _present(body, name):
        raise bad_request(f"missing required field: {name}")
    value = body[name]
    if value not in allowed:
        raise bad_request(f"field {name} must be one of {sorted(allowed)}")
    return value


def req_datetime(body, name):
    """Required datetime field; returns (datetime, raw_string)."""
    if not _present(body, name):
        raise bad_request(f"missing required field: {name}")
    raw = body[name]
    dt = parse_datetime(raw)
    if dt is None:
        raise bad_request(f"field {name} must be an ISO 8601 datetime")
    return dt, raw


def req_samples(body, name, length):
    if not _present(body, name):
        raise bad_request(f"missing required field: {name}")
    value = body[name]
    if not isinstance(value, list) or len(value) != length:
        raise bad_request(f"field {name} must be an array of exactly {length} numbers")
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise bad_request(f"field {name} must contain only numbers")
        if isinstance(item, float) and (math.isnan(item) or math.isinf(item)):
            raise bad_request(f"field {name} must contain only finite numbers")
    return value


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, bounded [1, 100]; offset default 0
# ---------------------------------------------------------------------------
def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise bad_request("limit must be an integer")
        if str(raw_limit).strip() != str(limit):
            raise bad_request("limit must be an integer")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise bad_request("offset must be an integer")
        if str(raw_offset).strip() != str(offset):
            raise bad_request("offset must be an integer")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + len(page)) < total
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
