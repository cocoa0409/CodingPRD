"""Response envelope helpers (PRD 2.2)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def wall_now_iso():
    dt = datetime.now(timezone.utc)
    return "%s.%03dZ" % (dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)


def base_meta():
    return {"api_request_id": request_id(), "api_request_timestamp": wall_now_iso()}


def envelope(data, response_type="object", status=200, meta_extra=None):
    meta = base_meta()
    if meta_extra:
        meta.update(meta_extra)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def ok(data):
    return envelope(data, "object", 200)


def created(data):
    return envelope(data, "object", 201)


def ok_list(rows, limit, offset, total_count):
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(rows) < total_count,
    }
    return envelope(rows, "array", 200, meta_extra)


def error_response(error_id, message, status):
    return envelope({"error_id": error_id, "message": message}, "error", status)


def paginate(rows, limit, offset):
    return rows[offset : offset + limit]
