"""Shared route helpers: pagination parsing, body access, schema validation,
common-field stamping, and list serialization.

Body schema violations raise ERR_INVALID_REQUEST (422, PRD §2.9). Pagination
bounds violations raise ERR_VALIDATION_OUT_OF_RANGE (422, PRD §2.3).
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

from flask import request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_VALIDATION_OUT_OF_RANGE,
)

PAGE_DEFAULT = 10
PAGE_MIN = 1
PAGE_MAX = 100
OFFSET_DEFAULT = 0


def parse_pagination():
    """limit default 10 (min 1, max 100), offset default 0, >= 0.

    Out-of-range or non-integer values -> ERR_VALIDATION_OUT_OF_RANGE (422).
    """
    limit_raw = request.args.get("limit", str(PAGE_DEFAULT))
    offset_raw = request.args.get("offset", str(OFFSET_DEFAULT))
    try:
        limit = int(limit_raw)
        offset = int(offset_raw)
    except (TypeError, ValueError):
        raise APIError(ERR_VALIDATION_OUT_OF_RANGE, 422, "limit/offset must be integers")
    if limit < PAGE_MIN or limit > PAGE_MAX:
        raise APIError(ERR_VALIDATION_OUT_OF_RANGE, 422, "limit must be in [1,100]")
    if offset < 0:
        raise APIError(ERR_VALIDATION_OUT_OF_RANGE, 422, "offset must be >= 0")
    return limit, offset


def paginate(items: list, limit: int, offset: int):
    total = len(items)
    return items[offset:offset + limit], total


def get_body() -> dict:
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise APIError(ERR_INVALID_REQUEST, 422, "Body must be a JSON object")
    return body


def require_fields(body: dict, fields: Iterable[str]):
    for f in fields:
        if f not in body or body[f] is None:
            raise APIError(ERR_INVALID_REQUEST, 422, f"Missing required field: {f}")


def require_str(body: dict, field: str, allow_empty: bool = False) -> str:
    v = body.get(field)
    if not isinstance(v, str):
        raise APIError(ERR_INVALID_REQUEST, 422, f"{field} must be a string")
    if not allow_empty and v.strip() == "":
        raise APIError(ERR_INVALID_REQUEST, 422, f"{field} must be non-empty")
    return v


def require_enum(body: dict, field: str, allowed: Iterable[str]) -> str:
    v = body.get(field)
    if v not in set(allowed):
        raise APIError(ERR_INVALID_REQUEST, 422, f"{field} must be one of {sorted(set(allowed))}")
    return v


def require_int(body: dict, field: str, minimum: Optional[int] = None,
                maximum: Optional[int] = None) -> int:
    v = body.get(field)
    # bool is a subclass of int; reject it explicitly
    if isinstance(v, bool) or not isinstance(v, int):
        raise APIError(ERR_INVALID_REQUEST, 422, f"{field} must be an integer")
    if minimum is not None and v < minimum:
        raise APIError(ERR_INVALID_REQUEST, 422, f"{field} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise APIError(ERR_INVALID_REQUEST, 422, f"{field} must be <= {maximum}")
    return v


def optional_int(body: dict, field: str, default: int, minimum: Optional[int] = None,
                 maximum: Optional[int] = None) -> int:
    if field not in body or body[field] is None:
        return default
    return require_int(body, field, minimum, maximum)


def require_bool(body: dict, field: str) -> bool:
    v = body.get(field)
    if not isinstance(v, bool):
        raise APIError(ERR_INVALID_REQUEST, 422, f"{field} must be a boolean")
    return v


def optional_bool(body: dict, field: str, default: bool) -> bool:
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise APIError(ERR_INVALID_REQUEST, 422, f"{field} must be a boolean")
    return v


def optional_str(body: dict, field: str, default: Any = None) -> Any:
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        raise APIError(ERR_INVALID_REQUEST, 422, f"{field} must be a string")
    return v


# ---- common system fields ----------------------------------------------------
def stamp_create(record: dict, full: bool = True) -> dict:
    """Set id/created_at (+ updated_at/version when full). Adds a _seq sort key.

    full=False is used for FeeTransaction and AuditEvent: immutable event-log
    records carrying only id + created_at (PRD §2.4).
    """
    now = db.wall_now_iso()
    record["id"] = db.new_uuid()
    record["created_at"] = now
    record["_seq"] = db.next_seq()
    if full:
        record["updated_at"] = now
        record["version"] = 1
    return record


def touch(record: dict) -> None:
    """Mutation bump: refresh updated_at and increment version (full entities)."""
    if "version" in record:
        record["version"] += 1
    if "updated_at" in record:
        record["updated_at"] = db.wall_now_iso()


# ---- serialization (strip internal keys) -------------------------------------
_INTERNAL = {"_seq"}


def serialize(record: dict) -> dict:
    return {k: v for k, v in record.items() if k not in _INTERNAL}


def serialize_list(records: list) -> list:
    return [serialize(r) for r in records]


def order_by_created(items: Iterable[dict]) -> list:
    return sorted(items, key=lambda r: (r["created_at"], r.get("_seq", 0)))
