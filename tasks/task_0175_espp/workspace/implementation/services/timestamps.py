"""Helpers for stamping created_at / updated_at / version on rows."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict


from core.utils import format_iso


def _now_real() -> str:
    """Real wall-clock used to stamp created_at / updated_at on rows."""
    return format_iso(datetime.now(timezone.utc))


def stamp_create(row: Dict[str, Any], *, with_updated: bool = True, with_version: bool = True) -> None:
    ts = _now_real()
    row.setdefault("created_at", ts)
    if with_updated:
        row.setdefault("updated_at", ts)
    if with_version:
        row.setdefault("version", 1)


def stamp_update(row: Dict[str, Any], *, with_version: bool = True) -> None:
    row["updated_at"] = _now_real()
    if with_version and "version" in row:
        row["version"] = int(row.get("version", 0)) + 1
