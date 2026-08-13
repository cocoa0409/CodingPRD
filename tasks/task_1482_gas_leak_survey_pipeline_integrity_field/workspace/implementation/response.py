"""Response envelope helpers (PRD §2.2)."""
import random
import string

from flask import jsonify

from db import fmt_dt, now


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_dt(now()),
    }


def success(data, response_type="object", code=200, pagination=None):
    meta = _meta()
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), code


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def list_response(all_items, serialize_fn, limit, offset):
    """Items must already be filtered and sorted; applies the slice."""
    total = len(all_items)
    page = all_items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return success([serialize_fn(e) for e in page], response_type="array",
                   code=200, pagination=pagination)
