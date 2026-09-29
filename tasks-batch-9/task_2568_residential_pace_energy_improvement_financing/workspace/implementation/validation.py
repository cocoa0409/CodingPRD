"""Ladder stage 3 - pure request-shape validation, no database access."""

import re
from datetime import date

from flask import request

from errors import fail

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
INT_RE = re.compile(r"^-?\d+$")

COUNTY_CODES = ("06073", "06037", "12086")
DEEMED_CONSENT_COUNTIES = ("06073", "06037")
OCCUPANCY_TYPES = ("OWNER_OCCUPIED", "RENTAL", "VACANT")
LANGUAGES = ("EN", "ES")
LIEN_STATUSES = ("ACTIVE", "RELEASED")
PRODUCT_CATEGORIES = ("SOLAR_PV", "HVAC", "ROOF", "WINDOWS", "WATER_EFFICIENCY")
PRODUCT_STATUSES = ("ACTIVE", "RETIRED")
COMPLAINT_CATEGORIES = (
    "WORKMANSHIP_DEFECT",
    "INCOMPLETE_WORK",
    "SAVINGS_SHORTFALL",
    "PERMIT_FAILURE",
)
SEVERITIES = ("MINOR", "MAJOR", "SEVERE")
CURE_REASON_CODES = (
    "TAX_DELINQUENCY",
    "MEASURE_SIR_FAIL",
    "APPRAISAL_MISSING",
    "LENDER_UNRESPONSIVE",
)
ANALYST_DECLINE_REASONS = (
    "CLTV_LIMIT",
    "PTV_LIMIT",
    "EQUITY_FLOOR",
    "SIR_FLOOR",
    "BANKRUPTCY",
)
TRANSFER_MODES = ("ASSUME_WITH_PROPERTY", "PAYOFF_AT_CLOSING")
ALLOWED_TERMS = (10, 15, 18, 20, 25)


def body():
    payload = request.get_json(silent=True)
    if payload is None:
        raw = request.get_data(cache=True, as_text=True)
        if raw and raw.strip():
            fail("ERR_VALIDATION", "Request body must be a JSON object")
        return {}
    if not isinstance(payload, dict):
        fail("ERR_VALIDATION", "Request body must be a JSON object")
    return payload


def _missing(key):
    fail("ERR_VALIDATION", "Field '%s' is required" % key)


def present(payload, key):
    return key in payload and payload[key] is not None


def req_str(payload, key, min_len=1, max_len=None):
    if not present(payload, key):
        _missing(key)
    value = payload[key]
    if not isinstance(value, str):
        fail("ERR_VALIDATION", "Field '%s' must be a string" % key)
    if len(value) < min_len:
        fail("ERR_VALIDATION", "Field '%s' must not be empty" % key)
    if max_len is not None and len(value) > max_len:
        fail("ERR_VALIDATION", "Field '%s' is too long" % key)
    return value


def opt_str(payload, key, default=None, min_len=1, max_len=None):
    if not present(payload, key):
        return default
    return req_str(payload, key, min_len=min_len, max_len=max_len)


def req_int(payload, key, minimum=None, maximum=None):
    if not present(payload, key):
        _missing(key)
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_VALIDATION", "Field '%s' must be an integer" % key)
    if minimum is not None and value < minimum:
        fail("ERR_VALIDATION", "Field '%s' must be at least %s" % (key, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_VALIDATION", "Field '%s' must be at most %s" % (key, maximum))
    return value


def opt_int(payload, key, default=None, minimum=None, maximum=None):
    if not present(payload, key):
        return default
    return req_int(payload, key, minimum=minimum, maximum=maximum)


def req_bool(payload, key):
    if not present(payload, key):
        _missing(key)
    value = payload[key]
    if not isinstance(value, bool):
        fail("ERR_VALIDATION", "Field '%s' must be a boolean" % key)
    return value


def opt_bool(payload, key, default=None):
    if not present(payload, key):
        return default
    return req_bool(payload, key)


def req_enum(payload, key, allowed):
    value = req_str(payload, key)
    if value not in allowed:
        fail("ERR_VALIDATION", "Field '%s' must be one of %s" % (key, ", ".join(allowed)))
    return value


def opt_enum(payload, key, allowed, default=None):
    if not present(payload, key):
        return default
    return req_enum(payload, key, allowed)


def parse_date(value, key):
    if not isinstance(value, str) or not DATE_RE.match(value):
        fail("ERR_VALIDATION", "Field '%s' must be a YYYY-MM-DD date" % key)
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        fail("ERR_VALIDATION", "Field '%s' must be a valid calendar date" % key)


def req_date(payload, key):
    if not present(payload, key):
        _missing(key)
    parse_date(payload[key], key)
    return payload[key]


def opt_date(payload, key, default=None):
    if not present(payload, key):
        return default
    return req_date(payload, key)


def req_id(payload, key):
    return req_str(payload, key)


def opt_id(payload, key, default=None):
    return opt_str(payload, key, default=default)


def req_str_array(payload, key, allowed=None, no_duplicates=False):
    if not present(payload, key):
        _missing(key)
    value = payload[key]
    if not isinstance(value, list) or not value:
        fail("ERR_VALIDATION", "Field '%s' must be a non-empty array" % key)
    for item in value:
        if not isinstance(item, str) or not item:
            fail("ERR_VALIDATION", "Field '%s' must contain non-empty strings" % key)
        if allowed is not None and item not in allowed:
            fail("ERR_VALIDATION", "Field '%s' contains an unsupported value" % key)
    if no_duplicates and len(set(value)) != len(value):
        fail("ERR_VALIDATION", "Field '%s' must not contain duplicates" % key)
    return value


def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        if not INT_RE.match(raw_limit.strip()):
            fail("ERR_VALIDATION", "limit must be an integer")
        limit = int(raw_limit.strip())
        if limit < 1 or limit > 100:
            fail("ERR_VALIDATION", "limit must be between 1 and 100")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        if not INT_RE.match(raw_offset.strip()):
            fail("ERR_VALIDATION", "offset must be an integer")
        offset = int(raw_offset.strip())
        if offset < 0:
            fail("ERR_VALIDATION", "offset must not be negative")
    return limit, offset


def filter_value(name):
    value = request.args.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None
