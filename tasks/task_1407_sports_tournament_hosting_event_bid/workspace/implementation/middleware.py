"""Auth header extraction, role/ownership checking, body parsing, pagination.

PRD §2.1: every request carries X-User-ID and X-User-Role. Missing either, or a
role outside the declared list, is ERR_UNAUTHENTICATED (401). A role outside the
endpoint's authorized set, or a violated entity-backed ownership scope, is
ERR_FORBIDDEN (403). Auth runs before existence checks (PRD §2.9).
"""

from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN, ERR_VALIDATION

ALL_ROLES = {
    "CommissionAdmin",
    "SanctioningReviewer",
    "CvbAuditor",
    "TeamRep",
    "Official",
    "Volunteer",
    "HotelManager",
    "VenueManager",
    "Any",
}


def require_auth():
    """Priority 1: header presence + declared role."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or role is None or not uid.strip() or not role.strip():
        raise ApiError(*ERR_UNAUTHENTICATED,
                       "X-User-ID and X-User-Role headers must be present and non-empty.")
    if role not in ALL_ROLES:
        raise ApiError(*ERR_UNAUTHENTICATED, f"Unknown role: {role}")
    return uid, role


def require_roles(*roles):
    """Priorities 1-2: authentication, then role membership in the endpoint set."""
    uid, role = require_auth()
    if role not in roles:
        raise ApiError(*ERR_FORBIDDEN,
                       f"Role '{role}' is not permitted for this endpoint.")
    return uid, role


def require_any_authenticated():
    """GET endpoints: any declared role may read."""
    return require_auth()


def forbid(condition, message):
    if condition:
        raise ApiError(*ERR_FORBIDDEN, message)


def get_body():
    data = request.get_json(silent=True)
    if data is None:
        if request.data:
            raise ApiError(*ERR_VALIDATION, "Request body must be a JSON object.")
        return {}
    if not isinstance(data, dict):
        raise ApiError(*ERR_VALIDATION, "Request body must be a JSON object.")
    return data


# ---------------------------------------------------------------------------
# Field validators. Unknown/extra keys are ignored (server-computed or stray
# client fields are disregarded, never echoed).
# ---------------------------------------------------------------------------

def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or not v.strip():
        raise ApiError(*ERR_VALIDATION, f"Field {field} is required and must be a non-empty string.")
    return v


def opt_str(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, str):
        raise ApiError(*ERR_VALIDATION, f"Field {field} must be a string.")
    return v


def req_int(data, field, lo=None, hi=None):
    v = data.get(field)
    if not _is_int(v):
        raise ApiError(*ERR_VALIDATION, f"Field {field} is required and must be an integer.")
    if lo is not None and v < lo:
        raise ApiError(*ERR_VALIDATION, f"Field {field} must be >= {lo}.")
    if hi is not None and v > hi:
        raise ApiError(*ERR_VALIDATION, f"Field {field} must be <= {hi}.")
    return v


def opt_int(data, field, default=None, lo=None, hi=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not _is_int(v):
        raise ApiError(*ERR_VALIDATION, f"Field {field} must be an integer.")
    if lo is not None and v < lo:
        raise ApiError(*ERR_VALIDATION, f"Field {field} must be >= {lo}.")
    if hi is not None and v > hi:
        raise ApiError(*ERR_VALIDATION, f"Field {field} must be <= {hi}.")
    return v


def req_number(data, field, lo=None, hi=None):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError(*ERR_VALIDATION, f"Field {field} is required and must be a number.")
    if lo is not None and v < lo:
        raise ApiError(*ERR_VALIDATION, f"Field {field} must be >= {lo}.")
    if hi is not None and v > hi:
        raise ApiError(*ERR_VALIDATION, f"Field {field} must be <= {hi}.")
    return v


def opt_number(data, field, default=None, lo=None, hi=None):
    if field not in data or data[field] is None:
        return default
    return req_number(data, field, lo=lo, hi=hi)


def req_bool(data, field):
    v = data.get(field)
    if not isinstance(v, bool):
        raise ApiError(*ERR_VALIDATION, f"Field {field} is required and must be a boolean.")
    return v


def opt_bool(data, field, default=False):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, bool):
        raise ApiError(*ERR_VALIDATION, f"Field {field} must be a boolean.")
    return v


def req_enum(data, field, domain):
    v = data.get(field)
    if not isinstance(v, str) or v not in domain:
        raise ApiError(*ERR_VALIDATION, f"Field {field} must be one of {sorted(domain)}.")
    return v


def opt_enum(data, field, domain, default=None):
    if field not in data or data[field] is None:
        return default
    return req_enum(data, field, domain)


def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit, offset = 10, 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(*ERR_VALIDATION, "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError(*ERR_VALIDATION, "limit must be between 1 and 100.")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(*ERR_VALIDATION, "offset must be an integer.")
        if offset < 0:
            raise ApiError(*ERR_VALIDATION, "offset must be >= 0.")
    return limit, offset
