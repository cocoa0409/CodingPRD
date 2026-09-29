"""Response envelope helpers (SCAFFOLD §1.0 / PRD §2.2)."""
import random
import string

from flask import jsonify

import clock

_ALPHANUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": clock.now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data or {}}), status


def list_response(items, page_meta, status=200):
    return jsonify({"meta": _meta(page_meta), "response_type": "array", "data": items}), status


def error_response(error_id, message, status):
    return (
        jsonify(
            {
                "meta": _meta(),
                "response_type": "error",
                "data": {"error_id": error_id, "message": message},
            }
        ),
        status,
    )
