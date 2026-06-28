"""Response envelope helpers (PRD §2.2, SCAFFOLD §1.0).

success: { meta:{api_request_id, api_request_timestamp[, pagination]},
           response_type:"object"|"array", data:{} }
error:   { meta:{...}, response_type:"error",
           data:{error_id, message} }
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify

import clock as clockmod


def _request_id():
    rnd = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + rnd


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": clockmod.format_iso_ms(datetime.now(timezone.utc)),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, status=201)


def listing(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": _meta(
            {
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": has_more,
            }
        ),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error(api_err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": api_err.error_id, "message": api_err.message},
    }
    return jsonify(body), api_err.http_status
