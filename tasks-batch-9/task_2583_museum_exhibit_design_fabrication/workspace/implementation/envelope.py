"""Response envelope helpers (PRD §2.2) and pagination (PRD §2.3)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from errors import ApiError
from store import db

ALNUM = string.ascii_uppercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0
PAGINATION_MIN_OFFSET = 0


def api_request_id():
    return "req_" + "".join(random.choice(ALNUM) for _ in range(20))


def iso(moment):
    """ISO 8601 UTC with exactly three fractional digits."""
    if moment is None:
        return None
    if isinstance(moment, str):
        return moment
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (moment.microsecond // 1000)


def _meta():
    return {
        "api_request_id": api_request_id(),
        "api_request_timestamp": iso(db.now()),
    }


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def empty_response(status=200):
    return object_response({}, status)


def list_response(rows, serializer, limit, offset):
    total = len(rows)
    window = rows[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(window)) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serializer(r) for r in window],
    }
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name, None)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    try:
        value = int(text, 10)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    if value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "%s may not be smaller than %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "%s may not be larger than %d." % (name, maximum))
    return value


def pagination():
    limit = _int_param("limit", PAGINATION_DEFAULT_LIMIT, PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT)
    offset = _int_param("offset", PAGINATION_DEFAULT_OFFSET, PAGINATION_MIN_OFFSET, None)
    return limit, offset


def query_filter(name):
    raw = request.args.get(name, None)
    if raw is None or raw == "":
        return None
    return raw


def query_bool_filter(name):
    raw = request.args.get(name, None)
    if raw is None or raw == "":
        return None
    text = raw.strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    raise ApiError("ERR_INVALID_REQUEST", "%s must be a boolean." % name)
