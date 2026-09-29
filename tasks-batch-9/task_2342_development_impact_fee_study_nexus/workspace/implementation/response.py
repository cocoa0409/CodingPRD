"""Response envelope construction (PRD 2.2) and pagination (PRD 2.3)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from errors import raise_error
from util import iso_ms

_ALPHABET = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso_ms(datetime.now(timezone.utc)),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(data, status=200):
    payload = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(payload), status


def list_response(items, limit, offset, total_count):
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    payload = {"meta": _meta(meta), "response_type": "array", "data": items}
    return jsonify(payload), 200


def error_response(error):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error.error_id, "message": error.message},
    }
    return jsonify(payload), error.http_status


def _query_int(name, default, minimum=None, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise_error("ERR_INVALID_REQUEST")
        return default
    if minimum is not None and value < minimum:
        raise_error("ERR_INVALID_REQUEST")
    if maximum is not None and value > maximum:
        raise_error("ERR_INVALID_REQUEST")
    return value


def pagination():
    """Returns (limit, offset), validating both against PRD 2.3."""
    limit = _query_int("limit", 10, 1, 100)
    offset = _query_int("offset", 0, 0, None)
    return limit, offset


def paginated(records, serializer):
    limit, offset = pagination()
    total = len(records)
    page = records[offset:offset + limit]
    return list_response([serializer(record) for record in page], limit, offset, total)
