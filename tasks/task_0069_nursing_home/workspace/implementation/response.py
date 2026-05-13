"""Response envelope builders.

Envelope (success):
  { "meta": { "api_request_id": ..., "api_request_timestamp": ... [, pagination] },
    "response_type": "object"|"array", "data": {...} }

Envelope (error):
  { "meta": {...}, "response_type": "error",
    "data": { "error_id": ..., "message": ... } }
"""
import secrets
import string
from flask import jsonify

from clock import iso_now


_ALPHABET = string.ascii_uppercase + string.digits


def _request_id():
    rnd = "".join(secrets.choice(_ALPHABET) for _ in range(20))
    return f"req_{rnd}"


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso_now(),
    }
    if extra:
        m.update(extra)
    return m


def success(data, status=200, pagination=None, is_list=False):
    envelope = {
        "meta": _meta(pagination),
        "response_type": "array" if is_list else "object",
        "data": data if data is not None else {},
    }
    resp = jsonify(envelope)
    resp.status_code = status
    return resp


def list_success(items, limit, offset, total_count, status=200):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + limit) < total_count,
    }
    return success(items, status=status, pagination=pagination, is_list=True)


def empty(status=204):
    envelope = {
        "meta": _meta(),
        "response_type": "object",
        "data": {},
    }
    resp = jsonify(envelope)
    resp.status_code = status
    return resp


def error(error_id, message, http_status):
    envelope = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    resp = jsonify(envelope)
    resp.status_code = http_status
    return resp
