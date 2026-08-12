"""Auth + request helpers (SCAFFOLD §1.4 / PRD §2.1, §2.12).

Every request must carry X-User-ID and X-User-Role; the role must be one of the
six declared roles. Validation priority (PRD §2.12, lower number wins):
  1 auth presence/declared role      -> ERR_UNAUTHENTICATED (401)
  2 endpoint + per-transition role   -> ERR_UNAUTHORIZED_ROLE (403)
  3 ownership / segregation of duty  -> ERR_OWNERSHIP_REQUIRED / ERR_SEGREGATION_OF_DUTIES (403)
  4 existence (path ids, then body FKs) -> ERR_NOT_FOUND (404)
  5 OCC version match                -> ERR_STALE_VERSION (412)
  6 state-machine preconditions      -> ERR_INVALID_STATE (409)
  7 classification/need-to-know/preservation gates
  8 temporal window rules
  9 referenced-entity state gates
 10 aggregate / field constraints
"""

from flask import request

from errors import err_unauthenticated, err_unauthorized_role, err_invalid_request

DECLARED_ROLES = {
    "IPCounsel",
    "SeniorCounsel",
    "HRPartner",
    "SecurityOfficer",
    "Employee",
    "CounterpartyRep",
}


def actor():
    """Priority 1: headers present and role declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in DECLARED_ROLES:
        raise err_unauthenticated()
    return user_id, role


def require_roles(role, *allowed):
    """Priority 2: endpoint-level role authorization."""
    if role not in allowed:
        raise err_unauthorized_role(
            f"Role {role} is not permitted for this endpoint"
        )


def body():
    """JSON request body as a dict; malformed/missing JSON behaves as {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return data


def require_field(data, field):
    """Required-field presence (ERR_INVALID_REQUEST)."""
    val = data.get(field)
    if val is None or (isinstance(val, str) and val == ""):
        raise err_invalid_request(f"Missing required field: {field}")
    return val


def optional_str(data, field):
    val = data.get(field)
    if val is None:
        return None
    if not isinstance(val, str):
        raise err_invalid_request(f"Field {field} must be a string")
    return val


def require_str(data, field):
    val = require_field(data, field)
    if not isinstance(val, str):
        raise err_invalid_request(f"Field {field} must be a string")
    return val


def require_int(data, field):
    val = require_field(data, field)
    if not isinstance(val, int) or isinstance(val, bool):
        raise err_invalid_request(f"Field {field} must be an integer")
    return val


def require_enum(data, field, allowed):
    val = require_str(data, field)
    if val not in allowed:
        raise err_invalid_request(
            f"Field {field} must be one of {sorted(allowed)}"
        )
    return val


def optional_enum(data, field, allowed, default=None):
    val = data.get(field)
    if val is None:
        return default
    if val not in allowed:
        raise err_invalid_request(
            f"Field {field} must be one of {sorted(allowed)}"
        )
    return val
