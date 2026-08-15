"""Shared helpers: date/datetime parsing, Decimal rounding (round-half-up),
request body validation, pagination, and foreign-key resolution.

Money is integer cents; workload credits are 2dp decimals rounded half-up.
All credit arithmetic goes through Decimal(str(...)) so 2dp values stay exact.
"""

from datetime import datetime, date, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import db
from errors import ApiError, ERR_VALIDATION


# ---------------------------------------------------------------------------
# Dates and datetimes
# ---------------------------------------------------------------------------

def parse_dt(value, field="datetime"):
    """Parse an ISO 8601 datetime string; accepts trailing Z or offsets."""
    if not isinstance(value, str) or not value.strip():
        raise ApiError(ERR_VALIDATION, 400, f"{field} must be an ISO 8601 datetime string")
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ApiError(ERR_VALIDATION, 400, f"{field} is not a valid ISO 8601 datetime")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_date(value, field="date"):
    """Parse a strict ISO date (YYYY-MM-DD); returns datetime.date."""
    if not isinstance(value, str) or not value.strip():
        raise ApiError(ERR_VALIDATION, 400, f"{field} must be an ISO date string (YYYY-MM-DD)")
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise ApiError(ERR_VALIDATION, 400, f"{field} is not a valid ISO date")


def today():
    """Current logical date (UTC) per the logical clock (PRD §2.7)."""
    return db.now().astimezone(timezone.utc).date()


# ---------------------------------------------------------------------------
# Rounding (round-half-up via Decimal; never float arithmetic for money)
# ---------------------------------------------------------------------------

def dec(value):
    """Exact Decimal view of a stored/input numeric (2dp floats round-trip
    cleanly through str())."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu2(value):
    """round_half_up to 2 decimal places; returns a float for JSON output."""
    q = dec(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(q)


def rhu0(value):
    """round_half_up to whole units; returns an int (integer cents)."""
    q = dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


# ---------------------------------------------------------------------------
# Request body handling
# ---------------------------------------------------------------------------

def body_json():
    """Return the request JSON body as a dict; empty body -> {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_VALIDATION, 400, "request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _check_value(name, value, spec):
    kind = spec["type"]
    if kind == "string":
        if not isinstance(value, str):
            raise ApiError(ERR_VALIDATION, 400, f"{name} must be a string")
    elif kind == "integer":
        if not _is_int(value):
            raise ApiError(ERR_VALIDATION, 400, f"{name} must be an integer")
        if "min" in spec and value < spec["min"]:
            raise ApiError(ERR_VALIDATION, 400, f"{name} must be >= {spec['min']}")
        if "max" in spec and value > spec["max"]:
            raise ApiError(ERR_VALIDATION, 400, f"{name} must be <= {spec['max']}")
    elif kind == "number":
        if not _is_number(value):
            raise ApiError(ERR_VALIDATION, 400, f"{name} must be a number")
        if "min" in spec:
            if spec.get("min_exclusive"):
                if not value > spec["min"]:
                    raise ApiError(ERR_VALIDATION, 400, f"{name} must be > {spec['min']}")
            elif value < spec["min"]:
                raise ApiError(ERR_VALIDATION, 400, f"{name} must be >= {spec['min']}")
        if "max" in spec and value > spec["max"]:
            raise ApiError(ERR_VALIDATION, 400, f"{name} must be <= {spec['max']}")
    elif kind == "boolean":
        if not isinstance(value, bool):
            raise ApiError(ERR_VALIDATION, 400, f"{name} must be a boolean")
    elif kind == "date":
        parse_date(value, name)
    elif kind == "datetime":
        parse_dt(value, name)
    elif kind == "enum":
        if not isinstance(value, str) or value not in spec["values"]:
            raise ApiError(ERR_VALIDATION, 400, f"{name} must be one of {sorted(spec['values'])}")
    elif kind == "string_array":
        if not isinstance(value, list) or any(not isinstance(i, str) for i in value):
            raise ApiError(ERR_VALIDATION, 400, f"{name} must be an array of strings")
    elif kind == "enum_array":
        if not isinstance(value, list):
            raise ApiError(ERR_VALIDATION, 400, f"{name} must be an array")
        if spec.get("non_empty") and len(value) == 0:
            raise ApiError(ERR_VALIDATION, 400, f"{name} must be a non-empty array")
        for item in value:
            if not isinstance(item, str) or item not in spec["values"]:
                raise ApiError(ERR_VALIDATION, 400, f"{name} items must be among {sorted(spec['values'])}")
    else:
        raise AssertionError(f"unknown spec type {kind}")


def check_shape(body, spec):
    """Validate request shape: required fields present, per-field
    type/enum/range checks. Unknown fields are IGNORED (client-supplied
    system/computed fields such as id or credit_units are discarded, per the
    resource-creation contract). Raises ERR_VALIDATION (400)."""
    for name, s in spec.items():
        if s.get("required") and name not in body:
            raise ApiError(ERR_VALIDATION, 400, f"missing required field: {name}")
        if name in body:
            value = body[name]
            # An explicit JSON null on an optional field means "absent".
            if value is None and not s.get("required"):
                continue
            _check_value(name, value, s)


def present(body, field):
    """True when an optional field was supplied with a non-null value."""
    return field in body and body[field] is not None


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3: limit default 10, min 1, max 100; offset default 0)
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
            raise ApiError(ERR_VALIDATION, 400, "limit must be an integer")
        if str(raw_limit).strip() != str(limit) and not str(raw_limit).strip().lstrip("+").isdigit():
            raise ApiError(ERR_VALIDATION, 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_VALIDATION, 400, "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_VALIDATION, 400, "offset must be an integer")
        if str(raw_offset).strip() != str(offset) and not str(raw_offset).strip().lstrip("+").isdigit():
            raise ApiError(ERR_VALIDATION, 400, "offset must be an integer")
        if offset < 0:
            raise ApiError(ERR_VALIDATION, 400, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + len(page)) < total
    return page, total, has_more


def apply_filters(items, allowed_filters, key=None):
    """Exact-match filters from query params. Unknown params are ignored.
    key: optional projection applied to each entity before matching (used to
    filter on lazily-derived fields such as an effective status)."""
    result = list(items)
    for field in allowed_filters:
        if field in request.args:
            wanted = request.args.get(field)
            result = [e for e in result if _filter_match((key or (lambda x: x))(e).get(field), wanted)]
    return result


def _filter_match(value, wanted):
    if value is None:
        return wanted in ("null", "")
    if isinstance(value, bool):
        return wanted.lower() == str(value).lower()
    return str(value) == wanted
