"""Body parsing, type validation, pagination, datetime parsing helpers."""
from datetime import datetime, timezone

from flask import request

from errors import err


def get_json_body():
    """Return the parsed JSON body as a dict ({} if empty/none)."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        raise err("ERR_VALIDATION", "Malformed JSON body.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_VALIDATION", "Request body must be a JSON object.")
    return body


def require(body, field):
    """Require a present, non-null field, else ERR_VALIDATION."""
    if field not in body or body[field] is None:
        raise err("ERR_VALIDATION", f"Missing required field: {field}.")
    return body[field]


def require_str(body, field):
    val = require(body, field)
    if not isinstance(val, str) or val == "":
        raise err("ERR_VALIDATION", f"Field {field} must be a non-empty string.")
    return val


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str):
        raise err("ERR_VALIDATION", f"Field {field} must be a string.")
    return val


def require_int(body, field):
    val = require(body, field)
    return _as_int(val, field)


def opt_int(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return _as_int(body[field], field)


def _as_int(val, field):
    if isinstance(val, bool):
        raise err("ERR_VALIDATION", f"Field {field} must be an integer.")
    if not isinstance(val, int):
        raise err("ERR_VALIDATION", f"Field {field} must be an integer.")
    return val


def require_number(body, field):
    val = require(body, field)
    return _as_number(val, field)


def opt_number(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return _as_number(body[field], field)


def _as_number(val, field):
    if isinstance(val, bool):
        raise err("ERR_VALIDATION", f"Field {field} must be a number.")
    if not isinstance(val, (int, float)):
        raise err("ERR_VALIDATION", f"Field {field} must be a number.")
    return val


def require_enum(body, field, allowed):
    val = require(body, field)
    if not isinstance(val, str) or val not in allowed:
        raise err("ERR_VALIDATION", f"Field {field} must be one of {sorted(allowed)}.")
    return val


def require_datetime(body, field):
    val = require(body, field)
    return parse_datetime(val, field)


def parse_datetime(val, field="datetime"):
    if not isinstance(val, str):
        raise err("ERR_VALIDATION", f"Field {field} must be an ISO 8601 string.")
    s = val.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        raise err("ERR_VALIDATION", f"Field {field} must be a valid ISO 8601 datetime.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_pagination():
    """Parse limit/offset query params (PRD §2.3). Raises ERR_PAGINATION_INVALID."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            raise err("ERR_PAGINATION_INVALID", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise err("ERR_PAGINATION_INVALID", "limit must be between 1 and 100.")
    if "offset" in args and args.get("offset") != "":
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            raise err("ERR_PAGINATION_INVALID", "offset must be an integer.")
        if offset < 0:
            raise err("ERR_PAGINATION_INVALID", "offset must be zero or greater.")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ascending and slice (PRD §2.3)."""
    ordered = sorted(items, key=lambda r: (r["created_at"], r["id"]))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return window, total
