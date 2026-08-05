"""Auth / authorization helpers and request-body field validators.

All raise ApiError with the exact scaffold error ids. Ordering of checks
follows PRD 2.10 (validation precedence) and is enforced by the call sites.
"""
from flask import request

from envelope import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED, ERR_VALIDATION

KNOWN_ROLES = {
    "Recruiter",
    "AccountManager",
    "CredentialingCoordinator",
    "ClientContact",
    "PlatformAdmin",
}

SPECIALTIES = {
    "FAMILY_MEDICINE",
    "CARDIOLOGY",
    "PSYCHIATRY",
    "ORTHOPEDIC_SURGERY",
    "EMERGENCY_MEDICINE",
}
STAFF_ROLES = {"RECRUITER", "ACCOUNT_MANAGER", "CREDENTIALING_COORDINATOR"}
ITEM_TYPES = {
    "STATE_LICENSE",
    "DEA_REGISTRATION",
    "BOARD_CERTIFICATION",
    "MALPRACTICE_HISTORY",
    "REFERENCE",
}
RELOC_CATEGORIES = {"MOVERS", "TEMP_HOUSING", "FLIGHTS", "LICENSING_FEES", "OTHER"}


# --------------------------------------------------------------------------
# auth (priority 1) + endpoint authorization (priority 2)
# --------------------------------------------------------------------------
def authenticate():
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id or role not in KNOWN_ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, "Missing or invalid authentication headers")
    return role, user_id


def authorize(allowed_roles):
    role, user_id = authenticate()
    if role not in allowed_roles:
        raise ApiError(ERR_UNAUTHORIZED, "Role %s not permitted for this operation" % role)
    return role, user_id


def require_action_role(role, action, action_role_map):
    """Action-level authorization: the acting role may perform this action."""
    allowed = action_role_map.get(action)
    if allowed is None:
        # unknown action for this endpoint -> well-formedness failure
        raise ApiError(ERR_VALIDATION, "Unknown action: %s" % action)
    if role not in allowed:
        raise ApiError(ERR_UNAUTHORIZED, "Role %s may not perform action %s" % (role, action))


# --------------------------------------------------------------------------
# body parsing / field validators (priority 3)
# --------------------------------------------------------------------------
def get_body():
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_VALIDATION, "Request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_str(body, key):
    if key not in body or body[key] is None:
        raise ApiError(ERR_VALIDATION, "Missing required field: %s" % key)
    v = body[key]
    if not isinstance(v, str) or v == "":
        raise ApiError(ERR_VALIDATION, "Field %s must be a non-empty string" % key)
    return v


def opt_str(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, str):
        raise ApiError(ERR_VALIDATION, "Field %s must be a string" % key)
    return v


def req_int(body, key, min_val=None, max_val=None):
    if key not in body or body[key] is None:
        raise ApiError(ERR_VALIDATION, "Missing required field: %s" % key)
    v = body[key]
    if not _is_int(v):
        raise ApiError(ERR_VALIDATION, "Field %s must be an integer" % key)
    if min_val is not None and v < min_val:
        raise ApiError(ERR_VALIDATION, "Field %s below minimum" % key)
    if max_val is not None and v > max_val:
        raise ApiError(ERR_VALIDATION, "Field %s above maximum" % key)
    return v


def opt_int(body, key, default=None, min_val=None, max_val=None):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not _is_int(v):
        raise ApiError(ERR_VALIDATION, "Field %s must be an integer" % key)
    if min_val is not None and v < min_val:
        raise ApiError(ERR_VALIDATION, "Field %s below minimum" % key)
    if max_val is not None and v > max_val:
        raise ApiError(ERR_VALIDATION, "Field %s above maximum" % key)
    return v


def req_number(body, key):
    if key not in body or body[key] is None:
        raise ApiError(ERR_VALIDATION, "Missing required field: %s" % key)
    v = body[key]
    if not _is_number(v):
        raise ApiError(ERR_VALIDATION, "Field %s must be a number" % key)
    return v


def req_bool(body, key):
    if key not in body or body[key] is None:
        raise ApiError(ERR_VALIDATION, "Missing required field: %s" % key)
    v = body[key]
    if not isinstance(v, bool):
        raise ApiError(ERR_VALIDATION, "Field %s must be a boolean" % key)
    return v


def opt_bool(body, key, default=False):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, bool):
        raise ApiError(ERR_VALIDATION, "Field %s must be a boolean" % key)
    return v


def req_enum(body, key, allowed):
    v = req_str(body, key)
    if v not in allowed:
        raise ApiError(ERR_VALIDATION, "Field %s has invalid value" % key)
    return v


def req_dt(body, key):
    v = req_str(body, key)
    _check_iso(v, key)
    return v


def opt_dt(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, str):
        raise ApiError(ERR_VALIDATION, "Field %s must be a string" % key)
    _check_iso(v, key)
    return v


def req_str_array(body, key, default=None):
    if key not in body or body[key] is None:
        if default is not None:
            return list(default)
        raise ApiError(ERR_VALIDATION, "Missing required field: %s" % key)
    v = body[key]
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise ApiError(ERR_VALIDATION, "Field %s must be a list of strings" % key)
    return v


def enum_array(body, key, allowed, default=None):
    if key not in body or body[key] is None:
        return list(default) if default is not None else []
    v = body[key]
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise ApiError(ERR_VALIDATION, "Field %s must be a list of strings" % key)
    for x in v:
        if x not in allowed:
            raise ApiError(ERR_VALIDATION, "Field %s has an invalid value" % key)
    return v


def _check_iso(v, key):
    from store import parse_dt
    try:
        parse_dt(v)
    except Exception:
        raise ApiError(ERR_VALIDATION, "Field %s must be an ISO-8601 datetime" % key)
