"""Shared route helpers: pagination, body parsing, field/type validation, ordering."""
from __future__ import annotations

from typing import Any
from flask import request

from errors import APIError, ERR_INVALID_REQUEST

# Pagination defaults (PRD §2.3 / SCAFFOLD response_envelope.pagination_defaults).
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def parse_pagination():
    limit = request.args.get("limit", str(DEFAULT_LIMIT))
    offset = request.args.get("offset", str(DEFAULT_OFFSET))
    try:
        limit_i = int(limit)
        offset_i = int(offset)
    except (TypeError, ValueError):
        raise APIError(ERR_INVALID_REQUEST, 400, "limit/offset must be integers")
    if limit_i < MIN_LIMIT or limit_i > MAX_LIMIT:
        raise APIError(ERR_INVALID_REQUEST, 400, "limit must be in [1,100]")
    if offset_i < 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "offset must be >= 0")
    return limit_i, offset_i


def paginate(items: list, limit: int, offset: int):
    total = len(items)
    return items[offset:offset + limit], total


def get_body() -> dict:
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise APIError(ERR_INVALID_REQUEST, 400, "Body must be a JSON object")
    return body


def require_fields(body: dict, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise APIError(ERR_INVALID_REQUEST, 400, f"Missing required field: {f}")


def is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def is_str(v: Any) -> bool:
    return isinstance(v, str)


def is_bool(v: Any) -> bool:
    return isinstance(v, bool)


def order_by_created(items: list) -> list:
    """Ascending creation order (PRD §2.3). Uses the monotonic _seq tiebreaker."""
    return sorted(items, key=lambda x: (x["created_at"], x.get("_seq", 0)))


def serialize(entity: dict) -> dict:
    """Public view: drop internal-only keys (prefixed with '_')."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def serialize_list(items: list) -> list:
    return [serialize(e) for e in items]
