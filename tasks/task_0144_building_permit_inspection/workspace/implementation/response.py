"""Response envelope helpers — emit exactly the structure the PRD §2.2 pins."""
from flask import jsonify

from store import db, fmt_ts, gen_request_id


def _meta(extra=None):
    m = {
        "api_request_id": gen_request_id(),
        "api_request_timestamp": fmt_ts(db.clock.now()),
    }
    if extra:
        m.update(extra)
    return m


def ok_object(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def ok_array(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": _meta(
            {
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": has_more,
            }
        ),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(error_id, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    from errors import ERROR_STATUS

    return jsonify(body), ERROR_STATUS[error_id]
