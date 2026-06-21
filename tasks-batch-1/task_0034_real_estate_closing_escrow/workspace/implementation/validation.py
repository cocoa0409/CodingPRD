"""Body-shape and pagination validation helpers (PRD §2.3, §2.10 priority 21)."""
from __future__ import annotations

from typing import Any

from flask import request

from errors import ERR_INVALID_REQUEST, err


def get_json_body() -> dict:
    """Return parsed JSON body (or {} when empty). Reject malformed JSON / non-object bodies."""
    if request.method in ("GET", "DELETE"):
        return {}
    raw = request.get_data(cache=True, as_text=True)
    if not raw or raw.strip() == "":
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception as exc:  # noqa: BLE001
        raise err(ERR_INVALID_REQUEST, "malformed JSON body") from exc
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return body


def require_fields(body: dict, fields: list[str]) -> None:
    missing = [f for f in fields if f not in body or body[f] is None]
    if missing:
        raise err(ERR_INVALID_REQUEST, f"missing required field(s): {','.join(missing)}")


def require_str(body: dict, key: str, *, allow_empty: bool = False) -> str:
    v = body.get(key)
    if not isinstance(v, str):
        raise err(ERR_INVALID_REQUEST, f"{key} must be a string")
    if not allow_empty and v == "":
        raise err(ERR_INVALID_REQUEST, f"{key} must be non-empty")
    return v


def require_int(body: dict, key: str) -> int:
    v = body.get(key)
    # Booleans are ints in Python; explicitly disallow because PRD distinguishes booleans.
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, f"{key} must be an integer")
    return v


def require_bool(body: dict, key: str) -> bool:
    v = body.get(key)
    if not isinstance(v, bool):
        raise err(ERR_INVALID_REQUEST, f"{key} must be a boolean")
    return v


def require_enum(body: dict, key: str, allowed: set[str]) -> str:
    v = body.get(key)
    if not isinstance(v, str) or v not in allowed:
        raise err(ERR_INVALID_REQUEST, f"{key} must be one of {sorted(allowed)}")
    return v


def parse_pagination() -> tuple[int, int]:
    """Read & validate `limit` and `offset` query params (PRD §2.3)."""
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    try:
        limit = int(limit_raw) if limit_raw is not None else 10
        offset = int(offset_raw) if offset_raw is not None else 0
    except (TypeError, ValueError) as exc:
        raise err(ERR_INVALID_REQUEST, "limit/offset must be integers") from exc
    if limit < 1 or limit > 100:
        raise err(ERR_INVALID_REQUEST, "limit must be in [1, 100]")
    if offset < 0:
        raise err(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def get_optional_query(name: str) -> Any:
    return request.args.get(name)


def paginate(items: list, limit: int, offset: int) -> tuple[list, int]:
    total = len(items)
    return items[offset : offset + limit], total
