"""ParentNotification emission (append-only; PRD §3.10)."""

from db import DB
from services.common import stamp_create
from db import next_seq


def emit(district_id, parent_id, student_id, bus_trip_id, kind, payload):
    """Append a ParentNotification event record (id + created_at only)."""
    rec = {
        "district_id": district_id,
        "parent_id": parent_id,
        "student_id": student_id,
        "bus_trip_id": bus_trip_id,
        "kind": kind,
        "payload": payload,
    }
    stamp_create(rec, common_fields=False)
    DB.parent_notifications[rec["id"]] = rec
    return rec
