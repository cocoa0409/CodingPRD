"""Response envelope helpers per PRD section 2.2 / 2.3."""
import secrets

from flask import jsonify

import db


def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(12),
        "api_request_timestamp": db.now_iso(),
    }


def success_obj(data, code=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), code


def success_list(items, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_resp(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status
