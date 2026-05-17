"""Tiny helpers for entity mutations (timestamp + version bump)."""
from __future__ import annotations

from ..clock import now


def bump(row: dict) -> None:
    """Refresh updated_at and bump version on an entity that has those fields."""
    row["updated_at"] = now()
    row["version"] = row.get("version", 1) + 1
