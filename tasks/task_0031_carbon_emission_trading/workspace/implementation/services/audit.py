"""Audit log helpers — every quota-affecting operation appends one row here."""

import clock
import db
from helpers import to_dec


def append(*, subject_type, subject_id, enterprise_id, action,
           delta_quota=0, delta_ccer=0, external_system=None):
    entry = {
        "id": db.new_id(),
        "subject_type": subject_type,
        "subject_id": subject_id,
        "enterprise_id": enterprise_id,
        "action": action,
        "delta_quota": to_dec(delta_quota),
        "delta_ccer": to_dec(delta_ccer),
        "external_system": external_system,
        "occurred_at": clock.now(),
        "created_at": clock.now(),
    }
    db.audit_log_entries.append(entry)
    return entry
