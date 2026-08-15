"""Standard response envelope helpers (SCAFFOLD response_envelope)."""
import random
import string

from flask import jsonify, request

from db import wall_now_iso
from errors import ApiError, bad_request


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=24))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": wall_now_iso(),
    }


def ok_obj(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    resp = jsonify(body)
    resp.status_code = code
    return resp


def parse_pagination():
    args = request.args
    raw_limit = args.get("limit", None)
    raw_offset = args.get("offset", None)
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise bad_request("Invalid limit")
        if limit < 1 or limit > 100:
            raise bad_request("limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise bad_request("Invalid offset")
        if offset < 0:
            raise bad_request("offset must be >= 0")
    return limit, offset


def ok_list(items, code=200):
    """items: full filtered list, already sorted by created_at asc."""
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    body = {"meta": meta, "response_type": "array", "data": page}
    resp = jsonify(body)
    resp.status_code = code
    return resp


def error_response(err):
    if isinstance(err, ApiError):
        body = {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": err.error_id, "message": err.message},
        }
        resp = jsonify(body)
        resp.status_code = err.http_status
        return resp
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INTERNAL", "message": str(err)},
    }
    resp = jsonify(body)
    resp.status_code = 500
    return resp
