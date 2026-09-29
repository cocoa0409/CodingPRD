"""Response envelope helpers (PRD 2.2) and pagination (PRD 2.3)."""

import json
import random
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import Response, request

from errors import invalid

_ALNUM = string.ascii_uppercase + string.digits

PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0
PAGINATION_OFFSET_MIN = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _timestamp():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": _timestamp()}


def _default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError("%r is not JSON serializable" % (obj,))


def _send(payload, status):
    body = json.dumps(payload, default=_default)
    return Response(body, status=status, mimetype="application/json")


def object_response(data, status=200):
    return _send({"meta": _meta(), "response_type": "object", "data": data or {}}, status)


def list_response(items, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return _send({"meta": meta, "response_type": "array", "data": items}, status)


def error_response(error_id, message, status):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _send(payload, status)


def _query_int(name, default, minimum, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise invalid("%s must be an integer" % name)
    if minimum is not None and value < minimum:
        raise invalid("%s must be >= %d" % (name, minimum))
    if maximum is not None and value > maximum:
        raise invalid("%s must be <= %d" % (name, maximum))
    return value


def pagination():
    limit = _query_int("limit", PAGINATION_LIMIT_DEFAULT, PAGINATION_LIMIT_MIN, PAGINATION_LIMIT_MAX)
    offset = _query_int("offset", PAGINATION_OFFSET_DEFAULT, PAGINATION_OFFSET_MIN, None)
    return limit, offset


def paginated(rows, serializer):
    """Rows must already be sorted by created_at ascending."""
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    return list_response([serializer(r) for r in page], limit, offset, total)
