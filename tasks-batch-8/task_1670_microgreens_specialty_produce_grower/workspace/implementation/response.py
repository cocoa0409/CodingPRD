"""Response envelope helpers matching the scaffold's response_envelope spec."""
import uuid
from flask import jsonify

from db import db


def now_iso():
    """Logical-clock 'now' as ISO 8601 UTC with three fractional digits."""
    dt = db.clock
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": now_iso(),
    }


def success(data, response_type="object", status=200, pagination=None):
    meta = _meta()
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def serialize(rec):
    """Strip internal bookkeeping keys before sending a resource out."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}
