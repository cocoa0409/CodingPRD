"""Escalation order pricing and interval conflict detection."""

from datetime import timedelta
from decimal import Decimal

import db
from validate import rhu
from services import constants as C


def turnaround_hours(escalation_type):
    return (C.FIELD_REVIEW_TAT_HOURS if escalation_type == "FIELD_REVIEW"
            else C.SECOND_APPRAISAL_TAT_HOURS)


def base_fee(escalation_type):
    return (C.FIELD_REVIEW_BASE_FEE_CENTS if escalation_type == "FIELD_REVIEW"
            else C.SECOND_APPRAISAL_BASE_FEE_CENTS)


def price(escalation_type, due_at, at_instant):
    """Five ordered steps: base fee, rush surcharge, subtotal, volume
    discount tier, total."""
    base = base_fee(escalation_type)
    hours_remaining = Decimal((due_at - at_instant).total_seconds()) / Decimal(3600)
    is_rush = hours_remaining < C.RUSH_THRESHOLD_HOURS
    surcharge = rhu(Decimal(base) * C.RUSH_SURCHARGE_RATE) if is_rush else 0
    subtotal = base + surcharge
    if subtotal < C.VOLUME_TIER_1_CENTS:
        discount_bps = 0
    elif subtotal <= C.VOLUME_TIER_2_CENTS:
        discount_bps = C.VOLUME_DISCOUNT_TIER_1_BPS
    else:
        discount_bps = C.VOLUME_DISCOUNT_TIER_2_BPS
    discount = rhu(Decimal(subtotal) * Decimal(discount_bps), Decimal(10000))
    return base, surcharge, discount_bps, subtotal - discount


def window_conflict(appraiser_id, start, end, exclude_order_id=None):
    """Half-open [start, end) comparison; the travel buffer widens the stored
    window on both sides while the incoming window is compared bare."""
    buffer_delta = timedelta(minutes=C.TRAVEL_BUFFER_MINUTES)
    for order in db.escalation_orders.values():
        if order.get("assigned_appraiser_id") != appraiser_id:
            continue
        if exclude_order_id is not None and order["id"] == exclude_order_id:
            continue
        if order["status"] not in ("ASSIGNED", "REASSIGNMENT_REQUIRED"):
            continue
        existing_start = order.get("inspection_window_start")
        existing_end = order.get("inspection_window_end")
        if existing_start is None or existing_end is None:
            continue
        low = existing_start - buffer_delta
        high = existing_end + buffer_delta
        if start < high and end > low:
            return True
    return False


def overlapping_dispute_slots(amc_id, start, end):
    """Closed [start, end] comparison, unbuffered, counted in aggregate."""
    count = 0
    for case in db.dispute_cases.values():
        if case["amc_id"] != amc_id:
            continue
        if case["status"] not in ("OPEN", "APPRAISER_RESPONDED"):
            continue
        if start <= case["review_slot_end"] and end >= case["review_slot_start"]:
            count += 1
    return count
