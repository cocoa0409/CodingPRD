"""Standard response envelope helpers (PRD section 2.2 / 2.3)."""

import secrets

from flask import jsonify

from db import wall_now
from helpers import fmt_ts, pagination_params


def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(12),
        "api_request_timestamp": fmt_ts(wall_now()),
    }


def success_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def success_list(records, serializer):
    """Serialize a filtered record list with offset pagination."""
    limit, offset = pagination_params()
    total = len(records)
    page = records[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    body = {"meta": meta, "response_type": "array", "data": [serializer(r) for r in page]}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status
