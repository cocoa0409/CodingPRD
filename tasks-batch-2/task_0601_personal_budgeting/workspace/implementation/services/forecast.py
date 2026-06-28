"""Cash-flow forecast (PRD §3.7, scaffold calc cash_flow_forecast).

Starting cash = sum over the household's LINKED DEPOSITORY accounts of
  cleared_balance_cents  (optimistic / include_pending=false, default), or
  available_balance_cents (conservative / include_pending=true).

Walk d = clock_today+1 .. clock_today+horizon_days. On each day, for each
SCHEDULED bill whose day_of_month == day-of-month(d), subtract amount_cents.
Same-day bills applied in ascending (day_of_month, created_at ASC) order.
Record point {date, projected_balance_cents}. shortfall = min < 0.
"""

from clock import clock, add_days, format_iso8601_ms
from db import db


def compute_forecast(household, horizon_days, include_pending):
    hid = household["id"]

    starting = 0
    for acc in db.accounts.values():
        if acc["household_id"] != hid:
            continue
        if acc["status"] != "LINKED":
            continue
        if acc["account_type"] != "DEPOSITORY":
            continue
        if include_pending:
            starting += acc["available_balance_cents"]
        else:
            starting += acc["cleared_balance_cents"]

    bills = [b for b in db.recurring_bills.values()
             if b["household_id"] == hid and b["status"] == "SCHEDULED"]

    today = clock.today()
    running = starting
    points = []
    for i in range(1, horizon_days + 1):
        d = add_days(today, i)
        dom = d.day
        # Bills whose monthly due-day matches this calendar day-of-month.
        due = [b for b in bills if b["day_of_month"] == dom]
        # Same-day ordering: ascending day_of_month then created_at ASC.
        due.sort(key=lambda b: (b["day_of_month"], b["created_at"], b.get("_seq", 0)))
        for b in due:
            running -= b["amount_cents"]
        points.append({
            "date": format_iso8601_ms(_to_midnight(d)),
            "projected_balance_cents": running,
        })

    if points:
        min_bal = min(p["projected_balance_cents"] for p in points)
    else:
        min_bal = starting
    return {
        "points": points,
        "min_projected_balance_cents": min_bal,
        "shortfall": min_bal < 0,
    }


def _to_midnight(d):
    from datetime import datetime, timezone
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
