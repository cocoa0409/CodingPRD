"""Shared helpers: body parsing/validation, common system fields, pagination,
serialization, and FK existence resolution (PRD §2.3, §2.4, §2.8)."""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from flask import request

import db
from errors import APIError, ERR_VALIDATION


# ---------------------------------------------------------------------------
# Request body parsing
# ---------------------------------------------------------------------------
def get_json_body() -> Dict[str, Any]:
    """Return the parsed JSON object body, or {} for an empty body.

    A body that is present but not a JSON object -> ERR_VALIDATION.
    """
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise APIError(ERR_VALIDATION, 422, "Request body is not valid JSON")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise APIError(ERR_VALIDATION, 422, "Request body must be a JSON object")
    return data


def require_fields(body: Dict[str, Any], fields: Iterable[str]) -> None:
    for f in fields:
        if body.get(f) is None:
            raise APIError(ERR_VALIDATION, 422, f"Missing required field: {f}")


def require_string(body: Dict[str, Any], field: str) -> str:
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise APIError(ERR_VALIDATION, 422, f"Field {field} must be a non-empty string")
    return v


def require_int(body: Dict[str, Any], field: str) -> int:
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise APIError(ERR_VALIDATION, 422, f"Field {field} must be an integer")
    return v


def optional_int(body: Dict[str, Any], field: str, default: int) -> int:
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise APIError(ERR_VALIDATION, 422, f"Field {field} must be an integer")
    return v


def optional_bool(body: Dict[str, Any], field: str, default: bool) -> bool:
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not isinstance(v, bool):
        raise APIError(ERR_VALIDATION, 422, f"Field {field} must be a boolean")
    return v


def require_enum(body: Dict[str, Any], field: str, choices: Iterable[str]) -> str:
    v = body.get(field)
    if v not in set(choices):
        raise APIError(ERR_VALIDATION, 422, f"Field {field} must be one of {sorted(set(choices))}")
    return v


# ---------------------------------------------------------------------------
# Common system fields (PRD §2.4)
# ---------------------------------------------------------------------------
def new_common_fields(versioned: bool = True) -> Dict[str, Any]:
    ts = db.now_iso()
    rec: Dict[str, Any] = {
        "id": db.new_uuid(),
        "created_at": ts,
        "_seq": db.next_seq(),
    }
    if versioned:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec: Dict[str, Any]) -> None:
    """A mutation refreshes updated_at and increments version (PRD §2.4)."""
    if "version" in rec:
        rec["updated_at"] = db.now_iso()
        rec["version"] = rec["version"] + 1


# ---------------------------------------------------------------------------
# Serialization — strip private keys (those starting with '_')
# ---------------------------------------------------------------------------
def serialize(rec: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def parse_pagination() -> tuple[int, int]:
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    limit = 10
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise APIError(ERR_VALIDATION, 422, "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100

    offset = 0
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise APIError(ERR_VALIDATION, 422, "offset must be an integer")
        if offset < 0:
            offset = 0

    return limit, offset


def paginate(records: list) -> tuple[list, int, int, int]:
    """Sort ascending by creation order, apply limit/offset.

    Returns (page_items_serialized, limit, offset, total_count).
    """
    ordered = sorted(records, key=lambda r: r["_seq"])
    total = len(ordered)
    limit, offset = parse_pagination()
    page = ordered[offset:offset + limit]
    return [serialize(r) for r in page], limit, offset, total


# ---------------------------------------------------------------------------
# Existence resolution (PRD §2.8) — raises the matching not-found error.
# ---------------------------------------------------------------------------
def resolve(store: Dict[str, Dict[str, Any]], rid: Optional[str], error_id: str) -> Dict[str, Any]:
    rec = store.get(rid) if rid is not None else None
    if rec is None:
        raise APIError(error_id, 404, f"{error_id}")
    return rec
