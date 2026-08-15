"""Auth header extraction and role checking per PRD §2.1."""

from flask import request

from errors import err_unauthenticated, err_unauthorized

ROLES = {"CoalitionAdmin", "InstitutionOfficer", "AgencyNavigator", "Participant", "FinancialCoach"}


def get_actor():
    """Extract and validate X-User-ID / X-User-Role headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        err_unauthenticated("Missing X-User-ID or X-User-Role header")
    if role not in ROLES:
        err_unauthenticated("X-User-Role is not a declared role")
    return user_id, role


def require_roles(*allowed):
    """Validate auth headers and that the role is in the allowed set."""
    user_id, role = get_actor()
    if role not in allowed:
        err_unauthorized("Role %s is not permitted for this endpoint" % role)
    return user_id, role


def get_json_body(required=True):
    """Return request JSON body; ERR_VALIDATION on malformed JSON when required."""
    from errors import err_validation

    data = request.get_json(silent=True)
    if data is None:
        if required:
            err_validation("Request body must be valid JSON")
        return {}
    if not isinstance(data, dict):
        err_validation("Request body must be a JSON object")
    return data


def require_fields(body, fields):
    """Ensure required fields are present (not missing)."""
    from errors import err_validation

    for f in fields:
        if f not in body or body[f] is None:
            err_validation("Missing required field: %s" % f)


def check_enum(value, allowed, field):
    from errors import err_validation

    if value not in allowed:
        err_validation("Field %s must be one of %s" % (field, sorted(allowed)))
    return value


def check_string(value, field):
    from errors import err_validation

    if not isinstance(value, str):
        err_validation("Field %s must be a string" % field)
    return value


def check_int(value, field):
    from errors import err_validation

    if isinstance(value, bool) or not isinstance(value, int):
        err_validation("Field %s must be an integer" % field)
    return value


def check_bool(value, field):
    from errors import err_validation

    if not isinstance(value, bool):
        err_validation("Field %s must be a boolean" % field)
    return value
