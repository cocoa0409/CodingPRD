"""Response envelope helpers per SCAFFOLD §1.0 / PRD §2.2."""

import secrets
import string

from flask import jsonify

from db import now_iso_ms


def _req_id() -> str:
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def success_object(data, http_status=200):
    body = {
        "meta": {
            "api_request_id": _req_id(),
            "api_request_timestamp": now_iso_ms(),
        },
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), http_status


def success_list(items, limit, offset, total_count, http_status=200):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": {
            "api_request_id": _req_id(),
            "api_request_timestamp": now_iso_ms(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), http_status


def error_response(error_id, message, http_status):
    body = {
        "meta": {
            "api_request_id": _req_id(),
            "api_request_timestamp": now_iso_ms(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status


def parse_pagination(args):
    """Parse limit/offset per §2.3: default 10, min 1, max 100, offset default 0."""
    from errors import err_invalid_request

    raw_limit = args.get("limit", None)
    raw_offset = args.get("offset", None)
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_invalid_request("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_invalid_request("offset must be an integer")
        if offset < 0:
            raise err_invalid_request("offset must be >= 0")
    return limit, offset
