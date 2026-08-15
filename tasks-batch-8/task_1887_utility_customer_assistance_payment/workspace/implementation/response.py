"""Response envelope helpers (SCAFFOLD.yaml §1.0 / PRD §2.2, §2.3).

Success: { "meta": { api_request_id, api_request_timestamp[, limit, offset,
                     total_count, has_more] },
           "response_type": "object" | "array", "data": ... }
Error:   { "meta": { api_request_id, api_request_timestamp },
           "response_type": "error", "data": { error_id, message } }
"""

import uuid
from datetime import datetime, timezone

from flask import jsonify


def _meta():
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": ts,
    }


def success_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
