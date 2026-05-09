from clock import CLOCK
from db import DATA, init_immutable


def write_audit(actor_role, actor_id, entity_type, entity_id, action):
    row = {
        "actor_role": actor_role,
        "actor_id": actor_id,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "action": action,
        "occurred_at": CLOCK.iso(),
    }
    init_immutable(row)
    DATA.audit_logs[row["id"]] = row
    return row
