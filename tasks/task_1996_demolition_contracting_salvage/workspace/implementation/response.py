"""Standard response envelope helpers, matching SCAFFOLD.yaml response_envelope.

Success: {"meta": {...}, "response_type": "object"|"array", "data": ...}
Error:   {"meta": {...}, "response_type": "error", "data": {"error_id", "message"}}
List responses add limit/offset/total_count/has_more to meta.
"""

import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from errors import err, ERR_VALIDATION
from util import fmt_ts


def _meta():
    rid = "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=24))
    return {
        "api_request_id": rid,
        "api_request_timestamp": fmt_ts(datetime.now(timezone.utc)),
    }


def success(data, status=200, response_type="object", pagination=None):
    m = _meta()
    if pagination is not None:
        m.update(pagination)
    body = {"meta": m, "response_type": response_type, "data": data}
    return jsonify(body), status


def error(error_id, status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def list_response(records, serializer):
    """Sort by created_at ascending (insertion order breaks ties), paginate,
    and wrap in the envelope. limit default 10, min 1, max 100; offset default 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None or raw_limit == "":
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err(ERR_VALIDATION, "invalid limit")
        limit = max(1, min(100, limit))
    if raw_offset is None or raw_offset == "":
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err(ERR_VALIDATION, "invalid offset")
        offset = max(0, offset)

    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return success([serializer(r) for r in page], status=200,
                   response_type="array", pagination=pagination)
