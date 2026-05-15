"""Common request validation / OCC helpers."""
from typing import Any

from flask import request

from .errors import ApiError


def get_json_body() -> dict:
    if not request.is_json:
        # Allow empty body for endpoints that take no input.
        if request.content_length in (0, None):
            return {}
    try:
        body = request.get_json(silent=True)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return body


def require_fields(body: dict, fields: list[str]):
    missing = [f for f in fields if f not in body or body[f] is None]
    if missing:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            f"Missing required field(s): {', '.join(missing)}",
        )


def require_non_empty_string(body: dict, field: str):
    v = body.get(field)
    if not isinstance(v, str) or v.strip() == "":
        raise ApiError("ERR_INVALID_REQUEST", f"Field '{field}' must be a non-empty string.")


def require_int(body: dict, field: str) -> int:
    v = body.get(field)
    if not isinstance(v, int) or isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", f"Field '{field}' must be an integer.")
    return v


def require_enum(body: dict, field: str, allowed: list[str]) -> str:
    v = body.get(field)
    if v not in allowed:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            f"Field '{field}' must be one of {allowed}.",
        )
    return v


def check_version_if_provided(body: dict, record: dict):
    """Optimistic-concurrency: if 'version' is in the body, must match stored value."""
    if "version" in body and body["version"] is not None:
        v = body["version"]
        if not isinstance(v, int) or isinstance(v, bool):
            raise ApiError("ERR_INVALID_REQUEST", "Field 'version' must be an integer.")
        if int(v) != int(record.get("version", -1)):
            raise ApiError("ERR_INVALID_REQUEST", "Version mismatch (optimistic concurrency).")
