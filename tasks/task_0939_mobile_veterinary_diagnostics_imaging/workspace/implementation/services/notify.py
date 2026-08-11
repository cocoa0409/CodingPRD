"""Append-only Notification rows (PRD 3.9 'Notifications').

Notifications carry only `id` and `created_at` — no `updated_at`, no `version`.
"""

from core import db

KINDS = (
    "STOP_BUMPED",
    "APPOINTMENT_CANCELLED",
    "STUDY_REPEAT_REQUIRED",
    "REPORT_PUBLISHED",
    "TAT_BREACHED",
    "STAT_UPGRADED",
)


def append(clinic_id, study_id, kind, message):
    rec = db.new_record(with_version=False)
    rec["clinic_id"] = clinic_id
    rec["study_id"] = study_id
    rec["kind"] = kind
    rec["message"] = message
    return db.insert("notifications", rec)
