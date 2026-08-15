"""Standard success / error response envelopes (PRD 2.2, 2.3).

Success: { "meta": {api_request_id, api_request_timestamp}, "response_type":
"object"|"array", "data": ... } -- list responses add limit/offset/total_count/
has_more to meta.  Error: same meta, response_type "error", data carries
{error_id, message}.
"""
from flask import Response

from store import db
from util import dumps, iso, new_request_id


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso(db.now()),
    }


def _respond(payload, status):
    return Response(dumps(payload), status=status, mimetype="application/json")


def ok(data, status=200):
    return _respond(
        {"meta": _meta(), "response_type": "object", "data": data}, status
    )


def created(data):
    return ok(data, 201)


def listing(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    return _respond({"meta": meta, "response_type": "array", "data": rows}, 200)


def error(error_id, message, status):
    return _respond(
        {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": error_id, "message": message},
        },
        status,
    )
