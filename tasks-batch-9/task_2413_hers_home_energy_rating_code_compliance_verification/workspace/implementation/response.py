"""Response envelope helpers (PRD §2.2)."""

import random
import string

from flask import jsonify

from db import wall_now_iso

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": wall_now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def array_response(items, limit, offset, total_count):
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return (
        jsonify({"meta": _meta(meta_extra), "response_type": "array", "data": items}),
        200,
    )


def error_response(error_id, message, status):
    return (
        jsonify(
            {
                "meta": _meta(),
                "response_type": "error",
                "data": {"error_id": error_id, "message": message},
            }
        ),
        status,
    )


class Result:
    """What a view returns; serialization happens after derived reconciliation."""

    def __init__(self, payload, serializer=None, status=200, page=None):
        self.payload = payload
        self.serializer = serializer
        self.status = status
        self.page = page  # (limit, offset, total_count) for list endpoints

    def render(self):
        if self.page is not None:
            limit, offset, total = self.page
            items = [
                self.serializer(row) if self.serializer else row for row in self.payload
            ]
            return array_response(items, limit, offset, total)
        data = self.serializer(self.payload) if self.serializer else self.payload
        if data is None:
            data = {}
        return object_response(data, self.status)
