"""Shared helpers: datetime parsing, round-half-up math, request body
validation, pagination, and query filters."""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import db
from errors import ApiError, ERR_VALIDATION, ERR_NOT_FOUND


# ---------------------------------------------------------------------------
# Datetimes
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


def dt_of(entity, field):
    """Parse a stored datetime string field."""
    return parse_dt(entity[field], field)


# ---------------------------------------------------------------------------
# Rounding (round-half-up on Decimal; never float money)
# ---------------------------------------------------------------------------

def rhu_div(numer, denom):
    """round_half_up(numer / denom) to whole integer cents."""
    q = (Decimal(int(numer)) / Decimal(int(denom))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


def ceil_hours(seconds):
    """Partial hours round UP to the next whole hour (PRD 2.7)."""
    s = int(seconds)
    if s <= 0:
        return 0
    return (s + 3599) // 3600


def floor_hours(seconds):
    """Screening staffing: turnaround length rounds DOWN to whole hours."""
    s = int(seconds)
    if s <= 0:
        return 0
    return s // 3600


def ceil_div(numer, denom):
    """Ceil division for non-negative integers."""
    if numer <= 0:
        return 0
    return (numer + denom - 1) // denom


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


def raw_body():
    """Lenient body access for the priority-5 OCC pre-check (no 400)."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


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
        if "gt" in spec and not value > spec["gt"]:
            raise ApiError(ERR_VALIDATION, 400, f"{name} must be > {spec['gt']}")
        if "min" in spec and value < spec["min"]:
            raise ApiError(ERR_VALIDATION, 400, f"{name} must be >= {spec['min']}")
    elif kind == "datetime":
        parse_dt(value, name)
    elif kind == "enum":
        if value not in spec["values"]:
            raise ApiError(ERR_VALIDATION, 400, f"{name} must be one of {sorted(spec['values'])}")
    else:
        raise AssertionError(f"unknown spec type {kind}")


def check_shape(body, spec):
    """Validate request shape (pipeline priority 6): required fields present,
    types and enum values valid, integer ranges respected. Unknown fields are
    ignored (the PRD validation pipeline names no unknown-field rejection)."""
    for name, s in spec.items():
        if s.get("required") and (name not in body or body[name] is None):
            raise ApiError(ERR_VALIDATION, 400, f"missing required field: {name}")
        if name in body:
            value = body[name]
            if value is None and not s.get("required"):
                continue
            _check_value(name, value, s)


def require_fk(collection, value, what=None):
    """Resolve a foreign key to an existing entity (priority 3 -> 404)."""
    ent = db.get(collection, value)
    if ent is None:
        raise ApiError(ERR_NOT_FOUND, 404, f"{what or collection} not found")
    return ent


def exist_body_fks(body, mapping):
    """Priority-3 existence check for body foreign keys, in the order the
    fields are declared. Only present, non-null fields are checked; a missing
    FK field is the priority-6 shape check's job."""
    for field, (collection, what) in mapping.items():
        if field in body and body[field] is not None:
            require_fk(collection, body[field], what)


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3: limit default 10 / min 1 / max 100, offset default 0;
# items ordered by created_at ascending)
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
            raise ApiError(ERR_VALIDATION, 400, "limit must be an integer")
        if str(raw_limit).strip() != str(limit) and not str(raw_limit).strip().lstrip("+").isdigit():
            raise ApiError(ERR_VALIDATION, 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_VALIDATION, 400, "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(str(raw_offset).strip())
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
