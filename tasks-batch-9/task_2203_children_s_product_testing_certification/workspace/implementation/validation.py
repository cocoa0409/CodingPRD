"""Request-shape validation (priority 5) -> ERR_INVALID_REQUEST / HTTP 400.

Only shape lives here: presence of required fields, enum membership, regex
conformance, numeric ranges and pagination bounds. Everything semantic lives in
the service layer so the documented priority ordering can be honoured.
"""

import re

from flask import request

import clock
from errors import ApiError

MISSING = object()

RE_UPPER_SNAKE = re.compile(r"^[A-Z][A-Z0-9_]*$")
RE_UPPER_ALNUM_DASH = re.compile(r"^[A-Z0-9-]+$")
RE_UPPER_ALNUM = re.compile(r"^[A-Z0-9]+$")
RE_COUNTRY = re.compile(r"^[A-Z]{2}$")
RE_MONTH = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")
RE_BATCH_CODE = re.compile(r"^[A-Z0-9]{3,10}-[0-9]{6}$")


def bad(field, detail):
    raise ApiError("ERR_INVALID_REQUEST", "%s: %s" % (field, detail))


def json_body():
    """The parsed JSON object body, or {} when absent."""
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "body must be a JSON object")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "body must be a JSON object")
    return payload


def _present(body, key):
    return key in body and body[key] is not None


def string_field(body, key, min_len=1, max_len=None, pattern=None, required=True,
                 default=MISSING):
    if not _present(body, key):
        if required:
            bad(key, "is required")
        return None if default is MISSING else default
    value = body[key]
    if not isinstance(value, str):
        bad(key, "must be a string")
    if len(value) < min_len:
        bad(key, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        bad(key, "must be at most %d characters" % max_len)
    if pattern is not None and not pattern.match(value):
        bad(key, "does not match the required format")
    return value


def enum_field(body, key, allowed, required=True, default=MISSING):
    if not _present(body, key):
        if required:
            bad(key, "is required")
        return None if default is MISSING else default
    value = body[key]
    if not isinstance(value, str) or value not in allowed:
        bad(key, "must be one of %s" % sorted(allowed))
    return value


def int_field(body, key, minimum=None, maximum=None, required=True, default=MISSING):
    if not _present(body, key):
        if required:
            bad(key, "is required")
        return None if default is MISSING else default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, int):
        bad(key, "must be an integer")
    if minimum is not None and value < minimum:
        bad(key, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        bad(key, "must be <= %s" % maximum)
    return value


def number_field(body, key, minimum=None, maximum=None, required=True, default=MISSING):
    if not _present(body, key):
        if required:
            bad(key, "is required")
        return None if default is MISSING else default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad(key, "must be a number")
    if minimum is not None and value < minimum:
        bad(key, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        bad(key, "must be <= %s" % maximum)
    return value


def bool_field(body, key, required=True, default=MISSING):
    if not _present(body, key):
        if required:
            bad(key, "is required")
        return None if default is MISSING else default
    value = body[key]
    if not isinstance(value, bool):
        bad(key, "must be a boolean")
    return value


def datetime_field(body, key, required=True, default=MISSING):
    if not _present(body, key):
        if required:
            bad(key, "is required")
        return None if default is MISSING else default
    value = body[key]
    if not isinstance(value, str):
        bad(key, "must be an ISO 8601 timestamp string")
    parsed = clock.parse_iso8601(value)
    if parsed is None:
        bad(key, "must be an ISO 8601 timestamp string")
    return parsed


def id_field(body, key, required=True):
    """A foreign-key reference: shape only (non-empty string)."""
    if not _present(body, key):
        if required:
            bad(key, "is required")
        return None
    value = body[key]
    if not isinstance(value, str) or not value.strip():
        bad(key, "must be a non-empty id string")
    return value


# --------------------------------------------------------------------------
# Query parameters
# --------------------------------------------------------------------------

def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            bad("limit", "must be an integer")
        if limit < 1 or limit > 100:
            bad("limit", "must be between 1 and 100")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            bad("offset", "must be an integer")
        if offset < 0:
            bad("offset", "must not be negative")
    return limit, offset


def query_enum(name, allowed):
    args = request.args
    if name not in args:
        return None
    value = args.get(name)
    if value is None or value == "":
        bad(name, "must be one of %s" % sorted(allowed))
    if value not in allowed:
        bad(name, "must be one of %s" % sorted(allowed))
    return value


def query_string(name):
    args = request.args
    if name not in args:
        return None
    value = args.get(name)
    if value is None or value == "":
        bad(name, "must be a non-empty string")
    return value


def query_bool(name):
    args = request.args
    if name not in args:
        return None
    value = args.get(name)
    if value in ("true", "True", "TRUE"):
        return True
    if value in ("false", "False", "FALSE"):
        return False
    bad(name, "must be true or false")
