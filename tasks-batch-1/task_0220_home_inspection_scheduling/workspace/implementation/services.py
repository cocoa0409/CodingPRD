"""Shared business-logic services that span multiple route handlers:
order fee/duration/balance recomputation and the inspector daily-load ledger.
"""
import calculations as calc
from db import db

# Order statuses that count toward an inspector's booked minutes on a date
# (PRD §3.4 / scaffold inspector_daily_load).
BOOKED_STATUSES = {"SCHEDULED", "IN_PROGRESS", "REPORT_DRAFT", "DELIVERED"}

NON_TERMINAL_ORDER_STATUSES = {"REQUESTED", "SCHEDULED", "IN_PROGRESS", "REPORT_DRAFT"}


def active_addons_for_order(order_id):
    return [
        a for a in db.addons.values()
        if a["order_id"] == order_id and a["status"] == "ACTIVE"
    ]


def recompute_order_duration(order):
    """Set order duration_minutes from base type + ACTIVE add-ons (PRD §3.4)."""
    active = active_addons_for_order(order["id"])
    order["duration_minutes"] = calc.order_duration_minutes(
        order["inspection_type"],
        [a["added_duration_minutes"] for a in active],
    )


def compute_quoted_fee(order):
    """Quoted fee from the property's recorded square footage (variant QUOTED)."""
    fs = db.fee_schedules[order["fee_schedule_id"]]
    prop = db.properties[order["property_id"]]
    active = active_addons_for_order(order["id"])
    return calc.inspection_fee_cents(
        prop["square_footage"],
        order["inspection_type"],
        fs,
        [a["price_cents"] for a in active],
    )


def compute_final_fee(order):
    """Final fee from the report's measured square footage (variant FINAL)."""
    fs = db.fee_schedules[order["fee_schedule_id"]]
    report = report_for_order(order["id"])
    active = active_addons_for_order(order["id"])
    return calc.inspection_fee_cents(
        report["measured_square_footage"],
        order["inspection_type"],
        fs,
        [a["price_cents"] for a in active],
    )


def effective_fee_cents(order):
    """Effective fee driving amount_due, by lifecycle stage (PRD §2.9 / §3.5)."""
    status = order["status"]
    if status == "DELIVERED":
        return order.get("final_fee_cents") or 0
    if status in ("SCHEDULED", "IN_PROGRESS", "REPORT_DRAFT"):
        return order.get("quoted_fee_cents") or 0
    # REQUESTED (and CANCELLED) contribute 0 effective fee.
    return 0


def recompute_amount_due(order):
    """amount_due = effective_fee - amount_paid + amount_refunded (PRD §2.9)."""
    eff = effective_fee_cents(order)
    order["amount_due_cents"] = (
        eff - order["amount_paid_cents"] + order["amount_refunded_cents"]
    )


def report_for_order(order_id):
    for r in db.reports.values():
        if r["order_id"] == order_id:
            return r
    return None


def booked_minutes(inspector_id, date_str, exclude_order_id=None):
    """Sum duration_minutes of the inspector's orders on a date in booked states."""
    total = 0
    for o in db.inspection_orders.values():
        if o["id"] == exclude_order_id:
            continue
        if (
            o["inspector_id"] == inspector_id
            and o.get("scheduled_date") == date_str
            and o["status"] in BOOKED_STATUSES
        ):
            total += o["duration_minutes"] or 0
    return total
