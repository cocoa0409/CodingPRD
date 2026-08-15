"""Standard response envelope helpers (PRD §2.2 / scaffold §1.0)."""

import json

from flask import Response

from util import new_request_id, wall_now_iso


def _json(body, status):
    return Response(
        json.dumps(body),
        status=status,
        mimetype="application/json",
    )


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": wall_now_iso(),
    }


def object_response(data, status=200):
    return _json({
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }, status)


def list_response(items, total_count, limit, offset, extra_meta=None):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    if extra_meta:
        meta.update(extra_meta)
    return _json({
        "meta": meta,
        "response_type": "array",
        "data": items,
    }, 200)


def error_response(error_id, message, status):
    return _json({
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }, status)
