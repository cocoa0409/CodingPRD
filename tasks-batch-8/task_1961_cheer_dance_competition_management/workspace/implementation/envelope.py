"""Response envelope + serialization helpers (PRD §2.2 / §2.3)."""
import random
import string
from datetime import date, datetime
from decimal import Decimal

from flask import jsonify, request

from store import now_iso


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def ser_val(v):
    if isinstance(v, datetime):
        from store import iso
        return iso(v)
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, list):
        return [ser_val(x) for x in v]
    if isinstance(v, dict):
        return {k: ser_val(x) for k, x in v.items()}
    return v


def serialize(rec):
    """Serialize one record: drop internal keys, convert datetime/Decimal."""
    if rec is None:
        return {}
    return {k: ser_val(v) for k, v in rec.items() if not k.startswith("_")}


def ok(data, code=200, pagination=None):
    meta = {"api_request_id": _request_id(), "api_request_timestamp": now_iso()}
    if pagination is not None:
        meta.update(pagination)
    if isinstance(data, list):
        payload = [serialize(item) for item in data]
        response_type = "array"
    else:
        payload = serialize(data) if isinstance(data, dict) and "_seq" in data else data
        response_type = "object"
    body = {"meta": meta, "response_type": response_type, "data": payload}
    return jsonify(body), code


def error_response(error_id, http_status, message):
    body = {
        "meta": {"api_request_id": _request_id(),
                 "api_request_timestamp": now_iso()},
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def paginate(items):
    """Apply limit/offset per PRD §2.3 (default 10/0, limit clamped 1..100)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta


def ok_list(items, code=200):
    page, meta = paginate(items)
    return ok(page, code=code, pagination=meta)
