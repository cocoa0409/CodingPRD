"""The response envelope of PRD Section 2.2."""

from flask import jsonify

import db
import tx


def _meta(extra=None):
    meta = {
        "api_request_id": db.request_id(),
        "api_request_timestamp": db.now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    """Single-object success response.  Commits the request first so the
    serialised row carries its post-mutation version and updated_at."""
    tx.commit()
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": db.serialize(data) if isinstance(data, dict) else data,
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(rows, limit, offset, total_count):
    tx.commit()
    body = {
        "meta": _meta(
            {
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": offset + len(rows) < total_count,
            }
        ),
        "response_type": "array",
        "data": [db.serialize(r) for r in rows],
    }
    return jsonify(body), 200


def error(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
