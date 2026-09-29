"""Standard response envelope helpers (PRD 2.2)."""

import random
import string

from flask import jsonify

import store

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def fmt_instant(value):
    """ISO 8601 UTC with exactly three fractional digits."""
    if value is None:
        return None
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (value.microsecond // 1000)


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_instant(store.now()),
    }
    if extra:
        meta.update(extra)
    return meta


def envelope(data, response_type, meta_extra=None):
    return {
        "meta": _meta(meta_extra),
        "response_type": response_type,
        "data": data,
    }


def obj(entity, serializer, status=200):
    """Commit pending mutations, then serialize a single resource."""
    store.commit()
    return jsonify(envelope(serializer(entity), "object")), status


def raw(data, status=200):
    store.commit()
    return jsonify(envelope(data, "object")), status


def created(entity, serializer):
    return obj(entity, serializer, 201)


def collection(rows, serializer, limit, offset, total_count):
    store.commit()
    has_more = (offset + len(rows)) < total_count
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    payload = [serializer(row) for row in rows]
    return jsonify(envelope(payload, "array", meta_extra)), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
