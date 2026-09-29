"""Authentication / RBAC (PRD Section 2.1) and request-shape validation (2.6 rank 5)."""

import functools
from decimal import Decimal, InvalidOperation

from flask import g, request

from errors import ApiError

ROLES = (
    "ProgramAdmin",
    "ProjectDeveloper",
    "RegulatoryReviewer",
    "IndependentVerifier",
    "Landowner",
)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def authenticate():
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if not user_id or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "missing %s header" % USER_ID_HEADER)
    if not role or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "missing %s header" % USER_ROLE_HEADER)
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "unrecognised role %r" % role)
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def require(*allowed_roles):
    """Decorator: authenticate, then enforce the endpoint's role list."""

    def decorator(view):
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            _, role = authenticate()
            if allowed_roles and role not in allowed_roles:
                raise ApiError("ERR_UNAUTHORIZED", "role %s may not perform this operation" % role)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def caller_id():
    return g.get("user_id")


# --------------------------------------------------------------------------- #
# Body / query validation
# --------------------------------------------------------------------------- #


def body():
    raw = request.get_data(cache=True)
    if not raw or not raw.strip():
        return {}
    parsed = request.get_json(force=True, silent=True)
    if parsed is None:
        raise ApiError("ERR_INVALID_REQUEST", "request body must be a JSON object")
    if not isinstance(parsed, dict):
        raise ApiError("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return parsed


def _invalid(field, reason):
    raise ApiError("ERR_INVALID_REQUEST", "%s %s" % (field, reason))


def _present(payload, field):
    return field in payload and payload[field] is not None


def to_decimal(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def req_str(payload, field, max_len=None):
    if not _present(payload, field):
        _invalid(field, "is required")
    value = payload[field]
    if not isinstance(value, str) or not value.strip():
        _invalid(field, "must be a non-empty string")
    if max_len is not None and len(value) > max_len:
        _invalid(field, "must be at most %d characters" % max_len)
    return value


def opt_str(payload, field, default=None, max_len=None):
    if not _present(payload, field):
        return default
    value = payload[field]
    if not isinstance(value, str):
        _invalid(field, "must be a string")
    if max_len is not None and len(value) > max_len:
        _invalid(field, "must be at most %d characters" % max_len)
    return value


def req_enum(payload, field, allowed):
    if not _present(payload, field):
        _invalid(field, "is required")
    value = payload[field]
    if not isinstance(value, str) or value not in allowed:
        _invalid(field, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


def opt_enum(payload, field, allowed, default=None):
    if not _present(payload, field):
        return default
    return req_enum(payload, field, allowed)


def req_bool(payload, field):
    if not _present(payload, field):
        _invalid(field, "is required")
    value = payload[field]
    if not isinstance(value, bool):
        _invalid(field, "must be a boolean")
    return value


def opt_bool(payload, field, default=None):
    if not _present(payload, field):
        return default
    return req_bool(payload, field)


def _check_range(field, value, gt, ge, lt, le):
    if gt is not None and not value > gt:
        _invalid(field, "must be greater than %s" % _plain(gt))
    if ge is not None and not value >= ge:
        _invalid(field, "must be greater than or equal to %s" % _plain(ge))
    if lt is not None and not value < lt:
        _invalid(field, "must be less than %s" % _plain(lt))
    if le is not None and not value <= le:
        _invalid(field, "must be less than or equal to %s" % _plain(le))


def _plain(value):
    text = str(value)
    return text


def req_num(payload, field, gt=None, ge=None, lt=None, le=None):
    if not _present(payload, field):
        _invalid(field, "is required")
    value = to_decimal(payload[field])
    if value is None:
        _invalid(field, "must be a number")
    _check_range(field, value, gt, ge, lt, le)
    return value


def opt_num(payload, field, default=None, gt=None, ge=None, lt=None, le=None):
    if not _present(payload, field):
        return default
    return req_num(payload, field, gt=gt, ge=ge, lt=lt, le=le)


def req_int(payload, field, gt=None, ge=None, lt=None, le=None):
    if not _present(payload, field):
        _invalid(field, "is required")
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, int):
        _invalid(field, "must be an integer")
    _check_range(field, value, gt, ge, lt, le)
    return value


def opt_int(payload, field, default=None, gt=None, ge=None, lt=None, le=None):
    if not _present(payload, field):
        return default
    return req_int(payload, field, gt=gt, ge=ge, lt=lt, le=le)


def req_ts(payload, field):
    import clock as _clock

    if not _present(payload, field):
        _invalid(field, "is required")
    value = payload[field]
    if not isinstance(value, str) or _clock.parse_iso(value) is None:
        _invalid(field, "must be an ISO 8601 timestamp")
    return value


def opt_ts(payload, field, default=None):
    if not _present(payload, field):
        return default
    return req_ts(payload, field)


# --------------------------------------------------------------------------- #
# Query parameters
# --------------------------------------------------------------------------- #

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def pagination():
    limit = _query_int("limit", PAGINATION_DEFAULT_LIMIT, PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT)
    offset = _query_int("offset", PAGINATION_DEFAULT_OFFSET, 0, None)
    return limit, offset


def _query_int(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        _invalid(name, "must be an integer")
    if str(value) != raw.strip():
        # reject things like "1.0" or "+1" that int() would silently accept
        try:
            if int(raw.strip()) != value:
                _invalid(name, "must be an integer")
        except (TypeError, ValueError):
            _invalid(name, "must be an integer")
    if minimum is not None and value < minimum:
        _invalid(name, "must be at least %d" % minimum)
    if maximum is not None and value > maximum:
        _invalid(name, "must be at most %d" % maximum)
    return value


def query_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        _invalid(name, "must be one of %s" % ", ".join(sorted(allowed)))
    return raw


def query_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def query_int(name, gt=None, ge=None, lt=None, le=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        _invalid(name, "must be an integer")
    _check_range(name, value, gt, ge, lt, le)
    return value


def paginate(rows):
    limit, offset = pagination()
    total = len(rows)
    return rows[offset:offset + limit], limit, offset, total
