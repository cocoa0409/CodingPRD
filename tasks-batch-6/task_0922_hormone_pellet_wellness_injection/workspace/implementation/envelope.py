"""The response envelope of PRD 2.2 and the pagination block of PRD 2.3."""
from flask import jsonify

import store
import util


def _meta():
    return {
        "api_request_id": util.new_request_id(),
        "api_request_timestamp": util.fmt_dt(store.now()),
    }


def ok(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_array(items, code=200, pagination=None):
    meta = _meta()
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), code


def fail(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def paginate(rows, limit, offset):
    """Window a filtered, ordered row list and describe the window."""
    total = len(rows)
    window = rows[offset: offset + limit]
    block = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }
    return window, block
