"""Response envelope construction (PRD section 2.2 / 2.3)."""

from flask import Response

from db import db
from util import fmt_iso, json_text, request_id

PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_iso(db.clock),
    }


def _respond(body, status):
    return Response(json_text(body), status=status, mimetype="application/json")


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return _respond(body, status)


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return _respond(body, 200)


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _respond(body, status)
