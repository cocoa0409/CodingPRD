"""Standard success / error response envelope (PRD §2.2) and pagination (§2.3)."""
import json
import random
import string

from flask import Response

from store import iso, store

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(store.now()),
    }


def _emit(payload, status):
    return Response(
        json.dumps(payload, allow_nan=False),
        status=status,
        mimetype="application/json",
    )


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return _emit(body, status)


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return _emit(body, 200)


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _emit(body, status)


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
