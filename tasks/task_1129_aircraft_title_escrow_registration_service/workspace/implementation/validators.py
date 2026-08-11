"""Request validation helpers per scaffold §1.4."""

from flask import request

from errors import ApiError, ERR_INVALID_REQUEST


def get_body():
    """Get JSON body, must be a dict."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be a JSON object.", 400)
    return body


def require_fields(body: dict, required: list, optional: list = None):
    """Check required fields present, no unknown fields.

    Returns dict of validated fields.
    """
    optional = optional or []
    all_allowed = set(required) | set(optional)

    # Check unknown fields
    unknown = set(body.keys()) - all_allowed
    if unknown:
        raise ApiError(
            ERR_INVALID_REQUEST,
            f"Unknown fields: {', '.join(sorted(unknown))}",
            400,
        )

    # Check required fields
    for field in required:
        if field not in body or body[field] is None:
            raise ApiError(
                ERR_INVALID_REQUEST,
                f"Missing required field: {field}",
                400,
            )

    return body


def require_positive_int(value, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ApiError(
            ERR_INVALID_REQUEST,
            f"{field_name} must be a positive integer.",
            400,
        )
    return value


def require_non_negative_int(value, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ApiError(
            ERR_INVALID_REQUEST,
            f"{field_name} must be a non-negative integer.",
            400,
        )
    return value


def require_enum(value, field_name: str, allowed: list):
    if value not in allowed:
        raise ApiError(
            ERR_INVALID_REQUEST,
            f"{field_name} must be one of: {', '.join(allowed)}",
            400,
        )
    return value


def require_string(value, field_name: str):
    if not isinstance(value, str) or not value.strip():
        raise ApiError(
            ERR_INVALID_REQUEST,
            f"{field_name} must be a non-empty string.",
            400,
        )
    return value


def require_date_string(value, field_name: str):
    """Validate YYYY-MM-DD format."""
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST, f"{field_name} must be a date string.", 400)
    parts = value.split("-")
    if len(parts) != 3:
        raise ApiError(ERR_INVALID_REQUEST, f"{field_name} must be YYYY-MM-DD.", 400)
    try:
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        if not (1 <= m <= 12 and 1 <= d <= 31 and 1900 <= y <= 2100):
            raise ValueError
        from datetime import date
        date(y, m, d)  # validate real date
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, f"{field_name} must be a valid YYYY-MM-DD date.", 400)
    return value
