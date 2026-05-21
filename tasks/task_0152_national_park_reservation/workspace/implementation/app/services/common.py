"""Shared helpers for entity mutation tracking."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from ..clock import now_utc
from ..util import format_iso8601


def stamp_create(entity: Dict[str, Any]) -> Dict[str, Any]:
    ts = format_iso8601(now_utc())
    entity.setdefault("created_at", ts)
    entity.setdefault("updated_at", ts)
    entity.setdefault("version", 1)
    return entity


def stamp_update(entity: Dict[str, Any]) -> Dict[str, Any]:
    entity["updated_at"] = format_iso8601(now_utc())
    entity["version"] = entity.get("version", 0) + 1
    return entity


def append_only_create(entity: Dict[str, Any]) -> Dict[str, Any]:
    entity.setdefault("created_at", format_iso8601(now_utc()))
    return entity
