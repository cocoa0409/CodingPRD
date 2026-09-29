"""Request body / query-string shape validation helpers.

Every failure here is ERR_VALIDATION (HTTP 422) — rank 7 (body shape) or
rank 8 (pagination) of the PRD section 2.11 evaluation order.
"""

import json
from decimal import Decimal

from flask import request

from db import parse_iso
from errors import ApiError

MISSING = object()


def _bad():
    raise ApiError("ERR_VALIDATION")


def body():
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw, parse_float=Decimal)
    except Exception:
        _bad()
    if not isinstance(parsed, dict):
        _bad()
    return parsed


def present(data, key):
    return key in data


def raw_ref(data, key):
    """A body-borne foreign key value usable for an existence lookup."""
    value = data.get(key)
    if isinstance(value, str) and value.strip() != "":
        return value
    return None


def _absent(data, key, required, default):
    """(True, value) when the key is absent or explicitly null."""
    if key not in data or data[key] is None:
        if required:
            _bad()
        return True, default
    return False, data[key]


def str_field(data, key, min_len=0, max_len=None, required=True, default=None,
              non_blank=False):
    absent, value = _absent(data, key, required, default)
    if absent:
        return value
    if not isinstance(value, str):
        _bad()
    if len(value) < min_len:
        _bad()
    if max_len is not None and len(value) > max_len:
        _bad()
    if non_blank and value.strip() == "":
        _bad()
    return value


def int_field(data, key, minimum=None, maximum=None, required=True, default=None):
    absent, value = _absent(data, key, required, default)
    if absent:
        return value
    # A Decimal that happens to be integral is still not an integer input.
    if isinstance(value, bool) or not isinstance(value, int):
        _bad()
    if minimum is not None and value < minimum:
        _bad()
    if maximum is not None and value > maximum:
        _bad()
    return value


def dec_field(data, key, minimum=None, maximum=None, max_dp=None, required=True,
              default=None):
    absent, value = _absent(data, key, required, default)
    if absent:
        return value
    if isinstance(value, bool):
        _bad()
    if isinstance(value, int):
        value = Decimal(value)
    elif isinstance(value, Decimal):
        pass
    elif isinstance(value, float):
        value = Decimal(repr(value))
    else:
        _bad()
    if not value.is_finite():
        _bad()
    exponent = value.as_tuple().exponent
    if max_dp is not None and -int(exponent) > max_dp:
        _bad()
    if minimum is not None and value < Decimal(minimum):
        _bad()
    if maximum is not None and value > Decimal(maximum):
        _bad()
    return value


def bool_field(data, key, required=True, default=None):
    absent, value = _absent(data, key, required, default)
    if absent:
        return value
    if not isinstance(value, bool):
        _bad()
    return value


def enum_field(data, key, allowed, required=True, default=None):
    absent, value = _absent(data, key, required, default)
    if absent:
        return value
    if not isinstance(value, str) or value not in allowed:
        _bad()
    return value


def dt_field(data, key, required=True):
    """Returns (raw_string, datetime) — the raw form is echoed back verbatim."""
    absent, value = _absent(data, key, required, None)
    if absent:
        return (None, None)
    if not isinstance(value, str):
        _bad()
    parsed = parse_iso(value)
    if parsed is None:
        _bad()
    return (value, parsed)


def id_field(data, key, required=True):
    absent, value = _absent(data, key, required, None)
    if absent:
        return None
    if not isinstance(value, str) or value.strip() == "":
        _bad()
    return value


# ---------------------------------------------------------------- pagination

def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        text = args.get("limit")
        if text is None or text.strip() == "":
            _bad()
        try:
            limit = int(text.strip(), 10)
        except (TypeError, ValueError):
            _bad()
        if limit < 1 or limit > 100:
            _bad()
    if "offset" in args:
        text = args.get("offset")
        if text is None or text.strip() == "":
            _bad()
        try:
            offset = int(text.strip(), 10)
        except (TypeError, ValueError):
            _bad()
        if offset < 0:
            _bad()
    return limit, offset


def q_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def q_bool(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    lowered = value.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return "__nomatch__"


def q_int(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    try:
        return int(value.strip(), 10)
    except (TypeError, ValueError):
        return "__nomatch__"
