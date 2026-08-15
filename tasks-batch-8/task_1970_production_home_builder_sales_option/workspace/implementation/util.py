"""Shared helpers: datetime parsing, rounding, request body validation,
pagination, and foreign-key resolution."""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from flask import request

import db
from errors import ApiError, ERR_INVALID_REQUEST


# ---------------------------------------------------------------------------
# Datetimes
# ---------------------------------------------------------------------------

def parse_dt(value, field="datetime"):
    """Parse an ISO 8601 datetime string; accepts trailing Z or offsets."""
    if not isinstance(value, str) or not value.strip():
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} must be an ISO 8601 datetime string")
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} is not a valid ISO 8601 datetime")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Rounding (round-half-up; never banker's rounding, never float money)
# ---------------------------------------------------------------------------

def rhu(value):
    """round_half_up of a Decimal to whole integer cents."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_days(days):
    """ceil(days * (1 + WEATHER_BUFFER_PCT)) for the padded closing estimate."""
    from constants import WEATHER_BUFFER_PCT

    inflated = Decimal(int(days)) * (Decimal("1") + WEATHER_BUFFER_PCT)
    return int(inflated.to_integral_value(rounding=ROUND_CEILING))


def decimal_of(value):
    """Exact Decimal for a JSON number (str() avoids binary float noise)."""
    return Decimal(str(value))


# ---------------------------------------------------------------------------
# Request body handling
# ---------------------------------------------------------------------------

def body_json():
    """Return the request JSON body as a dict; empty body -> {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _check_value(name, value, spec):
    kind = spec["type"]
    if kind == "string":
        if not isinstance(value, str):
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} must be a string")
    elif kind == "integer":
        if not _is_int(value):
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} must be an integer")
        if "min" in spec and value < spec["min"]:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} must be >= {spec['min']}")
        if "max" in spec and value > spec["max"]:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} must be <= {spec['max']}")
    elif kind == "number":
        if not _is_number(value):
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} must be a number")
        if "min" in spec and value < spec["min"]:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} is out of range")
        if "max" in spec and value > spec["max"]:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} is out of range")
    elif kind == "boolean":
        if not isinstance(value, bool):
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} must be a boolean")
    elif kind == "datetime":
        parse_dt(value, name)
    elif kind == "enum":
        if not isinstance(value, str) or value not in spec["values"]:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} must be one of {sorted(spec['values'])}")
    elif kind == "array":
        if not isinstance(value, list):
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} must be an array")
        item_spec = spec.get("items")
        if item_spec:
            for item in value:
                if not isinstance(item, dict):
                    raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} items must be objects")
                check_shape(item, item_spec, parent=name)
    else:
        raise AssertionError(f"unknown spec type {kind}")


def check_shape(body, spec, parent=None):
    """Validation tier 3 (body well-formedness): unknown fields rejected,
    required fields present, per-field type/enum/range checks.
    Raises ERR_INVALID_REQUEST (400)."""
    for key in body:
        if key not in spec:
            where = f"{parent}.{key}" if parent else key
            raise ApiError(ERR_INVALID_REQUEST, 400, f"unknown field: {where}")
    for name, s in spec.items():
        if s.get("required") and name not in body:
            where = f"{parent}.{name}" if parent else name
            raise ApiError(ERR_INVALID_REQUEST, 400, f"missing required field: {where}")
        if name in body:
            value = body[name]
            # An explicit JSON null on an optional field means "absent".
            if value is None and not s.get("required"):
                continue
            _check_value(f"{parent}.{name}" if parent else name, value, s)


def require_fk(collection, value, error_id, what=None):
    """Validation tier 4: resolve a path/body foreign key (404)."""
    ent = db.get(collection, value)
    if ent is None:
        raise ApiError(error_id, 404, f"{what or collection} not found")
    return ent


# ---------------------------------------------------------------------------
# Pagination (PRD section 2.3: limit/offset, defaults 10/0, limit 1..100)
# ---------------------------------------------------------------------------

def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be an integer")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + len(page)) < total
    return page, total, has_more


def _filter_match(value, wanted):
    if value is None:
        return False
    return str(value) == wanted


def apply_filters(items, allowed_filters):
    """Exact-match filters from query params. Unknown params are ignored."""
    result = items
    for field in allowed_filters:
        if field in request.args:
            wanted = request.args.get(field)
            result = [e for e in result if _filter_match(e.get(field), wanted)]
    return result
