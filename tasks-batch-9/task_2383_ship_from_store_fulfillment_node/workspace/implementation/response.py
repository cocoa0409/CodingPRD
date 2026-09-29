"""Response envelope helpers (PRD 2.2)."""
import random
import string
from datetime import datetime

from flask import jsonify

import clock
from util import iso

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(pagination=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": iso(clock.now()),
    }
    if pagination:
        meta.update(pagination)
    return meta


def serialize(row):
    """Public projection of a stored row: private keys dropped, datetimes ISO'd."""
    if row is None:
        return None
    out = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        if isinstance(value, datetime):
            out[key] = iso(value)
        elif isinstance(value, list):
            out[key] = list(value)
        else:
            out[key] = value
    return out


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def array_response(items, status=200, pagination=None):
    body = {"meta": _meta(pagination), "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def paged_response(rows, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit]
    items = [serialize(r) for r in page]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return array_response(items, 200, pagination)
