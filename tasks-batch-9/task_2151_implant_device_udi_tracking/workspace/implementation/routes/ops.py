"""C11 — the operational checkpoint (POST /udi/ops-runs)."""
from flask import Blueprint

from auth import INVENTORY_LEAD, endpoint
from calc import NOTIFICATION_ESCALATION_LIMIT, ROTATION_WINDOW_DAYS
from derive import (
    detach_reservation,
    lot_unit_conservation,
    recompute_catalog_available,
    recompute_notification_open_count,
)
from envelope import object_response
from graph import catalog_of_lot, lot_of, units_of_lot
from store import (
    clock_dt,
    clock_iso,
    db,
    expiry_instant,
    ordered,
    parse_iso,
    plus_days,
    touch,
)

bp = Blueprint("ops", __name__)


@bp.route("/udi/ops-runs", methods=["POST"])
@endpoint([INVENTORY_LEAD])
def ops_run():
    now = clock_dt()

    # RULE 1 — agreement period expiry
    expired_agreement_count = 0
    for agreement in ordered(db.agreements.values()):
        if agreement["status"] != "ACTIVE":
            continue
        period_end = parse_iso(agreement["period_end_utc"])
        if period_end is not None and period_end < now:
            agreement["status"] = "EXPIRED"
            touch(agreement)
            expired_agreement_count += 1

    # RULE 2 — lot expiry sweep (depth-3 cascade)
    expired_lot_count = 0
    expired_unit_count = 0
    detached_reservation_count = 0
    for lot in ordered(db.lots.values()):
        if lot["status"] not in ("QUARANTINE", "AVAILABLE"):
            continue
        instant = expiry_instant(lot.get("expiration_date"))
        if instant is None or instant > now:
            continue
        lot["status"] = "EXPIRED"
        touch(lot)
        expired_lot_count += 1
        for unit in units_of_lot(lot["id"]):
            custody = unit["custody_state"]
            if custody in ("QUARANTINED", "AVAILABLE"):
                unit["expired_at_utc"] = clock_iso()
                unit["custody_state"] = "EXPIRED"
                touch(unit)
                expired_unit_count += 1
            elif custody == "RESERVED":
                detach_reservation(unit, blocked=True)
                detached_reservation_count += 1
                unit["expired_at_utc"] = clock_iso()
                unit["custody_state"] = "EXPIRED"
                touch(unit)
                expired_unit_count += 1
        lot_unit_conservation(lot)
        recompute_catalog_available(catalog_of_lot(lot))

    # RULE 3 — rotation alert (report only)
    horizon = plus_days(now, ROTATION_WINDOW_DAYS)
    rotation_alert_count = 0
    for unit in db.device_units.values():
        if unit["custody_state"] != "AVAILABLE":
            continue
        lot = lot_of(unit)
        instant = expiry_instant(lot.get("expiration_date")) if lot else None
        if instant is not None and now <= instant <= horizon:
            rotation_alert_count += 1

    # RULE 4 — recall notification escalation
    escalated_notification_count = 0
    for notification in ordered(db.recall_notifications.values()):
        if notification["status"] != "PENDING":
            continue
        due = parse_iso(notification.get("due_utc"))
        if due is None or not due < now:
            continue
        notification["escalation_level"] = notification.get("escalation_level", 0) + 1
        touch(notification)
        escalated_notification_count += 1
        if notification["escalation_level"] >= NOTIFICATION_ESCALATION_LIMIT:
            notification["status"] = "UNREACHABLE"
            action = db.field_actions.get(notification["field_action_id"])
            recompute_notification_open_count(action)
            if action is not None and action["status"] == "PUBLISHED":
                action["status"] = "IN_REMEDIATION"
                touch(action)

    # RULE 5 — registry deadline breach (report only)
    overdue_submission_count = 0
    for submission in db.registry_submissions.values():
        if submission["status"] not in ("REQUIRED", "REJECTED"):
            continue
        deadline = parse_iso(submission.get("deadline_utc"))
        if deadline is not None and deadline < now:
            overdue_submission_count += 1

    db.ops_run_index += 1
    return object_response(
        {
            "ops_run_index": db.ops_run_index,
            "expired_agreement_count": expired_agreement_count,
            "expired_lot_count": expired_lot_count,
            "expired_unit_count": expired_unit_count,
            "detached_reservation_count": detached_reservation_count,
            "rotation_alert_count": rotation_alert_count,
            "escalated_notification_count": escalated_notification_count,
            "overdue_submission_count": overdue_submission_count,
        }
    )
