"""Response envelope helpers (PRD 2.2 / 2.9)."""
import json
import random
import string

from flask import Response

from store import now_iso, public_list, to_json

_ALPHANUM = string.ascii_uppercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": now_iso(),
    }


def _emit(body, status):
    return Response(
        json.dumps(body, default=to_json),
        status=status,
        mimetype="application/json",
    )


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": to_json(data) if data is not None else {},
    }
    return _emit(body, status)


def created(data):
    return ok(data, 201)


def ok_list(rows, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": public_list(rows),
    }
    return _emit(body, 200)


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _emit(body, status)
