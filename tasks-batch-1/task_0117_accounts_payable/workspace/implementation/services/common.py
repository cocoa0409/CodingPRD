"""Shared entity-bookkeeping helpers (PRD §2.4).

Full first-class entities carry id, created_at, updated_at, version (starts at 1,
increments on every mutation). Lightweight records (GL accounts, approval routes,
audit events) carry only id and created_at.
"""
from __future__ import annotations

import db


def new_common_fields() -> dict:
    """The four system-managed fields for a full first-class entity."""
    now = db.now_iso()
    return {
        "id": db.new_uuid(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }


def new_lightweight_fields() -> dict:
    """id + created_at only — for GLAccount, ApprovalRoute, AuditEvent."""
    return {
        "id": db.new_uuid(),
        "created_at": db.now_iso(),
        "_seq": db.next_seq(),
    }


def touch(entity: dict):
    """Refresh updated_at and bump version on a full entity."""
    entity["updated_at"] = db.now_iso()
    entity["version"] = entity.get("version", 1) + 1


def public(entity: dict) -> dict:
    """Strip internal-only keys (those prefixed with '_') from a serialized view."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}
