"""Response envelope helpers."""

import random
import string
from datetime import datetime, timezone
from flask import jsonify

from db import DB


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=22))


def _meta(extra=None):
    # api_request_timestamp is server wall-clock (a real "when the request was
    # served" timestamp); PRD example shows 3 fractional digits.
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S") + f".{now.microsecond // 1000:03d}Z"
    m = {"api_request_id": _request_id(), "api_request_timestamp": ts}
    if extra:
        m.update(extra)
    return m


def success_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, limit, offset, total_count, status=200):
    has_more = (offset + len(items)) < total_count
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    })
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
