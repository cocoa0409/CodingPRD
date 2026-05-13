"""Response envelope helpers per PRD §2.2."""
import secrets
import string
from datetime import datetime, timezone
from flask import jsonify


def _gen_request_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _now_iso() -> str:
    now = datetime.now(timezone.utc)
    # ISO 8601 UTC with three fractional digits, e.g. 2025-05-24T10:30:00.123Z
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _base_meta() -> dict:
    return {
        "api_request_id": _gen_request_id(),
        "api_request_timestamp": _now_iso(),
    }


def success(data, status: int = 200):
    body = {
        "meta": _base_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def success_list(items, limit: int, offset: int, total_count: int, status: int = 200):
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_response(error_id: str, message: str, http_status: int):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message or error_id,
        },
    }
    return jsonify(body), http_status
