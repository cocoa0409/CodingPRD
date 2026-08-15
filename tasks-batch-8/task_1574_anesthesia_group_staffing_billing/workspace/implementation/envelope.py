"""Standard response envelope per PRD 2.2 / SCAFFOLD response_envelope."""
import uuid
from flask import jsonify
from store import now_iso


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": now_iso(),
    }


def ok(data, code=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), code


def ok_list(items, limit, offset, total):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = offset + len(items) < total
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def err(error_id, status, message):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }), status
