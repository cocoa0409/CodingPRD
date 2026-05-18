"""Shared helpers for route modules."""
from __future__ import annotations

from flask import request

from config import DEFAULT_LIMIT, DEFAULT_OFFSET, MAX_LIMIT, MIN_LIMIT
from errors import (
    err_pagination_invalid,
    err_version_conflict,
)


def get_json() -> dict:
    """Return the request JSON body (always a dict, tolerates empty bodies)."""
    if request.is_json:
        body = request.get_json(silent=True)
    else:
        data = request.get_data(as_text=True)
        if not data.strip():
            return {}
        try:
            import json
            body = json.loads(data)
        except Exception:
            body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        return {}
    return body


def parse_pagination():
    """Read limit/offset from query string, validate per SCAFFOLD §1.4.24.

    Raises ERR_PAGINATION_INVALID (422) when limit/offset are syntactically
    present but out of bounds (or non-integer). Defaults apply if omitted.
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err_pagination_invalid("limit must be an integer.")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise err_pagination_invalid(
                f"limit must be in [{MIN_LIMIT},{MAX_LIMIT}]; got {limit}."
            )

    if offset_raw is None:
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err_pagination_invalid("offset must be an integer.")
        if offset < 0:
            raise err_pagination_invalid("offset must be >= 0.")

    return limit, offset


def paginate(items: list, limit: int, offset: int) -> list:
    return items[offset:offset + limit]


def sort_by_created_at(items):
    return sorted(items, key=lambda x: x.get("created_at", ""))


def parse_version(body: dict):
    if not isinstance(body, dict):
        return None
    if "version" not in body:
        return None
    v = body["version"]
    if v is None:
        return None
    if isinstance(v, bool):
        raise err_version_conflict("Invalid version value.")
    if isinstance(v, int):
        return v
    try:
        return int(v)
    except (TypeError, ValueError):
        raise err_version_conflict("Invalid version value.")


def check_version(entity: dict, expected) -> None:
    if expected is None:
        return
    if entity.get("version") != expected:
        raise err_version_conflict()
