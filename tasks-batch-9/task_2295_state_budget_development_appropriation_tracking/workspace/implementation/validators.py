"""Request-body and query-string well-formedness (ladder rung 6) plus the
monetary sign rules (rung 7) and pagination parsing.
"""

from flask import request

import db
from errors import fail
from util import parse_date, parse_datetime

_MISSING = object()


def body_json():
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Request body must be valid JSON.")
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


def _present(body, key):
    return key in body and body[key] is not None


def req_present(body, key):
    if not _present(body, key):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)


# --------------------------------------------------------------------------
# scalar readers -- every failure here is rung 6 (ERR_INVALID_REQUEST)
# --------------------------------------------------------------------------

def read_int(body, key, required=True, default=None):
    if not _present(body, key):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % key)
    return value


def read_number(body, key, required=True, default=None):
    if not _present(body, key):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % key)
    return value


def read_bool(body, key, required=True, default=None):
    if not _present(body, key):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    value = body[key]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % key)
    return value


def read_str(body, key, required=True, default=None, min_len=1, max_len=None):
    if not _present(body, key):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    value = body[key]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % key)
    if min_len is not None and len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' is too short." % key)
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' is too long." % key)
    return value


def read_enum(body, key, allowed, required=True, default=None):
    if not _present(body, key):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    value = body[key]
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def read_id(body, key, required=True):
    """A reference field: must be a non-empty string when supplied."""
    if not _present(body, key):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return None
    value = body[key]
    if not isinstance(value, str) or not value:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an id string." % key)
    return value


def read_id_list(body, key, required=True):
    if not _present(body, key):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return None
    value = body[key]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an array." % key)
    for item in value:
        if not isinstance(item, str) or not item:
            fail("ERR_INVALID_REQUEST", "Field '%s' must contain id strings." % key)
    return value


def read_instant(body, key, required=True, default=None):
    if not _present(body, key):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    parsed = parse_datetime(body[key])
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 UTC instant." % key)
    return parsed


def read_iso_date(body, key, required=True, default=None):
    if not _present(body, key):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    parsed = parse_date(body[key])
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 date (YYYY-MM-DD)." % key)
    return parsed


def peek_fk(body, key, getter):
    """Rung 4: resolve a body reference that is present and string-shaped.

    Reference resolution (404) sits above body well-formedness (400) in the
    ladder, so a *present but unresolvable* id must surface its not-found code
    before any missing-field check runs.  An absent or non-string value is left
    for the later rung-6 read to reject.
    """
    value = body.get(key)
    if isinstance(value, str) and value:
        return getter(value)
    return None


def bad_request(message):
    fail("ERR_INVALID_REQUEST", message)


def bad_amount(message):
    """Rung 7."""
    fail("ERR_INVALID_AMOUNT", message)


# --------------------------------------------------------------------------
# pagination and query filters
# --------------------------------------------------------------------------

def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer between 1 and 100.")
        if str(raw).strip() != str(limit):
            fail("ERR_INVALID_REQUEST", "limit must be an integer between 1 and 100.")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer of at least 0.")
        if str(raw).strip() != str(offset):
            fail("ERR_INVALID_REQUEST", "offset must be an integer of at least 0.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must be at least 0.")
    return limit, offset


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s." % (name, ", ".join(allowed)))
    return value


def query_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def query_int(name, minimum=None, maximum=None):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    if minimum is not None and parsed < minimum:
        fail("ERR_INVALID_REQUEST", "%s is out of range." % name)
    if maximum is not None and parsed > maximum:
        fail("ERR_INVALID_REQUEST", "%s is out of range." % name)
    return parsed


def page(rows):
    """Apply the page window and build the pagination meta block."""
    limit, offset = pagination()
    total = len(rows)
    window = rows[offset: offset + limit]
    return window, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(window)) < total,
    }


def listing(rows):
    ordered = db.sort_rows(rows)
    window, meta = page(ordered)
    return [db.serialize(row) for row in window], meta
