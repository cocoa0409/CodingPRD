"""Response envelope builders per SCAFFOLD §1.0 / PRD §2.2.

Success: {"meta": {api_request_id, api_request_timestamp[, limit, offset,
total_count, has_more]}, "response_type": "object"|"array", "data": ...}
Error:   {"meta": {api_request_id, api_request_timestamp},
          "response_type": "error", "data": {"error_id", "message"}}
"""
import json

from flask import Response

from util import new_request_id, request_timestamp


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": request_timestamp(),
    }


def _json_response(payload, status):
    return Response(
        json.dumps(payload, separators=(",", ":")),
        status=status,
        content_type="application/json",
    )


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return _json_response(body, status)


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta.update(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        }
    )
    body = {"meta": meta, "response_type": "array", "data": items}
    return _json_response(body, 200)


def error(error_id, status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _json_response(body, status)
