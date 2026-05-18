"""Shared parsing & validation helpers."""
from __future__ import annotations

from typing import Any, Iterable

from flask import request

from .errors import ApiError


def parse_json_body() -> dict[str, Any]:
    """Parse JSON body; tolerate empty body for action endpoints."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception as exc:  # noqa: BLE001
        raise ApiError("ERR_INVALID_REQUEST", f"Malformed JSON: {exc}", 400)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.", 400)
    return body


def require_field(body: dict[str, Any], field: str, *, types: Iterable[type] | None = None) -> Any:
    if field not in body:
        raise ApiError("ERR_INVALID_REQUEST", f"Missing required field '{field}'.", 400)
    value = body[field]
    if types is not None and not isinstance(value, tuple(types)):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            f"Field '{field}' must be of type {[t.__name__ for t in types]}.",
            400,
        )
    return value


def opt_field(body: dict[str, Any], field: str, *, types: Iterable[type] | None = None) -> Any:
    if field not in body:
        return None
    value = body[field]
    if value is None:
        return None
    if types is not None and not isinstance(value, tuple(types)):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            f"Field '{field}' must be of type {[t.__name__ for t in types]}.",
            400,
        )
    return value


def parse_pagination() -> tuple[int, int]:
    """limit (1..100, default 10), offset (>=0, default 0)."""
    args = request.args
    try:
        limit = int(args.get("limit", 10))
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "limit/offset must be integers.", 400)
    if limit < 1 or limit > 100:
        raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.", 400)
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", "offset must be >= 0.", 400)
    return limit, offset


def check_occ(stored: dict[str, Any], body: dict[str, Any]) -> None:
    """Per PRD §2.6: when client provides `version`, compare it.

    Mismatch -> ERR_INVALID_STATE_TRANSITION (409). When omitted, no check.
    """
    if "version" not in body or body.get("version") is None:
        return
    client_version = body["version"]
    if not isinstance(client_version, int) or isinstance(client_version, bool):
        raise ApiError("ERR_INVALID_REQUEST", "version must be an integer.", 400)
    if client_version != stored.get("version"):
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Optimistic concurrency check failed; resource has been modified.",
            409,
        )
