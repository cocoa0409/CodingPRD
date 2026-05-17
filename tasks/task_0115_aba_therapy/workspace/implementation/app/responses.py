"""Response envelope helpers — PRD §2.2."""
import secrets
import string
from datetime import datetime, timezone
from typing import Any, Tuple


def _request_id() -> str:
    alphabet = string.ascii_letters + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{suffix}"


def _server_now_iso() -> str:
    """Wall-clock server timestamp used for the response meta line."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def _meta_base() -> dict:
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _server_now_iso(),
    }


def success_response(data: Any, status: int = 200, *, response_type: str = "object",
                     pagination: dict = None) -> Tuple[dict, int]:
    meta = _meta_base()
    if pagination is not None:
        meta.update(pagination)
    return {
        "meta": meta,
        "response_type": response_type,
        "data": data,
    }, status


def list_response(items: list, total: int, limit: int, offset: int,
                  status: int = 200) -> Tuple[dict, int]:
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return success_response(items, status=status, response_type="array", pagination=pagination)


def error_response(error_id: str, message: str, http_status: int) -> Tuple[dict, int]:
    return {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }, http_status
