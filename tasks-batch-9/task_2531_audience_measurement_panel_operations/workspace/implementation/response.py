"""Response envelope helpers, list ordering and offset pagination."""
from flask import jsonify, request

from errors import ERROR_STATUS
from store import db, public
from util import bad_request, request_id, wall_now_iso

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": wall_now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def _payload(data):
    if isinstance(data, dict) and "_kind" in data:
        return public(data)
    if isinstance(data, list):
        return [public(item) if isinstance(item, dict) and "_kind" in item
                else item for item in data]
    return data


def ok(data, status=200):
    db.flush()
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": _payload(data),
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def error_body(error_id, message, status=None):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status or ERROR_STATUS.get(error_id, 422)


def read_pagination():
    args = request.args
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            raise bad_request("limit must be an integer")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise bad_request("limit must be between %d and %d"
                              % (LIMIT_MIN, LIMIT_MAX))
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            raise bad_request("offset must be an integer")
        if offset < 0:
            raise bad_request("offset must be zero or greater")
    return limit, offset


def order_rows(kind, rows):
    """Default ordering is created_at ASC; three collections override it."""
    if kind == "markets":
        rows = sorted(rows, key=lambda r: (r.get("market_code") or "", r["_seq"]))
        return sorted(rows, key=lambda r: r["created_at"], reverse=True)
    if kind == "tuning_intervals":
        return sorted(rows, key=lambda r: (r.get("start_iso") or "",
                                           r["created_at"], r["_seq"]))
    if kind == "processing_runs":
        return sorted(rows, key=lambda r: (r.get("window_start_iso") or "",
                                           r["created_at"], r["_seq"]))
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def listing(kind, rows):
    limit, offset = read_pagination()
    ordered = order_rows(kind, rows)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    db.flush()
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": offset + len(page) < total,
        }),
        "response_type": "array",
        "data": [public(row) for row in page],
    }
    return jsonify(body), 200


def apply_filters(rows, spec):
    """spec: {query_param: (row_field, kind)} where kind is str|bool|int."""
    args = request.args
    for param, (field, kind) in spec.items():
        if param not in args:
            continue
        raw = args.get(param)
        if kind == "bool":
            low = str(raw).strip().lower()
            if low in ("true", "1"):
                want = True
            elif low in ("false", "0"):
                want = False
            else:
                raise bad_request("%s must be a boolean" % param)
            rows = [r for r in rows if r.get(field) is want]
        elif kind == "int":
            try:
                want = int(str(raw).strip())
            except (TypeError, ValueError):
                raise bad_request("%s must be an integer" % param)
            rows = [r for r in rows if r.get(field) == want]
        else:
            rows = [r for r in rows if r.get(field) == raw]
    return rows
