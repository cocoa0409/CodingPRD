"""Response envelope construction (PRD 2.2)."""

import random
import string

from flask import jsonify

from db import now_ts

_ALPHANUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def build_meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": now_ts(),
    }
    if extra:
        meta.update(extra)
    return meta


def serialize(record):
    """Drop internal bookkeeping keys before the record leaves the process."""
    if not isinstance(record, dict):
        return record
    return dict((k, v) for k, v in record.items() if not k.startswith("_"))


def success(data, status=200, pagination=None, response_type="object"):
    body = {
        "meta": build_meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def error(error_id, message, status):
    body = {
        "meta": build_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
