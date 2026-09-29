"""Response envelope (PRD 2.2) and pagination (PRD 2.3)."""

import uuid
from datetime import datetime, timezone

from flask import jsonify, request

from errors import ApiError, fail


def _meta():
    now = datetime.now(timezone.utc)
    return {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ"
        % (
            now.year,
            now.month,
            now.day,
            now.hour,
            now.minute,
            now.second,
            now.microsecond // 1000,
        ),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def read_pagination():
    """Parse and validate limit/offset from the query string."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        if raw is None or not _is_int(raw):
            fail("ERR_VALIDATION", "limit must be an integer.")
        limit = int(raw)
        if limit < 1 or limit > 100:
            fail("ERR_VALIDATION", "limit must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        if raw is None or not _is_int(raw):
            fail("ERR_VALIDATION", "offset must be an integer.")
        offset = int(raw)
        if offset < 0:
            fail("ERR_VALIDATION", "offset must be 0 or greater.")
    return limit, offset


def _is_int(raw):
    text = raw.strip()
    if text.startswith("-") or text.startswith("+"):
        text = text[1:]
    return text.isdigit() and text != ""


def paginate(rows, limit, offset):
    return rows[offset : offset + limit]


def list_response(rows, serializer=None):
    limit, offset = read_pagination()
    total = len(rows)
    page = paginate(rows, limit, offset)
    if serializer is not None:
        page = [serializer(r) for r in page]
    return ok_list(page, limit, offset, total)
