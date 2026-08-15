"""Auth header extraction, role checking, pagination, and body validation."""
from flask import request
import errors

ROLES = {"AssetAccountant", "Controller", "InventoryClerk", "TaxAnalyst"}


def get_auth():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED if missing/invalid."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise errors.unauthenticated()
    return user_id, role


def require_roles(*allowed):
    """Check auth and that role is in the allowed set. Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed:
        raise errors.forbidden()
    return user_id, role


def get_pagination():
    """Parse limit/offset query params with defaults and bounds."""
    try:
        limit = int(request.args.get("limit", "10"))
    except (TypeError, ValueError):
        raise errors.invalid_request("limit must be an integer")
    try:
        offset = int(request.args.get("offset", "0"))
    except (TypeError, ValueError):
        raise errors.invalid_request("offset must be an integer")
    if limit < 1 or limit > 100:
        raise errors.invalid_request("limit must be between 1 and 100")
    if offset < 0:
        raise errors.invalid_request("offset must be >= 0")
    return limit, offset


def get_body(required_fields=None):
    """Parse JSON body. Raises ERR_INVALID_REQUEST when not JSON or missing fields."""
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    if required_fields:
        for f in required_fields:
            if f not in data or data[f] is None:
                raise errors.invalid_request(f"Missing required field: {f}")
    return data


def require_string(data, field):
    v = data.get(field)
    if v is None:
        raise errors.invalid_request(f"Missing required field: {field}")
    if not isinstance(v, str) or not v:
        raise errors.invalid_request(f"Field {field} must be a non-empty string")
    return v


def optional_string(data, field):
    v = data.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise errors.invalid_request(f"Field {field} must be a string")
    return v


def require_int(data, field):
    v = data.get(field)
    if v is None:
        raise errors.invalid_request(f"Missing required field: {field}")
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.invalid_request(f"Field {field} must be an integer")
    return v


def optional_int(data, field):
    v = data.get(field)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.invalid_request(f"Field {field} must be an integer")
    return v


def require_enum(data, field, values):
    v = data.get(field)
    if v is None:
        raise errors.invalid_request(f"Missing required field: {field}")
    if not isinstance(v, str) or v not in values:
        raise errors.invalid_request(f"Field {field} must be one of {sorted(values)}")
    return v


def optional_enum(data, field, values):
    v = data.get(field)
    if v is None:
        return None
    if not isinstance(v, str) or v not in values:
        raise errors.invalid_request(f"Field {field} must be one of {sorted(values)}")
    return v


def require_bool(data, field):
    v = data.get(field)
    if v is None:
        raise errors.invalid_request(f"Missing required field: {field}")
    if not isinstance(v, bool):
        raise errors.invalid_request(f"Field {field} must be a boolean")
    return v


def optional_bool(data, field):
    v = data.get(field)
    if v is None:
        return None
    if not isinstance(v, bool):
        raise errors.invalid_request(f"Field {field} must be a boolean")
    return v


# ISO date validation
import re
import datetime as _dt

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def require_date(data, field):
    v = require_string(data, field)
    if not _DATE_RE.match(v):
        raise errors.invalid_request(f"Field {field} must be an ISO date (YYYY-MM-DD)")
    try:
        _dt.date.fromisoformat(v)
    except ValueError:
        raise errors.invalid_request(f"Field {field} is not a valid calendar date")
    return v


def require_period(data, field):
    v = require_string(data, field)
    if not _PERIOD_RE.match(v):
        raise errors.invalid_request(f"Field {field} must be a period (YYYY-MM)")
    return v
