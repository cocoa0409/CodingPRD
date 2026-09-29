"""Response envelope helpers (PRD 2.2 / scaffold response_envelope)."""

import random
import string

from flask import jsonify

import db
from util import fmt_ts

_ALPHABET = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_ts(db.now()),
    }


def ok(data, status=200):
    payload = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(payload), status


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    payload = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(payload), 200


def error(error_id, message, status):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(payload), status


def page(rows, serializer):
    from util import paging

    limit, offset = paging()
    total = len(rows)
    window = rows[offset:offset + limit]
    return ok_list([serializer(r) for r in window], limit, offset, total)
