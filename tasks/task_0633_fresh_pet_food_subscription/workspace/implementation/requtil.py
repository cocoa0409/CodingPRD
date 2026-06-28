"""Request parsing / validation helpers.

A malformed body, missing required field, or type mismatch => ERR_INVALID_REQUEST (400).
"""
from datetime import datetime, timezone

from flask import request

import errors


def get_body():
    """Parse the JSON body. Missing body is treated as {} for endpoints with no
    required fields; a malformed (non-JSON) body raises ERR_INVALID_REQUEST.
    """
    if request.method in ("POST", "PATCH", "PUT"):
        raw = request.get_data(as_text=True)
        if raw is None or raw.strip() == "":
            return {}
        try:
            data = request.get_json(force=True, silent=False)
        except Exception:
            errors.fail(errors.ERR_INVALID_REQUEST, "Malformed JSON body")
        if data is None:
            return {}
        if not isinstance(data, dict):
            errors.fail(errors.ERR_INVALID_REQUEST, "Body must be a JSON object")
        return data
    return {}


def require_fields(body, *names):
    for n in names:
        if n not in body or body[n] is None:
            errors.fail(errors.ERR_INVALID_REQUEST, f"Missing required field: {n}")


def as_str(body, name, required=False, default=None):
    if name not in body or body[name] is None:
        if required:
            errors.fail(errors.ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return default
    val = body[name]
    if not isinstance(val, str):
        errors.fail(errors.ERR_INVALID_REQUEST, f"Field {name} must be a string")
    return val


def as_bool(body, name, required=False, default=None):
    if name not in body or body[name] is None:
        if required:
            errors.fail(errors.ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return default
    val = body[name]
    if not isinstance(val, bool):
        errors.fail(errors.ERR_INVALID_REQUEST, f"Field {name} must be a boolean")
    return val


def as_int(body, name, required=False, default=None):
    if name not in body or body[name] is None:
        if required:
            errors.fail(errors.ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        errors.fail(errors.ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    return val


def as_number(body, name, required=False, default=None):
    if name not in body or body[name] is None:
        if required:
            errors.fail(errors.ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        errors.fail(errors.ERR_INVALID_REQUEST, f"Field {name} must be a number")
    return val


def as_list(body, name, required=False, default=None):
    if name not in body or body[name] is None:
        if required:
            errors.fail(errors.ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return default
    val = body[name]
    if not isinstance(val, list):
        errors.fail(errors.ERR_INVALID_REQUEST, f"Field {name} must be a list")
    return val


def as_datetime(body, name, required=False, default=None):
    if name not in body or body[name] is None:
        if required:
            errors.fail(errors.ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return default
    return parse_datetime(body[name], name)


def parse_datetime(val, name="datetime"):
    if not isinstance(val, str):
        errors.fail(errors.ERR_INVALID_REQUEST, f"Field {name} must be an ISO date string")
    s = val.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        errors.fail(errors.ERR_INVALID_REQUEST, f"Field {name} is not a valid ISO datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# --- Pagination (PRD §2.3) ------------------------------------------------
def pagination():
    """limit default 10, min 1, max 100; offset default 0, min 0."""
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    try:
        limit = int(limit) if limit is not None else 10
    except (ValueError, TypeError):
        errors.fail(errors.ERR_INVALID_REQUEST, "limit must be an integer")
    try:
        offset = int(offset) if offset is not None else 0
    except (ValueError, TypeError):
        errors.fail(errors.ERR_INVALID_REQUEST, "offset must be an integer")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def query(name):
    return request.args.get(name)
