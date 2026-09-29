"""Request-shape validation (PRD ordering step 4) and query-string parsing.

Scope, verbatim from PRD 2.8: every non-optional field present and non-null;
every enum-valued field a declared member; every integer field an integer
inside its declared range; every money field a non-negative integer of cents;
every decimal field respecting its declared scale; remedy_options non-empty
with unique members; every timestamp a valid ISO 8601 UTC instant; every
interval well ordered.  Unknown body keys and any attempt to supply a
server-computed field are ignored silently.
"""

from decimal import Decimal, InvalidOperation

from flask import request

import responses
import store
from errors import raise_error

MISSING = object()


def bad():
    raise_error("ERR_INVALID_REQUEST")


def body():
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None or not isinstance(parsed, dict):
        bad()
    return parsed


def present(data, key):
    return key in data and data[key] is not None


def _req(data, key):
    if key not in data or data[key] is None:
        bad()
    return data[key]


def req_str(data, key, min_len, max_len):
    value = _req(data, key)
    if not isinstance(value, str):
        bad()
    if len(value) < min_len or len(value) > max_len:
        bad()
    return value


def opt_str(data, key, min_len, max_len):
    if not present(data, key):
        return MISSING
    return req_str(data, key, min_len, max_len)


def req_enum(data, key, members):
    value = _req(data, key)
    if not isinstance(value, str) or value not in members:
        bad()
    return value


def opt_enum(data, key, members):
    if not present(data, key):
        return MISSING
    return req_enum(data, key, members)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_int(data, key, minimum=None, maximum=None):
    value = _req(data, key)
    if not _is_int(value):
        bad()
    if minimum is not None and value < minimum:
        bad()
    if maximum is not None and value > maximum:
        bad()
    return value


def req_money(data, key):
    """Money fields are non-negative integer counts of cents."""
    return req_int(data, key, minimum=0)


def req_bool(data, key):
    value = _req(data, key)
    if not isinstance(value, bool):
        bad()
    return value


def opt_bool(data, key):
    if not present(data, key):
        return MISSING
    return req_bool(data, key)


def req_decimal(data, key, scale, minimum=None, maximum=None,
                exclusive_minimum=None):
    value = _req(data, key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad()
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        bad()
    exponent = dec.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -scale:
        bad()
    if minimum is not None and dec < Decimal(str(minimum)):
        bad()
    if maximum is not None and dec > Decimal(str(maximum)):
        bad()
    if exclusive_minimum is not None and dec <= Decimal(str(exclusive_minimum)):
        bad()
    return store.rhu(dec, scale)


def req_ts(data, key):
    value = _req(data, key)
    parsed = store.parse_ts(value)
    if parsed is None:
        bad()
    return parsed


def opt_ts(data, key):
    if not present(data, key):
        return MISSING
    return req_ts(data, key)


def req_enum_array(data, key, members):
    value = _req(data, key)
    if not isinstance(value, list) or len(value) == 0:
        bad()
    seen = set()
    for item in value:
        if not isinstance(item, str) or item not in members:
            bad()
        if item in seen:
            bad()
        seen.add(item)
    return list(value)


def pagination():
    limit = responses.PAGINATION_LIMIT_DEFAULT
    offset = responses.PAGINATION_OFFSET_DEFAULT
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        if raw_limit.strip() == "":
            bad()
        try:
            limit = int(raw_limit)
        except ValueError:
            bad()
        if limit < responses.PAGINATION_LIMIT_MIN or limit > responses.PAGINATION_LIMIT_MAX:
            bad()
    if raw_offset is not None:
        if raw_offset.strip() == "":
            bad()
        try:
            offset = int(raw_offset)
        except ValueError:
            bad()
        if offset < responses.PAGINATION_OFFSET_MIN:
            bad()
    return limit, offset


def q_enum(name, members):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in members:
        bad()
    return raw


def q_str(name):
    return request.args.get(name)


def q_bool(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    bad()
