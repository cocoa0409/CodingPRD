"""Shared helpers for route modules — body parsing, pagination, OCC."""
from __future__ import annotations

from flask import request

from config import DEFAULT_LIMIT, DEFAULT_OFFSET, MAX_LIMIT, MIN_LIMIT
from errors import err_invalid_request, err_version_conflict


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
    """Read limit/offset from query string.

    Per PRD §2.3: limit defaults 10, min 1, max 100; offset defaults 0.
    Out-of-bounds → ERR_INVALID_REQUEST (400).
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err_invalid_request("limit must be an integer.")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise err_invalid_request(
                f"limit must be in [{MIN_LIMIT},{MAX_LIMIT}]; got {limit}."
            )

    if offset_raw is None:
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err_invalid_request("offset must be an integer.")
        if offset < 0:
            raise err_invalid_request("offset must be >= 0.")

    return limit, offset


def paginate(items: list, limit: int, offset: int) -> list:
    return items[offset:offset + limit]


def sort_by_created_at(items):
    return sorted(items, key=lambda x: x.get("created_at"))


def parse_version(body: dict):
    if not isinstance(body, dict) or "version" not in body:
        return None
    v = body["version"]
    if v is None:
        return None
    if isinstance(v, bool):
        raise err_invalid_request("Invalid version value.")
    if isinstance(v, int):
        return v
    try:
        return int(v)
    except (TypeError, ValueError):
        raise err_invalid_request("Invalid version value.")


def check_version(entity: dict, expected) -> None:
    if expected is None:
        return
    if entity.get("version") != expected:
        raise err_version_conflict()


def require_int(value, field_name: str, *, allow_zero: bool = True):
    """Validate that value is an integer (not a bool, not a float).

    Raises ERR_INVALID_REQUEST if not.
    """
    if value is None:
        raise err_invalid_request(f"{field_name} is required.")
    if isinstance(value, bool) or not isinstance(value, int):
        raise err_invalid_request(f"{field_name} must be an integer.")
    if not allow_zero and value <= 0:
        raise err_invalid_request(f"{field_name} must be positive.")
    return value


def require_non_negative_int(value, field_name: str):
    require_int(value, field_name)
    if value < 0:
        raise err_invalid_request(f"{field_name} must be >= 0.")
    return value


def require_str(value, field_name: str, *, min_length: int = 1):
    if not isinstance(value, str) or len(value) < min_length:
        raise err_invalid_request(f"{field_name} is required (string).")
    return value
