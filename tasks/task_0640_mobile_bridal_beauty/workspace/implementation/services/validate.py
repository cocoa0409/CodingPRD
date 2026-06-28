"""Request body field validators (PRD §2.9 — ERR_INVALID_REQUEST on bad shape)."""
import errors
from db import parse_iso


def _is_bool(v):
    return isinstance(v, bool)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def require_str(body, field):
    if field not in body:
        raise errors.invalid_request(f"{field} is required")
    v = body[field]
    if not isinstance(v, str) or v == "":
        raise errors.invalid_request(f"{field} must be a non-empty string")
    return v


def require_enum(body, field, allowed):
    if field not in body:
        raise errors.invalid_request(f"{field} is required")
    v = body[field]
    if not isinstance(v, str) or v not in allowed:
        raise errors.invalid_request(f"{field} must be one of {sorted(allowed)}")
    return v


def require_int_min(body, field, minimum):
    if field not in body:
        raise errors.invalid_request(f"{field} is required")
    v = body[field]
    if not _is_int(v):
        raise errors.invalid_request(f"{field} must be an integer")
    if v < minimum:
        raise errors.invalid_request(f"{field} must be >= {minimum}")
    return v


def require_number_min(body, field, minimum):
    if field not in body:
        raise errors.invalid_request(f"{field} is required")
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise errors.invalid_request(f"{field} must be a number")
    if v < minimum:
        raise errors.invalid_request(f"{field} must be >= {minimum}")
    return v


def require_datetime(body, field):
    if field not in body:
        raise errors.invalid_request(f"{field} is required")
    dt = parse_iso(body[field])
    if dt is None:
        raise errors.invalid_request(f"{field} must be an ISO 8601 datetime")
    return dt


def optional_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not _is_bool(v):
        raise errors.invalid_request(f"{field} must be a boolean")
    return v


def optional_int_min(body, field, minimum, default=None):
    if field not in body or body[field] is None:
        return default
    return require_int_min(body, field, minimum)


def require_int_field(body, field):
    if field not in body:
        raise errors.invalid_request(f"{field} is required")
    v = body[field]
    if not _is_int(v):
        raise errors.invalid_request(f"{field} must be an integer")
    return v
