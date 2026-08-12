"""Auth header extraction, role checking, pagination parsing (PRD §2.1, §2.3, §2.9)."""

from functools import wraps

from flask import g, request

from errors import err_unauthenticated, err_unauthorized_role, err_validation

ROLES = {"Participant", "PlanSponsorAdmin", "RolloverProcessor", "TaxReportingOfficer", "OperationsAgent"}
ALL_ROLES = ("Participant", "PlanSponsorAdmin", "RolloverProcessor", "TaxReportingOfficer", "OperationsAgent")


def require_roles(*roles):
    """Priority 1 (auth) then priority 2 (RBAC)."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role or role not in ROLES:
                raise err_unauthenticated()
            if role not in roles:
                raise err_unauthorized_role()
            g.user_id = uid
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco


def body():
    """Parsed JSON object body; malformed JSON -> ERR_VALIDATION. Missing body -> {}."""
    data = request.get_json(silent=True)
    if data is None:
        if request.data:
            raise err_validation("Request body is not valid JSON")
        return {}
    if not isinstance(data, dict):
        raise err_validation("Request body must be a JSON object")
    return data


def req_str(data, field):
    v = data.get(field)
    if v is None or not isinstance(v, str) or v == "":
        raise err_validation("Missing or invalid required field: %s" % field)
    return v


def opt_str(data, field):
    v = data.get(field)
    if v is not None and not isinstance(v, str):
        raise err_validation("Field must be a string: %s" % field)
    return v


def req_enum(data, field, members):
    v = data.get(field)
    if v not in members:
        raise err_validation("Field %s must be one of %s" % (field, sorted(members)))
    return v


def req_int(data, field):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_validation("Missing or invalid required integer field: %s" % field)
    return v


def opt_int(data, field):
    v = data.get(field)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_validation("Field must be an integer: %s" % field)
    return v


def opt_bool(data, field, default=None):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise err_validation("Field must be a boolean: %s" % field)
    return v


def pagination_params():
    """limit default 10 (min 1, max 100); offset default 0 (>= 0)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_validation("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_validation("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_validation("offset must be an integer")
        if offset < 0:
            raise err_validation("offset must be >= 0")
    return limit, offset


def paginate(rows):
    """rows pre-sorted by (created_at ASC, insertion seq). Returns (page, total, limit, offset)."""
    limit, offset = pagination_params()
    total = len(rows)
    return rows[offset : offset + limit], total, limit, offset
