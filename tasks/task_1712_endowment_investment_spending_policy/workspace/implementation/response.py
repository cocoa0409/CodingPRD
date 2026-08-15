from flask import jsonify

from util import now_iso, new_request_id


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now_iso(),
    }


def success(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def success_array(items, status=200):
    """Array success envelope without pagination fields (e.g. bulk_upsert)."""
    body = {"meta": _meta(), "response_type": "array", "data": items}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def success_list(items, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp
