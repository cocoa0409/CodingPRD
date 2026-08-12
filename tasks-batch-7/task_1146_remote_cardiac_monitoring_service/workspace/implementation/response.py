"""Response envelope helpers, matching SCAFFOLD response_envelope exactly."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify

from clock import now


def fmt_ts(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def serialize(rec):
    out = {}
    for k, v in rec.items():
        if isinstance(v, datetime):
            out[k] = fmt_ts(v)
        elif isinstance(v, list):
            out[k] = [serialize(x) if isinstance(x, dict) else x for x in v]
        else:
            out[k] = v
    return out


def _meta():
    return {
        "api_request_id": "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=24)),
        "api_request_timestamp": fmt_ts(now()),
    }


def success(data, status=200, response_type="object"):
    return jsonify({"meta": _meta(), "response_type": response_type, "data": data}), status


def success_list(items, limit, offset, serializer=serialize):
    total = len(items)
    page = items[offset:offset + limit]
    meta = _meta()
    meta.update({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    })
    return jsonify({"meta": meta, "response_type": "array",
                    "data": [serializer(x) for x in page]}), 200


def error_response(error_id, status, message):
    return jsonify({"meta": _meta(), "response_type": "error",
                    "data": {"error_id": error_id, "message": message}}), status
