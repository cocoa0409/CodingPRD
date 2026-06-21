"""Notification record creation (PRD §3.7).

Notifications are append-only: id + created_at only (no updated_at, no version).
to_phone is a snapshot of the recipient customer's phone at send time.
"""
import db


def create_notification(subject_type, subject_id, template, to_phone, channel="SMS"):
    rec = db.base_fields(versioned=False)
    rec.update({
        "subject_type": subject_type,
        "subject_id": subject_id,
        "channel": channel,
        "template": template,
        "to_phone": to_phone,
    })
    db.notifications[rec["id"]] = rec
    return rec
