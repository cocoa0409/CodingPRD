"""Shared helpers: record creation, version bumping, serialization, pagination,
request-body parsing, and validation primitives.

Per PRD §2.4: every primary resource carries id (UUID, no prefix), created_at,
updated_at (ISO 8601 UTC, 3 fractional digits), and an integer version starting
at 1 and incrementing by exactly one on every mutation. created_at is fixed at
creation and is the canonical ordering key (realized via the _seq counter).
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from flask import request

import db
from errors import err

# Internal bookkeeping keys not exposed in API responses.
_INTERNAL = {"_seq"}


def new_record(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Build a fresh record with system-managed common fields."""
    ts = db.now_iso()
    rec = {
        "id": db.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    rec.update(fields)
    return rec


def touch(rec: Dict[str, Any]) -> None:
    """Apply a mutation: bump version by one and refresh updated_at (PRD §2.4)."""
    rec["version"] += 1
    rec["updated_at"] = db.now_iso()


def serialize(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Public projection of a record (strips internal bookkeeping)."""
    return {k: v for k, v in rec.items() if k not in _INTERNAL}


# ---- request body / query parsing -------------------------------------------

def get_json_body() -> Dict[str, Any]:
    """Return the parsed JSON object body, or {} when absent.

    A body that is present but not a JSON object is an invalid request.
    """
    if request.content_length in (None, 0) and not (request.data or b"").strip():
        return {}
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def require_str(body: Dict[str, Any], field: str) -> str:
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        err("ERR_INVALID_REQUEST", f"Field '{field}' must be a non-empty string")
    return v


def require_present(body: Dict[str, Any], field: str) -> Any:
    if field not in body or body[field] is None:
        err("ERR_INVALID_REQUEST", f"Field '{field}' is required")
    return body[field]


def is_int(v: Any) -> bool:
    """True bool is rejected (Python bool is a subclass of int)."""
    return isinstance(v, int) and not isinstance(v, bool)


def optional_int(body: Dict[str, Any], field: str, default: int) -> int:
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not is_int(v):
        err("ERR_INVALID_REQUEST", f"Field '{field}' must be an integer")
    return v


def require_int(body: Dict[str, Any], field: str) -> int:
    v = require_present(body, field)
    if not is_int(v):
        err("ERR_INVALID_REQUEST", f"Field '{field}' must be an integer")
    return v


def require_enum(body: Dict[str, Any], field: str, allowed: Iterable[str]) -> str:
    v = require_present(body, field)
    if not isinstance(v, str) or v not in set(allowed):
        err("ERR_INVALID_REQUEST", f"Field '{field}' must be one of {sorted(allowed)}")
    return v


# ---- existence helpers ------------------------------------------------------

def path_lookup(store: Dict[str, Dict[str, Any]], rid: str) -> Dict[str, Any]:
    """Path-referenced existence (ERR_NOT_FOUND, 404)."""
    rec = store.get(rid)
    if rec is None:
        err("ERR_NOT_FOUND", "Resource not found")
    return rec


def fk_lookup(store: Dict[str, Dict[str, Any]], fk_id: Any) -> Dict[str, Any]:
    """Body FK existence (ERR_REFERENCED_ENTITY_NOT_FOUND, 422)."""
    if not isinstance(fk_id, str) or fk_id not in store:
        err("ERR_REFERENCED_ENTITY_NOT_FOUND", "Referenced entity not found")
    return store[fk_id]


# ---- pagination + list helpers ----------------------------------------------

def parse_pagination():
    """limit default 10, min 1, max 100; offset default 0 (PRD §2.3).

    Out-of-range / malformed values are clamped rather than erroring; the PRD
    defines defaults/min/max without specifying a rejection path.
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            limit = 10
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            offset = 0
        if offset < 0:
            offset = 0
    return limit, offset


def ordered(store: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """All records sorted by created_at ASC (via the monotonic _seq)."""
    return sorted(store.values(), key=lambda r: r["_seq"])


def paginate(items: List[Dict[str, Any]]):
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset: offset + limit]
    return [serialize(r) for r in page], limit, offset, total
