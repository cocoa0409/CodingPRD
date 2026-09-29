"""Request-body schema validation (ladder step 4) and pagination (step 5)."""

import re

from flask import request

from db import parse_day, parse_instant
from errors import ApiError

MISSING = object()

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
INT_RE = re.compile(r"^[+-]?\d+$")


def bad_request(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    """The parsed JSON object of a write request; {} when no body was sent."""
    raw = request.get_data() or b""
    if not raw.strip():
        return {}
    data = request.get_json(silent=True)
    if data is None:
        bad_request("Request body must be valid JSON.")
    if not isinstance(data, dict):
        bad_request("Request body must be a JSON object.")
    return data


def _present(data, key):
    return isinstance(data, dict) and key in data


def field(data, key, kind, required=False, default=None, nullable=False, **rules):
    """Read one input field, enforcing type, enum membership and ranges."""
    if not _present(data, key):
        if required:
            bad_request("Field '%s' is required." % key)
        return default
    raw = data[key]
    if raw is None:
        if nullable:
            return None
        if required:
            bad_request("Field '%s' must not be null." % key)
        return default
    return _check(raw, key, kind, rules)


def _check(raw, key, kind, rules):
    if kind == "string":
        if not isinstance(raw, str):
            bad_request("Field '%s' must be a string." % key)
        low = rules.get("min_len", 1)
        high = rules.get("max_len")
        if len(raw) < low:
            bad_request("Field '%s' must be at least %d characters." % (key, low))
        if high is not None and len(raw) > high:
            bad_request("Field '%s' must be at most %d characters." % (key, high))
        return raw
    if kind == "email":
        if not isinstance(raw, str):
            bad_request("Field '%s' must be a string." % key)
        if not 1 <= len(raw) <= rules.get("max_len", 200):
            bad_request("Field '%s' has an invalid length." % key)
        if not EMAIL_RE.match(raw):
            bad_request("Field '%s' must be a valid email address." % key)
        return raw
    if kind == "integer":
        if isinstance(raw, bool) or not isinstance(raw, int):
            bad_request("Field '%s' must be an integer." % key)
        low = rules.get("min_value")
        high = rules.get("max_value")
        if low is not None and raw < low:
            bad_request("Field '%s' must be at least %d." % (key, low))
        if high is not None and raw > high:
            bad_request("Field '%s' must be at most %d." % (key, high))
        return raw
    if kind == "boolean":
        if not isinstance(raw, bool):
            bad_request("Field '%s' must be a boolean." % key)
        return raw
    if kind == "enum":
        allowed = rules["values"]
        if not isinstance(raw, str) or raw not in allowed:
            bad_request("Field '%s' must be one of %s." % (key, ", ".join(allowed)))
        return raw
    if kind == "datetime":
        parsed = parse_instant(raw)
        if parsed is None:
            bad_request("Field '%s' must be an ISO 8601 datetime." % key)
        return parsed
    if kind == "date":
        parsed = parse_day(raw)
        if parsed is None:
            bad_request("Field '%s' must be a YYYY-MM-DD calendar date." % key)
        return raw.strip()
    raise AssertionError("unknown field kind %r" % kind)


# ------------------------------------------------------------------ paging
def pagination():
    limit, offset = 10, 0
    args = request.args
    if "limit" in args:
        raw = args.get("limit")
        if not INT_RE.match(raw or ""):
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be an integer from 1 to 100.")
        limit = int(raw)
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be an integer from 1 to 100.")
    if "offset" in args:
        raw = args.get("offset")
        if not INT_RE.match(raw or ""):
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be an integer of 0 or more.")
        offset = int(raw)
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be an integer of 0 or more.")
    return limit, offset


def window(rows, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta


def qs(name):
    """A raw query-string filter value, or None when not supplied."""
    value = request.args.get(name)
    return value if value not in (None, "") else None


def qs_int(name):
    value = request.args.get(name)
    if value in (None, ""):
        return None
    if not INT_RE.match(value):
        return object()  # sentinel that can never match a stored integer
    return int(value)
