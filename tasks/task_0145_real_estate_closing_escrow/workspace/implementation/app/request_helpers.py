"""Request-side helpers shared by route modules."""
from __future__ import annotations

from typing import Any, Dict, Tuple

from flask import request

from app.errors import ApiError


def get_json_body() -> Dict[str, Any]:
    """Return the JSON body as a dict.

    For endpoints that may legitimately have no body (e.g., /fund with no
    version), return an empty dict if the body is missing or empty. Reject
    explicitly malformed JSON or non-object bodies with ERR_BAD_REQUEST.
    """
    if not request.data:
        return {}
    try:
        body = request.get_json(silent=False)
    except Exception as exc:
        raise ApiError("ERR_BAD_REQUEST", "Malformed JSON body.") from exc
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_BAD_REQUEST", "Request body must be a JSON object.")
    return body


def get_pagination() -> Tuple[int, int]:
    """Return ``(limit, offset)`` per §2.3, raising ERR_BAD_REQUEST on misuse."""
    limit_raw = request.args.get("limit", "10")
    offset_raw = request.args.get("offset", "0")
    try:
        limit = int(limit_raw)
        offset = int(offset_raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_BAD_REQUEST", "limit/offset must be integers.")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_BAD_REQUEST", "limit must be between 1 and 100.")
    if offset < 0:
        raise ApiError("ERR_BAD_REQUEST", "offset must be >= 0.")
    return limit, offset


def check_version(row: Dict[str, Any], body: Dict[str, Any]) -> None:
    """Optimistic concurrency check.

    If the request body supplies ``version``, it must equal the row's current
    version. When absent, the check is skipped.
    """
    if "version" in body and body["version"] is not None:
        if not isinstance(body["version"], int) or isinstance(body["version"], bool):
            raise ApiError("ERR_BAD_REQUEST", "version must be an integer.")
        if int(body["version"]) != int(row.get("version", 1)):
            raise ApiError(
                "ERR_VERSION_MISMATCH",
                f"Expected version {row.get('version', 1)}, got {body['version']}.",
            )
