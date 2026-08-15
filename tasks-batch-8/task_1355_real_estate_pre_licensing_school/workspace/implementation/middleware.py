"""Auth header extraction, role checking, and validation helpers."""

from functools import wraps
from flask import request
import db
import errors


VALID_ROLES = {
    "StateCommission", "SchoolDirector", "Registrar", "ComplianceOfficer",
    "Instructor", "Proctor", "Student",
}

ENTITY_BACKED_ROLES = {"Student", "Instructor", "Proctor"}


def get_auth():
    """Extract and validate X-User-ID / X-User-Role headers."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")

    if not user_id or not role:
        errors.raise_error(errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                           "X-User-ID and X-User-Role headers are required")

    if role not in VALID_ROLES:
        errors.raise_error(errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                           f"Unknown role: {role}")

    # Entity-backed roles: X-User-ID must reference an existing entity
    if role == "Student":
        if user_id not in db.students:
            errors.raise_error(errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                               f"Student not found: {user_id}")
    elif role in ("Instructor", "Proctor"):
        if user_id not in db.instructors:
            errors.raise_error(errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                               f"Instructor not found: {user_id}")

    return {"user_id": user_id, "role": role}


def require_roles(*allowed_roles):
    """Decorator: validate auth then check role is in allowed list."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            auth = get_auth()
            if auth["role"] not in allowed_roles:
                errors.raise_error(errors.ERR_UNAUTHORIZED_ROLE,
                                   f"Role {auth['role']} not authorized for this endpoint")
            request.auth = auth
            return f(*args, **kwargs)
        return wrapper
    return decorator


def check_director_scope(school, auth):
    """SchoolDirector may only act on schools with director_user_id == X-User-ID."""
    if auth["role"] == "SchoolDirector":
        if school.get("director_user_id") != auth["user_id"]:
            errors.raise_error(errors.ERR_FORBIDDEN_SCOPE,
                               "Director does not own this school")


def check_student_scope(student_id, auth):
    """Student may only access own records."""
    if auth["role"] == "Student":
        if student_id != auth["user_id"]:
            errors.raise_error(errors.ERR_FORBIDDEN_SCOPE,
                               "Student can only access own records")


def check_instructor_scope(instructor_id, auth):
    """Instructor may only act on own offerings."""
    if auth["role"] == "Instructor":
        if instructor_id != auth["user_id"]:
            errors.raise_error(errors.ERR_FORBIDDEN_SCOPE,
                               "Instructor can only act on own offerings")


def check_proctor_scope(proctor_instructor_id, auth):
    """Proctor may only act on assigned attempts."""
    if auth["role"] == "Proctor":
        if proctor_instructor_id != auth["user_id"]:
            errors.raise_error(errors.ERR_FORBIDDEN_SCOPE,
                               "Proctor can only act on assigned attempts")


def parse_pagination():
    """Parse and validate limit/offset query params."""
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
    except (ValueError, TypeError):
        errors.raise_error(errors.ERR_INVALID_PAGINATION_PARAMETERS,
                           "limit must be an integer")
    try:
        offset = int(raw_offset)
    except (ValueError, TypeError):
        errors.raise_error(errors.ERR_INVALID_PAGINATION_PARAMETERS,
                           "offset must be an integer")
    if limit < 1 or limit > 100:
        errors.raise_error(errors.ERR_INVALID_PAGINATION_PARAMETERS,
                           "limit must be between 1 and 100")
    if offset < 0:
        errors.raise_error(errors.ERR_INVALID_PAGINATION_PARAMETERS,
                           "offset must be >= 0")
    return limit, offset


def get_json_body(required_fields=None, optional_fields=None, all_fields=None):
    """Parse JSON body; validate required/optional/unknown fields.

    If all_fields is provided, it's the complete set of allowed fields.
    Otherwise required_fields + optional_fields form the allowed set.
    """
    if not request.is_json:
        if required_fields:
            errors.raise_error(errors.ERR_INVALID_REQUEST, "JSON body required")
        return {}

    body = request.get_json(silent=True)
    if body is None:
        if required_fields:
            errors.raise_error(errors.ERR_INVALID_REQUEST, "Invalid JSON body")
        return {}

    if not isinstance(body, dict):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Body must be a JSON object")

    # Determine allowed fields
    if all_fields is not None:
        allowed = set(all_fields)
    else:
        allowed = set(required_fields or []) | set(optional_fields or [])

    # Check unknown fields
    for key in body:
        if key not in allowed:
            errors.raise_error(errors.ERR_INVALID_REQUEST,
                               f"Unknown field: {key}")

    # Check required fields
    for field in (required_fields or []):
        if field not in body:
            errors.raise_error(errors.ERR_INVALID_REQUEST,
                               f"Required field missing: {field}")

    return body


def validate_enum(value, allowed_values, field_name):
    """Validate an enum field."""
    if value not in allowed_values:
        errors.raise_error(errors.ERR_INVALID_ENUM,
                           f"Invalid value for {field_name}: {value}")
    return value


def validate_int_range(value, min_val, max_val, field_name, err_tuple=None):
    """Validate an integer field is within range."""
    if not isinstance(value, int) or isinstance(value, bool):
        errors.raise_error(err_tuple or errors.ERR_INVALID_REQUEST,
                           f"{field_name} must be an integer")
    if value < min_val or value > max_val:
        errors.raise_error(err_tuple or errors.ERR_INVALID_REQUEST,
                           f"{field_name} must be between {min_val} and {max_val}")
    return value


def parse_date(s, field_name):
    """Parse an ISO calendar date string."""
    from datetime import date
    if not isinstance(s, str):
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           f"{field_name} must be a string")
    try:
        parts = s.split("-")
        if len(parts) != 3:
            raise ValueError
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           f"{field_name} must be a valid ISO date (YYYY-MM-DD)")


def parse_datetime(s, field_name):
    """Parse an ISO datetime string."""
    from datetime import datetime, timezone
    if not isinstance(s, str):
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           f"{field_name} must be a string")
    try:
        # Try parsing ISO format
        s_clean = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s_clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           f"{field_name} must be a valid ISO datetime")
