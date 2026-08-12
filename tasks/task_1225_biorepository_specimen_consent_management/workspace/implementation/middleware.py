"""Auth middleware: X-User-ID / X-User-Role extraction, RBAC checks."""
from flask import request

from errors import raise_error

ALL_ROLES = {
    "BiobankAdmin",
    "ConsentCoordinator",
    "LabTechnician",
    "CommitteeReviewer",
    "Researcher",
    "QualityOfficer",
}


def get_actor():
    """Validate presence of auth headers; return (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "" or role is None or role.strip() == "":
        raise_error(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers must be present and non-empty",
        )
    return user_id, role


def require_roles(allowed):
    """Validate auth headers and role membership. Returns (user_id, role)."""
    user_id, role = get_actor()
    if role not in allowed:
        raise_error(
            "ERR_INSUFFICIENT_PERMISSIONS",
            f"Role {role} is not permitted for this endpoint",
        )
    return user_id, role


def get_json_body():
    """Return request JSON body as a dict; empty body becomes {}."""
    if request.data is None or request.data == b"":
        return {}
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise_error("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def check_known_fields(body, allowed_fields):
    """Reject unknown request fields with ERR_INVALID_REQUEST."""
    for key in body:
        if key not in allowed_fields:
            raise_error("ERR_INVALID_REQUEST", f"Unknown request field: {key}")


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise_error("ERR_INVALID_REQUEST", f"Missing required field: {f}")


def validate_enum(value, allowed, field):
    if value not in allowed:
        raise_error(
            "ERR_INVALID_REQUEST",
            f"Invalid value for {field}: {value!r}; must be one of {sorted(allowed)}",
        )
    return value


def validate_use_list(value, field, non_empty=True):
    """Validate a subset of the consent use enum."""
    USES = {"GENERAL_RESEARCH", "DISEASE_SPECIFIC", "GENETIC_ANALYSIS", "COMMERCIAL_USE"}
    if not isinstance(value, list):
        raise_error("ERR_INVALID_REQUEST", f"{field} must be an array")
    for v in value:
        if v not in USES:
            raise_error("ERR_INVALID_REQUEST", f"Invalid use value in {field}: {v!r}")
    if non_empty and len(value) == 0:
        raise_error("ERR_INVALID_REQUEST", f"{field} must be a non-empty subset")
    return value


def validate_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise_error("ERR_INVALID_REQUEST", f"{field} must be a number")
    return value


def validate_positive_number(value, field):
    value = validate_number(value, field)
    if value <= 0:
        raise_error("ERR_INVALID_REQUEST", f"{field} must be > 0")
    return value


def validate_integer(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise_error("ERR_INVALID_REQUEST", f"{field} must be an integer")
    return value


def validate_string(value, field):
    if not isinstance(value, str) or value == "":
        raise_error("ERR_INVALID_REQUEST", f"{field} must be a non-empty string")
    return value


def validate_bool(value, field):
    if not isinstance(value, bool):
        raise_error("ERR_INVALID_REQUEST", f"{field} must be a boolean")
    return value


def parse_pagination():
    """Parse limit/offset query params per pagination_defaults."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_error("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_error("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_error("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise_error("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset
