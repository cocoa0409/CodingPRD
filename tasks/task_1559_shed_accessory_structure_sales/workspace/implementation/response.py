"""Response envelope helpers (SCAFFOLD response_envelope / PRD §2.2).

Success:
  { "meta": { "api_request_id": "req_...", "api_request_timestamp": "ISO8601" },
    "response_type": "object" | "array", "data": ... }
  List responses additionally carry limit/offset/total_count/has_more in meta.

Error:
  { "meta": { ... }, "response_type": "error",
    "data": { "error_id": "...", "message": "..." } }
"""

import random
import string
from flask import jsonify

import db


def _request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return f"req_{suffix}"


def _meta() -> dict:
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.now_iso(),
    }


def success_object(data, status: int = 200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def success_list(items, limit: int, offset: int, total_count: int, status: int = 200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_response(error_id: str, message: str, http_status: int):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
