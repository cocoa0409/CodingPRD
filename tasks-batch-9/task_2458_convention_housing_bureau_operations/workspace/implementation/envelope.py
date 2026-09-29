"""Response envelope helpers (PRD §2.2 / §2.3)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

from store import iso_ms

_ALNUM = string.ascii_uppercase + string.digits


def _api_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _api_request_id(),
        "api_request_timestamp": iso_ms(datetime.now(timezone.utc)),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(items, pagination):
    body = {"meta": _meta(pagination), "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset : offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, pagination
