"""Shared entity-bookkeeping helpers (PRD §2.4).

Mutable entities (Property, ExpensePool, ExpenseLineItem, Tenant, Lease, TiDraw,
Reconciliation, EstoppelCertificate) carry id, created_at, updated_at, version
(starts at 1, increments on every mutation including cascades). Append-only
entities (SalesReport, LedgerEntry) carry only id + created_at.
"""
from __future__ import annotations

import db


def new_common_fields() -> dict:
    """The four system-managed fields for a mutable entity."""
    now = db.now_iso()
    return {
        "id": db.new_uuid(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }


def new_append_only_fields() -> dict:
    """id + created_at only — for SalesReport and LedgerEntry."""
    return {
        "id": db.new_uuid(),
        "created_at": db.now_iso(),
        "_seq": db.next_seq(),
    }


def touch(entity: dict):
    """Refresh updated_at and bump version on a mutable entity."""
    entity["updated_at"] = db.now_iso()
    entity["version"] = entity.get("version", 1) + 1
