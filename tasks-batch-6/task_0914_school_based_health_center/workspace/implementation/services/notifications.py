"""Parent notification creation (PRD 3.2 selector + PRD 3.11 events).

Notifications are never created directly by a client; every one of them is a
by-product of a domain event.  The four selector branches are evaluated in the
exact order PRD 3.2 pins: empty pool, confidential encounter, guardian
opt-out, otherwise queued.
"""

import store
from services import calc


def raise_notification(event_type, student_id, visit=None):
    guardian = calc.select_guardian(student_id)
    visit_id = visit["id"] if visit is not None else None

    if guardian is None:
        guardian_id = None
        status = "UNDELIVERABLE"
        suppression_reason = "NO_GUARDIAN_ON_FILE"
    elif visit is not None and visit.get("confidential"):
        guardian_id = guardian["id"]
        status = "SUPPRESSED_CONFIDENTIAL"
        suppression_reason = "CONFIDENTIAL_SERVICE"
    elif guardian.get("notification_opt_out"):
        guardian_id = guardian["id"]
        status = "SUPPRESSED_OPT_OUT"
        suppression_reason = "GUARDIAN_OPT_OUT"
    else:
        guardian_id = guardian["id"]
        status = "QUEUED"
        suppression_reason = None

    return store.new_row(
        "notifications",
        {
            "student_id": student_id,
            "guardian_id": guardian_id,
            "visit_id": visit_id,
            "event_type": event_type,
            "status": status,
            "delivery_attempt_count": 0,
            "sent_at": None,
            "acknowledged_at": None,
            "suppression_reason": suppression_reason,
        },
    )
