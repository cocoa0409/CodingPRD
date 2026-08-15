"""Response envelope helpers — exact structure from scaffold response_envelope."""

import random
import string
from flask import jsonify
from db import store, iso_fmt


def _req_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _meta():
    return {
        "api_request_id": _req_id(),
        "api_request_timestamp": iso_fmt(store.now()),
    }


def success_obj(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
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
    return jsonify(body), 200


def error_resp(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status


def parse_pagination(args):
    """Parse limit/offset with defaults: limit default 10, min 1, max 100; offset default 0."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = 10
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            offset = 0
        if offset < 0:
            offset = 0
    return limit, offset
