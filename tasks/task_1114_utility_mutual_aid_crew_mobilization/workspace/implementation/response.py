import random
import string
from datetime import datetime, timezone


def _req_id():
    rand = "".join(random.choices(string.ascii_uppercase + string.digits, k=18))
    return f"req_{rand}"


def _ts():
    # ISO 8601 UTC with three fractional digits
    now = datetime.now(timezone.utc)
    ms = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    return ms


def success_object(data, status=200):
    body = {
        "meta": {
            "api_request_id": _req_id(),
            "api_request_timestamp": _ts(),
        },
        "response_type": "object",
        "data": data,
    }
    return body, status


def success_array(items, limit, offset, total_count, has_more):
    body = {
        "meta": {
            "api_request_id": _req_id(),
            "api_request_timestamp": _ts(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        },
        "response_type": "array",
        "data": items,
    }
    return body, 200


def error_body(error_id, message):
    body = {
        "meta": {
            "api_request_id": _req_id(),
            "api_request_timestamp": _ts(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return body
