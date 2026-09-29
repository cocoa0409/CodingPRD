"""The response envelope of PRD section 2.2 and the pagination meta of 2.3."""

import random
import string

from flask import jsonify

import clock

_ALPHANUM = string.ascii_uppercase + string.digits


def api_request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": api_request_id(),
        "api_request_timestamp": clock.format_instant(clock.now()),
    }


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def array_response(items, status=200, page=None):
    """A list response.  `page` carries the four pagination fields of 2.3;
    computed reads that declare no `limit`/`offset` omit them entirely."""
    meta = _meta()
    if page is not None:
        meta["limit"] = page["limit"]
        meta["offset"] = page["offset"]
        meta["total_count"] = page["total_count"]
        meta["has_more"] = page["has_more"]
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def paginate(records, limit, offset):
    """Slice an already-ordered collection and describe the page."""
    total = len(records)
    window = records[offset:offset + limit]
    page = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }
    return window, page
