"""Response envelope helpers (PRD section 2.2 / 2.3)."""

import random
import string

from flask import jsonify

from db import wall_now_iso

_ALPHABET = string.ascii_lowercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(24))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": wall_now_iso(),
    }


def object_response(data, http_status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), http_status


def list_response(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": rows,
    }
    return jsonify(body), 200


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
