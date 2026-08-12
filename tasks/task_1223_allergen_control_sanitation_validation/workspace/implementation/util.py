import json
from datetime import datetime, timezone

from flask import request

from errors import ApiError


def body():
    raw = request.get_data(cache=True)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Malformed JSON request body")
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return data


def _bad(field, msg="Invalid or missing field"):
    raise ApiError("ERR_INVALID_REQUEST", 400, f"{msg}: {field}")


def req_str(b, k):
    v = b.get(k)
    if not isinstance(v, str) or not v.strip():
        _bad(k)
    return v


def opt_str(b, k):
    v = b.get(k)
    if v is None:
        return None
    if not isinstance(v, str):
        _bad(k)
    return v


def opt_bool(b, k, default=None):
    v = b.get(k)
    if v is None:
        return default
    if not isinstance(v, bool):
        _bad(k)
    return v


def req_int(b, k, minv=None):
    v = b.get(k)
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(k)
    if minv is not None and v < minv:
        _bad(k)
    return v


def opt_int(b, k, default=None, minv=None):
    v = b.get(k)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(k)
    if minv is not None and v < minv:
        _bad(k)
    return v


def req_num(b, k):
    v = b.get(k)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad(k)
    return v


def req_list_str(b, k):
    v = b.get(k)
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        _bad(k)
    return list(v)


def opt_list_str(b, k):
    v = b.get(k)
    if v is None:
        return None
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        _bad(k)
    return list(v)


def req_enum(b, k, allowed):
    v = b.get(k)
    if not isinstance(v, str) or v not in allowed:
        _bad(k, "Invalid value for field")
    return v


def parse_dt(s):
    if not isinstance(s, str):
        _bad("datetime")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(t)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Invalid ISO8601 datetime: {s}")
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def req_dt_str(b, k):
    v = req_str(b, k)
    parse_dt(v)
    return v


def fmt_dt(d):
    return d.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def pagination_params():
    raw_l = request.args.get("limit")
    if raw_l is None:
        limit = 10
    else:
        try:
            limit = int(raw_l)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    raw_o = request.args.get("offset")
    if raw_o is None:
        offset = 0
    else:
        try:
            offset = int(raw_o)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    return limit, offset


def query_bool(name):
    v = request.args.get(name)
    if v is None:
        return None
    if v.lower() == "true":
        return True
    if v.lower() == "false":
        return False
    raise ApiError("ERR_INVALID_REQUEST", 400, f"Invalid boolean query parameter: {name}")
