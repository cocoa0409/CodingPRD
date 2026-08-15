"""Standard response envelope helpers (PRD section 2.2 / 2.3)."""
import secrets
import string

from flask import jsonify

from db import now_iso

_ALPHABET = string.ascii_letters + string.digits


def _meta():
    return {
        "api_request_id": "req_" + "".join(secrets.choice(_ALPHABET) for _ in range(20)),
        "api_request_timestamp": now_iso(),
    }


def success_object(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(api_error):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": api_error.error_id,
            "message": api_error.message,
        },
    }
    return jsonify(body), api_error.http_status
