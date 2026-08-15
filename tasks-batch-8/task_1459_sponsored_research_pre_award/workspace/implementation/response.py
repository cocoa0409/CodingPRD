"""Standard response envelope helpers."""

from flask import jsonify

from errors import ApiError, bad_request
from utils import new_request_id, now_request_ts


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now_request_ts(),
    }


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def parse_pagination():
    """Validate and return (limit, offset) per the pagination spec."""
    args = request_args()
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise bad_request("Query parameter 'limit' must be an integer")
        if str(limit_raw).strip() not in (str(limit),):
            # reject things like '1.5'
            raise bad_request("Query parameter 'limit' must be an integer")
        if limit < 1 or limit > 100:
            raise bad_request("Query parameter 'limit' must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise bad_request("Query parameter 'offset' must be an integer")
        if str(offset_raw).strip() not in (str(offset),):
            raise bad_request("Query parameter 'offset' must be an integer")
        if offset < 0:
            raise bad_request("Query parameter 'offset' must be >= 0")
    return limit, offset


def request_args():
    from flask import request
    return request.args
