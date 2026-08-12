"""Standard response envelope helpers (SCAFFOLD response_envelope)."""
import json
import uuid
from decimal import Decimal

from flask import Response, request

import db


class _Encoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)


def _meta(include_pagination=None):
    rid = "req_" + uuid.uuid4().hex[:24]
    m = {
        "api_request_id": rid,
        "api_request_timestamp": db.now_iso(),
    }
    if include_pagination is not None:
        limit, offset, total_count = include_pagination
        m["limit"] = limit
        m["offset"] = offset
        m["total_count"] = total_count
        m["has_more"] = (offset + limit) < total_count
    return m


def _dump(payload, status):
    body = json.dumps(payload, cls=_Encoder)
    return Response(body, status=status, content_type="application/json")


def success_object(data, status=200):
    payload = {"meta": _meta(), "response_type": "object", "data": data}
    return _dump(payload, status)


def success_list(items, limit, offset, total_count, status=200):
    payload = {
        "meta": _meta((limit, offset, total_count)),
        "response_type": "array",
        "data": items,
    }
    return _dump(payload, status)


def error_response(error_id, http_status, message):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _dump(payload, http_status)


def get_body():
    """Parse the JSON request body; returns {} when absent/unparseable."""
    if request.content_length in (None, 0):
        return {}
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        from errors import ApiError, ERR_INVALID_REQUEST
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return data


def pagination_params():
    """Parse limit/offset query params with defaults 10/0, clamped to [1,100]/[0,inf)."""
    def _parse(name, default):
        raw = request.args.get(name)
        if raw is None:
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    limit = _parse("limit", 10)
    offset = _parse("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(records, serializer):
    """Sort by created_at ASC, slice, and wrap in the list envelope."""
    limit, offset = pagination_params()
    ordered = sorted(records, key=db.sort_key)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return success_list([serializer(r) for r in page], limit, offset, total)
