"""Response envelope helpers (PRD §2.2, §2.3)."""
import random
import string

from flask import jsonify

from db import store


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": store.now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def public(rec):
    """Strip internal-only fields (those prefixed with _) before serialization."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def ok_object(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": public(data) if isinstance(data, dict) else (data or {}),
    }
    return jsonify(body), status


def ok_empty(status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": {},
    }
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        }),
        "response_type": "array",
        "data": [public(i) for i in items],
    }
    return jsonify(body), 200


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
