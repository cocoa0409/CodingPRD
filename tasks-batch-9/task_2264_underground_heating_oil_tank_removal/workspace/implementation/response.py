"""Standard response envelope — PRD §2.2 / SCAFFOLD §1.0."""

import random
import string

from flask import jsonify

from db import commit, db, iso, serialize, sort_rows

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(db.now()),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def entity_response(entity, status=200):
    # Flush pending audit bookkeeping first so the body carries the post-mutation
    # version / updated_at rather than the values the row had mid-request.
    commit()
    return object_response(serialize(entity), status)


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def list_response(rows, limit, offset):
    """Paginated array envelope: limit/offset/total_count/has_more live in meta."""
    commit()
    ordered = sort_rows(rows)
    total = len(ordered)
    window = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }
    body = {
        "meta": _meta(meta),
        "response_type": "array",
        "data": [serialize(row) for row in window],
    }
    return jsonify(body), 200
