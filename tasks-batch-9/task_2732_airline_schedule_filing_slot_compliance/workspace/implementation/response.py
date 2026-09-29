"""Standard response envelope of PRD section 2.2."""
from flask import jsonify

import db
from util import new_request_id, wall_now


def _meta(extra=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": wall_now(),
    }
    if extra:
        meta.update(extra)
    return meta


def envelope_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def envelope_array(rows, limit, offset, total_count, status=200):
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(rows) < total_count,
    })
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), status


def envelope_error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def ok(row, status=200):
    """Read path: serialise a single row without re-deriving anything."""
    db.flush()
    return envelope_object(db.public(row), status)


def raw(data, status=200):
    db.flush()
    return envelope_object(data, status)


def written(row, status=200):
    """Write path: re-derive the whole world, then serialise the target row."""
    import derive

    derive.recompute_all()
    db.flush()
    return envelope_object(db.public(row), status)


def written_raw(data_fn, status=200):
    """Write path for endpoints whose payload is not a single stored row."""
    import derive

    derive.recompute_all()
    db.flush()
    return envelope_object(data_fn(), status)


def listing(rows, limit, offset):
    total = len(rows)
    window = rows[offset:offset + limit]
    db.flush()
    return envelope_array([db.public(r) for r in window], limit, offset, total)
