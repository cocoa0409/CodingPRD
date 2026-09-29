"""Response envelope helpers (PRD 2.2, 2.3)."""

import random
import string

from flask import jsonify

from db import iso_now

_ALPHABET = string.ascii_uppercase + string.digits


def _meta():
    return {
        "api_request_id": "req_" + "".join(random.choice(_ALPHABET) for _ in range(20)),
        "api_request_timestamp": iso_now(),
    }


def strip_private(value):
    if isinstance(value, dict):
        return dict(
            (k, strip_private(v)) for k, v in value.items() if not str(k).startswith("_")
        )
    if isinstance(value, list):
        return [strip_private(v) for v in value]
    return value


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": strip_private(data if data is not None else {}),
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(records, limit, offset):
    total = len(records)
    page = records[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [strip_private(r) for r in page],
    }
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
