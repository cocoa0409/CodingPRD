"""Response envelope helpers (PRD section 2.2) and pagination (PRD section 2.3)."""

import random
import string

from flask import jsonify, request

from errors import ERR_INVALID_REQUEST, fail
from store import store
from timeutil import fmt_ms

_ALNUM = string.ascii_uppercase + string.digits

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_ms(store.now_ms()),
    }


def object_response(data, status=200):
    body = {"meta": base_meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def empty_response(status=200):
    return object_response({}, status)


def array_response(items, page_meta, status=200):
    meta = base_meta()
    meta.update(page_meta)
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        fail(ERR_INVALID_REQUEST, "Query parameter '%s' must be an integer." % name)
    value = int(text)
    if value < minimum or (maximum is not None and value > maximum):
        fail(ERR_INVALID_REQUEST, "Query parameter '%s' is out of bounds." % name)
    return value


def page_params():
    limit = _int_param("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _int_param("offset", OFFSET_DEFAULT, 0, None)
    return limit, offset


def paginate(rows):
    limit, offset = page_params()
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta
