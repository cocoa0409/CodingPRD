"""Audit-trail helper (PRD §3.9).

Each AuditEvent links to an invoice via invoice_id, carries a system event_type
label and the actor_user_id of the operator. Lightweight record: id + created_at
only (no updated_at/version).
"""
from __future__ import annotations

import db
from services.common import new_lightweight_fields


def append_audit(invoice_id: str, event_type: str, actor_user_id):
    ev = {
        **new_lightweight_fields(),
        "invoice_id": invoice_id,
        "event_type": event_type,
        "actor_user_id": actor_user_id,
    }
    db.audit_events[ev["id"]] = ev
    return ev
