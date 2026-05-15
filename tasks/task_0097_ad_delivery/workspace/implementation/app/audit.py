"""AuditLog helper."""
from . import store
from .auth import current_user_id, current_role


def emit(
    action: str,
    target_entity_type: str,
    target_entity_id: str,
    before_value: dict | None = None,
    after_value: dict | None = None,
    actor_user_id: str | None = None,
    actor_role: str | None = None,
):
    rec = {
        "id": store.gen_uuid(),
        "actor_user_id": actor_user_id if actor_user_id is not None else (current_user_id() or "system"),
        "actor_role": actor_role if actor_role is not None else (current_role() or "system"),
        "action": action,
        "target_entity_type": target_entity_type,
        "target_entity_id": target_entity_id,
        "before_value": before_value or {},
        "after_value": after_value or {},
    }
    store.stamp_common(rec, with_version=False)
    store.insert("AuditLog", rec)
    return rec
