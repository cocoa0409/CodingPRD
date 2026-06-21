"""Standard response envelope helpers per PRD §2.2."""
import random
import string
from datetime import datetime, timezone
from flask import jsonify


def _request_id() -> str:
    alphabet = string.ascii_uppercase + string.ascii_lowercase + string.digits
    return "req_" + "".join(random.choices(alphabet, k=20))


def _now_iso() -> str:
    # ISO 8601 UTC with three fractional digits, Z suffix
    return iso_utc(datetime.now(timezone.utc))


def iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    # Truncate to milliseconds, formatted with Z
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def parse_iso_utc(s: str) -> datetime:
    """Parse ISO 8601 UTC string. Accepts trailing Z or +00:00."""
    if not isinstance(s, str):
        raise ValueError("expected string datetime")
    cleaned = s.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    dt = datetime.fromisoformat(cleaned)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def success_object(data, status: int = 200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _now_iso(),
        },
        "response_type": "object",
        "data": data if data is not None else {},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def success_array(data_list, *, limit: int, offset: int, total_count: int, status: int = 200):
    has_more = (offset + limit) < total_count
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _now_iso(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        },
        "response_type": "array",
        "data": list(data_list),
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(error_id: str, message: str, status: int):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _now_iso(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp
