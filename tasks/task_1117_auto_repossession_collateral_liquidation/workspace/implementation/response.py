"""Standard response envelope (SCAFFOLD §1.0 / PRD §2.2)."""
import secrets
from datetime import datetime, timezone

from flask import jsonify

from util import fmt_dt


def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(12),
        "api_request_timestamp": fmt_dt(datetime.now(timezone.utc)),
    }


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def array_response(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = offset + limit < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def list_response(records, serializer):
    """Validate pagination params, slice, and wrap a list of serialized rows."""
    from util import pagination_params  # local import: flask request context

    limit, offset = pagination_params()
    total = len(records)
    page = records[offset:offset + limit]
    return array_response([serializer(r) for r in page], limit, offset, total)
