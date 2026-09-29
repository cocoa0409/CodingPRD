"""Input coercion and the ERR_VALIDATION global step (PRD 2.8 step 1, PRD 2.3).

A malformed body, an unknown enum value or a missing required input yields
ERR_VALIDATION (422) and is evaluated before the role gate.
"""
from decimal import Decimal, InvalidOperation

from flask import request

import constants
from errors import fail
from util import dec, parse_iso, q2

_SENTINEL = object()


def body():
    """The JSON object of the request, or {} when no body was supplied."""
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_VALIDATION", "Request body is not valid JSON")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        fail("ERR_VALIDATION", "Request body must be a JSON object")
    return parsed


def _present(payload, key):
    return key in payload and payload[key] is not None


def req_str(payload, key):
    if not _present(payload, key):
        fail("ERR_VALIDATION", "%s is required" % key)
    value = payload[key]
    if not isinstance(value, str) or value.strip() == "":
        fail("ERR_VALIDATION", "%s must be a non-empty string" % key)
    return value


def opt_str(payload, key, default=None):
    if not _present(payload, key):
        return default
    value = payload[key]
    if not isinstance(value, str):
        fail("ERR_VALIDATION", "%s must be a string" % key)
    return value


def raw_opt_str(payload, key):
    """Optional string that may legitimately be blank (checked by a domain rule)."""
    if key not in payload or payload[key] is None:
        return None
    value = payload[key]
    if not isinstance(value, str):
        fail("ERR_VALIDATION", "%s must be a string" % key)
    return value


def req_enum(payload, key, allowed):
    value = req_str(payload, key)
    if value not in allowed:
        fail("ERR_VALIDATION", "%s must be one of %s" % (key, ", ".join(allowed)))
    return value


def opt_enum(payload, key, allowed, default=None):
    if not _present(payload, key):
        return default
    value = payload[key]
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_VALIDATION", "%s must be one of %s" % (key, ", ".join(allowed)))
    return value


def _as_decimal(key, value):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        fail("ERR_VALIDATION", "%s must be a number" % key)
    try:
        return dec(value)
    except (InvalidOperation, ValueError):
        fail("ERR_VALIDATION", "%s must be a number" % key)


def req_num(payload, key, gt=None, ge=None, places=2):
    if not _present(payload, key):
        fail("ERR_VALIDATION", "%s is required" % key)
    value = _as_decimal(key, payload[key])
    if gt is not None and value <= dec(gt):
        fail("ERR_VALIDATION", "%s must be greater than %s" % (key, gt))
    if ge is not None and value < dec(ge):
        fail("ERR_VALIDATION", "%s must be at least %s" % (key, ge))
    return value if places is None else value.quantize(Decimal(1).scaleb(-places))


def opt_num(payload, key, default=None, gt=None, ge=None, places=2):
    if not _present(payload, key):
        return default
    return req_num(payload, key, gt=gt, ge=ge, places=places)


def req_int(payload, key, ge=None, gt=None):
    if not _present(payload, key):
        fail("ERR_VALIDATION", "%s is required" % key)
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_VALIDATION", "%s must be an integer" % key)
    if ge is not None and value < ge:
        fail("ERR_VALIDATION", "%s must be at least %s" % (key, ge))
    if gt is not None and value <= gt:
        fail("ERR_VALIDATION", "%s must be greater than %s" % (key, gt))
    return value


def opt_int(payload, key, default=None, ge=None):
    if not _present(payload, key):
        return default
    return req_int(payload, key, ge=ge)


def req_bool(payload, key):
    if not _present(payload, key):
        fail("ERR_VALIDATION", "%s is required" % key)
    value = payload[key]
    if not isinstance(value, bool):
        fail("ERR_VALIDATION", "%s must be a boolean" % key)
    return value


def opt_bool(payload, key, default=None):
    if not _present(payload, key):
        return default
    return req_bool(payload, key)


def req_dt(payload, key):
    if not _present(payload, key):
        fail("ERR_VALIDATION", "%s is required" % key)
    try:
        return parse_iso(payload[key])
    except (ValueError, TypeError):
        fail("ERR_VALIDATION", "%s must be an ISO 8601 instant" % key)


def opt_dt(payload, key, default=None):
    if not _present(payload, key):
        return default
    return req_dt(payload, key)


def req_id(payload, key):
    return req_str(payload, key)


def opt_id(payload, key, default=None):
    if not _present(payload, key):
        return default
    value = payload[key]
    if not isinstance(value, str) or value.strip() == "":
        fail("ERR_VALIDATION", "%s must be a string identifier" % key)
    return value


def money(value):
    return q2(value)


# ------------------------------------------------------------------ query params

def pagination():
    limit = constants.PAGE_LIMIT_DEFAULT
    offset = constants.PAGE_OFFSET_DEFAULT
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None and raw_limit != "":
        limit = _query_int("limit", raw_limit)
        if limit < constants.PAGE_LIMIT_MIN or limit > constants.PAGE_LIMIT_MAX:
            fail("ERR_VALIDATION", "limit must be between 1 and 100")
    if raw_offset is not None and raw_offset != "":
        offset = _query_int("offset", raw_offset)
        if offset < 0:
            fail("ERR_VALIDATION", "offset may not be negative")
    return limit, offset


def _query_int(key, raw):
    try:
        return int(str(raw), 10)
    except (TypeError, ValueError):
        fail("ERR_VALIDATION", "%s must be an integer" % key)


def query_enum(key, allowed):
    raw = request.args.get(key)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        fail("ERR_VALIDATION", "%s must be one of %s" % (key, ", ".join(allowed)))
    return raw


def query_str(key):
    raw = request.args.get(key)
    if raw is None or raw == "":
        return None
    return raw


def query_int(key, ge=None):
    raw = request.args.get(key)
    if raw is None or raw == "":
        return None
    value = _query_int(key, raw)
    if ge is not None and value < ge:
        fail("ERR_VALIDATION", "%s must be at least %s" % (key, ge))
    return value


def paginate(items, limit, offset):
    total = len(items)
    return items[offset:offset + limit], total
