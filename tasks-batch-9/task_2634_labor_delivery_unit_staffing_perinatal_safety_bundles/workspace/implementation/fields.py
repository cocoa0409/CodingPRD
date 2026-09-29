"""Priority-5 field validation: types, enum membership, lengths, ranges."""

from flask import request

import clock
from errors import ApiError

_MISSING = object()


class Vals(dict):
    """Parsed body values plus the set of keys the caller actually supplied."""

    def __init__(self):
        dict.__init__(self)
        self.present = set()

    def has(self, key):
        return key in self.present


def _bad(name):
    raise ApiError("ERR_INVALID_FIELD_VALUE",
                   "Field '%s' failed type, enum, length or range validation." % name)


def spec(name, kind, **opts):
    opts["name"] = name
    opts["kind"] = kind
    return opts


def s_str(name, **o):
    return spec(name, "str", **o)


def s_int(name, **o):
    return spec(name, "int", **o)


def s_bool(name, **o):
    return spec(name, "bool", **o)


def s_enum(name, values, **o):
    return spec(name, "enum", values=values, **o)


def s_dt(name, **o):
    return spec(name, "dt", **o)


def s_array(name, **o):
    return spec(name, "array", **o)


def _check_one(sp, raw):
    name = sp["name"]
    kind = sp["kind"]
    if kind == "str":
        if not isinstance(raw, str):
            _bad(name)
        if sp.get("min_len") is not None and len(raw) < sp["min_len"]:
            _bad(name)
        if sp.get("max_len") is not None and len(raw) > sp["max_len"]:
            _bad(name)
        return raw
    if kind == "int":
        if isinstance(raw, bool) or not isinstance(raw, int):
            _bad(name)
        if sp.get("min") is not None and raw < sp["min"]:
            _bad(name)
        if sp.get("max") is not None and raw > sp["max"]:
            _bad(name)
        return raw
    if kind == "bool":
        if not isinstance(raw, bool):
            _bad(name)
        return raw
    if kind == "enum":
        if not isinstance(raw, str) or raw not in sp["values"]:
            _bad(name)
        return raw
    if kind == "dt":
        value = clock.parse_dt(raw)
        if value is None:
            _bad(name)
        return value
    if kind == "array":
        if not isinstance(raw, list):
            _bad(name)
        if sp.get("min_len") is not None and len(raw) < sp["min_len"]:
            _bad(name)
        if sp.get("max_len") is not None and len(raw) > sp["max_len"]:
            _bad(name)
        item = sp.get("item", "str")
        for element in raw:
            if item == "str":
                if not isinstance(element, str) or not element:
                    _bad(name)
            elif item == "enum":
                if not isinstance(element, str) or element not in sp["values"]:
                    _bad(name)
        return raw
    _bad(name)


def validate(body, specs):
    vals = Vals()
    for sp in specs:
        name = sp["name"]
        raw = body.get(name, _MISSING)
        if raw is _MISSING or raw is None:
            if sp.get("required"):
                _bad(name)
            vals[name] = sp.get("default")
            continue
        vals[name] = _check_one(sp, raw)
        vals.present.add(name)
    return vals


def pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            _bad("limit")
        if limit < 1 or limit > 100:
            _bad("limit")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            _bad("offset")
        if offset < 0:
            _bad("offset")
    return limit, offset


def q_enum(name, values):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in values:
        _bad(name)
    return raw


def q_bool(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    lowered = raw.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    _bad(name)


def q_int(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        _bad(name)


def q_str(name):
    return request.args.get(name)


def q_date(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    value = clock.parse_date(raw)
    if value is None:
        _bad(name)
    return value
