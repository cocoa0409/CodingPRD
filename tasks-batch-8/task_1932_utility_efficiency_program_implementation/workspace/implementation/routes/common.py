"""Shared helpers for route handlers."""

from __future__ import annotations

from flask import request

import db
import errors
from response import success_list


def get_body() -> dict:
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.ApiError(errors.ERR_INVALID_INSPECTION_PAYLOAD, "Request body must be a JSON object", 400)
    return body


def paginate(items: list):
    """Apply limit/offset parsing (defaults 10/0, min 1, max 100) and return a
    Flask response tuple for the slice."""
    try:
        limit_raw = request.args.get("limit", None)
        offset_raw = request.args.get("offset", None)
        limit = int(limit_raw) if limit_raw is not None else 10
        offset = int(offset_raw) if offset_raw is not None else 0
    except (TypeError, ValueError):
        raise errors.ApiError(errors.ERR_INVALID_INSPECTION_PAYLOAD, "Invalid pagination parameters", 400)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    ordered = sorted(items, key=lambda r: (r.get("created_at") or "", r.get("id") or ""))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return success_list(page, limit=limit, offset=offset, total_count=total)


def fetch_or_404(store: dict, key: str, label: str = "Resource"):
    obj = store.get(key)
    if obj is None:
        raise errors.not_found(f"{label} {key} not found")
    return obj


def ref_or_404(store: dict, key, label: str):
    """Body-referenced FK check."""
    if key is None:
        raise errors.referenced_not_found(f"{label} is required")
    obj = store.get(key)
    if obj is None:
        raise errors.referenced_not_found(f"Referenced {label} {key} not found")
    return obj
