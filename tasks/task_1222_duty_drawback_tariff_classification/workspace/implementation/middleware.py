"""Auth header extraction, role gating, body validation primitives (PRD §2.1/§2.7)."""
from flask import request

from errors import (
    ERR_FORBIDDEN,
    ERR_INVALID_REQUEST,
    ERR_UNAUTHENTICATED,
    raise_err,
)
from util import parse_dt

ROLES = {"FirmAdmin", "Analyst", "LicensedBroker", "ComplianceManager", "ClientContact"}


def authenticate():
    """Priority 1: X-User-Role and X-User-ID present; role in the declared five."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise_err(ERR_UNAUTHENTICATED, "Missing or unknown X-User-Role / X-User-ID")
    return user_id, role


def require_role(role, allowed):
    """Priority 2: acting role must be listed for the endpoint."""
    if role not in allowed:
        raise_err(ERR_FORBIDDEN, "Role not permitted for this endpoint")


def require_client_scope(user_id, role, client_id):
    """ClientContact may only touch resources whose client_id == X-User-ID."""
    if role == "ClientContact" and client_id != user_id:
        raise_err(ERR_FORBIDDEN, "ClientContact may only access own client's resources")


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(body, name):
    v = body.get(name)
    if v is None:
        raise_err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
    if not isinstance(v, str) or not v:
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a non-empty string")
    return v


def req_int(body, name, minimum=None):
    v = body.get(name)
    if v is None:
        raise_err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
    if not _is_int(v):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    if minimum is not None and v < minimum:
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be >= {minimum}")
    return v


def opt_int(body, name, minimum=None):
    if name not in body or body[name] is None:
        return None
    v = body[name]
    if not _is_int(v):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    if minimum is not None and v < minimum:
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be >= {minimum}")
    return v


def req_enum(body, name, allowed):
    v = body.get(name)
    if v is None:
        raise_err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
    if v not in allowed:
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be one of {sorted(allowed)}")
    return v


def req_dt(body, name):
    v = body.get(name)
    if v is None:
        raise_err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
    try:
        return parse_dt(v)
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be an ISO 8601 datetime")


def opt_dt(body, name):
    if name not in body or body[name] is None:
        return None
    try:
        return parse_dt(body[name])
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be an ISO 8601 datetime")


def opt_bool(body, name, default=False):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a boolean")
    return v


def opt_str(body, name):
    if name not in body or body[name] is None:
        return None
    v = body[name]
    if not isinstance(v, str) or not v:
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a non-empty string")
    return v
