"""Standard response envelope helpers (PRD section 2.2 / scaffold 1.0)."""

import json
import random
import string
from datetime import datetime, timezone

from flask import Response

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def iso_now():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)


def _meta():
    return {"api_request_id": request_id(), "api_request_timestamp": iso_now()}


def _emit(payload, status):
    return Response(
        json.dumps(payload, allow_nan=False),
        status=status,
        mimetype="application/json",
    )


def object_response(data, status=200):
    return _emit({"meta": _meta(), "response_type": "object", "data": data}, status)


def array_response(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return _emit({"meta": meta, "response_type": "array", "data": items}, 200)


def error_response(error_id, message, status):
    return _emit(
        {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": error_id, "message": message},
        },
        status,
    )
