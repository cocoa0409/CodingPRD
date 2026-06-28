"""Standard response envelope (PRD 2.2 / scaffold §1.0)."""
import random
import string

from flask import jsonify

import db


def _meta(extra=None):
    rid = "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))
    m = {"api_request_id": rid, "api_request_timestamp": db.now_iso()}
    if extra:
        m.update(extra)
    return m


# Internal bookkeeping keys that must never leak into API payloads.
_HIDDEN = ("_seq",)


def _clean(obj):
    if isinstance(obj, dict):
        return {k: v for k, v in obj.items() if k not in _HIDDEN}
    return obj


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": _clean(data) if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, status=201)


def listing(rows, limit, offset, total_count):
    has_more = (offset + len(rows)) < total_count
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        }),
        "response_type": "array",
        "data": [_clean(r) for r in rows],
    }
    return jsonify(body), 200


def error(api_error):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": api_error.error_id, "message": api_error.message},
    }
    return jsonify(body), api_error.http_status
