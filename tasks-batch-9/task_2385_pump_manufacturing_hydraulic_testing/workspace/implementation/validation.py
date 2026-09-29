"""Request shape validation (rung 3 of the rejection ladder) plus enum tables."""

import math
import re
from datetime import datetime, timezone

from flask import request

from errors import ApiError

# ---------------------------------------------------------------- enum tables

ALLOYS = ["CI_GG25", "DUCTILE_GGG40", "CD4MCU", "DUPLEX_S31803", "CN7M"]
SEAL_TYPES = ["SINGLE_CARTRIDGE", "DOUBLE_CARTRIDGE", "DUAL_PRESSURIZED", "PACKED_GLAND"]
FLUSH_PLANS = ["API_PLAN_02", "API_PLAN_11", "API_PLAN_23", "API_PLAN_32", "API_PLAN_53B"]
SERVICE_CLASSES = ["CLEAN", "CORROSIVE", "ABRASIVE", "CORROSIVE_ABRASIVE"]
BALANCE_GRADES = ["G1_0", "G2_5", "G6_3"]
TEST_GRADES = ["GRADE_1B", "GRADE_2B", "GRADE_3B"]
CORRECTION_BASES = ["AS_TESTED", "RATED_SPEED_CORRECTED"]
CONTROL_TYPES = ["DOL_STARTER", "SOFT_STARTER", "VFD", "NONE"]
DEFECT_TYPES = ["POROSITY", "SHRINKAGE", "INCLUSION", "COLD_SHUT", "MISRUN", "CORE_SHIFT"]
SEVERITIES = ["MINOR", "MAJOR", "CRITICAL"]
DISPOSITIONS = ["USE_AS_IS", "REPAIR_WELD", "SCRAP"]
CLAIM_CATEGORIES = ["PARTS", "LABOUR", "FREIGHT", "DOWNTIME"]

# ------------------------------------------------------------- body handling


def get_body():
    raw = request.get_data(cache=True)
    if raw is None or not raw.strip():
        return {}
    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def _bad(name, detail):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s" % (name, detail))


def check_keys(body, allowed):
    for key in body.keys():
        if key not in allowed:
            raise ApiError("ERR_INVALID_REQUEST", "Unknown field '%s'" % key)


def present(body, name):
    return name in body and body[name] is not None


def req_string(body, name, min_len=1, max_len=None):
    if not present(body, name):
        _bad(name, "is required")
    value = body[name]
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if len(value) < min_len:
        _bad(name, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(name, "must be at most %d characters" % max_len)
    return value


def req_enum(body, name, allowed):
    value = req_string(body, name)
    if value not in allowed:
        _bad(name, "must be one of %s" % ", ".join(allowed))
    return value


def req_bool(body, name):
    if not present(body, name):
        _bad(name, "is required")
    value = body[name]
    if not isinstance(value, bool):
        _bad(name, "must be a boolean")
    return value


def opt_bool(body, name, default=False):
    if not present(body, name):
        return default
    value = body[name]
    if not isinstance(value, bool):
        _bad(name, "must be a boolean")
    return value


def req_int(body, name, minimum=None, maximum=None):
    if not present(body, name):
        _bad(name, "is required")
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(name, "must be at least %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(name, "must be at most %s" % maximum)
    return value


def req_number(body, name, minimum=None, maximum=None, exclusive_min=None):
    if not present(body, name):
        _bad(name, "is required")
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(name, "must be a number")
    value = float(value)
    if math.isnan(value) or math.isinf(value):
        _bad(name, "must be a finite number")
    if exclusive_min is not None and value <= exclusive_min:
        _bad(name, "must be greater than %s" % exclusive_min)
    if minimum is not None and value < minimum:
        _bad(name, "must be at least %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(name, "must be at most %s" % maximum)
    return body[name]


def opt_number(body, name, minimum=None, maximum=None, exclusive_min=None, default=None):
    if not present(body, name):
        return default
    return req_number(body, name, minimum, maximum, exclusive_min)


def req_id(body, name):
    return req_string(body, name)


_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(\.\d{1,9})?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_datetime(value, name):
    if not isinstance(value, str):
        _bad(name, "must be an ISO 8601 datetime string")
    text = value.strip()
    if not _ISO_RE.match(text):
        _bad(name, "must be an ISO 8601 datetime string")
    normalised = text.replace(" ", "T").replace("t", "T")
    if normalised.endswith("z") or normalised.endswith("Z"):
        normalised = normalised[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalised)
    except ValueError:
        _bad(name, "must be an ISO 8601 datetime string")
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def req_datetime(body, name):
    if not present(body, name):
        _bad(name, "is required")
    return parse_datetime(body[name], name)


def req_array(body, name):
    if not present(body, name):
        _bad(name, "is required")
    value = body[name]
    if not isinstance(value, list):
        _bad(name, "must be an array")
    return value


# --------------------------------------------------------------- pagination

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0

_INT_RE = re.compile(r"^[+-]?\d+$")


def _query_int(name, default, minimum, maximum=None):
    raw = request.args.get(name)
    if raw is None:
        return default
    raw = raw.strip()
    if not _INT_RE.match(raw):
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer" % name)
    value = int(raw)
    if value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be at least %d" % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be at most %d" % (name, maximum))
    return value


def pagination():
    limit = _query_int("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _query_int("offset", OFFSET_DEFAULT, OFFSET_MIN, None)
    return limit, offset


def query_value(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value
