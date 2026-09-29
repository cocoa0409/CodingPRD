"""Response envelope helpers (PRD section 2.2)."""

import random
import string

from flask import jsonify

from db import wall_now

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": wall_now(),
    }


def public(row):
    """Strip private bookkeeping keys (prefixed with '_') from a stored row."""
    if isinstance(row, list):
        return [public(r) for r in row]
    if not isinstance(row, dict):
        return row
    return {k: v for k, v in row.items() if not k.startswith("_")}


def ok(data, status=200):
    return (
        jsonify({"meta": base_meta(), "response_type": "object", "data": public(data)}),
        status,
    )


def created(data):
    return ok(data, 201)


def ok_list(rows, total_count, limit, offset):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    return (
        jsonify({"meta": meta, "response_type": "array", "data": public(rows)}),
        200,
    )


def error_body(error_id, message):
    return {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
