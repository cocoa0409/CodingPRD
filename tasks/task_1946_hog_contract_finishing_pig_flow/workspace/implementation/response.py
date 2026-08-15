"""Standard response envelope helpers (PRD §2.2, §2.3)."""

import random
import string
from flask import jsonify

from db import store
from errors import malformed


def _request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return f"req_{suffix}"


def _meta(pagination=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": store.now_str(),
    }
    if pagination is not None:
        m["limit"] = pagination["limit"]
        m["offset"] = pagination["offset"]
        m["total_count"] = pagination["total_count"]
        m["has_more"] = pagination["has_more"]
    return m


def success_object(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status


def parse_pagination(args):
    """Parse limit/offset per §2.3: limit default 10, min 1, max 100; offset default 0."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None or raw_limit == "":
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise malformed("limit must be an integer")
        if limit < 1 or limit > 100:
            raise malformed("limit must be between 1 and 100")
    if raw_offset is None or raw_offset == "":
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise malformed("offset must be an integer")
        if offset < 0:
            raise malformed("offset must be >= 0")
    return limit, offset


def paginate(records, args, serializer):
    """Sort by creation order (oldest first), filter already applied, then slice."""
    limit, offset = parse_pagination(args)
    records = sorted(records, key=lambda r: r.get("_seq", 0))
    total = len(records)
    page = records[offset:offset + limit]
    return success_list([serializer(r) for r in page], limit, offset, total)
