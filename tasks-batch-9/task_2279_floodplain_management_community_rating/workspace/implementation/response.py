"""Response envelope helpers (PRD 2.2 / 2.3)."""

import random
import string

from flask import jsonify

from db import iso_now, jsonable, public

_ALPHANUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso_now(),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(row, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": public(row) if isinstance(row, dict) else row,
    }
    return jsonify(body), status


def raw_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": jsonable(data)}
    return jsonify(body), status


def list_response(rows, limit, offset, total_count):
    page = [public(r) for r in rows]
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": offset + len(page) < total_count,
        }),
        "response_type": "array",
        "data": page,
    }
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
