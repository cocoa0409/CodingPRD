"""Band-7 schema validation helpers.  Every failure is ERR_VALIDATION / 400."""

from decimal import Decimal, InvalidOperation

from flask import request

from db import parse_dt
from errors import fail

MISSING = object()


def body_json():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        fail("ERR_VALIDATION", "Request body must be a JSON object.")
    if not isinstance(payload, dict):
        fail("ERR_VALIDATION", "Request body must be a JSON object.")
    return payload


def present(body, name):
    return name in body and body[name] is not None


def v_string(body, name, required=False, min_len=1, max_len=None, default=MISSING,
             lower=False, pattern=None):
    if not present(body, name):
        if required:
            fail("ERR_VALIDATION", "%s is required." % name)
        return None if default is MISSING else default
    value = body[name]
    if not isinstance(value, str):
        fail("ERR_VALIDATION", "%s must be a string." % name)
    if len(value) < min_len:
        fail("ERR_VALIDATION", "%s must be at least %d character(s)." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        fail("ERR_VALIDATION", "%s must be at most %d character(s)." % (name, max_len))
    if lower and value != value.lower():
        fail("ERR_VALIDATION", "%s must be lowercase." % name)
    if pattern is not None and not pattern.match(value):
        fail("ERR_VALIDATION", "%s has an invalid format." % name)
    return value


def v_int(body, name, required=False, minimum=None, maximum=None, default=MISSING):
    if not present(body, name):
        if required:
            fail("ERR_VALIDATION", "%s is required." % name)
        return None if default is MISSING else default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_VALIDATION", "%s must be an integer." % name)
    if minimum is not None and value < minimum:
        fail("ERR_VALIDATION", "%s must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_VALIDATION", "%s must be <= %s." % (name, maximum))
    return value


def v_decimal(body, name, required=False, minimum=None, maximum=None, default=MISSING):
    if not present(body, name):
        if required:
            fail("ERR_VALIDATION", "%s is required." % name)
        return None if default is MISSING else default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        fail("ERR_VALIDATION", "%s must be a number." % name)
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        fail("ERR_VALIDATION", "%s must be a number." % name)
    if not dec.is_finite():
        fail("ERR_VALIDATION", "%s must be a finite number." % name)
    if minimum is not None and dec < minimum:
        fail("ERR_VALIDATION", "%s must be >= %s." % (name, minimum))
    if maximum is not None and dec > maximum:
        fail("ERR_VALIDATION", "%s must be <= %s." % (name, maximum))
    return dec


def v_bool(body, name, required=False, default=MISSING):
    if not present(body, name):
        if required:
            fail("ERR_VALIDATION", "%s is required." % name)
        return None if default is MISSING else default
    value = body[name]
    if not isinstance(value, bool):
        fail("ERR_VALIDATION", "%s must be a boolean." % name)
    return value


def v_enum(body, name, allowed, required=False, default=MISSING):
    if not present(body, name):
        if required:
            fail("ERR_VALIDATION", "%s is required." % name)
        return None if default is MISSING else default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_VALIDATION", "%s must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def v_datetime(body, name, required=False, default=MISSING):
    """Returns the raw string (echoed verbatim) after checking it parses."""
    if not present(body, name):
        if required:
            fail("ERR_VALIDATION", "%s is required." % name)
        return None if default is MISSING else default
    value = body[name]
    if not isinstance(value, str) or parse_dt(value) is None:
        fail("ERR_VALIDATION", "%s must be an ISO 8601 UTC timestamp." % name)
    return value


def v_str_list(body, name, required=False, min_items=0, max_items=None, unique=False,
               lower=False, allowed=None, default=MISSING):
    if not present(body, name):
        if required:
            fail("ERR_VALIDATION", "%s is required." % name)
        return None if default is MISSING else (list(default) if isinstance(default, list) else default)
    value = body[name]
    if not isinstance(value, list):
        fail("ERR_VALIDATION", "%s must be an array of strings." % name)
    for item in value:
        if not isinstance(item, str) or not item:
            fail("ERR_VALIDATION", "%s must contain non-empty strings." % name)
        if lower and item != item.lower():
            fail("ERR_VALIDATION", "%s entries must be lowercase." % name)
        if allowed is not None and item not in allowed:
            fail("ERR_VALIDATION", "%s entries must be one of %s." % (name, ", ".join(sorted(allowed))))
    if len(value) < min_items:
        fail("ERR_VALIDATION", "%s must contain at least %d entr(y/ies)." % (name, min_items))
    if max_items is not None and len(value) > max_items:
        fail("ERR_VALIDATION", "%s must contain at most %d entr(y/ies)." % (name, max_items))
    if unique and len(set(value)) != len(value):
        fail("ERR_VALIDATION", "%s entries must be unique." % name)
    return value


# ---------------------------------------------------------------------------
# query-string helpers
# ---------------------------------------------------------------------------

def q_int(name, default, minimum=None, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        fail("ERR_VALIDATION", "%s must be an integer." % name)
    if minimum is not None and value < minimum:
        fail("ERR_VALIDATION", "%s must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_VALIDATION", "%s must be <= %s." % (name, maximum))
    return value


def q_bool(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    fail("ERR_VALIDATION", "%s must be true or false." % name)


def q_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def paginate(rows):
    """Apply the limit/offset window; returns (page_rows, meta_fields)."""
    limit = q_int("limit", 10, 1, 100)
    offset = q_int("offset", 0, 0, None)
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
