"""The expiration, archival and downtime-close sweep (PRD §3.9)."""
import const
from common import by_seq, now, touch
from db import db
from services import domain

COUNTER_KEYS = (
    "tasks_marked_overdue",
    "tasks_expired",
    "order_sets_marked_expiring",
    "order_sets_expired",
    "order_sets_archived",
    "alerts_suspended",
    "alerts_retired",
    "burden_windows_closed",
    "downtime_events_closed",
)


def _reached(instant, clock):
    """Every schedule comparison is inclusive (PRD §3.9)."""
    return instant is not None and clock >= instant


def _expire_order_set(order_set, counts, clock):
    """An order set reaching EXPIRED suspends the alerts it feeds."""
    order_set["publication_state"] = "EXPIRED"
    touch(order_set)
    counts["order_sets_expired"] += 1
    for alert in by_seq(domain.alerts_linked_to(order_set["id"])):
        if alert["lifecycle_state"] == "ACTIVE":
            counts["burden_windows_closed"] += domain.suspend_alert(
                alert, const.SUSPENSION_REASON_SOURCE_EXPIRED
            )
            counts["alerts_suspended"] += 1


def run_sweep():
    clock = now()
    counts = {key: 0 for key in COUNTER_KEYS}

    # --- link 1: a due task becomes OVERDUE, and its order set starts expiring.
    for task in by_seq(db.annual_review_tasks.values()):
        if task["state"] != "PENDING":
            continue
        if not _reached(task["review_due_date"], clock):
            continue
        if _reached(task["expiration_at"], clock):
            # The clock is already past this task's expiration_at, so this sweep
            # never sees the intermediate step: link 2 takes it PENDING → EXPIRED
            # and its order set "straight from PUBLISHED" to EXPIRED (PRD §3.9).
            continue
        task["state"] = "OVERDUE"
        touch(task)
        counts["tasks_marked_overdue"] += 1
        if task["artifact_kind"] == "ORDER_SET":
            order_set = db.order_sets.get(task.get("order_set_id"))
            if order_set is not None and order_set["publication_state"] == "PUBLISHED":
                order_set["publication_state"] = "EXPIRING"
                touch(order_set)
                counts["order_sets_marked_expiring"] += 1

    # --- link 2: an expired task expires its order set or suspends its alert.
    for task in by_seq(db.annual_review_tasks.values()):
        if task["state"] not in ("PENDING", "OVERDUE"):
            continue
        if not _reached(task["expiration_at"], clock):
            continue
        task["state"] = "EXPIRED"
        touch(task)
        counts["tasks_expired"] += 1
        if task["artifact_kind"] == "ORDER_SET":
            order_set = db.order_sets.get(task.get("order_set_id"))
            if order_set is not None and order_set["publication_state"] in ("PUBLISHED", "EXPIRING"):
                _expire_order_set(order_set, counts, clock)
        else:
            alert = db.alerts.get(task.get("alert_id"))
            if alert is not None and alert["lifecycle_state"] == "ACTIVE":
                counts["burden_windows_closed"] += domain.suspend_alert(
                    alert, const.SUSPENSION_REASON_SOURCE_EXPIRED
                )
                counts["alerts_suspended"] += 1

    # --- link 3: an expired order set archives, retiring the alerts it fed.
    for order_set in by_seq(db.order_sets.values()):
        if order_set["publication_state"] != "EXPIRED":
            continue
        if not _reached(order_set["archive_eligible_at"], clock):
            continue
        order_set["publication_state"] = "ARCHIVED"
        order_set["archived_at"] = clock
        touch(order_set)
        counts["order_sets_archived"] += 1
        for alert in by_seq(domain.alerts_linked_to(order_set["id"])):
            if alert["lifecycle_state"] == "SUSPENDED":
                closed, _expired = domain.retire_alert(alert)
                counts["burden_windows_closed"] += closed
                counts["alerts_retired"] += 1

    # --- link 4: a downtime window whose end the clock has passed closes.
    for event in by_seq(db.downtime_events.values()):
        if event["state"] != "ACTIVE":
            continue
        if not _reached(event["window_end"], clock):
            continue
        event["state"] = "CLOSED"
        event["closed_at"] = clock
        touch(event)
        counts["downtime_events_closed"] += 1

    result = {"swept_at": clock}
    result.update(counts)
    return result
