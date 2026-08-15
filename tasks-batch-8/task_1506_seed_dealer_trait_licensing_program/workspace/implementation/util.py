"""Shared helpers: datetime parsing, rounding, request body validation,
pagination, and foreign-key resolution."""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from flask import request

import db
from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND


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


def dt_of(entity, field):
    """Parse a stored datetime string field (input fields echo verbatim)."""
    return parse_dt(entity[field], field)


# ---------------------------------------------------------------------------
# Rounding (round-half-up; never banker's rounding, never float money)
# ---------------------------------------------------------------------------

def rhu_div(numer, denom=10000):
    """round_half_up(numer / denom) to whole units, for non-negative numer."""
    q = (Decimal(int(numer)) / Decimal(int(denom))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


def rhu_1dp(value):
    """round_half_up to one decimal place; returns a float for JSON output."""
    q = Decimal(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return float(q)


def ceil_nonneg(numer, denom):
    """Smallest integer >= numer/denom for non-negative values."""
    q = (Decimal(numer) / Decimal(denom)).to_integral_value(rounding=ROUND_CEILING)
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
        raise ApiError(ERR_INVALID_REQUEST, 400, "request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


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
        if "min" in spec and not (value > spec["min"] if spec.get("min_exclusive") else value >= spec["min"]):
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} is out of range")
        if "max" in spec and value > spec["max"]:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} is out of range")
    elif kind == "boolean":
        if not isinstance(value, bool):
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} must be a boolean")
    elif kind == "datetime":
        parse_dt(value, name)
    elif kind == "enum":
        if value not in spec["values"]:
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
    """Validate request shape: unknown fields rejected, required fields
    present, per-field type/enum/range checks. Raises ERR_INVALID_REQUEST."""
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


def require_fk(collection, value, what=None):
    """Resolve a body/path foreign key to an existing entity (404)."""
    ent = db.get(collection, value)
    if ent is None:
        raise ApiError(ERR_NOT_FOUND, 404, f"{what or collection} not found")
    return ent


def exist_body_fks(body, mapping):
    """Priority-4 existence check for body foreign keys that are present.
    mapping: field name -> (collection, description)."""
    for field, (collection, what) in mapping.items():
        if field in body and body[field] is not None:
            require_fk(collection, body[field], what)


# ---------------------------------------------------------------------------
# Pagination
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
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be an integer")
        if str(raw_limit).strip() != str(limit) and not raw_limit.strip().lstrip("+").isdigit():
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
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


def apply_filters(items, allowed_filters):
    """Exact-match filters from query params. Unknown params are ignored."""
    result = items
    for field in allowed_filters:
        if field in request.args:
            wanted = request.args.get(field)
            result = [e for e in result if _filter_match(e.get(field), wanted)]
    return result


def _filter_match(value, wanted):
    if value is None:
        return wanted in ("null", "")
    if isinstance(value, bool):
        return wanted.lower() == str(value).lower()
    return str(value) == wanted
