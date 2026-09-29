"""Standard response envelope (PRD 2.2)."""

import random
import string

from flask import jsonify

import db

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(pagination=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": db.iso_ts(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def success(data, status=200, response_type="object", pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


class Resp:
    """Deferred response: serialization happens after the request commits so
    that `updated_at` / `version` reflect the committed values."""

    def __init__(self, kind, payload, status=200, pagination=None, raw=False):
        self.kind = kind
        self.payload = payload
        self.status = status
        self.pagination = pagination
        self.raw = raw

    def build(self):
        if self.kind == "array":
            data = self.payload if self.raw else db.serialize_all(self.payload)
        else:
            data = self.payload if self.raw else db.serialize(self.payload)
        return success(data, self.status, self.kind, self.pagination)


def obj(row, status=200):
    return Resp("object", row, status)


def raw_obj(data, status=200):
    return Resp("object", data, status, raw=True)


def listing(rows, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return Resp("array", page, 200, pagination)
