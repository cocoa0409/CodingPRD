"""Response envelope helpers, per scaffold response_envelope / PRD §2.2.

Success: {"meta": {api_request_id, api_request_timestamp}, "response_type": "object"|"array", "data": ...}
List success adds limit/offset/total_count/has_more to meta.
Error:   {"meta": {api_request_id, api_request_timestamp}, "response_type": "error",
          "data": {"error_id": ..., "message": ...}}
"""
import uuid
from flask import jsonify, request

from db import iso, now
from errors import ApiError, invalid_request


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": iso(now()),
    }


def ok_obj(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    resp = jsonify(body)
    resp.status_code = code
    return resp


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    resp = jsonify(body)
    resp.status_code = 200
    return resp


def err_response(err: ApiError):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    resp = jsonify(body)
    resp.status_code = err.http_status
    return resp


def get_body():
    """Return the JSON request body as a dict; {} when absent."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise invalid_request("Request body must be a JSON object")
    return data


def pagination_params():
    """Parse limit/offset query params (defaults 10/0, limit in 1..100)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise invalid_request("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid_request("offset must be an integer")
        if offset < 0:
            raise invalid_request("offset must be >= 0")
    return limit, offset


def list_response(records, serializer):
    """Sort by created_at ascending (seq tiebreak), paginate, wrap in envelope."""
    limit, offset = pagination_params()
    ordered = sorted(records, key=lambda r: (r.created_dt, r.seq))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, total)
