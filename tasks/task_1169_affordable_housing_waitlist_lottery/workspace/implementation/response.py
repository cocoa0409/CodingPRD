"""Response envelope helpers (SCAFFOLD §1.0 / PRD §2.2)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

import db


def _request_id() -> str:
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def _meta_base():
    # Request timestamp uses wall-clock for the envelope meta (it records when the
    # request was served), formatted ISO 8601 UTC with three fractional digits.
    now = datetime.now(timezone.utc)
    ms = now.microsecond // 1000
    ts = now.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms
    return {"api_request_id": _request_id(), "api_request_timestamp": ts}


def success(data, status=200, response_type="object"):
    body = {"meta": _meta_base(), "response_type": response_type, "data": data}
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    meta = _meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error(error_id, message, http_status):
    meta = _meta_base()
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
