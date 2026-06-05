"""Common-field stamping and request-body field validation helpers.

Common resource properties (PRD §2.4):
  - id: server-minted UUID, no type prefix
  - created_at: ISO-8601 UTC, 3 fractional digits
  - updated_at: ISO-8601 UTC, 3 fractional digits
  - version: integer starting at 1, +1 on every mutation
FplSchedule is the deliberate exception: only id + created_at (no updated_at,
no version).
"""
from __future__ import annotations

from typing import Any, Optional

import db
from errors import APIError, ERR_INVALID_REQUEST, ERR_NOT_FOUND


def stamp_create(rec: dict, *, versioned: bool = True) -> dict:
    """Populate id/created_at and (when versioned) updated_at/version."""
    ts = db.now_iso()
    rec["id"] = db.new_uuid()
    rec["created_at"] = ts
    if versioned:
        rec["updated_at"] = ts
        rec["version"] = 1
    # Hidden ordering key, stripped on serialize.
    rec["_seq"] = db.next_seq()
    return rec


def touch(rec: dict) -> None:
    """Bump updated_at + version on a mutation (PRD §2.4 / §2.5 cascade rule)."""
    rec["updated_at"] = db.now_iso()
    rec["version"] = rec.get("version", 1) + 1


def serialize(rec: dict) -> dict:
    """Public view of a record: drop private keys (those starting with '_')."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def serialize_list(recs: list) -> list:
    return [serialize(r) for r in recs]


def sort_by_created(recs: list) -> list:
    """Ascending by created_at, tie-broken by insertion sequence (PRD §2.3)."""
    return sorted(recs, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))


# --- Body field validation (priority 4: ERR_INVALID_REQUEST, 422) -----------

def require(body: dict, field: str) -> Any:
    if field not in body or body[field] is None:
        raise APIError(ERR_INVALID_REQUEST, 422, f"Missing required field: {field}")
    return body[field]


def require_str(body: dict, field: str) -> str:
    val = require(body, field)
    if not isinstance(val, str) or val == "":
        raise APIError(ERR_INVALID_REQUEST, 422, f"Field {field} must be a non-empty string")
    return val


def require_bool(body: dict, field: str) -> bool:
    val = require(body, field)
    if not isinstance(val, bool):
        raise APIError(ERR_INVALID_REQUEST, 422, f"Field {field} must be a boolean")
    return val


def optional_bool(body: dict, field: str, default: bool) -> bool:
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise APIError(ERR_INVALID_REQUEST, 422, f"Field {field} must be a boolean")
    return val


def require_int(body: dict, field: str, *, non_negative: bool = False) -> int:
    val = require(body, field)
    # bool is a subclass of int; reject it explicitly.
    if isinstance(val, bool) or not isinstance(val, int):
        raise APIError(ERR_INVALID_REQUEST, 422, f"Field {field} must be an integer")
    if non_negative and val < 0:
        raise APIError(ERR_INVALID_REQUEST, 422, f"Field {field} must be non-negative")
    return val


def optional_int(body: dict, field: str, default: Optional[int], *, non_negative: bool = False) -> Optional[int]:
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise APIError(ERR_INVALID_REQUEST, 422, f"Field {field} must be an integer")
    if non_negative and val < 0:
        raise APIError(ERR_INVALID_REQUEST, 422, f"Field {field} must be non-negative")
    return val


def require_enum(body: dict, field: str, allowed: set) -> str:
    val = require(body, field)
    if not isinstance(val, str) or val not in allowed:
        raise APIError(ERR_INVALID_REQUEST, 422, f"Field {field} must be one of {sorted(allowed)}")
    return val


def optional_enum(body: dict, field: str, allowed: set, default: str) -> str:
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str) or val not in allowed:
        raise APIError(ERR_INVALID_REQUEST, 422, f"Field {field} must be one of {sorted(allowed)}")
    return val


def require_str_field(body: dict, field: str) -> str:
    """A required ISO datetime / string passthrough (well-formedness only)."""
    return require_str(body, field)


# --- Existence lookups (priority 3: ERR_NOT_FOUND, 404) ----------------------

def get_or_404(store: dict, key: Any, what: str = "resource") -> dict:
    rec = store.get(key)
    if rec is None:
        raise APIError(ERR_NOT_FOUND, 404, f"{what} not found")
    return rec
