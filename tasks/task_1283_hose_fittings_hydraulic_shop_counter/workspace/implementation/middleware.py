"""Auth (PRD §2.1), body parsing, and field validation helpers.

Validation ladder (PRD §2.11): auth(1) -> forbidden(2) -> existence(3) ->
order terminal lockdown(4) -> state(5) -> OCC(6) -> business safety(7-10) ->
temporal(11-13) -> uniqueness(14) -> referential(15-16) -> fiscal(17-19) ->
malformed request(20). The helpers here implement layers 1-2 (require_roles),
3 (lookup helpers), and the field-shape primitives used by layer 20; route
handlers apply the remaining rungs in order.
"""

from datetime import datetime, timezone

from flask import request

from errors import (
    ApiError,
    ERR_UNAUTHENTICATED,
    ERR_FORBIDDEN,
    ERR_INVALID_REQUEST,
    ERR_CUSTOMER_NOT_FOUND,
    ERR_ASSET_NOT_FOUND,
    ERR_REEL_NOT_FOUND,
    ERR_COUPLING_NOT_FOUND,
    ERR_ORDER_NOT_FOUND,
    ERR_INSPECTION_NOT_FOUND,
    ERR_DISPATCH_NOT_FOUND,
)

ROLES = ("ShopManager", "CounterSales", "ShopTechnician", "FieldTechnician", "Customer")

NOT_FOUND_FOR = {
    "customer": ERR_CUSTOMER_NOT_FOUND,
    "asset": ERR_ASSET_NOT_FOUND,
    "reel": ERR_REEL_NOT_FOUND,
    "coupling": ERR_COUPLING_NOT_FOUND,
    "order": ERR_ORDER_NOT_FOUND,
    "inspection": ERR_INSPECTION_NOT_FOUND,
    "dispatch": ERR_DISPATCH_NOT_FOUND,
}


def require_roles(*roles):
    """Priority 1-2: authentication then endpoint role authorization."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401,
                       "Missing or unrecognized X-User-Role / X-User-ID headers")
    if role not in roles:
        raise ApiError(ERR_FORBIDDEN, 403, "Role not admitted by this endpoint")
    return uid, role


def check_customer_scope(role, uid, resource_customer_id):
    """Priority 2 ownership: the entity-backed Customer role may only touch
    resources whose customer_id equals X-User-ID (PRD §2.1)."""
    if role == "Customer" and resource_customer_id != uid:
        raise ApiError(ERR_FORBIDDEN, 403,
                       "Customer role may only access its own resources")


def body():
    """JSON object body; missing/empty body treated as {} so required-field
    validation fires uniformly. A present non-object body is a 400."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return data


def get_or_404(coll, key, kind):
    ent = coll.get(key) if isinstance(key, str) else None
    if ent is None:
        raise ApiError(NOT_FOUND_FOR[kind], 404, "{} not found".format(kind))
    return ent


def _fail(msg):
    raise ApiError(ERR_INVALID_REQUEST, 400, msg)


def present(data, name):
    return name in data and data[name] is not None


def get_str(data, name, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            _fail("Missing required field: " + name)
        return default
    v = data[name]
    if not isinstance(v, str):
        _fail("Field {} must be a string".format(name))
    return v


def get_int(data, name, required=True, default=None, min_val=None):
    if name not in data or data[name] is None:
        if required:
            _fail("Missing required field: " + name)
        return default
    v = data[name]
    if isinstance(v, bool) or not isinstance(v, int):
        _fail("Field {} must be an integer".format(name))
    if min_val is not None and v < min_val:
        _fail("Field {} must be >= {}".format(name, min_val))
    return v


def get_bool(data, name, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            _fail("Missing required field: " + name)
        return default
    v = data[name]
    if not isinstance(v, bool):
        _fail("Field {} must be a boolean".format(name))
    return v


def get_num(data, name, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            _fail("Missing required field: " + name)
        return default
    v = data[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _fail("Field {} must be a number".format(name))
    return v


def get_enum(data, name, allowed, required=True, default=None):
    v = get_str(data, name, required=required, default=default)
    if v is None:
        return None
    if v not in allowed:
        _fail("Field {} must be one of {}".format(name, list(allowed)))
    return v


def parse_datetime(s, field="datetime"):
    if not isinstance(s, str):
        _fail("Field {} must be an ISO 8601 string".format(field))
    t = s.strip()
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        _fail("Field {} is not a valid ISO 8601 datetime".format(field))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def get_dt(data, name, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            _fail("Missing required field: " + name)
        return default
    return parse_datetime(data[name], name)


def pagination():
    """PRD §2.3: limit default 10 (min 1, max 100), offset default 0."""
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
        offset = int(raw_offset)
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, 400, "limit/offset must be integers")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset
