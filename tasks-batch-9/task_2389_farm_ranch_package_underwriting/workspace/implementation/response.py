"""Standard response envelope (PRD §2.2)."""

import json
import random
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import Response

_ALPHANUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _request_timestamp():
    dt = datetime.now(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }


def public(value):
    """Strip private keys and render Decimals as JSON numbers."""
    if isinstance(value, dict):
        return {k: public(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, list):
        return [public(v) for v in value]
    if isinstance(value, Decimal):
        return float(value)
    return value


def _emit(payload, status):
    body = json.dumps(payload, default=lambda o: float(o) if isinstance(o, Decimal) else str(o))
    return Response(body, status=status, mimetype="application/json")


def ok(data, status=200):
    return _emit({"meta": base_meta(), "response_type": "object", "data": public(data)}, status)


def created(data):
    return ok(data, 201)


def ok_list(rows, limit, offset, total_count):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    return _emit({"meta": meta, "response_type": "array", "data": public(rows)}, 200)


def error(error_id, message, status):
    payload = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _emit(payload, status)


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
