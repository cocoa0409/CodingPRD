"""Standard response envelope helpers (PRD §2.2 / SCAFFOLD response_envelope)."""

import json
from decimal import Decimal
from flask import Response

from util import now_iso, request_id


class _Encoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)


def success(data, status=200, pagination=None):
    body = {
        "meta": {
            "api_request_id": request_id(),
            "api_request_timestamp": now_iso(),
        },
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    if pagination is not None:
        body["meta"]["limit"] = pagination["limit"]
        body["meta"]["offset"] = pagination["offset"]
        body["meta"]["total_count"] = pagination["total_count"]
        body["meta"]["has_more"] = pagination["has_more"]
    return Response(
        json.dumps(body, cls=_Encoder),
        status=status,
        mimetype="application/json",
    )


def error(error_id, message, status):
    body = {
        "meta": {
            "api_request_id": request_id(),
            "api_request_timestamp": now_iso(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return Response(
        json.dumps(body, cls=_Encoder),
        status=status,
        mimetype="application/json",
    )


def list_response(items, serializer, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    return success(
        [serializer(i) for i in page],
        status=200,
        pagination={"limit": limit, "offset": offset, "total_count": total, "has_more": has_more},
    )
