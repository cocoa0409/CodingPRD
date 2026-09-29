"""Response envelope helpers (PRD 2.2) and offset/limit pagination (PRD 2.3)."""

import random
import string

from flask import jsonify, request

from .errors import bad_request
from .store import now_iso, public

_ALPHABET = string.ascii_uppercase + string.digits

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(20))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": now_iso()}


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return object_response(data, 201)


def empty_response(status=200):
    return object_response({}, status)


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None:
        return default
    raw = raw.strip()
    if raw == "":
        bad_request("Query parameter '%s' must be an integer." % name)
    try:
        value = int(raw, 10)
    except ValueError:
        bad_request("Query parameter '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        bad_request("Query parameter '%s' is out of range." % name)
    if maximum is not None and value > maximum:
        bad_request("Query parameter '%s' is out of range." % name)
    return value


def pagination():
    """Validated (limit, offset) pair. Malformed values are ERR_INVALID_REQUEST."""
    limit = _int_param("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _int_param("offset", OFFSET_DEFAULT, 0, None)
    return limit, offset


def list_response(items):
    """Paginate an already sorted list of rows and wrap it in the array envelope."""
    limit, offset = pagination()
    total = len(items)
    page = items[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = offset + len(page) < total
    body = {"meta": meta, "response_type": "array", "data": [public(row) for row in page]}
    return jsonify(body), 200
