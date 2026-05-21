"""Shared bookkeeping helpers — version bumps, lookups."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from ..errors import (
    APIError,
    err_not_found,
    err_version_mismatch,
)
from ..store import store


def bump_version(entity: dict, now: datetime) -> None:
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = now


def check_version(entity: dict, supplied: Optional[int]) -> None:
    if supplied is None:
        return
    if not isinstance(supplied, int):
        raise err_version_mismatch("version must be an integer")
    if supplied != entity.get("version", 1):
        raise err_version_mismatch()


def require(collection: str, entity_id: Optional[str]):
    if entity_id is None:
        raise err_not_found()
    s = store()
    coll = getattr(s, collection)
    obj = coll.get(entity_id)
    if obj is None:
        raise err_not_found()
    return obj
