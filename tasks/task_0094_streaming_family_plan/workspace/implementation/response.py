"""Standard response envelope helpers (PRD §2.2).

Success (object/array) and error bodies all share the meta wrapper carrying
api_request_id (req_ prefix) and api_request_timestamp (ISO 8601 UTC, three
fractional digits). List responses add limit/offset/total_count/has_more into
meta (PRD §2.3).
"""
import secrets
import string

from flask import jsonify

from db import utc_now_iso


def _gen_request_id() -> str:
    alphabet = string.ascii_uppercase + string.ascii_lowercase + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _base_meta() -> dict:
    # api_request_timestamp is the real server time the response was produced.
    return {
        "api_request_id": _gen_request_id(),
        "api_request_timestamp": utc_now_iso(),
    }


def success_object(data, http_status: int = 200):
    body = {
        "meta": _base_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), http_status


def success_array(items: list, limit: int, offset: int, total_count: int,
                  http_status: int = 200):
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), http_status


def error_response(error_id: str, message: str, http_status: int):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
