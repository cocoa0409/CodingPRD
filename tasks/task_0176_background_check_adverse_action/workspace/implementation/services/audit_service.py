"""AuditEvent chain — tamper-evident append-only log.

Each event for a given subject_id references the prior event id; the
first event on a subject has previous_event_id = None. payload_hash is
the SHA-256 of (subject_id, event_type, actor_user_id, created_at,
previous_event_id) per PRD §2.11.
"""
from __future__ import annotations

import hashlib
from typing import List, Optional

from core.clock import logical_now_iso
from core.store import store
from core.utils import new_id


def _latest_event_for_subject(subject_id: str) -> Optional[dict]:
    for ev in reversed(store.audit_events):
        if ev["subject_id"] == subject_id:
            return ev
    return None


def append_event(
    *,
    event_type: str,
    subject_entity: str,
    subject_id: str,
    actor_role: str,
    actor_user_id: str,
) -> dict:
    prev = _latest_event_for_subject(subject_id)
    prev_id = prev["id"] if prev is not None else None
    created_at = logical_now_iso()
    ev_id = new_id()
    payload_input = "|".join(
        [
            subject_id or "",
            event_type or "",
            actor_user_id or "",
            created_at or "",
            prev_id or "",
        ]
    )
    payload_hash = hashlib.sha256(payload_input.encode("utf-8")).hexdigest()
    event = {
        "id": ev_id,
        "created_at": created_at,
        "event_type": event_type,
        "subject_entity": subject_entity,
        "subject_id": subject_id,
        "actor_role": actor_role,
        "actor_user_id": actor_user_id,
        "previous_event_id": prev_id,
        "payload_hash": payload_hash,
    }
    store.audit_events.append(event)
    return event


def events_for_order(order_id: str) -> List[dict]:
    """Return chronologically-ordered events relevant to an order.

    Includes events whose subject is the order itself and events for the
    order's items / disputes / adverse-action flow so the audit trail is
    a complete chain for FCRA evidence purposes.
    """
    subject_ids = {order_id}
    for item in store.list_items_for_order(order_id):
        subject_ids.add(item["id"])
        # And any disputes on the item.
    for disp in store.disputes.values():
        if disp["candidate_id"]:
            # cheap inclusion: include dispute events for items belonging
            # to this order.
            item = store.verification_items.get(disp["verification_item_id"])
            if item is not None and item["order_id"] == order_id:
                subject_ids.add(disp["id"])
    flow = store.adverse_flow_for_order(order_id)
    if flow is not None:
        subject_ids.add(flow["id"])
    return [ev for ev in store.audit_events if ev["subject_id"] in subject_ids]
