"""Standard response envelope (PRD §2.2) and pagination (PRD §2.3)."""

import json
import random
import string
from decimal import Decimal

from flask import Response, request

from db import now_iso
from errors import invalid

PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0
PAGINATION_OFFSET_MIN = 0

_ALPHANUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta(extra=None):
    meta = {"api_request_id": request_id(), "api_request_timestamp": now_iso()}
    if extra:
        meta.update(extra)
    return meta


def _default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError("Object of type %s is not JSON serializable" % type(obj).__name__)


def _json(body, status):
    return Response(
        json.dumps(body, default=_default),
        status=status,
        mimetype="application/json",
    )


def success(data, status=200, meta_extra=None):
    body = {
        "meta": _meta(meta_extra),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data if data is not None else {},
    }
    return _json(body, status)


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _json(body, status)


def pagination_params():
    """limit defaults to 10 (1..100); offset defaults to 0 (>= 0)."""
    limit = PAGINATION_LIMIT_DEFAULT
    offset = PAGINATION_OFFSET_DEFAULT
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid("limit must be an integer between 1 and 100.")
        if limit < PAGINATION_LIMIT_MIN or limit > PAGINATION_LIMIT_MAX:
            raise invalid("limit must be between 1 and 100.")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid("offset must be an integer of 0 or more.")
        if offset < PAGINATION_OFFSET_MIN:
            raise invalid("offset must be 0 or more.")
    return limit, offset


def paginated(rows, serializer):
    """Apply the pagination window and emit the list envelope."""
    limit, offset = pagination_params()
    total = len(rows)
    window = rows[offset:offset + limit]
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }
    return success([serializer(row) for row in window], 200, meta_extra)
