"""Standard response envelope helpers (PRD §2.2).

Success:
  { "meta": { "api_request_id": "req_...", "api_request_timestamp": "..." },
    "response_type": "object" | "array", "data": ... }
  List responses additionally carry limit/offset/total_count/has_more in meta.

Error:
  { "meta": { "api_request_id": "...", "api_request_timestamp": "..." },
    "response_type": "error",
    "data": { "error_id": "...", "message": "..." } }
"""
import random
import string

from flask import jsonify

from clock import now_iso


def _request_id() -> str:
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alphabet, k=20))


def success_object(data, status_code: int = 200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": now_iso(),
        },
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status_code


def success_list(items, limit: int, offset: int, total_count: int, status_code: int = 200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": now_iso(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status_code


def error_response(error_id: str, http_status: int, message: str):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": now_iso(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
