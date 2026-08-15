"""Datetime parsing/formatting, payload extraction, pagination, field validators."""
from datetime import datetime, timezone

from flask import request

from errors import ApiError, ERR_INVALID_REQUEST


def parse_dt(value):
    """Parse an ISO8601 string (with Z, offset, or date-only) to aware UTC datetime."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        if s.endswith(("Z", "z")):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD §2.4)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def payload():
    """Extract the JSON object body. Malformed JSON -> ERR_INVALID_REQUEST."""
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "malformed JSON body")
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "JSON body must be an object")
    return data


def pagination():
    """limit (default 10, 1..100) and offset (default 0, >=0) per PRD §2.3."""
    raw_l = request.args.get("limit")
    raw_o = request.args.get("offset")
    if raw_l is None:
        limit = 10
    else:
        try:
            limit = int(raw_l)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "invalid limit")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit out of range")
    if raw_o is None:
        offset = 0
    else:
        try:
            offset = int(raw_o)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "invalid offset")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset out of range")
    return limit, offset


def list_page(rows, serializer):
    """Sort by created_at ASC (insertion order tiebreak), paginate, wrap."""
    from response import ok_list  # lazy: avoids response<->util import cycle
    limit, offset = pagination()
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    page = rows[offset:offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, total)


def req_str(p, name):
    v = p.get(name)
    if not isinstance(v, str) or not v.strip():
        raise ApiError(ERR_INVALID_REQUEST, 400, "missing or invalid %s" % name)
    return v


def req_int(p, name, lo=None, hi=None):
    v = p.get(name)
    if not isinstance(v, int) or isinstance(v, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "missing or invalid %s" % name)
    if lo is not None and v < lo:
        raise ApiError(ERR_INVALID_REQUEST, 400, "%s below minimum" % name)
    if hi is not None and v > hi:
        raise ApiError(ERR_INVALID_REQUEST, 400, "%s above maximum" % name)
    return v


def req_enum(p, name, allowed):
    v = p.get(name)
    if v not in allowed:
        raise ApiError(ERR_INVALID_REQUEST, 400, "missing or invalid %s" % name)
    return v


def req_dt(p, name):
    v = parse_dt(p.get(name))
    if v is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "missing or invalid %s" % name)
    return v


def opt_bool(p, name, default=True):
    v = p.get(name, default)
    if not isinstance(v, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "invalid %s" % name)
    return v


def enum_filter(name, allowed):
    v = request.args.get(name)
    if v is not None and v not in allowed:
        raise ApiError(ERR_INVALID_REQUEST, 400, "invalid %s filter" % name)
    return v


def bool_filter(name):
    v = request.args.get(name)
    if v is None:
        return None
    lv = v.lower()
    if lv == "true":
        return True
    if lv == "false":
        return False
    raise ApiError(ERR_INVALID_REQUEST, 400, "invalid %s filter" % name)


def get_or_404(table, rid):
    from errors import ERR_NOT_FOUND
    rec = table.get(rid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 404, "resource not found")
    return rec
