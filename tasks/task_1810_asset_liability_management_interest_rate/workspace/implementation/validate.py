"""Rung-1/2 authentication plus rung-4 body-shape field validators.

The validation ladder (PRD 2.9) is enforced across the request pipeline:
  1. identity headers        -> authenticate()
  2. role authorization      -> the endpoint decorator
  3. path existence          -> handlers, left-to-right, ERR_NOT_FOUND
  4. body shape              -> the req_*/opt_* helpers below
  5. OCC                     -> handlers (ERR_STALE_VERSION)
  6..12                      -> handlers / services
"""

import math
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from timeutil import parse_instant, parse_month

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

ALL_ROLES = ("TreasuryAnalyst", "ModelRiskValidator", "ALCOChair", "Regulator")


def authenticate():
    """Rung 1: X-User-ID and X-User-Role must be present and non-empty."""
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if user_id is None or not user_id.strip():
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")
    if role is None or not role.strip():
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")
    return user_id, role


def get_body():
    """JSON object body; anything else (missing, malformed, non-object) is
    treated as an empty object so required-field checks fire uniformly."""
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        return body
    return {}


def _bad():
    raise ApiError("ERR_INVALID_REQUEST")


def _as_int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    return None


def _as_decimal(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def req_int(body, field, min_v=None, max_v=None):
    if field not in body or body[field] is None:
        _bad()
    v = _as_int(body[field])
    if v is None:
        _bad()
    if min_v is not None and v < min_v:
        _bad()
    if max_v is not None and v > max_v:
        _bad()
    return v


def opt_int(body, field, min_v=None, max_v=None, default=None):
    if field not in body or body[field] is None:
        return default
    return req_int(body, field, min_v, max_v)


def req_num(body, field, min_v=None, max_v=None):
    """Numeric field; echoes the caller's original JSON number back."""
    if field not in body or body[field] is None:
        _bad()
    d = _as_decimal(body[field])
    if d is None:
        _bad()
    if min_v is not None and d < Decimal(str(min_v)):
        _bad()
    if max_v is not None and d > Decimal(str(max_v)):
        _bad()
    return body[field]


def opt_num(body, field, min_v=None, max_v=None, default=None):
    if field not in body or body[field] is None:
        return default
    return req_num(body, field, min_v, max_v)


def req_str(body, field, non_empty=True):
    if field not in body or body[field] is None:
        _bad()
    v = body[field]
    if not isinstance(v, str):
        _bad()
    if non_empty and not v.strip():
        _bad()
    return v


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return req_str(body, field, non_empty=False)


def req_bool(body, field):
    if field not in body or body[field] is None:
        _bad()
    if not isinstance(body[field], bool):
        _bad()
    return body[field]


def opt_bool(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return req_bool(body, field)


def req_enum(body, field, values):
    if field not in body or body[field] is None:
        _bad()
    if body[field] not in values:
        _bad()
    return body[field]


def req_month(body, field):
    """'YYYY-MM' month string (PRD 2.4 monthly conventions)."""
    if field not in body or body[field] is None:
        _bad()
    if parse_month(body[field]) is None:
        _bad()
    return body[field]


def req_instant(body, field):
    """ISO 8601 instant supplied by the caller (stored raw, echoed verbatim)."""
    if field not in body or body[field] is None:
        _bad()
    if parse_instant(body[field]) is None:
        _bad()
    return body[field]


def req_object(body, field):
    if field not in body or body[field] is None:
        _bad()
    if not isinstance(body[field], dict):
        _bad()
    return body[field]
