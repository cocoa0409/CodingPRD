"""Response envelope helpers (PRD §2.2, scaffold §1.0)."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _timestamp():
    # ISO 8601 UTC with exactly three fractional digits (PRD §2.2/§2.4).
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _meta(extra=None):
    meta = {"api_request_id": _request_id(), "api_request_timestamp": _timestamp()}
    if extra:
        meta.update(extra)
    return meta


def success(data, status=200, list_meta=None):
    """Single-object or array success envelope.

    list_meta, when present, marks an array response and supplies pagination
    fields (limit, offset, total_count, has_more) inside meta.
    """
    if list_meta is not None:
        response_type = "array"
        meta = _meta(list_meta)
    else:
        response_type = "object"
        meta = _meta()
    body = {"meta": meta, "response_type": response_type, "data": data}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp
