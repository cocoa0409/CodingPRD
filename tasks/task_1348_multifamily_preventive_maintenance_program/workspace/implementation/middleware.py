"""Auth context extraction, role admission, field validators, pagination."""
from flask import request

import errors as E
from errors import ApiError

ROLES = ("PropertyManager", "Technician", "ComplianceAuditor")
ALL_ROLES = ROLES
LEDGER_READ_ROLES = ("PropertyManager", "ComplianceAuditor")


def auth():
    """Pipeline stage 1: X-User-ID and X-User-Role present and well-formed."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or not str(uid).strip():
        raise ApiError(E.ERR_AUTH, 400, "X-User-ID header missing or malformed")
    if role is None or role not in ROLES:
        raise ApiError(E.ERR_AUTH, 400, "X-User-Role header missing or malformed")
    return uid, role


def require_role(role, allowed):
    """Pipeline stage 2: role admission."""
    if role not in allowed:
        raise ApiError(E.ERR_PERMS, 403, "Role %s is not permitted for this endpoint" % role)


def require_technician_identity(uid, assigned):
    """Pipeline stage 2 (technician-scoped): X-User-ID must equal assignee."""
    if uid != assigned:
        raise ApiError(E.ERR_PERMS, 403, "X-User-ID does not match the assigned technician")


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return data


def _is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def v_str(data, name, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            raise ApiError(E.ERR_INVALID_REQUEST, 400, "Missing required field: %s" % name)
        return default
    val = data[name]
    if not isinstance(val, str) or not val.strip():
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "Field %s must be a non-empty string" % name)
    return val


def v_int(data, name, minv=None, maxv=None, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            raise ApiError(E.ERR_INVALID_REQUEST, 400, "Missing required field: %s" % name)
        return default
    val = data[name]
    if not _is_int(val):
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "Field %s must be an integer" % name)
    if minv is not None and val < minv:
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "Field %s must be >= %s" % (name, minv))
    if maxv is not None and val > maxv:
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "Field %s must be <= %s" % (name, maxv))
    return val


def v_bool(data, name, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            raise ApiError(E.ERR_INVALID_REQUEST, 400, "Missing required field: %s" % name)
        return default
    val = data[name]
    if not isinstance(val, bool):
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "Field %s must be a boolean" % name)
    return val


def v_enum(data, name, allowed, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            raise ApiError(E.ERR_INVALID_REQUEST, 400, "Missing required field: %s" % name)
        return default
    val = data[name]
    if val not in allowed:
        raise ApiError(E.ERR_INVALID_REQUEST, 400,
                       "Field %s must be one of %s" % (name, ", ".join(allowed)))
    return val


def pagination_params():
    """limit (default 10, min 1, max 100) and offset (default 0)."""
    raw_limit = request.args.get("limit", None)
    raw_offset = request.args.get("offset", None)
    limit, offset = 10, 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(E.ERR_INVALID_REQUEST, 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(E.ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(E.ERR_INVALID_REQUEST, 400, "offset must be an integer")
        if offset < 0:
            raise ApiError(E.ERR_INVALID_REQUEST, 400, "offset must be >= 0")
    return limit, offset


def paginate(records):
    """Sort by created_at ascending (insertion order tiebreak) and slice."""
    limit, offset = pagination_params()
    ordered = sorted(records, key=lambda r: (r["created_at"], r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total
