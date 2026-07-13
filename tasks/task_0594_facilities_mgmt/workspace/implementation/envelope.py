"""Standard response envelope (PRD 2.2) and pagination (PRD 2.3)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from errors import fail

_ALNUM = string.ascii_uppercase + string.digits

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def _meta():
    return {
        "api_request_id": "req_" + "".join(random.choice(_ALNUM) for _ in range(20)),
        "api_request_timestamp": iso(datetime.now(timezone.utc)),
    }


def object_response(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data or {}}), status


def list_response(rows, limit, offset, status=200):
    total = len(rows)
    page = rows[offset: offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = offset + limit < total
    return jsonify({"meta": meta, "response_type": "array", "data": page}), status


def error_response(error_id, message, status):
    return (
        jsonify(
            {
                "meta": _meta(),
                "response_type": "error",
                "data": {"error_id": error_id, "message": message},
            }
        ),
        status,
    )


def _as_int(raw, name):
    try:
        if isinstance(raw, str):
            raw = raw.strip()
        value = int(raw)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    if str(raw) != str(value):
        # tolerate "010" style but reject "1.5"/"abc" (already raised above)
        pass
    return value


def pagination():
    """Read and validate limit/offset from the query string (PRD 2.3)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT

    if raw_limit is not None and raw_limit != "":
        limit = _as_int(raw_limit, "limit")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100 inclusive.")
    if raw_offset is not None and raw_offset != "":
        offset = _as_int(raw_offset, "offset")
        if offset < OFFSET_MIN:
            fail("ERR_INVALID_REQUEST", "offset must be at least 0.")
    return limit, offset
