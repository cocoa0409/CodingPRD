"""Cross-aggregate cascades shared by multiple endpoints (PRD §2.7, §3.4-§3.6).

Centralizes the hold-promotion loop so check-in, expire-ready, and cancel all
behave identically.
"""

import clock
import db
from constants import PICKUP_WINDOW_DAYS
from services import derive


def promote_head_hold_for_title(title_id, freed_copy):
    """Promote the head WAITING hold on `title_id` onto `freed_copy`, if any.

    Used after a copy becomes free (loan check-in, hold expire/cancel of a READY
    hold). If a WAITING hold exists, the head one (lowest queue_position = earliest
    created_at) goes WAITING -> READY and reserves the copy:
        copy.status AVAILABLE -> ON_HOLD_SHELF
        hold.ready_copy_id = copy.id
        hold.ready_at = now ; pickup_deadline derived from ready_at
        promoted patron's ready_pickup_count reconciled
        hold.version bumped
    Returns the promoted hold, or None when no WAITING hold exists (copy stays
    AVAILABLE and the caller reconciles the title counters).
    """
    waiting = derive.waiting_holds_for_title(title_id)
    if not waiting:
        return None

    head = waiting[0]
    now = clock.now()

    freed_copy["status"] = "ON_HOLD_SHELF"
    db.touch(freed_copy)

    head["status"] = "READY"
    head["ready_copy_id"] = freed_copy["id"]
    head["ready_at"] = now
    db.touch(head)

    # reconcile promoted patron's ready_pickup_count (and other counters)
    derive.reconcile_patron_by_id(head["patron_id"])
    return head
