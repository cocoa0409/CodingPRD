"""Request-shape validation (PRD section 2.8 band 3).

Every helper raises ERR_INVALID_REQUEST (400) on a violation, apart from the UPC
check digit which has its own code in the same band.
"""

from flask import request

import clock
from errors import ApiError

CATEGORY_CODES = ("FROZEN_SNACKS", "DAIRY", "BEVERAGE", "SNACK_NUTS", "HBC")
VOID_RATE_BASES = ("STORE_COUNT_BASIS", "REPORTED_BASIS")
AMORTIZATION_METHODS = ("FORECAST_STRAIGHT", "VOLUME_WEIGHTED")
CONFLICT_SCOPES = ("NATIONAL", "RETAILER_LEVEL")
EVENT_TYPES = ("PRICE_FEATURE", "DISPLAY", "DEMO_SAMPLING")
REASON_CODES = ("PROMO_BILLBACK", "SHORTAGE", "COMPLIANCE_FINE", "DUPLICATE_BILLBACK")
CATALOG_DECISIONS = ("VALIDATED", "REJECTED")
PRINCIPAL_STATUSES = ("PROSPECT", "ACTIVE", "SUSPENDED", "TERMINATED")

MISSING = object()


def _bad(field, detail):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, detail))


def body():
    """The JSON request body as a dict; an absent body is treated as empty."""
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def present(data, field):
    return field in data and data[field] is not None


def forbid(data, field, reason):
    if field in data and data[field] is not None:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be omitted %s." % (field, reason))


def req(data, field):
    if field not in data or data[field] is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
    return data[field]


# --------------------------------------------------------------------------
# scalars
# --------------------------------------------------------------------------

def as_string(value, field, min_len=1, max_len=None):
    if not isinstance(value, str):
        _bad(field, "must be a string")
    if len(value) < min_len:
        _bad(field, "must be at least %d character(s)" % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(field, "must be at most %d character(s)" % max_len)
    return value


def req_string(data, field, min_len=1, max_len=None):
    return as_string(req(data, field), field, min_len, max_len)


def opt_string(data, field, default=None, min_len=1, max_len=None):
    if not present(data, field):
        return default
    return as_string(data[field], field, min_len, max_len)


def as_int(value, field, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(field, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(field, "must be >= %d" % minimum)
    if maximum is not None and value > maximum:
        _bad(field, "must be <= %d" % maximum)
    return value


def req_int(data, field, minimum=None, maximum=None):
    return as_int(req(data, field), field, minimum, maximum)


def opt_int(data, field, default=None, minimum=None, maximum=None):
    if not present(data, field):
        return default
    return as_int(data[field], field, minimum, maximum)


def req_bps(data, field):
    return req_int(data, field, 0, 10000)


def opt_bps(data, field, default=None):
    return opt_int(data, field, default, 0, 10000)


def req_bool(data, field):
    value = req(data, field)
    if not isinstance(value, bool):
        _bad(field, "must be a boolean")
    return value


def opt_bool(data, field, default=None):
    if not present(data, field):
        return default
    value = data[field]
    if not isinstance(value, bool):
        _bad(field, "must be a boolean")
    return value


def req_enum(data, field, allowed):
    value = req(data, field)
    if not isinstance(value, str) or value not in allowed:
        _bad(field, "must be one of %s" % ", ".join(allowed))
    return value


def opt_enum(data, field, allowed, default=None):
    if not present(data, field):
        return default
    return req_enum(data, field, allowed)


def req_date(data, field):
    value = req(data, field)
    parsed = clock.parse_date(value if isinstance(value, str) else None)
    if parsed is None:
        _bad(field, "must be a YYYY-MM-DD date")
    return parsed


def req_instant(data, field):
    value = req(data, field)
    parsed = clock.parse_instant(value if isinstance(value, str) else None)
    if parsed is None:
        _bad(field, "must be an ISO 8601 UTC instant")
    return parsed


def req_instant_raw(data, field):
    """The parsed instant plus the caller's own text, which is stored verbatim."""
    parsed = req_instant(data, field)
    return parsed, data[field].strip()


def req_id(data, field):
    return req_string(data, field)


def opt_id(data, field):
    return opt_string(data, field)


def req_id_array(data, field, min_len, max_len, unique=True):
    value = req(data, field)
    if not isinstance(value, list):
        _bad(field, "must be an array")
    if len(value) < min_len or len(value) > max_len:
        _bad(field, "must hold %d to %d elements" % (min_len, max_len))
    for element in value:
        if not isinstance(element, str) or not element:
            _bad(field, "must hold identifier strings")
    if unique and len(set(value)) != len(value):
        _bad(field, "must not contain duplicates")
    return value


def opt_id_array(data, field, min_len, max_len, unique=True):
    """An array that may be empty (used by the award decision)."""
    value = req(data, field)
    if not isinstance(value, list):
        _bad(field, "must be an array")
    if len(value) < min_len or len(value) > max_len:
        _bad(field, "must hold %d to %d elements" % (min_len, max_len))
    for element in value:
        if not isinstance(element, str) or not element:
            _bad(field, "must hold identifier strings")
    if unique and len(set(value)) != len(value):
        _bad(field, "must not contain duplicates")
    return value


# --------------------------------------------------------------------------
# domain-specific shapes
# --------------------------------------------------------------------------

_CHAIN_CODE_ALLOWED = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


def req_chain_code(data, field="chain_code"):
    value = req_string(data, field, 1, 16)
    for character in value:
        if character not in _CHAIN_CODE_ALLOWED:
            _bad(field, "must contain only uppercase letters, digits and underscores")
    return value


def upc_check_digit(upc):
    """GS1 mod-10 check digit over the first eleven digits, weights 3,1,3,1,..."""
    total = 0
    for index in range(11):
        weight = 3 if index % 2 == 0 else 1
        total += int(upc[index]) * weight
    return (10 - total % 10) % 10


def req_upc_shape(data, field="upc"):
    """Presence and twelve-digit shape only; the check digit is a later rung."""
    value = req(data, field)
    if not isinstance(value, str) or len(value) != 12 or not value.isdigit():
        _bad(field, "must be exactly twelve numeric characters")
    return value


def check_upc_digit(value):
    if int(value[11]) != upc_check_digit(value):
        raise ApiError("ERR_UPC_CHECK_DIGIT_INVALID")
    return value


def req_upc(data, field="upc"):
    return check_upc_digit(req_upc_shape(data, field))


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
            _bad("limit", "must be an integer")
        if limit < 1 or limit > 100:
            _bad("limit", "must be between 1 and 100")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            _bad("offset", "must be an integer")
        if offset < 0:
            _bad("offset", "must be >= 0")
    return limit, offset


def filter_value(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def filter_int(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        _bad(name, "must be an integer")


def query_required(name):
    value = request.args.get(name)
    if value is None or value == "":
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' is required." % name)
    return value


def query_required_enum(name, allowed):
    value = query_required(name)
    if value not in allowed:
        _bad(name, "must be one of %s" % ", ".join(allowed))
    return value
