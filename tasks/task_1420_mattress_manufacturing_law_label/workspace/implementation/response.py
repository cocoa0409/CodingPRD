"""Standard response envelope helpers (PRD section 2.2 / 2.3)."""
import random
import string

from flask import jsonify, request

import clock
import errors


def _request_id():
    rand = "".join(random.choices(string.ascii_uppercase + string.digits, k=18))
    return "req_" + rand


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.iso_fmt(clock.now()),
    }


def success_object(payload, status_code=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": payload,
    }
    return jsonify(body), status_code


def success_list(all_items, apply_pagination=True):
    items = list(all_items)
    total = len(items)
    if apply_pagination:
        limit_raw = request.args.get("limit")
        offset_raw = request.args.get("offset")
        limit = 10
        offset = 0
        if limit_raw is not None and limit_raw != "":
            try:
                limit = int(limit_raw)
            except (TypeError, ValueError):
                errors.raise_err(errors.ERR_VALIDATION_FAILED, "invalid limit")
            if limit < 1 or limit > 100:
                errors.raise_err(errors.ERR_VALIDATION_FAILED, "invalid limit")
        if offset_raw is not None and offset_raw != "":
            try:
                offset = int(offset_raw)
            except (TypeError, ValueError):
                errors.raise_err(errors.ERR_VALIDATION_FAILED, "invalid offset")
            if offset < 0:
                errors.raise_err(errors.ERR_VALIDATION_FAILED, "invalid offset")
    page = items[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + limit) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": page,
    }
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status
