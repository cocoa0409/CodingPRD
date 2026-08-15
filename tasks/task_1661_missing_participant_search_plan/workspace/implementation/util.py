"""Shared helpers: datetime parsing, whole-calendar-day arithmetic, half-up
rounding, request body shape validation, pagination, and FK resolution."""

import math
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_REFERENCE_NOT_FOUND,
    ERR_STALE_VERSION,
)


# ---------------------------------------------------------------------------
# Datetimes and whole-calendar-day arithmetic (PRD section 2.4)
# ---------------------------------------------------------------------------

def parse_dt(value, field="datetime"):
    """Parse an ISO 8601 datetime string; accepts trailing Z or offsets."""
    if not isinstance(value, str) or not value.strip():
        raise ApiError(
            ERR_INVALID_REQUEST, 400,
            f"{field} must be an ISO 8601 datetime string",
        )
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ApiError(
            ERR_INVALID_REQUEST, 400,
            f"{field} is not a valid ISO 8601 datetime",
        )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def days_between(a, b):
    """Whole calendar days from a to b: floor((b - a) / 86400s)."""
    return math.floor((b - a).total_seconds() / 86400)


# ---------------------------------------------------------------------------
# Money: integer cents, round half up (PRD section 2.5)
# ---------------------------------------------------------------------------

def rhu(numerator, denominator=1):
    """round_half_up(numerator / denominator) to whole cents (integer)."""
    q = (Decimal(int(numerator)) / Decimal(int(denominator))).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(q)


# ---------------------------------------------------------------------------
# Request body handling and shape validation (priority 2.5)
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


def _check_value(name, value, spec):
    kind = spec["type"]
    if kind == "string":
        if not isinstance(value, str):
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} must be a string")
    elif kind == "digits":
        n = spec["length"]
        if not isinstance(value, str) or len(value) != n or not value.isdigit():
            raise ApiError(
                ERR_INVALID_REQUEST, 400,
                f"{name} must be exactly {n} digits",
            )
    elif kind == "integer":
        if not _is_int(value):
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} must be an integer")
        if "min" in spec and value < spec["min"]:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} must be >= {spec['min']}")
        if "max" in spec and value > spec["max"]:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} must be <= {spec['max']}")
    elif kind == "datetime":
        parse_dt(value, name)
    elif kind == "enum":
        if value not in spec["values"]:
            raise ApiError(
                ERR_INVALID_REQUEST, 400,
                f"{name} must be one of {sorted(spec['values'])}",
            )
    else:
        raise AssertionError(f"unknown spec type {kind}")


def check_shape(body, spec):
    """Priority 2.5: undeclared fields rejected, required fields present,
    per-field type/enum/range checks. Raises ERR_INVALID_REQUEST."""
    for key in body:
        if key not in spec:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"unknown field: {key}")
    for name, s in spec.items():
        if s.get("required") and name not in body:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"missing required field: {name}")
        if name in body:
            value = body[name]
            # An explicit JSON null on an optional field means "absent".
            if value is None and not s.get("required"):
                continue
            _check_value(name, value, s)


def check_no_fields(body):
    """For endpoints declaring no input fields."""
    if body:
        raise ApiError(
            ERR_INVALID_REQUEST, 400,
            f"unknown field: {sorted(body.keys())[0]}",
        )


# ---------------------------------------------------------------------------
# Existence (priorities 3 and 4) and OCC (priority 5)
# ---------------------------------------------------------------------------

def path_entity(collection, ent_id, what=None):
    """Resolve a path identifier; missing -> ERR_NOT_FOUND."""
    ent = db.get(collection, ent_id)
    if ent is None:
        raise ApiError(ERR_NOT_FOUND, 404, f"{what or collection} not found")
    return ent


def body_fk(body, field, collection, what=None):
    """Resolve a required body foreign key; missing -> ERR_REFERENCE_NOT_FOUND."""
    ent = db.get(collection, body.get(field))
    if ent is None:
        raise ApiError(
            ERR_REFERENCE_NOT_FOUND, 404, f"{what or field} not found"
        )
    return ent


def occ_check(body, field, current):
    """Priority 5: optimistic concurrency. The field is shape-validated as a
    required integer before this runs."""
    if body[field] != current:
        raise ApiError(
            ERR_STALE_VERSION, 412,
            f"{field} does not match the current resource version",
        )


# ---------------------------------------------------------------------------
# Pagination (PRD section 2.3) and filters (section 2.10)
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
