"""Response envelope helpers (PRD 2.2 / 2.3)."""
import random
import string
from datetime import date, datetime, timezone
from decimal import Decimal

from flask import jsonify, request

from errors import ApiError
from store import iso3

ALPHANUM = string.ascii_uppercase + string.digits

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def request_id():
    return "req_" + "".join(random.choice(ALPHANUM) for _ in range(20))


def request_timestamp():
    return iso3(datetime.now(timezone.utc))


def base_meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": request_timestamp(),
    }


def jsonable(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return iso3(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def public(record):
    """Strip internal keys and coerce Decimal / datetime / date to JSON scalars."""
    return {k: jsonable(v) for k, v in record.items() if not k.startswith("_")}


def ok(data, status=200):
    body = {
        "meta": base_meta(),
        "response_type": "object",
        "data": jsonable(data) if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def array(items, status=200, pagination=None):
    meta = base_meta()
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [jsonable(i) for i in items],
    }
    return jsonify(body), status


def error_response(err):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def _page_int(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", "%s must be an integer" % name)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_VALIDATION", "%s may not be smaller than %d" % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_VALIDATION", "%s may not be larger than %d" % (name, maximum))
    return value


def pagination_params():
    limit = _page_int("limit", PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MIN, PAGE_LIMIT_MAX)
    offset = _page_int("offset", PAGE_OFFSET_DEFAULT, 0, None)
    return limit, offset


def paginated(rows, serializer):
    limit, offset = pagination_params()
    total = len(rows)
    window = rows[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }
    return array([serializer(r) for r in window], 200, meta)
