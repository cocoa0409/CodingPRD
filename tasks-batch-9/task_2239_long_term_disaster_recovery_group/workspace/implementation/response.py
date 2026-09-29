"""Response envelope helpers (PRD 2.2 / 2.3)."""

import random
import string

from flask import jsonify

import db

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.stamp_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(record, status=200):
    """Single-resource success envelope. Flushes pending version bumps first."""
    db.flush()
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": db.public(record) if record is not None else {},
    }
    return jsonify(body), status


def list_response(records, limit, offset, total_count, status=200):
    db.flush()
    body = {
        "meta": _meta(
            {
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": offset + len(records) < total_count,
            }
        ),
        "response_type": "array",
        "data": [db.public(r) for r in records],
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
    """Apply the offset window; returns (page, total_count)."""
    total = len(records)
    return records[offset : offset + limit], total
