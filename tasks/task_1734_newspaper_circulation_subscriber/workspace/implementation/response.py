"""Standard response envelope helpers (scaffold response_envelope, PRD 2.2/2.3).

success: { meta: {api_request_id, api_request_timestamp[, limit, offset,
                  total_count, has_more]},
           response_type: "object" | "array", data: ... }
error:   { meta: {api_request_id, api_request_timestamp},
           response_type: "error", data: {error_id, message} }
"""
import secrets
import string
from datetime import datetime, timezone

from flask import jsonify, request

from errors import ApiError

_ALPHABET = string.ascii_letters + string.digits


def _wall_now_iso():
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def _meta():
    return {
        "api_request_id": "req_" + "".join(secrets.choice(_ALPHABET) for _ in range(20)),
        "api_request_timestamp": _wall_now_iso(),
    }


def ok_obj(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = offset + len(items) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def err(error_id, status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def pagination_args():
    """limit defaults to 10, must be >= 1 and <= 100; offset defaults to 0."""
    limit, offset = 10, 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    return limit, offset


def paginate(records, serializer):
    """records pre-sorted; returns an envelope list response."""
    limit, offset = pagination_args()
    total = len(records)
    page = records[offset:offset + limit]
    return ok_list([serializer(r) for r in page], total, limit, offset)
