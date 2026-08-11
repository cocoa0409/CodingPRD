"""Auth middleware (§2.1): X-User-ID and X-User-Role headers."""
from flask import request
import errors


ALL_ROLES = [
    "QualityAdmin", "QualityAnalyst", "Abstractor", "OverReader",
    "ProviderRelations", "Auditor", "QualityDirector",
]


def get_auth():
    """Returns (user_id, role). Raises ApiError on missing/empty headers."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id == "" or role is None or role == "":
        raise errors.missing_headers()
    return user_id, role


def require_roles(allowed):
    """Priority 1 (headers) then priority 3 (role authorization)."""
    user_id, role = get_auth()
    if role not in allowed:
        raise errors.insufficient()
    return user_id, role


def get_json_body():
    """Body-shape helper: returns dict or raises ERR_INVALID_REQUEST.

    A missing body on POST/PUT action endpoints is treated as an empty object —
    all of those endpoints' inputs are optional-at-body-shape level unless a
    required field is declared, which callers then enforce.
    """
    if request.data is None or request.data == b"":
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.invalid_request("Request body must be valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return body


def require_fields(body, fields):
    """Required-field presence + non-null check (priority 2)."""
    for f in fields:
        if f not in body or body[f] is None:
            raise errors.invalid_request("Missing required field: %s" % f)


def require_enum(body, field, allowed):
    val = body.get(field)
    if val is None:
        raise errors.invalid_request("Missing required field: %s" % field)
    if val not in allowed:
        raise errors.invalid_request("Field %s must be one of %s" % (field, allowed))
    return val


def optional_enum(body, field, allowed, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if val not in allowed:
        raise errors.invalid_request("Field %s must be one of %s" % (field, allowed))
    return val


def require_int(body, field):
    val = body.get(field)
    if val is None or isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request("Field %s must be an integer" % field)
    return val


def optional_int(body, field, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request("Field %s must be an integer" % field)
    return val


def optional_number(body, field, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.invalid_request("Field %s must be a number" % field)
    return val


def require_str(body, field):
    val = body.get(field)
    if val is None or not isinstance(val, str):
        raise errors.invalid_request("Field %s must be a string" % field)
    return val
