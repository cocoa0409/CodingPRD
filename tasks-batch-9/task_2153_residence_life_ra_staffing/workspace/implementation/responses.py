"""Response envelope helpers (PRD s2.2 / s2.3)."""
import random
import string

from flask import jsonify

import serializers
import store

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": store.fmt_iso(store.wall_now()),
    }
    if extra:
        meta.update(extra)
    return meta


class Result(object):
    def __init__(self, response_type, payload, status=200, meta=None, is_entity=False):
        self.response_type = response_type
        self.payload = payload
        self.status = status
        self.meta = meta or {}
        self.is_entity = is_entity


def obj(row, status=200):
    return Result("object", row, status, is_entity=True)


def raw(data, status=200):
    return Result("object", data, status, is_entity=False)


def page(rows, total, limit, offset):
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(rows) < total,
    }
    return Result("array", rows, 200, meta=meta, is_entity=True)


def render(result):
    if result.is_entity:
        if result.response_type == "array":
            data = serializers.serialize_many(result.payload)
        else:
            data = serializers.serialize(result.payload)
    else:
        data = result.payload
    body = {
        "meta": _meta(result.meta),
        "response_type": result.response_type,
        "data": data,
    }
    return jsonify(body), result.status


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
