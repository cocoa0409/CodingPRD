"""Dues pricing, chapter share, notice gap, back-dues — SCAFFOLD Table 3 / PRD §3.2, §3.4, §3.7."""
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone, timedelta
import calendar

import db
import errors


def round_half_up(value):
    """Round a Decimal to integer cents, half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def is_leap_year(y):
    return calendar.isleap(y)


def add_one_year(dt):
    """Anniversary +1 year, handling Feb 29 -> Feb 28 on non-leap targets."""
    try:
        return dt.replace(year=dt.year + 1)
    except ValueError:
        return dt.replace(year=dt.year + 1, day=28)


def schedule_in_force(category_id, at_dt):
    """The PUBLISHED schedule for category where effective_from <= at < COALESCE(effective_to, +inf)."""
    best = None
    for s in db.dues_schedules.values():
        if s["category_id"] != category_id or s["status"] != "PUBLISHED":
            continue
        ef = db.parse_dt(s["effective_from"])
        et = db.parse_dt(s["effective_to"]) if s.get("effective_to") else None
        if ef <= at_dt and (et is None or at_dt < et):
            if best is None or db.parse_dt(best["effective_from"]) < ef:
                best = s
    return best


def next_anchor_after(start_date, month, day):
    """Next occurrence of (month, day) strictly after start_date (a date)."""
    year = start_date.year
    for y in (year, year + 1, year + 2):
        # clamp day to month length
        last = calendar.monthrange(y, month)[1]
        d = min(day, last)
        candidate = datetime(y, month, d, tzinfo=timezone.utc).date()
        if candidate > start_date:
            return candidate
    # unreachable
    return datetime(year + 3, month, 1, tzinfo=timezone.utc).date()


def compute_invoice_amount(member, at_dt):
    """dues_invoice_amount calculation. Returns (amount_cents, period_start, period_end, schedule)."""
    category_id = member["category_id"]
    policy = db.renewal_cycle_policies.get(member["cycle_policy_id"])
    schedule = schedule_in_force(category_id, at_dt)
    if schedule is None:
        raise errors.ApiError(errors.ERR_NOT_FOUND,
                              "No PUBLISHED dues schedule in force for category", 404)
    base_cents = int(schedule["annual_amount_cents"])
    mode = policy["mode"]

    if mode == "ANNIVERSARY":
        # anchored to joined_at; period_start is the relevant anniversary date
        joined = db.parse_dt(member["joined_at"])
        # find the anniversary period containing/at `at_dt`
        anchor = joined
        while add_one_year(anchor) <= at_dt:
            anchor = add_one_year(anchor)
        period_start = anchor
        period_end = add_one_year(anchor)
        amount_cents = base_cents
    else:  # CALENDAR
        period_start = at_dt
        end_date = next_anchor_after(
            at_dt.date(),
            int(policy["calendar_anchor_month"]),
            int(policy["calendar_anchor_day"]),
        )
        period_end = datetime(end_date.year, end_date.month, end_date.day, tzinfo=timezone.utc)
        proration = policy["proration_method"]
        if proration == "PRO_RATA_DAILY":
            days_remaining = (period_end.date() - at_dt.date()).days
            days_in_year = 366 if is_leap_year(at_dt.year) else 365
            amount_cents = round_half_up(
                Decimal(base_cents) * Decimal(days_remaining) / Decimal(days_in_year))
        else:  # FULL_PERIOD or NONE -> full base
            amount_cents = base_cents

    return amount_cents, period_start, period_end, schedule


def chapter_share(amount_cents, bps):
    """chapter_share_amount — chapter share computed FIRST, rounded half-up."""
    return round_half_up(Decimal(amount_cents) * Decimal(int(bps)) / Decimal(10000))


def compute_back_dues(member, lapse_dt, request_dt):
    """reinstatement_back_dues — walk gap chronologically, one year at a time."""
    cursor = lapse_dt
    total = 0
    last_schedule = None
    while cursor < request_dt:
        amount, _ps, _pe, sched = compute_invoice_amount(member, cursor)
        total += amount
        last_schedule = sched
        cursor = add_one_year(cursor)
    return total, last_schedule
