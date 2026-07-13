"""Response envelope helpers (PRD 2.2 / SCAFFOLD response_envelope)."""
import random
import string

from flask import jsonify, request

import store
from errors import err

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": store.wall_now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data or {}}
    return jsonify(body), status


def array_response(items, pagination, status=200):
    body = {"meta": _meta(pagination), "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


# --------------------------------------------------------------------------
# Pagination (PRD 2.3): limit default 10, min 1, max 100; offset default 0.
# --------------------------------------------------------------------------
def _int_arg(name, default, minimum, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    if value < minimum:
        raise err("ERR_INVALID_REQUEST", "%s must be >= %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise err("ERR_INVALID_REQUEST", "%s must be <= %d." % (name, maximum))
    return value


def paginate(items):
    limit = _int_arg("limit", 10, 1, 100)
    offset = _int_arg("offset", 0, 0)
    total = len(items)
    window = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }
    return window, meta
