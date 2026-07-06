"""Standard response envelope helpers (PRD §2.2 / SCAFFOLD response_envelope).

Success envelope (verbatim field names from the scaffold):
  { "meta": {api_request_id, api_request_timestamp [, limit, offset,
              total_count, has_more]},
    "response_type": "object" | "array",
    "data": {...} | [...] }

Error envelope:
  { "meta": {api_request_id, api_request_timestamp},
    "response_type": "error",
    "data": {"error_id": "...", "message": "..."} }
"""
from flask import jsonify
from util import request_id, request_timestamp


def _meta(extra=None):
    m = {
        "api_request_id": request_id(),
        "api_request_timestamp": request_timestamp(),
    }
    if extra:
        m.update(extra)
    return m


def success(data, status=200, response_type="object", pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def object_response(data, status=200):
    return success(data, status=status, response_type="object")


def array_response(items, limit, offset, total_count):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return success(items, status=200, response_type="array", pagination=pagination)


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
