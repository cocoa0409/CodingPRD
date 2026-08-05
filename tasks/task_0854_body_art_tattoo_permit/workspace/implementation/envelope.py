"""Response envelope helpers — PRD §2.2 / SCAFFOLD response_envelope."""

from flask import g, jsonify

import store
from util import new_request_id, render_ts


def _meta(extra=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": render_ts(store.now()),
    }
    if extra:
        meta.update(extra)
    return meta


def tracker():
    if not hasattr(g, "tracker"):
        g.tracker = store.Tracker()
    return g.tracker


def watch(rec):
    return tracker().watch(rec)


def force(rec):
    return tracker().force(rec)


def mark_new(rec):
    return tracker().mark_new(rec)


def commit():
    # updated_at is stored as a datetime; util.render_ts formats it on the way out.
    tracker().commit(store.now())


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def array_response(rows, limit, offset, total_count):
    meta = _meta(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(rows)) < total_count,
        }
    )
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def send(data, status=200):
    """Commit pending version bumps, then serialise."""
    commit()
    return object_response(data() if callable(data) else data, status)
