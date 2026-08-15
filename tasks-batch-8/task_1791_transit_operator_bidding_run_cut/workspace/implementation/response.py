"""Standard response envelope helpers (PRD section 2.2)."""
import secrets
import string

from flask import jsonify

from db import now_iso


def _req_id():
    return "req_" + "".join(
        secrets.choice(string.ascii_letters + string.digits) for _ in range(20)
    )


def _meta():
    return {
        "api_request_id": _req_id(),
        "api_request_timestamp": now_iso(),
    }


def ok_obj(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def err(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
