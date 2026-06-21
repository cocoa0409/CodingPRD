"""Append-only audit log (PRD §2.9). Each entry records onboarding_id,
actor_role, actor_user_id, action, detail. Entries are never edited."""

from db import db, stamp_audit_create


def append(onboarding_id, actor_role, actor_user_id, action, detail):
    entry = {
        "onboarding_id": onboarding_id,
        "actor_role": actor_role,
        "actor_user_id": actor_user_id,
        "action": action,
        "detail": detail,
    }
    stamp_audit_create(entry)
    db.audit_entries[entry["id"]] = entry
    return entry
