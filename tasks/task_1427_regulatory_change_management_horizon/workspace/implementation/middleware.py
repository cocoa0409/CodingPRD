"""Auth extraction, role checks, and request-body field validation.

Priority order (PRD §2.10):
  1   auth context (headers)            -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400)
  2   role admission / ownership        -> ERR_UNAUTHORIZED_ROLE / ERR_NOT_RESOURCE_OWNER (403)
  2.5 request body shape                -> ERR_INVALID_REQUEST (400)
  3   existence (path ids L-to-R, FKs)  -> ERR_NOT_FOUND (404)
  4   state preconditions               -> 409 state family
  5   segregation of duties / suspension-> 403
  6   clock-relative temporal           -> 422
  7   uniqueness / structural caps      -> 409
  8   cross-entity referential state    -> 409
"""

from flask import request

from db import parse_dt
from errors import (ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, ApiError,
                    invalid_request, missing_context, unauthorized_role)

ROLES = (
    "ComplianceOfficer",
    "ComplianceManager",
    "BusinessOwner",
    "BoardSecretary",
    "PlatformAdmin",
)

ALL_ROLES = ROLES


def auth_context():
    """Priority 1: both headers present and role is one of the five declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise missing_context()
    return user_id, role


def require_roles(role, allowed):
    """Priority 2 (role part)."""
    if role not in allowed:
        raise unauthorized_role()


# ---------------------------------------------------------------------------
# Body helpers (priority 2.5)
# ---------------------------------------------------------------------------


def get_body():
    """Return the JSON object body; `{}` when absent, 400 when malformed."""
    data = request.get_json(silent=True, force=False)
    if data is None:
        # No JSON body at all -> treat as empty object so required-field
        # checks below fire with ERR_INVALID_REQUEST.
        return {}
    if not isinstance(data, dict):
        raise invalid_request("request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(data, field):
    v = data.get(field)
    if v is None or not isinstance(v, str):
        raise invalid_request("missing or invalid required string field: %s" % field)
    return v


def opt_str(data, field):
    v = data.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise invalid_request("field %s must be a string" % field)
    return v


def req_int(data, field, minimum=None, maximum=None):
    v = data.get(field)
    if v is None or not _is_int(v):
        raise invalid_request("missing or invalid required integer field: %s" % field)
    if minimum is not None and v < minimum:
        raise invalid_request("field %s must be >= %s" % (field, minimum))
    if maximum is not None and v > maximum:
        raise invalid_request("field %s must be <= %s" % (field, maximum))
    return v


def opt_int(data, field, minimum=None, maximum=None):
    v = data.get(field)
    if v is None:
        return None
    if not _is_int(v):
        raise invalid_request("field %s must be an integer" % field)
    if minimum is not None and v < minimum:
        raise invalid_request("field %s must be >= %s" % (field, minimum))
    if maximum is not None and v > maximum:
        raise invalid_request("field %s must be <= %s" % (field, maximum))
    return v


def req_enum(data, field, allowed):
    v = data.get(field)
    if v is None or not isinstance(v, str) or v not in allowed:
        raise invalid_request("missing or invalid enum field: %s" % field)
    return v


def req_dt(data, field):
    v = data.get(field)
    if v is None:
        raise invalid_request("missing required datetime field: %s" % field)
    try:
        return parse_dt(v)
    except (ValueError, TypeError):
        raise invalid_request("field %s must be an ISO 8601 datetime" % field)


def opt_dt(data, field):
    v = data.get(field)
    if v is None:
        return None
    try:
        return parse_dt(v)
    except (ValueError, TypeError):
        raise invalid_request("field %s must be an ISO 8601 datetime" % field)


def opt_bool(data, field):
    v = data.get(field)
    if v is None:
        return None
    if not isinstance(v, bool):
        raise invalid_request("field %s must be a boolean" % field)
    return v


# ---------------------------------------------------------------------------
# Existence helpers (priority 3)
# ---------------------------------------------------------------------------


def get_or_404(collection, entity_id, what="resource"):
    entity = collection.get(entity_id)
    if entity is None:
        from errors import not_found
        raise not_found(what)
    return entity


def auth_or_401ish():
    """Unused placeholder kept for symmetry."""
    raise ApiError(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400, "missing")
