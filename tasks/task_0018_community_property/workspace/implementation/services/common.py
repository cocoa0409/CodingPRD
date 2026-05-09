"""Shared entity-mutation helpers: bumping version, refreshing updated_at,
serializing entities for outgoing JSON, etc.

PRD §2.4: every "common-fields" entity carries id, created_at, updated_at, version.
Three exceptions (PaymentRecord, Vote, AccessLog, AuditEntry) carry only id+created_at.
"""
from __future__ import annotations

import copy
from typing import Any

import db
from utils import iso_format


def stamp_create(entity: dict, *, with_version: bool = True) -> dict:
    """Mint id/created_at on a new entity. Optionally add updated_at + version=1."""
    now = db.now()
    entity["id"] = db.new_id()
    entity["created_at"] = iso_format(now)
    if with_version:
        entity["updated_at"] = iso_format(now)
        entity["version"] = 1
    return entity


def bump(entity: dict) -> None:
    """Refresh updated_at and increment version. No-op for entities without those fields."""
    if "version" in entity:
        entity["version"] = int(entity.get("version", 0)) + 1
    if "updated_at" in entity:
        entity["updated_at"] = iso_format(db.now())


def snapshot(entity: dict) -> dict:
    """Deep copy of an entity for AuditEntry before/after."""
    return copy.deepcopy(entity)
