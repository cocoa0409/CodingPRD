"""Standard response envelope (PRD section 2.2, SCAFFOLD response_envelope)."""

import random
import string

from flask import jsonify

import db

REQUEST_ID_PREFIX = "req_"
REQUEST_ID_BODY_LENGTH = 20

PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0

_ALPHABET = string.ascii_uppercase + string.digits


def api_request_id():
    return REQUEST_ID_PREFIX + "".join(
        random.choice(_ALPHABET) for _ in range(REQUEST_ID_BODY_LENGTH)
    )


def _meta():
    return {
        "api_request_id": api_request_id(),
        "api_request_timestamp": db.now_iso(),
    }


PRIVATE_PREFIX = "_"


def public(record):
    """Strip internal bookkeeping keys before serialising a record."""
    if record is None:
        return None
    if isinstance(record, list):
        return [public(item) for item in record]
    return {k: v for k, v in record.items() if not k.startswith(PRIVATE_PREFIX)}


def object_response(record, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": public(record),
    }
    return jsonify(body), status


def list_response(records, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(records)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": public(list(records)),
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def paginate(records, limit, offset):
    total = len(records)
    window = records[offset : offset + limit]
    return window, total
