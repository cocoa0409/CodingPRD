"""The response envelope of PRD §2.2."""

import random
import string

from flask import jsonify

from util import wall_clock_stamp

_ALPHANUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": wall_clock_stamp(),
    }
    if extra:
        meta.update(extra)
    return meta


def public(record):
    """Strip internal bookkeeping keys before serialization."""
    if record is None:
        return None
    return {k: v for k, v in record.items() if not k.startswith("_")}


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": public(data) if data else (data or {})}
    return jsonify(body), status


def raw_object_response(data, status=200):
    """For computed views that are plain dicts rather than stored records."""
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def array_response(records, limit, offset, total_count, status=200):
    page = records[offset:offset + limit]
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(page) < total_count,
    }
    body = {
        "meta": _meta(meta_extra),
        "response_type": "array",
        "data": [public(r) for r in page],
    }
    return jsonify(body), status


def empty_response(status=204):
    if status == 204:
        return "", 204
    return jsonify({"meta": _meta(), "response_type": "object", "data": {}}), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
