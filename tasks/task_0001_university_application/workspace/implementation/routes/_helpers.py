"""Shared route helpers: pagination parsing, body validation, ownership check."""
from __future__ import annotations

from typing import Any, Optional
from flask import request

from errors import APIError, ERR_INVALID_REQUEST, ERR_FORBIDDEN_OWNER_MISMATCH


def parse_pagination():
    limit = request.args.get("limit", "10")
    offset = request.args.get("offset", "0")
    try:
        limit_i = int(limit)
        offset_i = int(offset)
    except (TypeError, ValueError):
        raise APIError(ERR_INVALID_REQUEST, 400, "limit/offset must be integers")
    if limit_i < 1 or limit_i > 100:
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


def assert_owner(applicant_id: str, caller_role: str, caller_user_id: str):
    if caller_role == "Applicant" and caller_user_id != applicant_id:
        raise APIError(ERR_FORBIDDEN_OWNER_MISMATCH, 403, "Caller does not own this resource")


def order_by_created_at(items: list) -> list:
    return sorted(items, key=lambda x: x["created_at"])
