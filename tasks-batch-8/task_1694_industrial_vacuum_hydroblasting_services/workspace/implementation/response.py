"""Standard response envelope helpers (PRD section 2.2)."""

import uuid

from flask import jsonify

from util import fmt_ts, now, serialize


def _meta(pagination=None):
    meta = {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": fmt_ts(now()),
    }
    if pagination is not None:
        limit, offset, total_count = pagination
        meta["limit"] = limit
        meta["offset"] = offset
        meta["total_count"] = total_count
        meta["has_more"] = (offset + limit) < total_count
    return meta


def success(data, status=200, pagination=None, response_type="object"):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": serialize(data),
    }
    return jsonify(body), status


def success_object(data, status=200):
    return success(data, status=status, response_type="object")


def success_list(items, limit, offset, total_count):
    return success(
        items,
        status=200,
        pagination=(limit, offset, total_count),
        response_type="array",
    )


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
