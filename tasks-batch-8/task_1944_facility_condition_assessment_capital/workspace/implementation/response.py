"""Standard response envelope (PRD section 2.2 / scaffold response_envelope)."""

from flask import jsonify

from util import now_iso, request_id


def _meta(pagination=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": now_iso(),
    }
    if pagination:
        meta.update(pagination)
    return meta


def ok_object(data, status=200):
    return (
        jsonify({"meta": _meta(), "response_type": "object", "data": data}),
        status,
    )


def ok_list(items, limit, offset, total_count):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return (
        jsonify(
            {
                "meta": _meta(pagination),
                "response_type": "array",
                "data": items,
            }
        ),
        200,
    )


def err(error_id, message, status):
    return (
        jsonify(
            {
                "meta": _meta(),
                "response_type": "error",
                "data": {"error_id": error_id, "message": message},
            }
        ),
        status,
    )
