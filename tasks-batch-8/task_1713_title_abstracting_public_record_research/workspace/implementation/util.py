"""Shared helpers: datetime/date parsing, rounding, request body validation,
pagination, and foreign-key resolution."""

import re
from datetime import datetime, date, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import db
from errors import ApiError, ERR_VALIDATION

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")


# ---------------------------------------------------------------------------
# Datetimes and dates
# ---------------------------------------------------------------------------

def parse_dt(value, field="datetime"):
    """Parse an ISO 8601 datetime string; accepts trailing Z or offsets.
    All timestamp comparisons in this domain are made to the second, so the
    parsed value is truncated to whole seconds."""
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
    return parsed.astimezone(timezone.utc).replace(microsecond=0)


def parse_date(value, field="date"):
    """Parse a strict ISO YYYY-MM-DD date string."""
    if not isinstance(value, str) or not _DATE_RE.match(value.strip()):
        raise ApiError(ERR_VALIDATION, 400, f"{field} must be an ISO YYYY-MM-DD date string")
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ApiError(ERR_VALIDATION, 400, f"{field} is not a valid calendar date")


def dt_of_stored(value):
    """Parse a stored datetime string (server-formatted or echoed input)."""
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0)


# ---------------------------------------------------------------------------
# Rounding (round-half-up on integer cents; never float money)
# ---------------------------------------------------------------------------

def rhu(numer, denom=1):
    """round_half_up(numer / denom) to whole units."""
    q = (Decimal(int(numer)) / Decimal(int(denom))).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
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
    elif kind == "boolean":
        if not isinstance(value, bool):
            raise ApiError(ERR_VALIDATION, 400, f"{name} must be a boolean")
    elif kind == "datetime":
        parse_dt(value, name)
    elif kind == "date":
        parse_date(value, name)
    elif kind == "state_code":
        if not isinstance(value, str) or not _STATE_CODE_RE.match(value):
            raise ApiError(ERR_VALIDATION, 400, f"{name} must be exactly 2 uppercase letters A-Z")
    elif kind == "enum":
        if value not in spec["values"]:
            raise ApiError(ERR_VALIDATION, 400, f"{name} must be one of {sorted(spec['values'])}")
    else:
        raise AssertionError(f"unknown spec type {kind}")


def check_shape(body, spec, parent=None):
    """Validate request shape: unknown fields rejected, required fields
    present, per-field type/enum/range checks. Raises ERR_VALIDATION."""
    for key in body:
        if key not in spec:
            where = f"{parent}.{key}" if parent else key
            raise ApiError(ERR_VALIDATION, 400, f"unknown field: {where}")
    for name, s in spec.items():
        if s.get("required") and name not in body:
            where = f"{parent}.{name}" if parent else name
            raise ApiError(ERR_VALIDATION, 400, f"missing required field: {where}")
        if name in body:
            value = body[name]
            # An explicit JSON null on an optional field means "absent".
            if value is None and not s.get("required"):
                continue
            _check_value(f"{parent}.{name}" if parent else name, value, s)


def require_fk(collection, value, error_id, what):
    """Resolve a body/path foreign key to an existing entity (404)."""
    ent = db.get(collection, value)
    if ent is None:
        raise ApiError(error_id, 404, f"{what} not found")
    return ent


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
            raise ApiError(ERR_VALIDATION, 400, "limit must be an integer")
        if str(raw_limit).strip() != str(limit) and not raw_limit.strip().lstrip("+").isdigit():
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
        return wanted in ("", "null")
    if isinstance(value, bool):
        return wanted.lower() == ("true" if value else "false")
    return str(value) == wanted
