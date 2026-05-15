"""Append-only audit-log writer per PRD §2.8 and §3.7.

A row is appended on every state transition, every concurrency-rule
loser rejection, every sync-envelope flip, every clock-tick-driven
transition, every cascade hop, and every exposure deliver/void.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from flask import g

from .envelope import fresh_uuid, server_now_iso8601
from .storage import DB


def append_audit(
    *,
    festival_id: str,
    event_category: str,
    subject_entity_type: str,
    subject_entity_id: str,
    from_state: Optional[str] = None,
    to_state: Optional[str] = None,
    payload_summary: str = "",
    actor_user_id: Optional[str] = None,
    actor_role: Optional[str] = None,
) -> Dict[str, Any]:
    """Append a single AuditEntry row.

    The actor defaults to the request's headers via `g`; the special
    string ``"system"`` is the convention for cascade and clock-tick
    auto-emitted rows.  The audit row has no `updated_at` and no
    `version` (PRD §2.4 lists the three append-only entities).
    """
    if actor_user_id is None:
        actor_user_id = getattr(g, "actor_user_id", "system")
    if actor_role is None:
        actor_role = getattr(g, "actor_role", "system")

    row: Dict[str, Any] = {
        "id": fresh_uuid(),
        "festival_id": festival_id,
        "actor_user_id": actor_user_id,
        "actor_role": actor_role,
        "event_category": event_category,
        "subject_entity_type": subject_entity_type,
        "subject_entity_id": subject_entity_id,
        "from_state": from_state,
        "to_state": to_state,
        "payload_summary": payload_summary,
        "created_at": server_now_iso8601(),
    }
    DB.audit_entries[row["id"]] = row
    DB.audit_order_by_festival[festival_id].append(row["id"])
    return row


def list_audit_for_festival(
    festival_id: str,
    *,
    event_category: Optional[str] = None,
    subject_entity_type: Optional[str] = None,
    created_at_after: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return the festival's audit rows in append order, filtered.

    The order is per-festival `created_at` ascending (PRD §2.8 / §3.7).
    The append order in `audit_order_by_festival` mirrors that
    chronological order exactly because the writer appends synchronously
    under the GIL.
    """
    ordered_ids = DB.audit_order_by_festival.get(festival_id, [])
    rows = [DB.audit_entries[aid] for aid in ordered_ids if aid in DB.audit_entries]
    if event_category is not None:
        rows = [r for r in rows if r["event_category"] == event_category]
    if subject_entity_type is not None:
        rows = [r for r in rows if r["subject_entity_type"] == subject_entity_type]
    if created_at_after is not None:
        rows = [r for r in rows if r["created_at"] > created_at_after]
    # Sort defensively by created_at to handle wall-clock ties: the
    # stamping function emits monotonically-non-decreasing timestamps
    # under the GIL, but explicit sort guards against subtle reorderings.
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return rows


def append_occ_conflict(
    *,
    festival_id: str,
    subject_entity_type: str,
    subject_entity_id: str,
    payload_summary: str = "OCC version conflict",
) -> None:
    """Helper: append an OCC_CONFLICT audit row.

    Called by the schedule-change apply-vs-reject race and the
    festival-publish CAS loser per the §1.2.1 concurrency rules.
    """
    append_audit(
        festival_id=festival_id,
        event_category="OCC_CONFLICT",
        subject_entity_type=subject_entity_type,
        subject_entity_id=subject_entity_id,
        payload_summary=payload_summary,
    )
