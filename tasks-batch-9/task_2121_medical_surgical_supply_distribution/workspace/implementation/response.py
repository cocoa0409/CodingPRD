"""Standard response envelope (PRD 2.2)."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify

from db import flush, serialize, iso_ms

_ALPHABET = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": iso_ms(datetime.now(timezone.utc)),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(entity, status=200):
    """Single-resource (or computed-projection) success envelope."""
    flush()
    data = entity if isinstance(entity, dict) and "_seq" not in entity else serialize(entity)
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_empty(status=200):
    flush()
    body = {"meta": _meta(), "response_type": "object", "data": {}}
    return jsonify(body), status


def ok_list(rows, limit, offset, total_count):
    flush()
    has_more = (offset + len(rows)) < total_count
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    })
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serialize(r) for r in rows],
    }
    return jsonify(body), 200


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
