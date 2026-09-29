"""Body and query shape screening — PRD 2.6 step 3, always ERR_INVALID_REQUEST.

"The body is a JSON object, every required input field is present with its
declared type, every enum field carries a declared member, every numeric field
is finite and — unless that field's own rule says otherwise — non-negative, and
limit and offset are integers inside their bounds."
"""

import math

from flask import request

import db
from errors import bad_request

MISSING = object()


def json_body(required=True):
    data = request.get_json(silent=True)
    if data is None:
        if required:
            raise bad_request("A JSON object body is required.")
        return {}
    if not isinstance(data, dict):
        raise bad_request("Request body must be a JSON object.")
    return data


def present(body, field):
    return field in body and body[field] is not None


def _num(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad_request("Field '%s' must be a number." % field)
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise bad_request("Field '%s' must be a finite number." % field)
    return value


def num(body, field, required=True, default=None, allow_negative=False,
        gt=None, ge=None, lt=None, le=None):
    if not present(body, field):
        if required:
            raise bad_request("Field '%s' is required." % field)
        return default
    value = _num(body[field], field)
    if not allow_negative and value < 0:
        raise bad_request("Field '%s' must not be negative." % field)
    if gt is not None and not value > gt:
        raise bad_request("Field '%s' must be greater than %s." % (field, gt))
    if ge is not None and not value >= ge:
        raise bad_request("Field '%s' must be at least %s." % (field, ge))
    if lt is not None and not value < lt:
        raise bad_request("Field '%s' must be below %s." % (field, lt))
    if le is not None and not value <= le:
        raise bad_request("Field '%s' must be at most %s." % (field, le))
    return value


def integer(body, field, required=True, default=None, allow_negative=False,
            ge=None, le=None):
    if not present(body, field):
        if required:
            raise bad_request("Field '%s' is required." % field)
        return default
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_request("Field '%s' must be an integer." % field)
    if not allow_negative and value < 0:
        raise bad_request("Field '%s' must not be negative." % field)
    if ge is not None and value < ge:
        raise bad_request("Field '%s' must be at least %s." % (field, ge))
    if le is not None and value > le:
        raise bad_request("Field '%s' must be at most %s." % (field, le))
    return value


def text(body, field, required=True, default=None, min_len=1, max_len=None):
    if not present(body, field):
        if required:
            raise bad_request("Field '%s' is required." % field)
        return default
    value = body[field]
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be a string." % field)
    if min_len is not None and len(value.strip()) < min_len:
        raise bad_request("Field '%s' must not be blank." % field)
    if max_len is not None and len(value) > max_len:
        raise bad_request("Field '%s' exceeds %d characters." % (field, max_len))
    return value


def enum(body, field, members, required=True, default=None):
    if not present(body, field):
        if required:
            raise bad_request("Field '%s' is required." % field)
        return default
    value = body[field]
    if not isinstance(value, str) or value not in members:
        raise bad_request("Field '%s' must be one of %s." % (field, ", ".join(members)))
    return value


def boolean(body, field, required=True, default=None):
    if not present(body, field):
        if required:
            raise bad_request("Field '%s' is required." % field)
        return default
    value = body[field]
    if not isinstance(value, bool):
        raise bad_request("Field '%s' must be a boolean." % field)
    return value


def ident(body, field, required=True, default=None):
    """A reference field: a non-empty string.  Existence is step 4/5, later."""
    if not present(body, field):
        if required:
            raise bad_request("Field '%s' is required." % field)
        return default
    value = body[field]
    if not isinstance(value, str) or value.strip() == "":
        raise bad_request("Field '%s' must be a non-empty string." % field)
    return value


def timestamp(body, field, required=True, default=None):
    """An ISO 8601 UTC instant.  Returns (raw_string, datetime)."""
    if not present(body, field):
        if required:
            raise bad_request("Field '%s' is required." % field)
        return default, None
    value = body[field]
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be an ISO 8601 UTC timestamp." % field)
    parsed = db.parse_dt(value)
    if parsed is None:
        raise bad_request("Field '%s' must be an ISO 8601 UTC timestamp." % field)
    return value, parsed


def string_array(body, field, required=True, default=None, min_len=1,
                 max_len=120):
    if not present(body, field):
        if required:
            raise bad_request("Field '%s' is required." % field)
        return default
    value = body[field]
    if not isinstance(value, list):
        raise bad_request("Field '%s' must be an array of strings." % field)
    for entry in value:
        if not isinstance(entry, str):
            raise bad_request("Field '%s' entries must be strings." % field)
        if len(entry.strip()) < min_len:
            raise bad_request("Field '%s' entries must not be blank." % field)
        if max_len is not None and len(entry) > max_len:
            raise bad_request(
                "Field '%s' entries exceed %d characters." % (field, max_len))
    return value


# ---------------------------------------------------------------------------
# Query parameters
# ---------------------------------------------------------------------------
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def _query_int(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text_value = raw.strip()
    negative = text_value.startswith("-")
    digits = text_value[1:] if negative or text_value.startswith("+") else text_value
    if not digits.isdigit():
        raise bad_request("Query parameter '%s' must be an integer." % name)
    value = int(text_value)
    if value < minimum or (maximum is not None and value > maximum):
        raise bad_request("Query parameter '%s' is out of bounds." % name)
    return value


def pagination():
    limit = _query_int("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _query_int("offset", OFFSET_DEFAULT, OFFSET_MIN, None)
    return limit, offset


def query_enum(name, members):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in members:
        raise bad_request("Query parameter '%s' must be one of %s."
                          % (name, ", ".join(members)))
    return raw


def query_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def query_int(name, minimum=None, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return _query_int(name, None, minimum if minimum is not None else -10 ** 12,
                      maximum)
