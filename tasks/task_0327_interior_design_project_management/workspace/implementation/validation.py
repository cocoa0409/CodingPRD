"""Body parsing & field validation helpers (PRD §2.6 priority 4).

ERR_INVALID_REQUEST (422): missing/ill-typed/out-of-range body field, invalid
enum, or window_end <= window_start.
ERR_VALIDATION (400): malformed JSON body or pagination params out of range.
"""
from datetime import datetime

from flask import request

from errors import err


def get_json_body():
    """Parse the JSON body. Malformed JSON -> ERR_VALIDATION (400)."""
    if request.method in ("POST", "PATCH", "PUT"):
        if request.content_length in (None, 0) and not request.data:
            return {}
        try:
            body = request.get_json(force=True, silent=False)
        except Exception:
            raise err("ERR_VALIDATION", "Malformed JSON body.")
        if body is None:
            return {}
        if not isinstance(body, dict):
            raise err("ERR_VALIDATION", "Request body must be a JSON object.")
        return body
    return {}


def require_str(body, field, allow_empty=False):
    if field not in body:
        raise err("ERR_INVALID_REQUEST", f"Missing required field '{field}'.")
    v = body[field]
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' must be a string.")
    if not allow_empty and v == "":
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' must not be empty.")
    return v


def optional_str(body, field, default=""):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' must be a string.")
    return v


def require_int(body, field):
    if field not in body:
        raise err("ERR_INVALID_REQUEST", f"Missing required field '{field}'.")
    v = body[field]
    # bool is a subclass of int; reject it explicitly
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' must be an integer.")
    return v


def optional_int(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' must be an integer.")
    return v


def require_number(body, field):
    if field not in body:
        raise err("ERR_INVALID_REQUEST", f"Missing required field '{field}'.")
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' must be a number.")
    return v


def optional_number(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' must be a number.")
    return v


def optional_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' must be a boolean.")
    return v


def require_enum(body, field, choices):
    v = require_str(body, field)
    if v not in choices:
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' must be one of {sorted(choices)}.")
    return v


def optional_enum(body, field, choices, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str) or v not in choices:
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' must be one of {sorted(choices)}.")
    return v


def require_datetime(body, field):
    """ISO 8601 instant. Returns (raw_string, parsed_datetime)."""
    raw = require_str(body, field)
    parsed = parse_datetime(raw, field)
    return raw, parsed


def parse_datetime(raw, field="datetime"):
    s = raw
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except (ValueError, AttributeError):
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' must be an ISO 8601 datetime.")


def parse_pagination():
    """limit default 10 (min 1, max 100); offset default 0. Out of range -> ERR_VALIDATION."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise err("ERR_VALIDATION", "limit must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "offset must be an integer.")
        if offset < 0:
            raise err("ERR_VALIDATION", "offset must be >= 0.")
    return limit, offset
