"""Request-body and query-parameter validation (rejection band 3, PRD 2.5)."""

import json

from flask import request

import db
from errors import ApiError, invalid

RESOURCE_AREAS = ("BIOLOGICAL", "CULTURAL", "AIR", "WATER", "SOCIOECONOMIC")
EC_CODES = (
    "EC_HISTORIC",
    "EC_ENDANGERED_SPECIES",
    "EC_WETLAND",
    "EC_ENVIRONMENTAL_JUSTICE",
    "EC_FLOODPLAIN",
)


def raw_body():
    data = request.get_data(cache=True)
    if data is None or not data.strip():
        return {}
    try:
        parsed = json.loads(data)
    except Exception:
        raise invalid("request body is not valid JSON")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise invalid("request body must be a JSON object")
    return parsed


def parse_body(spec):
    """Validate the body against `spec` and return a normalised dict.

    spec: field name -> {"required": bool, "check": callable, "default": value}
    Unknown fields, missing required fields and type/range violations all raise
    ERR_INVALID_REQUEST.
    """
    data = raw_body()
    for key in data:
        if key not in spec:
            raise invalid("unknown field: %s" % key)
    out = {}
    for name, rule in spec.items():
        if name not in data or data[name] is None:
            if rule.get("required"):
                raise invalid("missing required field: %s" % name)
            out[name] = rule.get("default")
            continue
        out[name] = rule["check"](data[name], name)
    return out


def no_body():
    data = raw_body()
    if data:
        raise invalid("unknown field: %s" % sorted(data.keys())[0])
    return {}


# ---------------------------------------------------------------- checkers


def c_str(min_len=1, max_len=None):
    def check(value, name):
        if not isinstance(value, str):
            raise invalid("%s must be a string" % name)
        if min_len and not value.strip():
            raise invalid("%s must be a non-empty string" % name)
        if len(value) < min_len:
            raise invalid("%s must be at least %d characters" % (name, min_len))
        if max_len is not None and len(value) > max_len:
            raise invalid("%s must be at most %d characters" % (name, max_len))
        return value

    return check


def c_bool(value, name):
    if not isinstance(value, bool):
        raise invalid("%s must be a boolean" % name)
    return value


def c_int(lo=None, hi=None):
    def check(value, name):
        if isinstance(value, bool) or not isinstance(value, int):
            raise invalid("%s must be an integer" % name)
        if lo is not None and value < lo:
            raise invalid("%s must be >= %s" % (name, lo))
        if hi is not None and value > hi:
            raise invalid("%s must be <= %s" % (name, hi))
        return value

    return check


def c_num(lo=None, hi=None, lo_exclusive=False, hi_exclusive=False):
    def check(value, name):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise invalid("%s must be a number" % name)
        value = float(value)
        if lo is not None:
            if lo_exclusive and not value > lo:
                raise invalid("%s must be > %s" % (name, lo))
            if not lo_exclusive and value < lo:
                raise invalid("%s must be >= %s" % (name, lo))
        if hi is not None:
            if hi_exclusive and not value < hi:
                raise invalid("%s must be < %s" % (name, hi))
            if not hi_exclusive and value > hi:
                raise invalid("%s must be <= %s" % (name, hi))
        return value

    return check


def c_enum(values):
    def check(value, name):
        if not isinstance(value, str) or value not in values:
            raise invalid("%s must be one of %s" % (name, ", ".join(values)))
        return value

    return check


def c_datetime(value, name):
    if not isinstance(value, str):
        raise invalid("%s must be an ISO 8601 datetime string" % name)
    if db.parse_dt(value) is None:
        raise invalid("%s must be an ISO 8601 datetime string" % name)
    return value


def c_enum_array(values, min_items=0):
    def check(value, name):
        if not isinstance(value, list):
            raise invalid("%s must be an array" % name)
        if len(value) < min_items:
            raise invalid("%s must contain at least %d element(s)" % (name, min_items))
        for item in value:
            if not isinstance(item, str) or item not in values:
                raise invalid("%s elements must be one of %s" % (name, ", ".join(values)))
        return list(value)

    return check


