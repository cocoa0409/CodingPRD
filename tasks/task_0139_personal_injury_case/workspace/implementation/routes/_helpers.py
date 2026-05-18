"""Per-request helpers for routes: body parsing, pagination, sorting."""
from __future__ import annotations

from flask import request

from config import DEFAULT_LIMIT, DEFAULT_OFFSET, MAX_LIMIT, MIN_LIMIT
from errors import raise_error


def get_json_body() -> dict:
    """Read the request body as JSON; treat missing/empty as {}.

    Reject bodies that are arrays or scalars — only object bodies are valid
    for this API.
    """
    if not request.data:
        return {}
    try:
        body = request.get_json(force=False, silent=False)
    except Exception:
        raise_error("ERR_VALIDATION", "Request body must be valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_error("ERR_VALIDATION", "Request body must be a JSON object.")
    return body


def get_pagination_args() -> tuple[int, int]:
    """Read `limit` and `offset` query params. Apply defaults + bounds."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None or raw_limit == "":
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_error("ERR_VALIDATION", "limit must be an integer.")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise_error(
                "ERR_VALIDATION",
                f"limit must be in [{MIN_LIMIT}, {MAX_LIMIT}].",
            )

    if raw_offset is None or raw_offset == "":
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_error("ERR_VALIDATION", "offset must be an integer.")
        if offset < 0:
            raise_error("ERR_VALIDATION", "offset must be non-negative.")

    return limit, offset


def paginate(items: list, limit: int, offset: int) -> tuple[list, int]:
    """Return the page slice + total_count."""
    total = len(items)
    return items[offset:offset + limit], total


def require_field(body: dict, field: str, *, allow_zero: bool = False):
    """Return the value of `field` in `body`, raising ERR_VALIDATION if absent.

    Empty strings are treated as missing. `None` is missing unless allow_zero=True
    and the user explicitly intends a None default.
    """
    if field not in body:
        raise_error("ERR_VALIDATION", f"Missing required field: {field}.")
    value = body[field]
    if value is None:
        raise_error("ERR_VALIDATION", f"Field {field} cannot be null.")
    if isinstance(value, str) and value.strip() == "":
        raise_error("ERR_VALIDATION", f"Field {field} cannot be empty.")
    return value
