"""Response envelope helpers (PRD §2.2 / scaffold §1.0)."""

import random
import string

from flask import jsonify, request

from db import db, fmt_ts
from errors import invalid

ALPHANUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(ALPHANUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_ts(db.clock),
    }


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# ------------------------------------------------------------------- pagination
def pagination_args():
    """limit defaults to 10 (1..100), offset defaults to 0 (PRD §2.3)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    limit = 10
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            invalid("limit must be an integer between 1 and 100")
        if limit < 1 or limit > 100:
            invalid("limit must be between 1 and 100")

    offset = 0
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            invalid("offset must be a non-negative integer")
        if offset < 0:
            invalid("offset must be a non-negative integer")

    return limit, offset


def paginate(rows, serializer):
    limit, offset = pagination_args()
    total = len(rows)
    page = rows[offset:offset + limit]
    return ok_list([serializer(row) for row in page], limit, offset, total)
