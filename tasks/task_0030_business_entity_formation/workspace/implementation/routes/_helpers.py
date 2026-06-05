"""Route helpers: pagination parsing, sorting, JSON body parsing."""
from __future__ import annotations

from flask import request

import errors


def parse_pagination():
    """Parse limit/offset query parameters per PRD §2.3."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise errors.err_invalid_request("limit must be an integer.")
        if limit < 1 or limit > 100:
            raise errors.err_invalid_request("limit must be in 1..100.")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise errors.err_invalid_request("offset must be an integer.")
        if offset < 0:
            raise errors.err_invalid_request("offset must be >= 0.")
    return limit, offset


def parse_json_body_optional() -> dict:
    """Parse JSON body; return {} if body is empty."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.err_invalid_request("Body must be valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.err_invalid_request("Body must be a JSON object.")
    return body


def parse_json_body_required() -> dict:
    body = parse_json_body_optional()
    if not body:
        raise errors.err_invalid_request("Request body required.")
    return body


def sort_by_created(items: list) -> list:
    """Stable sort by created_at ascending (PRD §2.3) — _created_seq matches order."""
    return sorted(items, key=lambda r: r.get("_created_seq", 0))


def sort_events(items: list) -> list:
    return sorted(items, key=lambda r: r.get("_created_seq", 0))
