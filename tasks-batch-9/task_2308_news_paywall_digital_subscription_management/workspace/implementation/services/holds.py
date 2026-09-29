"""Hold geometry, frozen credits and the paired dimension transitions (PRD 3.7)."""
from datetime import timedelta

import config
from clock import clock, parse_date
from db import db
from response import touch
from services.derive import inclusive_days, subscription_holds
from services.money import dec, rhu
from services.pricing import recompute_next_price


def daily_print_rate_cents(plan):
    """Rate first, rounded once; the product is never rounded again."""
    divisor = plan["print_deliveries_per_cycle"]
    if not divisor:
        return 0
    return rhu(dec(plan["print_component_cents"]) / dec(divisor))


def weekday_code(day):
    return config.WEEKDAY_CODES[day.weekday()]


def credit_computation(plan, hold_type, start_date, end_date):
    if hold_type == "PAUSE_BILLING":
        return 0, 0
    rate = daily_print_rate_cents(plan)
    start = parse_date(start_date)
    end = parse_date(end_date)
    delivery_days = 0
    day = start
    while day <= end:
        if weekday_code(day) in plan["print_delivery_days"]:
            delivery_days += 1
        day += timedelta(days=1)
    return delivery_days, rate * delivery_days


def buffer_conflict(sub, hold_type, start_date, end_date):
    """Closed interval plus a two-day buffer (PRD 2.11 / 3.7)."""
    new_start = parse_date(start_date)
    new_end = parse_date(end_date)
    buffer = timedelta(days=config.HOLD_BUFFER_DAYS)
    for existing in subscription_holds(sub["id"]):
        if existing["status"] not in config.HOLD_OCCUPYING_STATUSES:
            continue
        existing_start = parse_date(existing["start_date"])
        existing_end = parse_date(existing["end_date"])
        if hold_type == "DELIVERY_INTERRUPTION":
            if existing["hold_type"] != "VACATION_DELIVERY":
                continue
            if existing_start <= new_start <= existing_end:
                return True
            continue
        if new_start <= existing_end + buffer and existing_start <= new_end + buffer:
            return True
    return False


def other_print_hold_active(sub, exclude_id):
    for hold in subscription_holds(sub["id"]):
        if hold["id"] == exclude_id:
            continue
        if hold["status"] != "ACTIVE":
            continue
        if hold["hold_type"] in ("VACATION_DELIVERY", "DELIVERY_INTERRUPTION"):
            return True
    return False


def other_pause_hold_active(sub, exclude_id):
    for hold in subscription_holds(sub["id"]):
        if hold["id"] == exclude_id:
            continue
        if hold["status"] == "ACTIVE" and hold["hold_type"] == "PAUSE_BILLING":
            return True
    return False


def activate_hold(hold, sub, plan):
    """HOLDS pass: a SCHEDULED hold whose start_date has arrived comes into force."""
    hold["status"] = "ACTIVE"
    touch(hold)
    if hold["hold_type"] == "PAUSE_BILLING":
        if sub["lifecycle_status"] == "ACTIVE":
            sub["lifecycle_status"] = "PAUSED"
            touch(sub)
            return "paused"
    elif hold["hold_type"] == "VACATION_DELIVERY":
        if sub["print_fulfillment_status"] == "SCHEDULED":
            sub["print_fulfillment_status"] = "HELD"
            touch(sub)
    return None


def complete_hold(hold, sub, plan):
    """HOLDS pass: an ACTIVE hold whose end_date has passed runs its course."""
    hold["status"] = "COMPLETED"
    touch(hold)
    resumed = None
    if hold["hold_type"] == "PAUSE_BILLING":
        if sub["lifecycle_status"] == "PAUSED" and not other_pause_hold_active(sub, hold["id"]):
            sub["lifecycle_status"] = "ACTIVE"
            paused_days = inclusive_days(hold["start_date"], hold["end_date"])
            sub["cycle_start_on"] = (
                parse_date(sub["cycle_start_on"]) + timedelta(days=paused_days)
            ).isoformat()
            recompute_next_price(sub, plan)
            touch(sub)
            resumed = "resumed"
    else:
        if sub["print_fulfillment_status"] in ("HELD", "INTERRUPTED") and not other_print_hold_active(
            sub, hold["id"]
        ):
            sub["print_fulfillment_status"] = "SCHEDULED"
            touch(sub)
    return resumed


def release_hold(hold, sub, plan):
    """Compensating action: the credit is reversed, lifetime credit is untouched."""
    was_active = hold["status"] == "ACTIVE"
    hold["status"] = "RELEASED"
    touch(hold)
    if was_active:
        if hold["hold_type"] == "PAUSE_BILLING":
            if sub["lifecycle_status"] == "PAUSED" and not other_pause_hold_active(
                sub, hold["id"]
            ):
                sub["lifecycle_status"] = "ACTIVE"
        elif sub["print_fulfillment_status"] in ("HELD", "INTERRUPTED") and not other_print_hold_active(
            sub, hold["id"]
        ):
            sub["print_fulfillment_status"] = "SCHEDULED"
    recompute_next_price(sub, plan)
    touch(sub)


def release_terminal_holds(sub):
    """Hop four of the final-decline chain."""
    released = []
    for hold in subscription_holds(sub["id"]):
        if hold["status"] in ("SCHEDULED", "ACTIVE"):
            hold["status"] = "RELEASED"
            touch(hold)
            released.append(hold)
    return released


def release_holds_after_access_end(sub, access_until):
    """Hop three of the confirm-cancellation chain."""
    boundary = parse_date(access_until) if access_until else None
    released = []
    for hold in subscription_holds(sub["id"]):
        if hold["status"] != "SCHEDULED":
            continue
        if boundary is not None and parse_date(hold["start_date"]) <= boundary:
            continue
        hold["status"] = "RELEASED"
        touch(hold)
        released.append(hold)
    return released


def create_hold(sub, hold_type, start_date, end_date, delivery_days, credit_cents, status):
    from db import new_entity
    from response import mark_created

    hold = new_entity()
    hold.update(
        {
            "subscription_id": sub["id"],
            "hold_type": hold_type,
            "start_date": start_date,
            "end_date": end_date,
            "status": status,
            "delivery_days_credited": delivery_days,
            "credit_cents": credit_cents,
            "credit_applied": False,
            "credit_applied_cycle_index": None,
        }
    )
    db.holds[hold["id"]] = hold
    mark_created(hold)
    return hold


def plan_of(sub):
    return db.offer_plans.get(sub["offer_plan_id"])


def clock_date_iso():
    return clock.date().isoformat()
