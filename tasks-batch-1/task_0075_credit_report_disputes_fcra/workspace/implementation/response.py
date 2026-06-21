from datetime import datetime, timezone

from flask import jsonify

from util import new_request_id, iso_now


def _meta(extra=None):
    m = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso_now(datetime.now(timezone.utc)),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, response_type="object", pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def ok_list(items, limit, offset, total_count, status=200):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return ok(items, status=status, response_type="array", pagination=pagination)


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp
