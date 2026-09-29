"""Response envelope helpers (SCAFFOLD §1.0 / PRD §2.2)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from errors import ApiError
from util import is_int

_ALPHABET = string.ascii_uppercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(20))


def _timestamp():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": _timestamp()}


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def _parse_page_int(raw, default, minimum, maximum):
    if raw is None:
        return default
    text = raw.strip()
    if text == "":
        raise ApiError("ERR_INVALID_REQUEST")
    try:
        value = int(text, 10)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST")
    if value < minimum:
        raise ApiError("ERR_INVALID_REQUEST")
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST")
    return value


def pagination():
    limit = _parse_page_int(
        request.args.get("limit"),
        PAGINATION_DEFAULT_LIMIT,
        PAGINATION_MIN_LIMIT,
        PAGINATION_MAX_LIMIT,
    )
    offset = _parse_page_int(
        request.args.get("offset"), PAGINATION_DEFAULT_OFFSET, 0, None
    )
    return limit, offset


def paginate(rows, serializer):
    limit, offset = pagination()
    total = len(rows)
    window = rows[offset:offset + limit]
    return ok_list([serializer(r) for r in window], limit, offset, total)


__all__ = [
    "ok",
    "ok_list",
    "error_response",
    "pagination",
    "paginate",
    "is_int",
]
