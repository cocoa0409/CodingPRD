"""Common entity machinery: system-field stamping, version bumps, serialization.

PRD §2.4: every primary resource carries id, created_at, updated_at, version.
CheckIn and NoShowEvent are immutable audit rows with only id + created_at.
"""
from __future__ import annotations

from typing import Any, Dict, List

import db


# Internal bookkeeping keys never exposed in API output.
_INTERNAL_KEYS = {"_seq"}

# Field projection order is irrelevant for JSON; we just strip internal keys.


def stamp_new(record: Dict[str, Any], with_version: bool = True) -> Dict[str, Any]:
    """Stamp id, created_at, (updated_at, version) and a monotonic _seq.

    with_version=False -> immutable audit row (CheckIn, NoShowEvent): only id +
    created_at, no updated_at / version (PRD §2.4).
    """
    ts = db.now_iso()
    record["id"] = db.new_uuid()
    record["created_at"] = ts
    record["_seq"] = db.next_seq()
    if with_version:
        record["updated_at"] = ts
        record["version"] = 1
    return record


def touch(record: Dict[str, Any]) -> None:
    """Mark a mutation: refresh updated_at and bump version (PRD §2.4 / §2.8)."""
    record["updated_at"] = db.now_iso()
    record["version"] = record.get("version", 1) + 1


def public(record: Dict[str, Any]) -> Dict[str, Any]:
    """Project a record for API output, dropping internal keys."""
    return {k: v for k, v in record.items() if k not in _INTERNAL_KEYS}


def public_list(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [public(r) for r in records]
