from datetime import date, timedelta
from decimal import Decimal

from db import db
from util import parse_date, round_half_up


def remaining_full_months(effective_date: date, term_end: date) -> int:
    """Count of full calendar-month boundaries strictly after effective_date up to and including term_end."""
    if effective_date >= term_end:
        return 0
    count = 0
    # Start iterating: first month whose first day is strictly after effective_date
    year = effective_date.year
    month = effective_date.month
    # First candidate first-of-month strictly after effective_date
    if effective_date.day == 1:
        # next month's first
        month += 1
        if month > 12:
            month = 1
            year += 1
    else:
        month += 1
        if month > 12:
            month = 1
            year += 1
    while True:
        first = date(year, month, 1)
        if first <= effective_date:
            # Shouldn't happen but safety
            month += 1
            if month > 12:
                month = 1
                year += 1
            continue
        # Last day of this month
        if month == 12:
            next_first = date(year + 1, 1, 1)
        else:
            next_first = date(year, month + 1, 1)
        last_day = next_first - timedelta(days=1)
        if last_day > term_end:
            break
        count += 1
        # Advance to next month
        year, month = next_first.year, next_first.month
    return count


def compute_termination_penalty(lease: dict, effective_date: date) -> int:
    plan = lease["billing_plan"]
    if plan != "MONTHLY":
        return 0
    term_end = parse_date(lease["term_end_date"])
    if term_end is None:
        return 0
    months = remaining_full_months(effective_date, term_end)
    if months <= 0:
        return 0
    gross = Decimal(months) * Decimal(lease.get("monthly_rate_cents", 0)) * Decimal("0.3")
    return round_half_up(gross)


def lease_view(l: dict) -> dict:
    return {
        "id": l["id"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
        "tenant_id": l["tenant_id"],
        "billing_plan": l["billing_plan"],
        "monthly_rate_cents": l.get("monthly_rate_cents", 0),
        "term_start_date": l["term_start_date"],
        "term_end_date": l["term_end_date"],
        "status": l["status"],
        "reviewer_user_id": l.get("reviewer_user_id"),
        "termination_penalty_cents": l.get("termination_penalty_cents"),
        "termination_effective_date": l.get("termination_effective_date"),
    }
