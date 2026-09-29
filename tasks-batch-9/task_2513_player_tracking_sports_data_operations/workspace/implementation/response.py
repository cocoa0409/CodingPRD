"""Response envelope helpers.

The envelope is transcribed literally from PRD §2.2: a ``meta`` wrapper carrying
``api_request_id`` and ``api_request_timestamp`` (plus the four pagination fields
on list endpoints), a ``response_type`` discriminator of ``object`` / ``array`` /
``error``, and a ``data`` payload.
"""

import random
import string

from flask import jsonify

from util import iso_now

_ALPHANUM = string.ascii_uppercase + string.digits


def _request_id():
    """PRD §2.2: server-generated identifier that starts with ``req_``."""
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso_now(),
    }


def object_response(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def array_response(items, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status
