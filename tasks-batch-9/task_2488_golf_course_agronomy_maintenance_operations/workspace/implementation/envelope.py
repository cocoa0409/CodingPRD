"""Response envelope helpers (PRD 2.2 / SCAFFOLD response_envelope)."""

import json

from flask import Response

from util import new_request_id, now_iso


def _meta(extra=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def _json_response(payload, status):
    body = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    return Response(body, status=status, mimetype="application/json")


def ok(data, status=200):
    return _json_response(
        {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}},
        status,
    )


def created(data):
    return ok(data, 201)


def ok_list(items, page_meta):
    return _json_response(
        {"meta": _meta(page_meta), "response_type": "array", "data": items},
        200,
    )


def error_response(error_id, message, status):
    return _json_response(
        {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": error_id, "message": message},
        },
        status,
    )
