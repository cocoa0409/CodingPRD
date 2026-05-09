import json
import secrets
import string
from datetime import datetime, timezone
from decimal import Decimal
from flask import jsonify, make_response


def now_iso() -> str:
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def request_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _to_jsonable(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_jsonable(x) for x in obj]
    if isinstance(obj, tuple):
        return [_to_jsonable(x) for x in obj]
    return obj


def success(data, status_code=200, response_type=None, pagination=None):
    if response_type is None:
        response_type = "array" if isinstance(data, list) else "object"
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": now_iso(),
    }
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": _to_jsonable(data),
    }
    resp = make_response(json.dumps(body, separators=(",", ":")), status_code)
    resp.headers["Content-Type"] = "application/json"
    return resp


def error(error_id: str, http_status: int, message: str):
    body = {
        "meta": {
            "api_request_id": request_id(),
            "api_request_timestamp": now_iso(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    resp = make_response(json.dumps(body, separators=(",", ":")), http_status)
    resp.headers["Content-Type"] = "application/json"
    return resp


def paginate(items, limit, offset):
    total = len(items)
    sliced = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return sliced, pagination
