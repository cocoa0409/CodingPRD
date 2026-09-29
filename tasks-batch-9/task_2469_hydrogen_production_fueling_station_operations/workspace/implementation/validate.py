"""Schema validation helpers — every failure is ERR_INVALID_REQUEST (400)."""
import json
from datetime import datetime
from decimal import Decimal

from flask import request

from constants import PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MAX, PAGE_LIMIT_MIN
from errors import raise_error
from store import parse_iso

MISSING = object()


def bad(message):
    raise_error("ERR_INVALID_REQUEST", message)


def json_body():
    """Parse the request body as a JSON object; absent body becomes {}."""
    raw = request.get_data(cache=True)
    if raw is None or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        bad("Request body is not valid JSON.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        bad("Request body must be a JSON object.")
    return data


def _pick(d, name, required, default):
    if name not in d or d[name] is None:
        if required:
            bad("Field '%s' is required." % name)
        return default
    return d[name]


def _dp_of(value):
    dec = Decimal(str(value))
    exp = dec.as_tuple().exponent
    if not isinstance(exp, int):
        bad("Field must be a finite number.")
    return dec, max(0, -exp)


def f_num(d, name, dp, required=True, default=MISSING, gt=None, ge=None, lt=None, le=None):
    value = _pick(d, name, required, default)
    if value is MISSING or value is default and name not in d:
        return default if default is not MISSING else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field '%s' must be a number." % name)
    dec, places = _dp_of(value)
    if places > dp:
        bad("Field '%s' allows at most %d decimal places." % (name, dp))
    if gt is not None and not dec > gt:
        bad("Field '%s' must be greater than %s." % (name, gt))
    if ge is not None and not dec >= ge:
        bad("Field '%s' must be greater than or equal to %s." % (name, ge))
    if lt is not None and not dec < lt:
        bad("Field '%s' must be less than %s." % (name, lt))
    if le is not None and not dec <= le:
        bad("Field '%s' must be less than or equal to %s." % (name, le))
    return dec.quantize(Decimal(1).scaleb(-dp))


def f_int(d, name, required=True, default=MISSING, ge=None, le=None):
    value = _pick(d, name, required, default)
    if value is MISSING or value is default and name not in d:
        return default if default is not MISSING else None
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % name)
    if ge is not None and value < ge:
        bad("Field '%s' must be >= %s." % (name, ge))
    if le is not None and value > le:
        bad("Field '%s' must be <= %s." % (name, le))
    return value


def f_str(d, name, required=True, default=MISSING, nonempty=True):
    value = _pick(d, name, required, default)
    if value is MISSING or value is default and name not in d:
        return default if default is not MISSING else None
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % name)
    if nonempty and not value.strip():
        bad("Field '%s' must not be empty." % name)
    return value


def f_enum(d, name, allowed, required=True, default=MISSING):
    value = _pick(d, name, required, default)
    if value is MISSING or value is default and name not in d:
        return default if default is not MISSING else None
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def f_bool(d, name, required=True, default=MISSING):
    value = _pick(d, name, required, default)
    if value is MISSING or value is default and name not in d:
        return default if default is not MISSING else None
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % name)
    return value


def f_dt(d, name, required=True, default=MISSING):
    """Returns (datetime, raw_string) or (None, None)."""
    value = _pick(d, name, required, default)
    if value is MISSING or value is default and name not in d:
        return None, None
    if not isinstance(value, str):
        bad("Field '%s' must be an ISO 8601 datetime string." % name)
    try:
        return parse_iso(value), value
    except Exception:
        bad("Field '%s' must be an ISO 8601 datetime string." % name)


def f_date(d, name, required=True, default=MISSING):
    value = _pick(d, name, required, default)
    if value is MISSING or value is default and name not in d:
        return None
    if not isinstance(value, str):
        bad("Field '%s' must be a YYYY-MM-DD date string." % name)
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        bad("Field '%s' must be a YYYY-MM-DD date string." % name)


def f_id_list(d, name):
    value = _pick(d, name, True, MISSING)
    if not isinstance(value, list) or not value:
        bad("Field '%s' must be a non-empty array." % name)
    for element in value:
        if not isinstance(element, str) or not element.strip():
            bad("Every element of '%s' must be a non-empty string id." % name)
    return list(value)


def forbid(d, name):
    if name in d and d[name] is not None:
        bad("Field '%s' must be omitted for this request." % name)


# ---------- query string ----------
def pagination():
    limit = PAGE_LIMIT_DEFAULT
    offset = 0
    if "limit" in request.args:
        raw = request.args.get("limit")
        try:
            limit = int(raw)
        except Exception:
            bad("Query parameter 'limit' must be an integer.")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            bad("Query parameter 'limit' must be between %d and %d."
                % (PAGE_LIMIT_MIN, PAGE_LIMIT_MAX))
    if "offset" in request.args:
        raw = request.args.get("offset")
        try:
            offset = int(raw)
        except Exception:
            bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            bad("Query parameter 'offset' must not be negative.")
    return limit, offset


def q_str(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def q_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        bad("Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def paginate(rows, limit, offset):
    return rows[offset:offset + limit]
