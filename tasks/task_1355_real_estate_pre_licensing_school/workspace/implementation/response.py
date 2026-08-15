"""Standard response envelope helpers."""

import uuid
from datetime import datetime, timezone
from flask import jsonify


def _req_meta():
    rid = "req_" + uuid.uuid4().hex[:24]
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    return {"api_request_id": rid, "api_request_timestamp": ts}


def success_object(data, status=200):
    body = {
        "meta": _req_meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count, status=200):
    has_more = (offset + len(items)) < total_count
    meta = _req_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = has_more
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status
