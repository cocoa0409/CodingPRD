"""Standard response envelope helpers."""

import random
import string
from flask import jsonify

from util import iso_format
from db import clock


def _request_id():
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def _meta(include_pagination=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso_format(clock.now()),
    }
    if include_pagination:
        m.update(include_pagination)
    return m


def success(data, status_code=200, response_type="object", pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status_code


def error(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def list_success(items, total_count, limit, offset):
    has_more = (offset + len(items)) < total_count
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    return success(items, 200, "array", pagination)
