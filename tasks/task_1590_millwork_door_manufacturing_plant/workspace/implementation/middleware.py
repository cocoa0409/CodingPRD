"""Validation-ladder helpers (PRD §2.5): auth context, authorization, payload checks."""

from flask import request

from errors import err

VALID_ROLES = {
    "PlantManager",
    "Estimator",
    "Architect",
    "ProductionLead",
    "LabelAuthority",
    "QAInspector",
    "ShippingCoordinator",
    "Any",
}


def get_context():
    """Rung 1: X-User-ID and X-User-Role must be present and non-empty."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "X-User-ID and X-User-Role headers must be present and non-empty")
    if role not in VALID_ROLES:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "X-User-Role is not a recognized role")
    return user_id, role


def require_role(role, *allowed):
    """Rung 2: role must be permitted for this operation."""
    if role not in allowed:
        raise err("ERR_INSUFFICIENT_PERMISSIONS",
                  "Role %s is not permitted for this operation" % role)


def raw_body():
    """Parse the JSON body; absent body becomes {} (for no-input action endpoints)."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def validate_fields(body, required=(), optional=()):
    """Rung 4 (structural): required fields present, no unknown fields."""
    allowed = set(required) | set(optional)
    for key in body:
        if key not in allowed:
            raise err("ERR_INVALID_REQUEST", "Unknown field: %s" % key)
    for key in required:
        if key not in body or body[key] is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % key)


def json_body(required=(), optional=()):
    """Body must be a JSON object with required fields present and no unknown fields."""
    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    validate_fields(body, required, optional)
    return body


def req_string(body, field):
    val = body.get(field)
    if not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a string" % field)
    return val


def req_bool(body, field):
    val = body.get(field)
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean" % field)
    return val


def req_int(body, field):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)
    return val


def req_number(body, field):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a number" % field)
    return val


def req_enum(body, field, values):
    val = body.get(field)
    if not isinstance(val, str) or val not in values:
        raise err("ERR_INVALID_REQUEST", "Field %s must be one of %s" % (field, ", ".join(values)))
    return val


def opt_enum(body, field, values):
    if field not in body:
        return None
    return req_enum(body, field, values)


def require_existence(store, rec_id, error_id, label):
    """Rung 3: id must reference an existing resource."""
    rec = store.get(rec_id)
    if rec is None:
        raise err(error_id, "%s not found: %s" % (label, rec_id))
    return rec
