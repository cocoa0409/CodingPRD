"""Standard response envelope (section 2.2)."""

import random
import string

from flask import jsonify

import clock
import db

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": clock.fmt_dt(clock.now()),
    }


def envelope(response_type, data, meta_extra=None, status=200):
    meta = base_meta()
    if meta_extra:
        meta.update(meta_extra)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def obj_out(serializer, record, status=200):
    """Commit the request's version bookkeeping, then emit a single resource."""
    db.commit()
    return envelope("object", serializer(record), None, status)


def raw_out(data, status=200):
    db.commit()
    return envelope("object", data, None, status)


def arr_out(serializer, rows, page):
    db.commit()
    items = [serializer(r) for r in page["items"]]
    meta_extra = {
        "limit": page["limit"],
        "offset": page["offset"],
        "total_count": page["total_count"],
        "has_more": page["has_more"],
    }
    return envelope("array", items, meta_extra, 200)


def error_out(error_id, message, status):
    return envelope(
        "error", {"error_id": error_id, "message": message}, None, status
    )
