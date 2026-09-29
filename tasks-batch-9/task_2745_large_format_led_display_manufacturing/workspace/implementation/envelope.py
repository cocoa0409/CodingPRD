"""Response envelope helpers (PRD section 2.2 / 2.3)."""

import json
from decimal import Decimal

from flask import Response

import store


def _default(obj):
    if isinstance(obj, Decimal):
        # Decimals are only ever produced by our own rounding helpers, which
        # already fix the scale; serialise them as JSON numbers.
        text = format(obj, "f")
        return json.loads(text, parse_float=float)
    raise TypeError(repr(obj) + " is not JSON serializable")


def _dump(payload):
    return json.dumps(payload, default=_default)


def _meta(extra=None):
    meta = {
        "api_request_id": store.request_id(),
        "api_request_timestamp": store.wall_now(),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return Response(_dump(body), status=status, mimetype="application/json")


def array_response(items, limit, offset, total_count):
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    })
    body = {"meta": meta, "response_type": "array", "data": items}
    return Response(_dump(body), status=200, mimetype="application/json")


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return Response(_dump(body), status=status, mimetype="application/json")


def paginated(rows, limit, offset, serializer):
    total = len(rows)
    page = rows[offset:offset + limit]
    return array_response([serializer(r) for r in page], limit, offset, total)
