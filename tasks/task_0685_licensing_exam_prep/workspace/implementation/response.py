"""Standard response envelope helpers (PRD §2.2). Field names per scaffold §1.0:
meta{api_request_id, api_request_timestamp[, pagination]}, response_type, data."""
import random
import string
from flask import jsonify

from db import _wall_now_iso

_ALNUM = string.ascii_letters + string.digits


def _request_id():
    return "req_" + "".join(random.choices(_ALNUM, k=20))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _wall_now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def success(data, status=200, response_type="object"):
    body = {
        "meta": _meta(),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def list_success(items, limit, offset, total_count, has_more, status=200):
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
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
