"""Auth extraction and request-shape validation helpers."""
from flask import request

import db
from errors import ApiError, validation, raise_err

ROLES = {"Insured", "Auditor", "AuditManager", "Underwriter", "BillingClerk"}


class Ctx:
    user_id = None
    role = None


def authenticate():
    """Priority 1: headers present and role declared -> else 401."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise_err("ERR_UNAUTHENTICATED",
                  "Missing or unknown X-User-Role / X-User-ID headers")
    Ctx.user_id = user_id
    Ctx.role = role
    return Ctx


def require_role(*roles):
    """Priority 3: caller role must be listed for the endpoint."""
    if Ctx.role not in roles:
        raise_err("ERR_FORBIDDEN", "Role not permitted on this endpoint")


# --- body parsing / shape validation (priority 2) ---------------------------

def get_body():
    raw = request.get_data()
    if not raw or not raw.strip():
        return {}
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        validation("Request body must be a JSON object")
    return data


def check_allowed(body, allowed):
    extra = [k for k in body if k not in allowed]
    if extra:
        validation("Undeclared field(s): %s" % ", ".join(sorted(extra)))


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(body, key):
    v = body.get(key)
    if v is None:
        validation("Missing required field: %s" % key)
    if not isinstance(v, str):
        validation("Field %s must be a string" % key)
    return v


def opt_str(body, key, default=None):
    v = body.get(key, default)
    if v is not None and not isinstance(v, str):
        validation("Field %s must be a string" % key)
    return v


def req_int(body, key, min_value=None, gt=None):
    v = body.get(key)
    if v is None:
        validation("Missing required field: %s" % key)
    if not _is_int(v):
        validation("Field %s must be an integer" % key)
    if min_value is not None and v < min_value:
        validation("Field %s must be >= %s" % (key, min_value))
    if gt is not None and v <= gt:
        validation("Field %s must be > %s" % (key, gt))
    return v


def opt_int(body, key, default=None, min_value=None, gt=None):
    if key not in body or body.get(key) is None:
        return default
    v = body.get(key)
    if not _is_int(v):
        validation("Field %s must be an integer" % key)
    if min_value is not None and v < min_value:
        validation("Field %s must be >= %s" % (key, min_value))
    if gt is not None and v <= gt:
        validation("Field %s must be > %s" % (key, gt))
    return v


def req_bool(body, key):
    v = body.get(key)
    if v is None:
        validation("Missing required field: %s" % key)
    if not isinstance(v, bool):
        validation("Field %s must be a boolean" % key)
    return v


def opt_bool(body, key, default=None):
    if key not in body or body.get(key) is None:
        return default
    v = body.get(key)
    if not isinstance(v, bool):
        validation("Field %s must be a boolean" % key)
    return v


def req_number(body, key):
    v = body.get(key)
    if v is None:
        validation("Missing required field: %s" % key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        validation("Field %s must be a number" % key)
    return v


def opt_number(body, key, default=None):
    if key not in body or body.get(key) is None:
        return default
    return req_number(body, key)


def req_enum(body, key, members):
    v = body.get(key)
    if v is None:
        validation("Missing required field: %s" % key)
    if not isinstance(v, str) or v not in members:
        validation("Field %s must be one of %s" % (key, ", ".join(sorted(members))))
    return v


def req_dt(body, key):
    v = req_str(body, key)
    try:
        db.parse_dt(v)
    except (ValueError, TypeError):
        validation("Field %s must be a valid ISO 8601 datetime" % key)
    return v


def req_array(body, key, non_empty=False, item_type=None):
    v = body.get(key)
    if v is None:
        validation("Missing required field: %s" % key)
    if not isinstance(v, list):
        validation("Field %s must be an array" % key)
    if non_empty and len(v) == 0:
        validation("Field %s must be non-empty" % key)
    if item_type is str:
        for it in v:
            if not isinstance(it, str):
                validation("Field %s items must be strings" % key)
    return v


def parse_pagination():
    """limit/offset query params with defaults 10/0, bounds 1..100 / >=0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            validation("limit must be an integer")
        if limit < 1 or limit > 100:
            validation("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            validation("offset must be an integer")
        if offset < 0:
            validation("offset must be >= 0")
    return limit, offset
