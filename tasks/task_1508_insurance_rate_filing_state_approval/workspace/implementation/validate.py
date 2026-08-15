"""Request-body validation helpers (PRD §2.8 stage 3: ERR_INVALID_REQUEST).

Bodies are parsed with parse_float=Decimal so decimal inputs keep their exact
representation for downstream half-up rounding.
"""
import json
import re
from decimal import Decimal

from flask import request

from errors import ApiError, ERR_INVALID_REQUEST
from timeutil import parse_date, parse_timestamp

_STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")


def _invalid(message):
    return ApiError(ERR_INVALID_REQUEST, message, 400)


def get_json_body(required=True):
    """Parse the request body as a JSON object.

    Returns {} when no body is present and required=False. Raises
    ERR_INVALID_REQUEST for malformed JSON or a non-object body.
    """
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        if required:
            raise _invalid("Request body is required")
        return {}
    try:
        body = json.loads(raw, parse_float=Decimal, parse_int=int)
    except (ValueError, TypeError):
        raise _invalid("Request body is not well-formed JSON")
    if not isinstance(body, dict):
        raise _invalid("Request body must be a JSON object")
    return body


def validate_body(body, spec):
    """Validate body against spec: {field: (required, validator)}.

    validator: (value) -> cleaned value, raising ValueError on bad input.
    Unknown fields, missing required fields, and type/enum/format violations
    all surface as ERR_INVALID_REQUEST.
    Returns a dict of cleaned values (present optional fields included).
    """
    for key in body:
        if key not in spec:
            raise _invalid(f"Unknown field: {key}")
    out = {}
    for name, (required, validator) in spec.items():
        if name not in body or body[name] is None:
            if required:
                raise _invalid(f"Missing required field: {name}")
            out[name] = None
            continue
        value = body[name]
        try:
            out[name] = validator(value)
        except (ValueError, TypeError):
            raise _invalid(f"Invalid value for field: {name}")
    return out


# --- field validators -------------------------------------------------------

def v_string(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("expected non-empty string")
    return value


def v_int(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("expected integer")
    return value


def v_pos_int(value):
    v = v_int(value)
    if v <= 0:
        raise ValueError("expected positive integer")
    return v


def v_nonneg_int(value):
    v = v_int(value)
    if v < 0:
        raise ValueError("expected non-negative integer")
    return v


def v_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise ValueError("expected number")
    return value if isinstance(value, Decimal) else Decimal(value)


def v_pos_number(value):
    v = v_number(value)
    if v <= 0:
        raise ValueError("expected positive number")
    return v


def v_nonneg_number(value):
    v = v_number(value)
    if v < 0:
        raise ValueError("expected non-negative number")
    return v


def v_enum(members):
    def _v(value):
        if not isinstance(value, str) or value not in members:
            raise ValueError("invalid enum member")
        return value

    return _v


def v_state_code(value):
    if not isinstance(value, str) or not _STATE_CODE_RE.match(value):
        raise ValueError("state_code must be an uppercase A-Z pair")
    return value


def v_date(value):
    d = parse_date(value)
    if d is None:
        raise ValueError("expected YYYY-MM-DD date")
    return value  # keep canonical string form


def v_timestamp(value):
    dt = parse_timestamp(value)
    if dt is None:
        raise ValueError("expected ISO 8601 timestamp")
    return dt


def v_optional(validator):
    def _v(value):
        if value is None:
            return None
        return validator(value)

    return _v


def pagination_params():
    """Parse limit/offset query params (defaults 10/0, limit within 1..100)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise _invalid("limit must be an integer")
        if limit < 1 or limit > 100:
            raise _invalid("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise _invalid("offset must be an integer")
        if offset < 0:
            raise _invalid("offset must be non-negative")
    return limit, offset


def apply_filters(items, filters):
    """Equality filters drawn from the resource's own fields."""
    out = items
    for name, value in filters.items():
        if value is None:
            continue
        out = [e for e in out if e.get(name) == value]
    return out


def paginate(items):
    """Sort by (created_at, insertion seq) ascending, then paginate."""
    limit, offset = pagination_params()
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    page = ordered[offset : offset + limit]
    return page, total, limit, offset
