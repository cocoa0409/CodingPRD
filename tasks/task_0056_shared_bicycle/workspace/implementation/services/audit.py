"""Audit log writer.

PRD §2.9: every state-changing action that mutates money, fleet state,
geofence configuration, or external-system synchronization writes one
AuditLog entry.
"""
from __future__ import annotations

from typing import Any, Dict

from flask import g

from db import LOCK, audit_logs, new_id, regions
from time_utils import now_iso


def write_audit(
    *,
    event_kind: str,
    action: str,
    subject_type: str,
    subject_id: str,
    before: Dict[str, Any] | None = None,
    after: Dict[str, Any] | None = None,
    region_id: str | None = None,
) -> Dict[str, Any]:
    """Append an AuditLog entry and return it.

    `clock_minute` is sourced from the supplied region (if any). If no
    region id is provided, falls back to the first region's clock, then 0.
    """
    with LOCK:
        clock_minute = 0
        region = None
        if region_id and region_id in regions:
            region = regions[region_id]
        if region is None and regions:
            region = next(iter(regions.values()))
        if region is not None:
            clock_minute = region.get("clock_minutes", 0)

        entry = {
            "id": new_id(),
            "created_at": now_iso(),
            "actor_role": getattr(g, "user_role", None),
            "actor_id": getattr(g, "user_id", None),
            "event_kind": event_kind,
            "action": action,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "before": before or {},
            "after": after or {},
            "clock_minute": clock_minute,
        }
        audit_logs[entry["id"]] = entry
    return entry
