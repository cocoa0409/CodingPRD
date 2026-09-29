"""Response envelope helpers."""
import random
import string

from flask import jsonify, request

import store
from errors import ApiError

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": store.now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(items, limit, offset, total_count):
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    })
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------- pagination
def pagination():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        limit = _int_param(limit_raw)
        if limit is None or limit < 1 or limit > 100:
            raise ApiError("ERR_PAGINATION_INVALID", "limit must be an integer in [1,100]")
    if offset_raw is not None:
        offset = _int_param(offset_raw)
        if offset is None or offset < 0:
            raise ApiError("ERR_PAGINATION_INVALID", "offset must be an integer >= 0")
    return limit, offset


def _int_param(raw):
    text = str(raw).strip()
    if text == "":
        return None
    try:
        return int(text)
    except ValueError:
        return None


def paginate(records, limit, offset):
    total = len(records)
    page = records[offset: offset + limit]
    return [store.public(r) for r in page], total


def list_response(records, filters=None):
    """Apply the default ordering, optional equality filters, and paginate."""
    limit, offset = pagination()
    rows = store.ordered(records)
    if filters:
        for field, value in filters.items():
            if value is not None:
                rows = [r for r in rows if r.get(field) == value]
    items, total = paginate(rows, limit, offset)
    return listing(items, limit, offset, total)
