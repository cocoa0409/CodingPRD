"""Response envelope helpers (SCAFFOLD.yaml §1.0 / PRD §2.2, §2.3).

Success: {"meta": {"api_request_id": "req_...", "api_request_timestamp": iso},
          "response_type": "object"|"array", "data": ...}
List responses additionally carry limit/offset/total_count/has_more in meta.
Error:   {"meta": {...}, "response_type": "error",
          "data": {"error_id": ..., "message": ...}}
"""

import secrets

from flask import jsonify

from logical_clock import CLOCK

# Pagination (SCAFFOLD §1.0 pagination_fields / pagination_defaults)
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(10),
        "api_request_timestamp": CLOCK.now_iso(),
    }


def success_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(api_err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": api_err.error_id, "message": api_err.message},
    }
    return jsonify(body), api_err.http_status
