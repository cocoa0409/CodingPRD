"""Customer notification emission (PRD 3.7 / calculations.order_routing_status_derivation).

The notification_type is chosen by a single pinned rule, first match winning.
"""
import clock
from db import db, new_row


def choose_type(event, reroute=False, dc_fallback_raised=False,
                replacements_created=False, cancelled_units=0, total_units=0,
                initiated_by=None):
    if event == "order_cancel" and cancelled_units == total_units:
        return "CANCELLATION_FULL"
    if event == "order_cancel" or (event == "assignment_cancel" and not reroute):
        return "CANCELLATION_PARTIAL"
    if dc_fallback_raised:
        return "DC_FALLBACK"
    if event == "reject" and replacements_created:
        return "REJECTION_REROUTED"
    if event == "short_pick" and replacements_created:
        return "SHORT_PICK_REROUTED"
    if (event == "system_retry" and initiated_by == "SYSTEM_DEACTIVATION"
            and replacements_created):
        return "NODE_DEACTIVATED_REROUTED"
    return "UNROUTABLE"


def emit(order, assignment, notification_type, units_affected, channel="EMAIL"):
    summary = "Order %s: %s affecting %d unit(s)." % (
        order["order_code"], notification_type, units_affected)
    return new_row("notifications", {
        "order_id": order["id"],
        "assignment_id": assignment["id"] if assignment else None,
        "notification_type": notification_type,
        "channel": channel,
        "units_affected": units_affected,
        "body_summary": summary,
        "sent_at_utc": clock.now(),
    })
