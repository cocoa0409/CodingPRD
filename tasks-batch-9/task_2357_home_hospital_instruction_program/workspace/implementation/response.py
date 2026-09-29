"""Standard response envelope helpers (PRD §2.2, §2.3)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

_ALPHANUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _request_timestamp():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }


def success(data, response_type="object", page=None, status=200):
    meta = base_meta()
    if page:
        meta.update(page)
    return jsonify({"meta": meta, "response_type": response_type, "data": data}), status


def failure(error_id, message, status):
    return (
        jsonify(
            {
                "meta": base_meta(),
                "response_type": "error",
                "data": {"error_id": error_id, "message": message},
            }
        ),
        status,
    )


def paginate(items, limit, offset):
    """Apply the page window and build the pagination `meta` fields."""
    total = len(items)
    window = items[offset : offset + limit]
    page = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }
    return window, page
