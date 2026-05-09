"""Audit log writes. Audit rows are write-once (PRD §2.7)."""
from __future__ import annotations

from flask import g

import db
from utils import iso_format


def write_audit(*, subject_kind: str, subject_id: str, action: str,
                before: dict | None = None, after: dict | None = None) -> dict:
    entry = {
        "id": db.new_id(),
        "created_at": iso_format(db.now()),
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "action": action,
        "actor_role": getattr(g, "user_role", None),
        "actor_id": getattr(g, "user_id", None),
        "before": before or {},
        "after": after or {},
    }
    db.audit_entries[entry["id"]] = entry
    return entry
