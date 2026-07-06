"""Input-shape validators."""
import re
from errors import invalid_request


EMAIL_RE = re.compile(r"^[^@]+@[^@]+\.[^@]+$")


def require_fields(payload: dict, fields):
    for f in fields:
        if f not in payload:
            raise invalid_request(f"missing required field: {f}")


def require_enum(value, allowed, field: str):
    if value not in allowed:
        raise invalid_request(f"{field} must be one of {sorted(allowed)}")


def require_int(payload: dict, field: str, minimum=None):
    v = payload.get(field)
    if not isinstance(v, int) or isinstance(v, bool):
        raise invalid_request(f"{field} must be integer")
    if minimum is not None and v < minimum:
        raise invalid_request(f"{field} must be >= {minimum}")
    return v


def require_string(payload: dict, field: str, allow_empty=False):
    v = payload.get(field)
    if not isinstance(v, str) or (not allow_empty and not v):
        raise invalid_request(f"{field} must be a non-empty string")
    return v


def require_bool(payload: dict, field: str, default=False):
    if field not in payload:
        return default
    v = payload[field]
    if not isinstance(v, bool):
        raise invalid_request(f"{field} must be boolean")
    return v


def require_email(payload: dict, field: str = "email"):
    v = require_string(payload, field)
    if v != v.lower():
        raise invalid_request(f"{field} must be lowercase")
    if not EMAIL_RE.match(v):
        raise invalid_request(f"{field} must match email pattern")
    return v
