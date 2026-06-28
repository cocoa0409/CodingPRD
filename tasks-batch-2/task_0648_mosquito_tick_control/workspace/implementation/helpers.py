"""Shared parsing / validation / date helpers."""
from datetime import date, datetime, timezone

from errors import err, ERR_INVALID_REQUEST


# --- ISO datetime parsing (logical clock instants) ---
def parse_iso(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Accepts a trailing 'Z' or explicit offset; naive strings are treated as UTC.
    Raises ERR_INVALID_REQUEST on malformed input.
    """
    if not isinstance(value, str) or value == "":
        raise err(ERR_INVALID_REQUEST, "Invalid datetime value.")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, "Invalid ISO 8601 datetime.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# --- Calendar date (YYYY-MM-DD) parsing ---
def parse_date(value):
    """Parse a YYYY-MM-DD calendar date. Raises ERR_INVALID_REQUEST if bad."""
    if not isinstance(value, str) or value == "":
        raise err(ERR_INVALID_REQUEST, "Invalid calendar date value.")
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise err(ERR_INVALID_REQUEST, "Invalid YYYY-MM-DD calendar date.")


def req_date(body, field):
    return parse_date(req_str(body, field))


# --- Body / field validation ---
def require_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return body


def optional_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return body


def req_str(body, field):
    if field not in body or not isinstance(body[field], str) or body[field] == "":
        raise err(ERR_INVALID_REQUEST, f"Missing or invalid field: {field}")
    return body[field]


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    if not isinstance(body[field], str):
        raise err(ERR_INVALID_REQUEST, f"Invalid field: {field}")
    return body[field]


def req_int(body, field, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        raise err(ERR_INVALID_REQUEST, f"Missing required field: {field}")
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be an integer.")
    if minimum is not None and v < minimum:
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be >= {minimum}.")
    if maximum is not None and v > maximum:
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be <= {maximum}.")
    return v


def opt_int(body, field, default=None, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be an integer.")
    if minimum is not None and v < minimum:
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be >= {minimum}.")
    if maximum is not None and v > maximum:
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be <= {maximum}.")
    return v


def req_number(body, field, gt=None):
    if field not in body or body[field] is None:
        raise err(ERR_INVALID_REQUEST, f"Missing required field: {field}")
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be a number.")
    if gt is not None and not (v > gt):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be > {gt}.")
    return v


def opt_bool(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be a boolean.")
    return v


def req_enum(body, field, allowed):
    v = req_str(body, field)
    if v not in allowed:
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be one of {sorted(allowed)}.")
    return v


# --- Pagination (PRD §2.3) ---
def parse_pagination():
    from flask import request
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    try:
        limit = int(limit) if limit is not None else 10
    except (TypeError, ValueError):
        raise err(ERR_INVALID_REQUEST, "limit must be an integer.")
    try:
        offset = int(offset) if offset is not None else 0
    except (TypeError, ValueError):
        raise err(ERR_INVALID_REQUEST, "offset must be an integer.")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset
