"""Shared service helpers: system fields, audit, validation, serialization.

System-managed fields (PRD §2.4):
  id          — UUID, no prefix
  created_at  — ISO8601 UTC, 3 fractional digits
  updated_at  — ISO8601 UTC, refreshed on any mutation
  version     — integer starting at 1, +1 on every mutation
Payment / WeatherEvent / AuditEntry are lighter: id + created_at only
(no updated_at, no version) — they are immutable once written.
"""
from __future__ import annotations

from typing import Any, Optional

from db import db, new_id, now_iso
from errors import APIError, ERR_INVALID_REQUEST


# ---------------------------------------------------------------------------
# Record creation / mutation with system fields
# ---------------------------------------------------------------------------
def make_record(fields: dict, *, versioned: bool = True) -> dict:
    """Create a record with system fields populated.

    versioned=True  -> id, created_at, updated_at, version=1 (mutable records)
    versioned=False -> id, created_at only (immutable: Payment/WeatherEvent/AuditEntry)
    """
    ts = now_iso()
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = ts
    rec["_seq"] = db.next_seq()  # stable secondary sort key, stripped on serialize
    if versioned:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec: dict) -> None:
    """Record a mutation: refresh updated_at and bump version (PRD §2.4)."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1


def audit(entity_type: str, entity_id: str, action: str, actor_role: str) -> dict:
    """Append an immutable AuditEntry (PRD §2.1)."""
    entry = make_record(
        {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "action": action,
            "actor_role": actor_role,
        },
        versioned=False,
    )
    db.audit_entries[entry["id"]] = entry
    return entry


# ---------------------------------------------------------------------------
# Serialization — strip private fields (leading underscore) on the way out
# ---------------------------------------------------------------------------
def serialize(rec: dict) -> dict:
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def serialize_list(recs: list) -> list:
    return [serialize(r) for r in recs]


# ---------------------------------------------------------------------------
# created_at ASC ordering (PRD §2.3 default sort), tie-broken by insertion seq
# ---------------------------------------------------------------------------
def sort_by_created(recs: list) -> list:
    return sorted(recs, key=lambda r: (r["created_at"], r.get("_seq", 0)))


# ---------------------------------------------------------------------------
# Body / field validation helpers (ERR_INVALID_REQUEST, priority 18 / last)
# ---------------------------------------------------------------------------
def get_body() -> dict:
    from flask import request

    if request.data and request.data.strip():
        body = request.get_json(silent=True)
        if body is None:
            raise APIError(ERR_INVALID_REQUEST, 400, "Body must be valid JSON")
    else:
        body = {}
    if not isinstance(body, dict):
        raise APIError(ERR_INVALID_REQUEST, 400, "Body must be a JSON object")
    return body


def require_fields(body: dict, *names: str) -> None:
    for n in names:
        if n not in body or body[n] is None:
            raise APIError(ERR_INVALID_REQUEST, 400, f"Missing required field: {n}")


def require_str(body: dict, name: str, *, allow_empty: bool = False) -> str:
    val = body.get(name)
    if not isinstance(val, str):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{name} must be a string")
    if not allow_empty and val.strip() == "":
        raise APIError(ERR_INVALID_REQUEST, 400, f"{name} must be non-empty")
    return val


def require_int(body: dict, name: str, *, minimum: Optional[int] = None,
                maximum: Optional[int] = None) -> int:
    val = body.get(name)
    if isinstance(val, bool) or not isinstance(val, int):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{name} must be an integer")
    if minimum is not None and val < minimum:
        raise APIError(ERR_INVALID_REQUEST, 400, f"{name} must be >= {minimum}")
    if maximum is not None and val > maximum:
        raise APIError(ERR_INVALID_REQUEST, 400, f"{name} must be <= {maximum}")
    return val


def require_enum(body: dict, name: str, allowed: set) -> str:
    val = body.get(name)
    if not isinstance(val, str) or val not in allowed:
        raise APIError(ERR_INVALID_REQUEST, 400, f"{name} must be one of {sorted(allowed)}")
    return val


def optional_enum(body: dict, name: str, allowed: set, default: Any = None) -> Any:
    if name not in body or body[name] is None:
        return default
    return require_enum(body, name, allowed)
