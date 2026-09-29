"""Authentication / authorization (PRD 2.1) and request-body validation (PRD 2.5 step 4)."""
from functools import wraps

from flask import g, request

from db import parse_dt
from errors import ApiError

ROLE_FILER = "Filer"
ROLE_COMMENTER = "PublicCommenter"
ROLE_ANALYST = "CaseAnalyst"
ROLE_OFFICIAL = "ApprovingOfficial"
ROLE_MONITOR = "ComplianceMonitor"

ALL_ROLES = (ROLE_FILER, ROLE_COMMENTER, ROLE_ANALYST, ROLE_OFFICIAL, ROLE_MONITOR)
READ_ROLES_NO_COMMENTER = (ROLE_ANALYST, ROLE_OFFICIAL, ROLE_MONITOR, ROLE_FILER)


def require_roles(*roles):
    """Header presence + role validity (401), then endpoint authorization (403)."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not str(user_id).strip():
                raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required")
            if not role or role not in ALL_ROLES:
                raise ApiError("ERR_UNAUTHENTICATED", "a valid X-User-Role header is required")
            if role not in roles:
                raise ApiError(
                    "ERR_ROLE_NOT_PERMITTED",
                    "role %s may not call this endpoint" % role,
                )
            g.user_id = str(user_id)
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def actor_id():
    return g.user_id


def actor_role():
    return g.role


# --------------------------------------------------------------------------
# body helpers
# --------------------------------------------------------------------------
def get_body(required=False):
    raw = request.get_data()
    if not raw:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "a JSON request body is required")
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise ApiError("ERR_INVALID_REQUEST", "request body must be valid JSON")
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return body


def _bad(field, detail):
    raise ApiError("ERR_INVALID_REQUEST", "%s %s" % (field, detail))


def present(body, field):
    return field in body and body[field] is not None


def req_str(body, field, min_len=1, max_len=None):
    if not present(body, field):
        _bad(field, "is required")
    value = body[field]
    if not isinstance(value, str):
        _bad(field, "must be a string")
    if len(value.strip()) < max(min_len, 1) and min_len >= 1:
        _bad(field, "must be non-blank")
    if len(value) < min_len:
        _bad(field, "is too short")
    if max_len is not None and len(value) > max_len:
        _bad(field, "is too long")
    return value


def opt_str(body, field, min_len=1, max_len=None, default=None):
    if not present(body, field):
        return default
    return req_str(body, field, min_len=min_len, max_len=max_len)


def req_enum(body, field, allowed):
    if not present(body, field):
        _bad(field, "is required")
    value = body[field]
    if not isinstance(value, str) or value not in allowed:
        _bad(field, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


def opt_enum(body, field, allowed, default=None):
    if not present(body, field):
        return default
    return req_enum(body, field, allowed)


def _check_int(field, value, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(field, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(field, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(field, "must be <= %s" % maximum)
    return value


def req_int(body, field, minimum=None, maximum=None):
    if not present(body, field):
        _bad(field, "is required")
    return _check_int(field, body[field], minimum, maximum)


def opt_int(body, field, minimum=None, maximum=None, default=None):
    if not present(body, field):
        return default
    return _check_int(field, body[field], minimum, maximum)


def req_bool(body, field):
    if not present(body, field):
        _bad(field, "is required")
    if not isinstance(body[field], bool):
        _bad(field, "must be a boolean")
    return body[field]


def opt_bool(body, field, default=False):
    if not present(body, field):
        return default
    return req_bool(body, field)


def req_dt(body, field):
    if not present(body, field):
        _bad(field, "is required")
    parsed = parse_dt(body[field])
    if parsed is None:
        _bad(field, "must be a valid UTC timestamp")
    return parsed


def opt_dt(body, field, default=None):
    if not present(body, field):
        return default
    return req_dt(body, field)


def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            _bad("limit", "must be an integer")
        if limit < 1 or limit > 100:
            _bad("limit", "must be between 1 and 100")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            _bad("offset", "must be an integer")
        if offset < 0:
            _bad("offset", "must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    return items[offset:offset + limit]
