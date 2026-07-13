"""Authentication / RBAC helpers and request-input parsing."""
from flask import request
from errors import err

KNOWN_ROLES = {"Landlord", "Inspector", "Registrar", "Tenant"}


def identity():
    """Return (user_id, role), enforcing authentication.

    Both X-User-ID and X-User-Role must be present and the role must be known,
    else ERR_UNAUTHENTICATED (401).
    """
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in KNOWN_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    return uid, role


def require_role(allowed):
    """Authenticate and authorize the caller against the allowed role set.

    Returns (user_id, role). Raises ERR_UNAUTHORIZED (403) if role not allowed.
    """
    uid, role = identity()
    if role not in allowed:
        raise err("ERR_UNAUTHORIZED", "Role is not permitted for this operation")
    return uid, role


def body():
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        return {}
    return data


# ---- payload field validation helpers (raise ERR_VALIDATION / 422) ----

def require_fields(data, names):
    for n in names:
        if data.get(n) is None:
            raise err("ERR_VALIDATION", f"Missing required field: {n}")


def as_int(data, name, required=True, default=None):
    if name not in data or data.get(name) is None:
        if required:
            raise err("ERR_VALIDATION", f"Missing required field: {name}")
        return default
    v = data.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_VALIDATION", f"Field {name} must be an integer")
    return v


def check_enum(value, name, allowed):
    if value not in allowed:
        raise err("ERR_VALIDATION", f"Field {name} must be one of {sorted(allowed)}")
    return value
