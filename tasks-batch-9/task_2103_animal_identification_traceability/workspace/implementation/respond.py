"""Response envelope helpers (PRD 2.2 / 2.3)."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify

from timeutil import fmt_dt

_ALNUM = string.ascii_uppercase + string.digits


def _meta():
    return {
        "api_request_id": "req_" + "".join(random.choice(_ALNUM) for _ in range(20)),
        "api_request_timestamp": fmt_dt(datetime.now(timezone.utc)),
    }


def success(data, response_type="object", status=200, pagination=None):
    meta = _meta()
    if pagination:
        meta.update(pagination)
    resp = jsonify({"meta": meta, "response_type": response_type, "data": data})
    resp.status_code = status
    return resp


def listing(rows, limit, offset, total_count):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(rows) < total_count,
    }
    return success(rows, response_type="array", status=200, pagination=pagination)


def error(error_id, message, status):
    resp = jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    })
    resp.status_code = status
    return resp
