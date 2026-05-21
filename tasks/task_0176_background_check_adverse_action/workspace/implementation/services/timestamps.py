"""System-field stamping helpers.

For mutating ops:
- ``stamp_create(row)`` sets id, created_at, updated_at, version=1.
- ``stamp_update(row)`` refreshes updated_at and increments version by 1.

All timestamps use the logical clock so cooling-off math stays
consistent. Response-envelope timestamps remain wall-clock and are
handled separately in core.envelope.
"""
from __future__ import annotations

from core.clock import logical_now_iso
from core.utils import new_id


def stamp_create(row: dict, *, with_version: bool = True) -> dict:
    row.setdefault("id", new_id())
    ts = logical_now_iso()
    row["created_at"] = ts
    if with_version:
        row["updated_at"] = ts
        row["version"] = 1
    return row


def stamp_update(row: dict) -> dict:
    row["updated_at"] = logical_now_iso()
    row["version"] = int(row.get("version", 1)) + 1
    return row
