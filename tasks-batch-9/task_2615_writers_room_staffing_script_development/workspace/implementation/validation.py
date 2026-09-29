"""Body-schema validation primitives (PRD 2.11 step 7 -> ERR_INVALID_REQUEST)."""
from flask import request

from db import parse_iso
from errors import ApiError

MISSING = object()


def bad():
    raise ApiError("ERR_INVALID_REQUEST")


def body_json():
    try:
        data = request.get_json(silent=True)
    except Exception:
        data = None
    if data is None:
        data = {}
    if not isinstance(data, dict):
        bad()
    return data


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def raw(body, name):
    """Present-but-unvalidated fetch used by precedence step 6."""
    return body.get(name) if isinstance(body, dict) else None


def v_str(body, name, lo=1, hi=None, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            bad()
        return default
    value = body[name]
    if not isinstance(value, str):
        bad()
    if lo is not None and len(value) < lo:
        bad()
    if hi is not None and len(value) > hi:
        bad()
    return value


def v_int(body, name, lo=None, hi=None, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            bad()
        return default
    value = body[name]
    if not is_int(value):
        bad()
    if lo is not None and value < lo:
        bad()
    if hi is not None and value > hi:
        bad()
    return value


def v_num(body, name, lo=None, hi=None, lo_exclusive=False, hi_exclusive=False,
          required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            bad()
        return default
    value = body[name]
    if not is_num(value):
        bad()
    if lo is not None:
        if lo_exclusive and not value > lo:
            bad()
        if not lo_exclusive and value < lo:
            bad()
    if hi is not None:
        if hi_exclusive and not value < hi:
            bad()
        if not hi_exclusive and value > hi:
            bad()
    return value


def v_bool(body, name, required=False, default=False):
    if name not in body or body[name] is None:
        if required:
            bad()
        return default
    value = body[name]
    if not isinstance(value, bool):
        bad()
    return value


def v_enum(body, name, allowed, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            bad()
        return default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        bad()
    return value


def v_dt(body, name, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            bad()
        return default
    parsed = parse_iso(body[name])
    if parsed is None:
        bad()
    return parsed


def _exact_map(body, name, keys, required=True):
    if name not in body or body[name] is None:
        if required:
            bad()
        return None
    value = body[name]
    if not isinstance(value, dict):
        bad()
    if set(value.keys()) != set(keys):
        bad()
    return value


def v_map_int(body, name, keys, lo=None, hi=None, required=True):
    value = _exact_map(body, name, keys, required)
    if value is None:
        return None
    for key in keys:
        item = value[key]
        if not is_int(item):
            bad()
        if lo is not None and item < lo:
            bad()
        if hi is not None and item > hi:
            bad()
    return {k: value[k] for k in keys}


def v_map_num(body, name, keys, lo=None, hi=None, lo_exclusive=False, hi_exclusive=False,
              required=True):
    value = _exact_map(body, name, keys, required)
    if value is None:
        return None
    for key in keys:
        item = value[key]
        if not is_num(item):
            bad()
        if lo is not None:
            if lo_exclusive and not item > lo:
                bad()
            if not lo_exclusive and item < lo:
                bad()
        if hi is not None:
            if hi_exclusive and not item < hi:
                bad()
            if not hi_exclusive and item > hi:
                bad()
    return {k: value[k] for k in keys}


def v_id_list(body, name, size=None, required=True):
    if name not in body or body[name] is None:
        if required:
            bad()
        return None
    value = body[name]
    if not isinstance(value, list):
        bad()
    if size is not None and len(value) != size:
        bad()
    for item in value:
        if not isinstance(item, str) or item == "":
            bad()
    return value


def filter_value(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def filter_bool(name):
    value = request.args.get(name)
    if value is None:
        return None
    lowered = str(value).strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    return "__nomatch__"


def filter_int(name):
    value = request.args.get(name)
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return "__nomatch__"
