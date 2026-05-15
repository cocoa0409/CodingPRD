"""Common route helpers."""
from __future__ import annotations

from typing import Any, Optional

from flask import jsonify, request

from ..auth import current_actor, verify_borrower_ownership
from ..errors import ApiError
from ..response import success_envelope
from ..store import get_store


def get_json_body(allow_empty: bool = True) -> dict[str, Any]:
    """Parse the request JSON body; tolerate missing body for endpoints that accept none."""
    if request.method == "GET":
        return {}
    if not request.data:
        if allow_empty:
            return {}
        raise ApiError("ERR_INVALID_INPUT", "Request body required.")
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_INPUT", "Invalid JSON body.")
    if body is None:
        if allow_empty:
            return {}
        raise ApiError("ERR_INVALID_INPUT", "Request body required.")
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_INPUT", "Body must be a JSON object.")
    return body


def ok(data, status: int = 200, response_type: str = "object", pagination: dict[str, Any] | None = None):
    body = success_envelope(data, response_type=response_type, pagination=pagination)
    return jsonify(body), status


def created(data):
    return ok(data, status=201)


def list_ok(items, pagination):
    return ok(items, response_type="array", pagination=pagination)


def get_borrower_or_404(borrower_id: str) -> dict[str, Any]:
    store = get_store()
    b = store.borrowers.get(borrower_id)
    if not b:
        raise ApiError("ERR_BORROWER_NOT_FOUND", f"Borrower {borrower_id} not found.")
    verify_borrower_ownership(borrower_id)
    return b


def check_version_or_conflict(entity: dict[str, Any], body: dict[str, Any]) -> None:
    """If `version` is in the body, compare to entity['version'] and raise on mismatch."""
    if "version" not in body:
        return
    try:
        provided = int(body["version"])
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_INPUT", "version must be an integer.")
    if provided != int(entity.get("version", 0)):
        raise ApiError("ERR_VERSION_CONFLICT", "Stale version on PATCH.")
