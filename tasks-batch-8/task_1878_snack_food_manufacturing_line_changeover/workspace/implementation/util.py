import secrets
from datetime import datetime, timezone, date
from decimal import Decimal, ROUND_HALF_UP

from flask import request, jsonify

from errors import ApiError


# ---------- Decimal / rounding ----------

def D(x):
    """Exact Decimal from an int/float/str (never via binary float artifacts)."""
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def rhu(x: Decimal, places: int) -> Decimal:
    """Round-half-up to the given number of decimal places."""
    q = Decimal(1).scaleb(-places)
    return x.quantize(q, rounding=ROUND_HALF_UP)


def rhu_int(x: Decimal) -> int:
    return int(rhu(x, 0))


def num(x):
    """Serialize a stored numeric as a clean JSON number."""
    if isinstance(x, Decimal):
        if x == x.to_integral_value():
            return int(x)
        return float(x)
    return x


# ---------- Time ----------

def iso(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    return date.fromisoformat(s)


# ---------- Request body / type validators ----------

def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def is_intlike(x):
    return (isinstance(x, int) and not isinstance(x, bool)) or (
        isinstance(x, float) and float(x).is_integer()
    )


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", 400, f"missing or invalid field: {field}")
    return v


def req_num(data, field, gt=None, ge=None):
    v = data.get(field)
    if not is_number(v):
        raise ApiError("ERR_VALIDATION", 400, f"missing or invalid field: {field}")
    d = D(v)
    if gt is not None and not (d > D(gt)):
        raise ApiError("ERR_VALIDATION", 400, f"field out of range: {field}")
    if ge is not None and d < D(ge):
        raise ApiError("ERR_VALIDATION", 400, f"field out of range: {field}")
    return d


def opt_num(data, field, gt=None, ge=None, default=None):
    if field not in data or data.get(field) is None:
        return default
    return req_num(data, field, gt=gt, ge=ge)


def req_int(data, field, gt=None, ge=None):
    v = data.get(field)
    if not is_intlike(v):
        raise ApiError("ERR_VALIDATION", 400, f"missing or invalid field: {field}")
    iv = int(v)
    if gt is not None and not (iv > gt):
        raise ApiError("ERR_VALIDATION", 400, f"field out of range: {field}")
    if ge is not None and iv < ge:
        raise ApiError("ERR_VALIDATION", 400, f"field out of range: {field}")
    return iv


def opt_int(data, field, gt=None, ge=None, default=None):
    if field not in data or data.get(field) is None:
        return default
    return req_int(data, field, gt=gt, ge=ge)


def req_enum(data, field, allowed):
    v = data.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise ApiError("ERR_VALIDATION", 400, f"missing or invalid field: {field}")
    return v


def opt_bool(data, field, default=False):
    if field not in data or data.get(field) is None:
        return default
    v = data.get(field)
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", 400, f"invalid field: {field}")
    return v


# ---------- Envelope ----------

def req_meta(store):
    return {
        "api_request_id": "req_" + secrets.token_hex(8),
        "api_request_timestamp": iso(store.clock),
    }


def ok(store, data, status=200, response_type="object", pagination=None):
    meta = req_meta(store)
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    body = {"meta": meta, "response_type": response_type, "data": data}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def err_response(store, e: ApiError):
    body = {
        "meta": req_meta(store),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    resp = jsonify(body)
    resp.status_code = e.http_status
    return resp


def paginate(items):
    """items: full list, already sorted by (created_at, seq) ascending."""
    args = request.args
    raw_limit = args.get("limit", "10")
    raw_offset = args.get("offset", "0")
    try:
        limit = int(raw_limit)
        offset = int(raw_offset)
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", 400, "invalid pagination parameters")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta
