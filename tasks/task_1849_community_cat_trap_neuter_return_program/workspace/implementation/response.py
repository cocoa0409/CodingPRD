"""Standard response envelope helpers (SCAFFOLD.yaml §1.0 / PRD §2.2).

Success: {"meta": {"api_request_id", "api_request_timestamp", [pagination]},
          "response_type": "object" | "array", "data": ...}
Error:   {"meta": {"api_request_id", "api_request_timestamp"},
          "response_type": "error", "data": {"error_id", "message"}}

Pagination (PRD §2.3): query params limit (default 10, min 1, max 100) and
offset (default 0); list responses carry limit/offset/total_count/has_more in
meta. Out-of-range values are clamped into the allowed range.
"""

from datetime import datetime, timezone

from flask import jsonify, request

from util import new_req_id


def _meta():
    # api_request_timestamp is the server's wall-clock "when the request was
    # served" marker (3 fractional digits, Z); entity stamps use the logical
    # clock (see util.now_iso).
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    return {"api_request_id": new_req_id(), "api_request_timestamp": ts}


def success_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_array(items, total_count, limit, offset, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(error_id, http_status, message):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": error_id, "message": message}}
    return jsonify(body), http_status


def pagination_params():
    """Parse and clamp limit/offset per PRD §2.3."""
    raw_limit = request.args.get("limit")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = 10
        limit = max(1, min(100, limit))
    raw_offset = request.args.get("offset")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            offset = 0
        offset = max(0, offset)
    return limit, offset


def paginate(items):
    """Slice an already-sorted list and build the array envelope."""
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    return success_array(page, total, limit, offset)
