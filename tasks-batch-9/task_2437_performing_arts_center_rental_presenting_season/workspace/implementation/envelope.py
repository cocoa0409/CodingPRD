"""Response envelope helpers (PRD section 2.2)."""

import json
import random
import string

from flask import Response

from store import now_iso

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def _respond(payload, status):
    return Response(
        json.dumps(payload),
        status=status,
        mimetype="application/json",
    )


def object_response(data, status=200):
    return _respond(
        {"meta": _meta(), "response_type": "object", "data": data},
        status,
    )


def array_response(items, page_meta, status=200):
    return _respond(
        {"meta": _meta(page_meta), "response_type": "array", "data": items},
        status,
    )


def error_response(error_id, message, status):
    return _respond(
        {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": error_id, "message": message},
        },
        status,
    )
