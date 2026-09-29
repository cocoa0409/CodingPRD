"""Body / query shape validation (ladder rung 5)."""
import re

from flask import request

from db import parse_instant
from errors import fail

QUARTER_RE = re.compile(r"^\d{4}-Q[1-4]$")
STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")

_MISSING = object()


def body():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = {}
    return payload


def _bad(field, why):
    fail("ERR_INVALID_REQUEST", "%s %s" % (field, why))


def present(data, field):
    return field in data and data[field] is not None


def v_str(data, field, required=True, non_empty=True, default=None):
    if not present(data, field):
        if required:
            _bad(field, "is required")
        return default
    value = data[field]
    if not isinstance(value, str):
        _bad(field, "must be a string")
    if non_empty and value.strip() == "":
        _bad(field, "must be a non-empty string")
    return value


def v_enum(data, field, members, required=True, default=None):
    if not present(data, field):
        if required:
            _bad(field, "is required")
        return default
    value = data[field]
    if not isinstance(value, str) or value not in members:
        _bad(field, "must be one of %s" % ", ".join(sorted(members)))
    return value


def v_int(data, field, required=True, default=None, minimum=None, maximum=None):
    if not present(data, field):
        if required:
            _bad(field, "is required")
        return default
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(field, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(field, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(field, "must be <= %s" % maximum)
    return value


def v_num(data, field, required=True, default=None, minimum=None, maximum=None):
    if not present(data, field):
        if required:
            _bad(field, "is required")
        return default
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(field, "must be a number")
    if minimum is not None and value < minimum:
        _bad(field, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(field, "must be <= %s" % maximum)
    return value


def v_bool(data, field, required=True, default=None):
    if not present(data, field):
        if required:
            _bad(field, "is required")
        return default
    value = data[field]
    if not isinstance(value, bool):
        _bad(field, "must be a boolean")
    return value


def v_instant(data, field, required=True, default=None):
    """Validates ISO 8601 and returns the raw string (stored verbatim)."""
    if not present(data, field):
        if required:
            _bad(field, "is required")
        return default
    value = data[field]
    if parse_instant(value) is None:
        _bad(field, "must be a valid ISO 8601 instant")
    return value


def v_id(data, field, required=True, default=None):
    if not present(data, field):
        if required:
            _bad(field, "is required")
        return default
    value = data[field]
    if not isinstance(value, str) or value.strip() == "":
        _bad(field, "must be a non-empty identifier")
    return value


def pagination():
    """Rung 5: limit in [1, 100], offset >= 0."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_PAGINATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_PAGINATION", "limit must be between 1 and 100")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_PAGINATION", "offset must be an integer")
        if offset < 0:
            fail("ERR_INVALID_PAGINATION", "offset must be >= 0")
    return limit, offset


def qp(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value
