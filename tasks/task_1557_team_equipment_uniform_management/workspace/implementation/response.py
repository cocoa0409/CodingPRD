"""Standard response envelope (PRD §2.2 / SCAFFOLD.yaml response_envelope)."""
from flask import jsonify

from util import fmt_meta_ts, new_request_id


def _meta(pagination=None):
    m = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_meta_ts(),
    }
    if pagination:
        m.update(pagination)
    return m


def success(data, status=200, response_type="object", pagination=None):
    body = {"meta": _meta(pagination), "response_type": response_type, "data": data}
    return jsonify(body), status


def success_list(items, total_count, limit, offset):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(items) < total_count,
    }
    return success(items, 200, "array", pagination)


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
