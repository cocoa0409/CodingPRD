"""Cross-cutting route helpers: pagination, sorting, body retrieval."""
from __future__ import annotations

from flask import request

from errors import invalid_request


def get_json_body() -> dict:
    body = request.get_json(silent=True)
    if body is None:
        # Empty body is allowed for action endpoints. Treat as {}.
        return {}
    if not isinstance(body, dict):
        raise invalid_request("Request body must be a JSON object")
    return body


def parse_pagination():
    """PRD §2.3: limit defaults to 10 (min 1, max 100); offset defaults to 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise invalid_request("limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise invalid_request("offset must be an integer")
    if limit < 1 or limit > 100:
        raise invalid_request("limit must be between 1 and 100")
    if offset < 0:
        raise invalid_request("offset must be >= 0")
    return limit, offset


def sort_by_created_at(rows: list) -> list:
    return sorted(rows, key=lambda r: r.get("created_at", ""))


def slice_page(rows: list, limit: int, offset: int) -> tuple[list, int]:
    return rows[offset : offset + limit], len(rows)
