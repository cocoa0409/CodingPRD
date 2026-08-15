from flask import request

from errors import ApiError, ERR_AUTH, ERR_FORBIDDEN, ERR_INVALID_REQUEST

ROLES = (
    "Client",
    "EngagementManager",
    "StaffAppraiser",
    "ReviewAppraiser",
    "MAISigner",
    "RecordsManager",
    "LegalCounsel",
)


def auth():
    """Priority 1: X-User-ID and X-User-Role present and well-formed."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not role or role not in ROLES:
        raise ApiError(
            ERR_AUTH,
            400,
            "X-User-ID and X-User-Role headers must be present and well-formed",
        )
    return uid, role


def require_role(role, allowed):
    """Priority 2: caller role must be in the endpoint's roles list."""
    if role not in allowed:
        raise ApiError(
            ERR_FORBIDDEN, 403, "Caller role is not authorized for this endpoint"
        )


def get_body():
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _bad(msg):
    raise ApiError(ERR_INVALID_REQUEST, 400, msg)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        _bad(f"{field} is required and must be a non-empty string")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        _bad(f"{field} must be one of {sorted(allowed)}")
    return v


def opt_enum(body, field, allowed, default=None):
    v = body.get(field, default)
    if v is not None and v not in allowed:
        _bad(f"{field} must be one of {sorted(allowed)}")
    return v


def req_int(body, field, minimum=None, maximum=None):
    v = body.get(field)
    if not _is_int(v):
        _bad(f"{field} is required and must be an integer")
    if minimum is not None and v < minimum:
        _bad(f"{field} must be >= {minimum}")
    if maximum is not None and v > maximum:
        _bad(f"{field} must be <= {maximum}")
    return v


def opt_int(body, field, default=None, minimum=None, maximum=None):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not _is_int(v):
        _bad(f"{field} must be an integer")
    if minimum is not None and v < minimum:
        _bad(f"{field} must be >= {minimum}")
    if maximum is not None and v > maximum:
        _bad(f"{field} must be <= {maximum}")
    return v


def req_num(body, field, minimum=None, maximum=None):
    v = body.get(field)
    if not _is_num(v):
        _bad(f"{field} is required and must be a number")
    if minimum is not None and v < minimum:
        _bad(f"{field} must be >= {minimum}")
    if maximum is not None and v > maximum:
        _bad(f"{field} must be <= {maximum}")
    return v


def opt_num(body, field, default=None, minimum=None, maximum=None):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not _is_num(v):
        _bad(f"{field} must be a number")
    if minimum is not None and v < minimum:
        _bad(f"{field} must be >= {minimum}")
    if maximum is not None and v > maximum:
        _bad(f"{field} must be <= {maximum}")
    return v


def opt_bool(body, field, default=False):
    v = body.get(field, default)
    if not isinstance(v, bool):
        _bad(f"{field} must be a boolean")
    return v


def req_list(body, field):
    v = body.get(field)
    if not isinstance(v, list):
        _bad(f"{field} is required and must be an array")
    return v
