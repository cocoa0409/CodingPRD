"""Standard response envelope helpers (PRD section 2.2)."""
import secrets
import string

from flask import jsonify

from db import wall_now_iso

_ALPHABET = string.ascii_letters + string.digits


def _meta():
    return {
        "api_request_id": "req_" + "".join(secrets.choice(_ALPHABET) for _ in range(20)),
        "api_request_timestamp": wall_now_iso(),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, total_count, limit, offset, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def err(error_id, status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
