"""Derived-field recomputation (PRD 2.5: every derived value is immediate)."""
import config
from clock import clock, parse_date
from db import by_seq, db


# ------------------------------------------------------------------ OfferPlan
def plan_active_subscription_count(plan_id):
    return sum(
        1
        for s in db.subscriptions.values()
        if s.get("offer_plan_id") == plan_id
        and s.get("lifecycle_status") in config.LIFECYCLE_COUNTED_ON_PLAN
    )


def plan_subscriptions(plan_id, statuses):
    rows = [
        s
        for s in db.subscriptions.values()
        if s.get("offer_plan_id") == plan_id and s.get("lifecycle_status") in statuses
    ]
    return by_seq(rows)


# ------------------------------------------------------------------ Subscription
def subscription_holds(subscription_id):
    return by_seq([h for h in db.holds.values() if h.get("subscription_id") == subscription_id])


def subscription_invoices(subscription_id):
    return sorted(
        [i for i in db.invoices.values() if i.get("subscription_id") == subscription_id],
        key=lambda i: (i["cycle_index"], i["_seq"]),
    )


def invoice_attempts(invoice_id):
    return by_seq([a for a in db.payment_attempts.values() if a.get("invoice_id") == invoice_id])


def pending_credit_cents(sub):
    return sum(
        h["credit_cents"]
        for h in subscription_holds(sub["id"])
        if h["status"] in config.HOLD_OCCUPYING_STATUSES and not h["credit_applied"]
    )


def lifetime_credit_cents(sub):
    return sum(
        h["credit_cents"] for h in subscription_holds(sub["id"]) if h["credit_applied"]
    )


def tenure_cycles(sub):
    return sum(1 for i in subscription_invoices(sub["id"]) if i["status"] == "PAID")


def vacation_days_used_365(sub, extra_days=0):
    floor_date = clock.date() - _days(365)
    total = extra_days
    for hold in subscription_holds(sub["id"]):
        if hold["hold_type"] != "VACATION_DELIVERY":
            continue
        if hold["status"] not in config.HOLD_OCCUPYING_STATUSES:
            continue
        if parse_date(hold["start_date"]) < floor_date:
            continue
        total += inclusive_days(hold["start_date"], hold["end_date"])
    return total


def pause_count_365(sub):
    floor_date = clock.date() - _days(365)
    count = 0
    for hold in subscription_holds(sub["id"]):
        if hold["hold_type"] != "PAUSE_BILLING":
            continue
        if hold["status"] not in config.HOLD_OCCUPYING_STATUSES:
            continue
        if parse_date(hold["start_date"]) < floor_date:
            continue
        count += 1
    return count


def inclusive_days(start_date, end_date):
    return (parse_date(end_date) - parse_date(start_date)).days + 1


def _days(n):
    from datetime import timedelta

    return timedelta(days=n)


def max_payment_attempts(sub):
    reader = db.readers.get(sub.get("reader_id"))
    bonus = 0
    if reader is not None and reader.get("card_updater_status") == "UPDATED":
        bonus = config.CARD_UPDATER_BONUS_ATTEMPTS
    return config.DUNNING_MAX_ATTEMPTS + bonus


def open_episode_invoice(sub):
    """The invoice carrying the current dunning episode's attempts."""
    candidates = [
        i for i in subscription_invoices(sub["id"]) if invoice_attempts(i["id"])
    ]
    if not candidates:
        return None
    return candidates[-1]


def payment_attempt_count(sub):
    if sub.get("dunning_status") == "CURRENT":
        return 0
    invoice = open_episode_invoice(sub)
    if invoice is None:
        return 0
    return len(invoice_attempts(invoice["id"]))


# ------------------------------------------------------------------ GroupAccount
def group_seats(group_account_id):
    return by_seq([s for s in db.seats.values() if s.get("group_account_id") == group_account_id])


def peak_occupancy(intervals):
    """Aggregate peak concurrency over half-open [start, end) date intervals."""
    if not intervals:
        return 0
    boundaries = set()
    for start, end in intervals:
        boundaries.add(start)
        if end is not None:
            boundaries.add(end)
    peak = 0
    for boundary in sorted(boundaries):
        covering = 0
        for start, end in intervals:
            if start <= boundary and (end is None or end > boundary):
                covering += 1
        peak = max(peak, covering)
    return peak


def seat_intervals(group_account_id, statuses=config.SEAT_OCCUPYING_STATUSES, exclude_id=None):
    intervals = []
    for seat in group_seats(group_account_id):
        if seat["status"] not in statuses:
            continue
        if exclude_id is not None and seat["id"] == exclude_id:
            continue
        ends_on = parse_date(seat["ends_on"]) if seat.get("ends_on") else None
        intervals.append((parse_date(seat["starts_on"]), ends_on))
    return intervals


def seats_assigned_count(group):
    return peak_occupancy(seat_intervals(group["id"]))


def recompute_group_counters(group):
    assigned = seats_assigned_count(group)
    group["seats_assigned_count"] = assigned
    group["seats_available_count"] = max(0, group["seat_capacity"] - assigned)


def funding_subscription(group_account_id):
    rows = by_seq(
        [s for s in db.subscriptions.values() if s.get("group_account_id") == group_account_id]
    )
    return rows[0] if rows else None


def funding_subscription_live(group_account_id):
    for sub in by_seq(
        [s for s in db.subscriptions.values() if s.get("group_account_id") == group_account_id]
    ):
        if sub["lifecycle_status"] == "ACTIVE" and sub["dunning_status"] != "FAILED_FINAL":
            return sub
    return None
