"""Response envelope helpers — strictly emit the PRD §2.2 format."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify, Response


def _gen_request_id():
    alphabet = string.ascii_letters + string.digits
    suffix = "".join(random.choices(alphabet, k=20))
    return f"req_{suffix}"


def _current_iso():
    # Server wall-clock timestamp for the meta envelope (NOT the virtual clock).
    dt = datetime.now(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime(f"%Y-%m-%dT%H:%M:%S.{ms:03d}Z")


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
    return Response(status=status)
