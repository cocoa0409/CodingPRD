"""Standard response envelope (PRD §2.2)."""

import random
import string

from flask import jsonify

from util import now_iso

_ALNUM = string.ascii_uppercase + string.digits


def _meta(extra=None):
    meta = {
        "api_request_id": "req_" + "".join(random.choice(_ALNUM) for _ in range(20)),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def obj(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def arr(items, limit, offset, total, status=200):
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(items)) < total,
    })
    return jsonify({"meta": meta, "response_type": "array", "data": items}), status


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
