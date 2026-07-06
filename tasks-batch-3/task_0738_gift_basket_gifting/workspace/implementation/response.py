"""Standard response envelope helpers (per PRD §2.2)."""
import random
import string
from datetime import datetime, timezone
from flask import jsonify


def _now_ts_iso() -> str:
    """ISO 8601 UTC with three fractional digits."""
    now = datetime.now(timezone.utc)
    ms = int(now.microsecond / 1000)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def _gen_request_id() -> str:
    alphanum = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alphanum, k=20))


def _base_meta() -> dict:
    return {
        "api_request_id": _gen_request_id(),
        "api_request_timestamp": _now_ts_iso(),
    }


def success(data, status: int = 200, response_type: str = "object"):
    body = {
        "meta": _base_meta(),
        "response_type": response_type,
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


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
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error(error_id: str, http_status: int, message: str = ""):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message or error_id,
        },
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp
