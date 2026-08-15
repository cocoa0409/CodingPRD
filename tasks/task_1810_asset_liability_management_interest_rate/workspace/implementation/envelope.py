"""Response envelope of PRD 2.2 and the pagination contract of PRD 2.3.

Success:  {"meta": {"api_request_id", "api_request_timestamp", [limit, offset,
           total_count, has_more]}, "response_type": "object"|"array", "data": ...}
Error:    {"meta": {"api_request_id", "api_request_timestamp"},
           "response_type": "error", "data": {"error_id", "message"}}
"""

import random
import string

from flask import jsonify

from timeutil import clock

_ALPHANUM = string.ascii_uppercase + string.digits

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        # Server-generated ISO 8601 UTC timestamp with three fractional digits;
        # taken from the logical clock like every other server instant.
        "api_request_timestamp": clock.now_string(),
    }


def object_response(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def read_pagination(args):
    limit = LIMIT_DEFAULT
    raw_limit = args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = LIMIT_DEFAULT
        if limit < LIMIT_MIN:
            limit = LIMIT_MIN
        if limit > LIMIT_MAX:
            limit = LIMIT_MAX
    offset = OFFSET_DEFAULT
    raw_offset = args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            offset = OFFSET_DEFAULT
        if offset < 0:
            offset = OFFSET_DEFAULT
    return limit, offset


def sorted_records(records):
    """PRD 2.3: every list endpoint sorts by created_at ascending; the
    insertion sequence breaks ties (the logical clock may stand still)."""
    return sorted(records, key=lambda r: (r["_created_dt"], r["_seq"]))


def list_response(records, args, serialize):
    """records: raw store dicts; serialize: record -> public dict."""
    rows = sorted_records(records)
    limit, offset = read_pagination(args)
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
        "data": [serialize(r) for r in window],
    }
    return jsonify(body), 200
