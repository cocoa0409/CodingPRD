"""Response envelope helpers (PRD §2.2, §2.3)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

_ALPHANUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _request_timestamp():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }


def envelope(data, response_type, status, pagination=None):
    meta = _meta()
    if pagination:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def ok(data, status=200):
    return envelope(data, "object", status)


def created(data):
    return envelope(data, "object", 201)


def collection(rows, limit=None, offset=None, total=None):
    pagination = None
    if limit is not None:
        pagination = {
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": (offset + len(rows)) < total,
        }
    return envelope(rows, "array", 200, pagination)


def error(error_id, message, status):
    return envelope({"error_id": error_id, "message": message}, "error", status)
