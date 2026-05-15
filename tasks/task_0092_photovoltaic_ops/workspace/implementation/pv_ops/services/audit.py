"""Shared audit helper."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from pv_ops.store import Store


def write_audit(
    store: Store,
    *,
    actor_id: str,
    actor_role: str,
    target_type: str,
    target_id: str,
    action: str,
    before_value: Any,
    after_value: Any,
) -> dict:
    row = {
        "actor_id": actor_id,
        "actor_role": actor_role,
        "target_type": target_type,
        "target_id": target_id,
        "action": action,
        "before_value": deepcopy(before_value),
        "after_value": deepcopy(after_value),
    }
    store.insert_lite(row)
    store.audit_entries[row["id"]] = row
    return row