def c_code_array(min_items=0, min_len=2, max_len=24):
    """Ordered array of uppercase codes with no duplicates."""

    def check(value, name):
        if not isinstance(value, list):
            raise invalid("%s must be an array" % name)
        if len(value) < min_items:
            raise invalid("%s must contain at least %d element(s)" % (name, min_items))
        seen = set()
        for item in value:
            if not isinstance(item, str):
                raise invalid("%s elements must be strings" % name)
            if len(item) < min_len or len(item) > max_len:
                raise invalid(
                    "%s elements must be between %d and %d characters" % (name, min_len, max_len)
                )
            if item != item.upper() or not item.replace("_", "").replace("-", "").isalnum():
                raise invalid("%s elements must be uppercase codes" % name)
            if item in seen:
                raise invalid("%s must not contain duplicates" % name)
            seen.add(item)
        return list(value)

    return check


def c_id_array(min_items=0):
    def check(value, name):
        if not isinstance(value, list):
            raise invalid("%s must be an array" % name)
        if len(value) < min_items:
            raise invalid("%s must contain at least %d element(s)" % (name, min_items))
        seen = set()
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise invalid("%s elements must be non-empty strings" % name)
            if item in seen:
                raise invalid("%s must not contain duplicates" % name)
            seen.add(item)
        return list(value)

    return check


_FINDING_KEYS = {"code", "present", "severity", "narrative"}


def c_findings(value, name):
    """Array of {code, present, severity, narrative} objects, non-empty."""
    if not isinstance(value, list) or not value:
        raise invalid("%s must be a non-empty array" % name)
    out = []
    for item in value:
        if not isinstance(item, dict):
            raise invalid("%s elements must be objects" % name)
        for key in item:
            if key not in _FINDING_KEYS:
                raise invalid("unknown field in %s: %s" % (name, key))
        for key in ("code", "present", "severity"):
            if key not in item or item[key] is None:
                raise invalid("%s elements require %s" % (name, key))
        code = item["code"]
        if not isinstance(code, str) or code not in EC_CODES:
            raise invalid("%s.code must be a recognised extraordinary-circumstance code" % name)
        present = item["present"]
        if not isinstance(present, bool):
            raise invalid("%s.present must be a boolean" % name)
        severity = item["severity"]
        if isinstance(severity, bool) or not isinstance(severity, int):
            raise invalid("%s.severity must be an integer" % name)
        if severity < 0 or severity > 5:
            raise invalid("%s.severity must be between 0 and 5" % name)
        narrative = item.get("narrative")
        if present:
            if not isinstance(narrative, str) or not narrative.strip():
                raise invalid("%s.narrative is required when present is true" % name)
        elif narrative is not None and not isinstance(narrative, str):
            raise invalid("%s.narrative must be a string" % name)
        out.append(
            {
                "code": code,
                "present": present,
                "severity": severity,
                "narrative": narrative,
            }
        )
    return out


# ------------------------------------------------------------- query params


def pagination():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None:
        limit_value = 10
    else:
        limit_value = _query_int(limit, "limit")
        if limit_value < 1 or limit_value > 100:
            raise invalid("limit must be between 1 and 100")
    if offset is None:
        offset_value = 0
    else:
        offset_value = _query_int(offset, "offset")
        if offset_value < 0:
            raise invalid("offset must not be negative")
    return limit_value, offset_value


def _query_int(text, name):
    try:
        return int(str(text).strip())
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer" % name, 400)


def filters(*names):
    out = {}
    for name in names:
        value = request.args.get(name)
        if value is not None:
            out[name] = value
    return out


def apply_filters(items, spec):
    out = items
    for field, value in spec.items():
        out = [row for row in out if str(row.get(field)) == value]
    return out
