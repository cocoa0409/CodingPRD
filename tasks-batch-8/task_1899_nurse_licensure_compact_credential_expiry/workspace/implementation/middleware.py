"""Auth context extraction, role checks, body validation, pagination parsing."""

from flask import request

from errors import (
    ERR_FORBIDDEN_ROLE,
    ERR_INVALID_REQUEST,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ApiError,
)
from util import parse_date, parse_datetime

ROLES = {
    "CredentialingSpecialist",
    "PrimarySourceVerifier",
    "NurseManager",
    "ComplianceOfficer",
    "Nurse",
    "SystemOperator",
}


def auth_context():
    """Stage 1: identity headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must be present and the role must be a declared role",
            400,
        )
    return user_id, role


def require_role(role, allowed):
    """Stage 2: role authorization for the endpoint."""
    if role not in allowed:
        raise ApiError(ERR_FORBIDDEN_ROLE, "Role is not permitted for this endpoint", 403)


def get_body(allow_empty=True):
    """Parse the JSON object body. Absent body -> {} when allow_empty."""
    raw = request.get_data()
    if raw is None or raw == b"":
        if allow_empty:
            return {}
        raise ApiError(ERR_INVALID_REQUEST, "Request body is required", 400)
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be a JSON object", 400)
    return data


def validate_body(body, schema):
    """Validate body against schema {field: (kind, required, choices)}.

    kind: 'string' | 'bool' | 'int' | 'number' | 'date' | 'datetime' |
          'array_string' | 'array_enum'
    Returns a dict of converted values (dates -> date, datetimes -> datetime).
    Unknown fields, missing required fields, type mismatches, and invalid enum
    values are all ERR_INVALID_REQUEST (400).
    """
    for key in body:
        if key not in schema:
            raise ApiError(ERR_INVALID_REQUEST, f"Unknown field '{key}'", 400)
    out = {}
    for field, spec in schema.items():
        kind, required, choices = spec
        present = field in body and body[field] is not None
        if not present:
            if field in body and body[field] is None and kind in ("string",):
                # explicit null is a type mismatch for scalars
                raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' must not be null", 400)
            if required:
                raise ApiError(ERR_INVALID_REQUEST, f"Missing required field '{field}'", 400)
            continue
        value = body[field]
        if kind == "string":
            if not isinstance(value, str):
                raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' must be a string", 400)
        elif kind == "bool":
            if not isinstance(value, bool):
                raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' must be a boolean", 400)
        elif kind == "int":
            if not isinstance(value, int) or isinstance(value, bool):
                raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' must be an integer", 400)
        elif kind == "number":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' must be a number", 400)
        elif kind == "date":
            value = parse_date(value, field)
        elif kind == "datetime":
            value = parse_datetime(value, field)
        elif kind == "array_string":
            if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
                raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' must be an array of strings", 400)
        elif kind == "array_enum":
            if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
                raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' must be an array", 400)
        else:
            raise AssertionError(f"unknown kind {kind}")
        if choices is not None:
            if kind == "array_enum":
                bad = [v for v in value if v not in choices]
                if bad:
                    raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' contains an invalid value", 400)
            elif value not in choices:
                raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' has an invalid value", 400)
        out[field] = value
    return out


def pagination_params():
    """limit/offset per scaffold: default 10/0, limit clamped to [1, 100]."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, "limit must be an integer", 400)
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, "offset must be an integer", 400)
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset
