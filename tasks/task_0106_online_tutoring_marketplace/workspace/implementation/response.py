"""Response envelope helpers — strictly emit the PRD §2.2 format."""

import random
import string

from flask import jsonify

from clock import format_iso
from datetime import datetime, timezone


def _gen_request_id():
    alphabet = string.ascii_letters + string.digits
    suffix = "".join(random.choices(alphabet, k=20))
    return f"req_{suffix}"


def _current_iso():
    # Server wall clock (NOT the virtual clock) — this is the API timestamp.
    return format_iso(datetime.now(timezone.utc))


def success_response(data, status=200, response_type="object", pagination=None):
    meta = {
        "api_request_id": _gen_request_id(),
        "api_request_timestamp": _current_iso(),
    }
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    response = jsonify(body)
    response.status_code = status
    return response


def list_response(items, total_count, limit, offset, status=200):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + limit < total_count,
    }
    return success_response(
        items, status=status, response_type="array", pagination=pagination
    )


def error_response(error_id, message, http_status):
    meta = {
        "api_request_id": _gen_request_id(),
        "api_request_timestamp": _current_iso(),
    }
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    response = jsonify(body)
    response.status_code = http_status
    return response


def empty_response(status=204):
    """For 204 No Content — return empty body without Content-Type concerns."""
    from flask import Response
    return Response(status=status)
