"""Shared request-handling utilities: decimals, auth, body validation, pagination."""

import re
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import clock
import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED_ROLE,
    ERR_FORBIDDEN,
    ERR_NOT_FOUND,
    ERR_REFERENCED_NOT_FOUND,
)

ROLES = {
    "PlantAdmin",
    "RouteDriver",
    "PlantOperator",
    "CustomerServiceRep",
    "BillingClerk",
    "CustomerContact",
}

ALL_ROLES = frozenset(ROLES)
PLANT_SIDE = frozenset({"PlantAdmin", "PlantOperator", "RouteDriver", "CustomerServiceRep", "BillingClerk"})
FLOOR_READ = frozenset({"PlantAdmin", "PlantOperator", "CustomerServiceRep", "BillingClerk"})


# ---------------------------------------------------------------- decimals
def D(x):
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def round2(x):
    return D(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round0(x):
    return int(D(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round4(x):
    return D(x).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------- auth
class Auth:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Priority 1: X-User-ID and X-User-Role present and well-formed."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401, "Missing or malformed X-User-ID / X-User-Role headers")
    return Auth(uid, role)


def require_roles(auth, allowed):
    """Priority 2: role permitted to call this endpoint."""
    if auth.role not in allowed:
        raise ApiError(ERR_UNAUTHORIZED_ROLE, 403, "Role not permitted to call this endpoint")


def cc_owns(auth, customer_id):
    """CustomerContact ownership: X-User-ID is the acting Customer's id."""
    if auth.role == "CustomerContact" and auth.user_id != customer_id:
        raise ApiError(ERR_FORBIDDEN, 403, "CustomerContact may only access its own customer's resources")


# ---------------------------------------------------------------- body schema (priority 0)
def body_json(required=True):
    data = request.get_json(silent=True)
    if data is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return data


def _bad(msg):
    raise ApiError(ERR_INVALID_REQUEST, 400, msg)


def field(data, name, kind="s", required=True, choices=None, minv=None):
    """Validate one body field. kind: s=string, i=integer, n=number, b=boolean,
    date=YYYY-MM-DD, datetime=ISO 8601, month=YYYY-MM."""
    if name not in data or data[name] is None:
        if required:
            _bad("Missing required field: %s" % name)
        return None
    v = data[name]
    ok = True
    if kind == "s":
        ok = isinstance(v, str)
    elif kind == "i":
        ok = isinstance(v, int) and not isinstance(v, bool)
    elif kind == "n":
        ok = isinstance(v, (int, float)) and not isinstance(v, bool)
    elif kind == "b":
        ok = isinstance(v, bool)
    elif kind == "date":
        ok = isinstance(v, str) and clock.parse_date(v) is not None
    elif kind == "datetime":
        ok = isinstance(v, str) and clock.parse_dt(v) is not None
    elif kind == "month":
        ok = isinstance(v, str) and re.match(r"^\d{4}-(0[1-9]|1[0-2])$", v) is not None
    if not ok:
        _bad("Invalid type for field: %s" % name)
    if choices is not None and v not in choices:
        _bad("Invalid value for field: %s" % name)
    if minv is not None and v < minv:
        _bad("Field %s below minimum %s" % (name, minv))
    return v


# ---------------------------------------------------------------- path / body reference lookups
def _lookup(store, rid, error_id):
    e = store.get(rid)
    if e is None:
        raise ApiError(error_id, 404, "Resource not found: %s" % rid)
    return e


def path_get(store, rid):
    """Priority 3: path resource ids -> ERR_NOT_FOUND."""
    return _lookup(store, rid, ERR_NOT_FOUND)


def ref_get(store, rid):
    """Priority 4: body-referenced ids -> ERR_REFERENCED_NOT_FOUND."""
    return _lookup(store, rid, ERR_REFERENCED_NOT_FOUND)


# ---------------------------------------------------------------- pagination
def _qint(name):
    v = request.args.get(name)
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def paginate(items):
    """limit default 10 (min 1, max 100); offset default 0."""
    total = len(items)
    limit = _qint("limit")
    offset = _qint("offset")
    limit = 10 if limit is None else max(1, min(100, limit))
    offset = 0 if offset is None else max(0, offset)
    page = items[offset : offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


def filter_eq(items, param, key):
    v = request.args.get(param)
    if v is None:
        return items
    return [e for e in items if str(e.get(key)) == v]
