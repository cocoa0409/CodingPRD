"""Uniform response envelope (PRD section 2.1 / 2.4)."""
import random
import string

from flask import jsonify

from store import db
from util import iso

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": iso(db.now()),
    }


def object_response(data, status=200, meta=None):
    body = {
        "meta": base_meta(),
        "response_type": "object",
        "data": data,
    }
    if meta:
        body["meta"].update(meta)
    return jsonify(body), status


def array_response(rows, limit=None, offset=None, total_count=None, status=200, meta=None):
    envelope_meta = base_meta()
    if total_count is not None:
        envelope_meta["limit"] = limit
        envelope_meta["offset"] = offset
        envelope_meta["total_count"] = total_count
        envelope_meta["has_more"] = (offset + len(rows)) < total_count
    if meta:
        envelope_meta.update(meta)
    body = {
        "meta": envelope_meta,
        "response_type": "array",
        "data": rows,
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status


def paginate(rows, limit, offset):
    """Slice an already ordered list and return (page, total_count)."""
    total = len(rows)
    return rows[offset:offset + limit], total
