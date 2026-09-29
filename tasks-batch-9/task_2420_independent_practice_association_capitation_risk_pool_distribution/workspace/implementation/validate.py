"""Request-shape validation (PRD 2.10 check 3) and pagination (PRD 2.3)."""

import re

from flask import request

import db
from errors import fail

COVERAGE_MONTH_RE = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")
MEASUREMENT_PERIOD_RE = re.compile(r"^[0-9]{4}$")

PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0


def body():
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def _missing(name):
    fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)


def _bad(name, why):
    fail("ERR_INVALID_REQUEST", "Field '%s' %s." % (name, why))


def _present(payload, name):
    return name in payload and payload[name] is not None


def req_str(payload, name):
    if not _present(payload, name):
        _missing(name)
    value = payload[name]
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if not value.strip():
        _bad(name, "must not be empty")
    return value


def opt_str(payload, name, default=None):
    if not _present(payload, name):
        return default
    value = payload[name]
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if not value.strip():
        _bad(name, "must not be empty")
    return value


def req_int(payload, name, minimum=None, maximum=None):
    if not _present(payload, name):
        _missing(name)
    return _as_int(payload[name], name, minimum, maximum)


def opt_int(payload, name, minimum=None, maximum=None, default=None):
    if not _present(payload, name):
        return default
    return _as_int(payload[name], name, minimum, maximum)


def _as_int(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(name, "must be >= %d" % minimum)
    if maximum is not None and value > maximum:
        _bad(name, "must be <= %d" % maximum)
    return value


def req_enum(payload, name, allowed):
    if not _present(payload, name):
        _missing(name)
    value = payload[name]
    if not isinstance(value, str) or value not in allowed:
        _bad(name, "must be one of %s" % ", ".join(allowed))
    return value


def opt_enum(payload, name, allowed, default=None):
    if not _present(payload, name):
        return default
    return req_enum(payload, name, allowed)


def req_bool(payload, name):
    if not _present(payload, name):
        _missing(name)
    value = payload[name]
    if not isinstance(value, bool):
        _bad(name, "must be a boolean")
    return value


def opt_bool(payload, name, default=None):
    if not _present(payload, name):
        return default
    return req_bool(payload, name)


def req_instant(payload, name):
    if not _present(payload, name):
        _missing(name)
    value = payload[name]
    if not isinstance(value, str):
        _bad(name, "must be an ISO 8601 datetime string")
    parsed = db.parse_instant(value)
    if parsed is None:
        _bad(name, "must be an ISO 8601 datetime string")
    return parsed


def opt_instant(payload, name, default=None):
    if not _present(payload, name):
        return default
    return req_instant(payload, name)


def req_coverage_month(payload, name="coverage_month"):
    value = req_str(payload, name)
    if not COVERAGE_MONTH_RE.match(value):
        _bad(name, "must be YYYY-MM with a month between 01 and 12")
    return value


def req_measurement_period(payload, name="measurement_period"):
    value = req_str(payload, name)
    if not MEASUREMENT_PERIOD_RE.match(value):
        _bad(name, "must be exactly four digits")
    return value


# ---------------------------------------------------------------- query params
def query_enum(name, allowed):
    if name not in request.args:
        return None
    value = request.args.get(name)
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' is not a declared value." % name)
    return value


def query_str(name):
    if name not in request.args:
        return None
    value = request.args.get(name)
    if value is None or value == "":
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must not be empty." % name)
    return value


def query_coverage_month(name="coverage_month"):
    value = query_str(name)
    if value is None:
        return None
    if not COVERAGE_MONTH_RE.match(value):
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be YYYY-MM." % name)
    return value


def query_measurement_period(name="measurement_period"):
    value = query_str(name)
    if value is None:
        return None
    if not MEASUREMENT_PERIOD_RE.match(value):
        fail("ERR_INVALID_REQUEST",
             "Query parameter '%s' must be exactly four digits." % name)
    return value


def pagination():
    limit = PAGINATION_LIMIT_DEFAULT
    offset = PAGINATION_OFFSET_DEFAULT
    if "limit" in request.args:
        raw = request.args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
        if str(raw).strip() != str(limit):
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < PAGINATION_LIMIT_MIN or limit > PAGINATION_LIMIT_MAX:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100 inclusive.")
    if "offset" in request.args:
        raw = request.args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
        if str(raw).strip() != str(offset):
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must not be negative.")
    return limit, offset


def paginate(items, limit, offset):
    return items[offset:offset + limit]
