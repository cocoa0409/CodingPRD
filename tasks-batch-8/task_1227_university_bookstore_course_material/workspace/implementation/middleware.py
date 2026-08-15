"""Auth (PRD §2.1), body parsing, and field validation helpers.

Validation precedence (PRD §2.8): auth(1) -> forbidden(2) -> ownership(3) ->
existence(4) -> state(5, incl. OCC) -> business safety(6) -> temporal(7) ->
constraint(8) -> referential(9) -> fiscal(10). The helpers here implement
layers 1, 2, 4 (lookup helper) and 8 (field shape); route handlers apply the
rest in order.
"""

from datetime import datetime, date, timezone

from flask import request

from errors import (
    ApiError,
    ERR_UNAUTHENTICATED,
    ERR_FORBIDDEN,
    ERR_NOT_FOUND,
    ERR_VALIDATION,
)

ROLES = ("PlatformAdmin", "BookstoreManager", "FinanceAdmin", "Faculty", "Student")
ALL_ROLES = ROLES


def require_roles(*roles):
    """Priority 1-2: authentication then endpoint authorization."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401,
                       "Missing/unknown X-User-Role or X-User-ID")
    if role not in roles:
        raise ApiError(ERR_FORBIDDEN, 403, "Role not allowed for endpoint")
    return uid, role


def body():
    """JSON object body; missing/empty body treated as {} so required-field
    validation fires uniformly. A present non-object body is a 400."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_VALIDATION, 400, "Request body must be a JSON object")
    return data


def get_or_404(coll, key, label="resource"):
    ent = coll.get(key)
    if ent is None:
        raise ApiError(ERR_NOT_FOUND, 404, "{} not found".format(label))
    return ent


def _fail(msg):
    raise ApiError(ERR_VALIDATION, 400, msg)


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


def get_num(data, name, required=True, default=None, lo=None, hi=None):
    """Decimal-fraction percentages: at least `lo`, strictly less than `hi`."""
    if name not in data or data[name] is None:
        if required:
            _fail("Missing required field: " + name)
        return default
    v = data[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _fail("Field {} must be a number".format(name))
    if lo is not None and v < lo:
        _fail("Field {} must be >= {}".format(name, lo))
    if hi is not None and not v < hi:
        _fail("Field {} must be < {}".format(name, hi))
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


def parse_date(s, field="date"):
    """Strict YYYY-MM-DD calendar date; returned as the canonical string so
    closed-interval comparisons are lexicographic."""
    if not isinstance(s, str):
        _fail("Field {} must be a YYYY-MM-DD string".format(field))
    try:
        d = date.fromisoformat(s.strip())
    except ValueError:
        _fail("Field {} is not a valid YYYY-MM-DD date".format(field))
    if d.isoformat() != s.strip():
        _fail("Field {} must be in YYYY-MM-DD form".format(field))
    return d.isoformat()


def get_date(data, name, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            _fail("Missing required field: " + name)
        return default
    return parse_date(data[name], name)


def pagination():
    """PRD §2.3: limit default 10 (min 1, max 100), offset default 0."""
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
        offset = int(raw_offset)
    except (TypeError, ValueError):
        raise ApiError(ERR_VALIDATION, 400, "limit/offset must be integers")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset
