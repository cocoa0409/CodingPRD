"""AuditLog service.

Audited domains: CarePlan, Prescription, MedicationAdministration, CareAssessment.
Each state transition / administration insertion writes exactly one row.
"""
from clock import iso_now
from db import get_db, new_id


def log(actor_role, actor_id, entity_type, entity_id, action,
        previous_state=None, new_state=None):
    db = get_db()
    row_id = new_id()
    row = {
        "id": row_id,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "action": action,
        "previous_state": previous_state,
        "new_state": new_state,
        "occurred_at": iso_now(),
        "created_at": iso_now(),
    }
    db.audit_logs[row_id] = row
    return row
