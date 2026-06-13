"""Auth header extraction, role checks, and field-level validation helpers."""

from flask import request

from errors import err

VALID_ROLES = {"FoundationAdmin", "Applicant", "CommitteeMember", "DisbursementOfficer"}


def get_user_context():
    """Validate the two mandatory auth headers (PRD §2.1). Returns (user_id, role).
    Raises ERR_MISSING_OR_INVALID_USER_CONTEXT (401) when missing or invalid."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT",
                  "X-User-ID or X-User-Role header missing or invalid")
    return user_id, role


def require_role(role, allowed):
    """Role authorization (PRD §2.5 step 2)."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE",
                  "Acting role not permitted for this operation")


def get_json_body():
    """Parse the JSON body; tolerate empty bodies on action endpoints."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


# ---- Field validation primitives (lowest priority class, ERR_INVALID_REQUEST) ----

def require_present(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
    return body[field]


def as_string(value, field):
    if not isinstance(value, str) or value == "":
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a non-empty string")
    return value


def as_int(value, field):
    # Reject booleans (which are int subclasses) and non-integers.
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an integer")
    return value


def as_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a number")
    return value


def require_int(body, field):
    return as_int(require_present(body, field), field)


def require_string(body, field):
    return as_string(require_present(body, field), field)


def require_number(body, field):
    return as_number(require_present(body, field), field)


def validate_gpa(value, field):
    v = as_number(value, field)
    if v < 0.0 or v > 4.0:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be between 0.00 and 4.00")
    return v


def validate_score_0_100(value, field):
    v = as_int(value, field)
    if v < 0 or v > 100:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be between 0 and 100")
    return v


def validate_positive_cents(value, field):
    v = as_int(value, field)
    if v <= 0:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be greater than 0")
    return v


def validate_non_negative_cents(value, field):
    v = as_int(value, field)
    if v < 0:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be >= 0")
    return v


def parse_pagination():
    """Parse limit/offset query params (PRD §2.3).
    Defaults: limit 10 (min 1, max 100), offset 0 (min 0).
    Out-of-range -> ERR_INVALID_PAGINATION (400)."""
    args = request.args
    limit = 10
    offset = 0

    raw_limit = args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_PAGINATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_PAGINATION", "limit out of range (1-100)")

    raw_offset = args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_PAGINATION", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_PAGINATION", "offset must be >= 0")

    return limit, offset
