"""Auth extraction, role checks, request-body validation, pagination."""

import re
from datetime import date, datetime, timezone

from flask import request

import errors
from errors import raise_error

DECLARED_ROLES = {
    "HolderAdmin",
    "ComplianceOfficer",
    "StateAuditor",
    "TreasuryOps",
    "ClaimsExaminer",
    "ClaimsApprover",
    "Claimant",
}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_DAY_RE = re.compile(r"^\d{2}-\d{2}$")


class UserContext:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def get_user():
    """Layer 1 auth: X-User-ID and X-User-Role present; role declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in DECLARED_ROLES:
        raise_error(
            errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers are required and the role must be declared",
        )
    return UserContext(user_id, role)


def require_role(ctx, allowed):
    """Layer 2 auth: role permitted on this endpoint.

    `allowed` is a tuple of role names; the pseudo-role "Any" admits every
    declared role (including Claimant).
    """
    if "Any" in allowed:
        return
    if ctx.role not in allowed:
        raise_error(
            errors.ERR_UNAUTHORIZED_ROLE,
            f"Role {ctx.role} is not permitted on this endpoint",
        )


def body_json(required=True):
    """Return the request JSON object, enforcing ERR_INVALID_REQUEST shape."""
    if not request.data:
        if required:
            raise_error(errors.ERR_INVALID_REQUEST, "Request body is required")
        return {}
    try:
        data = request.get_json(force=False, silent=False)
    except Exception:
        raise_error(errors.ERR_INVALID_REQUEST, "Request body is not valid JSON")
    if not isinstance(data, dict):
        raise_error(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def parse_iso_date(value, field):
    """Validate a YYYY-MM-DD date string; returns datetime.date."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise_error(errors.ERR_INVALID_REQUEST, f"{field} must be a YYYY-MM-DD date string")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise_error(errors.ERR_INVALID_REQUEST, f"{field} is not a valid calendar date")


def parse_iso_datetime(value, field):
    """Validate an ISO8601 datetime; returns aware UTC datetime."""
    if not isinstance(value, str):
        raise_error(errors.ERR_INVALID_REQUEST, f"{field} must be an ISO8601 string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise_error(errors.ERR_INVALID_REQUEST, f"{field} is not a parseable ISO8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def req_string(data, field):
    value = data.get(field)
    if not isinstance(value, str) or value == "":
        raise_error(errors.ERR_INVALID_REQUEST, f"{field} is required and must be a string")
    return value


def opt_string(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    value = data[field]
    if not isinstance(value, str):
        raise_error(errors.ERR_INVALID_REQUEST, f"{field} must be a string")
    return value


def req_int(data, field, min_value=None, max_value=None):
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise_error(errors.ERR_INVALID_REQUEST, f"{field} is required and must be an integer")
    if min_value is not None and value < min_value:
        raise_error(errors.ERR_INVALID_REQUEST, f"{field} is below its minimum of {min_value}")
    if max_value is not None and value > max_value:
        raise_error(errors.ERR_INVALID_REQUEST, f"{field} exceeds its maximum of {max_value}")
    return value


def opt_int(data, field, default, min_value=None, max_value=None):
    if field not in data or data[field] is None:
        return default
    return req_int(data, field, min_value=min_value, max_value=max_value)


def req_enum(data, field, allowed):
    value = data.get(field)
    if not isinstance(value, str) or value not in allowed:
        raise_error(
            errors.ERR_INVALID_REQUEST,
            f"{field} must be one of {sorted(allowed)}",
        )
    return value


def req_date(data, field):
    return parse_iso_date(data.get(field), field)


def opt_date(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    return parse_iso_date(data[field], field)


def opt_month_day(data, field, default):
    if field not in data or data[field] is None:
        return default
    value = data[field]
    if not isinstance(value, str) or not _MONTH_DAY_RE.match(value):
        raise_error(errors.ERR_INVALID_REQUEST, f"{field} must be an MM-DD string")
    month, day = int(value[:2]), int(value[3:])
    # Validate against a leap year so 02-29 stays parseable.
    try:
        date(2000, month, day)
    except ValueError:
        raise_error(errors.ERR_INVALID_REQUEST, f"{field} is not a valid month-day")
    return value


def pagination_params():
    """Parse limit/offset with the scaffold defaults (limit 10, min 1, max 100)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_error(errors.ERR_INVALID_REQUEST, "limit must be an integer")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_error(errors.ERR_INVALID_REQUEST, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise_error(errors.ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset < 0:
        raise_error(errors.ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Apply created_at-asc ordering and slice; returns (page, meta dict)."""
    ordered = sorted(items, key=lambda r: (r["created_at"], r["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta
