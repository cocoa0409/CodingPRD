"""The SLA clock partition, breach tiers and service credits (PRD 3.6).

The clock is not elapsed time: every whole minute between the ticket's
created_at and the evaluation instant is classified into exactly one of three
buckets in a fixed precedence -- paused, then uncovered, then counted -- so
the three always sum back to the elapsed total.  That sum is the ticket-minute
conservation invariant of PRD 2.10 and it is why the partition is always
recomputed as a whole rather than accumulated field by field.
"""

from decimal import Decimal

from errors import ApiError
from money import (
    CREDIT_CAP_PCT_OF_MONTHLY_FEE, SLA_AT_RISK_PCT,
    SLA_BREACH_TIER_MAJOR_MAX_RATIO, SLA_BREACH_TIER_MINOR_MAX_RATIO,
    SLA_CREDIT_PCT_MAJOR, SLA_CREDIT_PCT_MINOR, SLA_CREDIT_PCT_SEVERE,
    BUSINESS_HOURS_END_UTC_MINUTE, BUSINESS_HOURS_START_UTC_MINUTE,
    as_decimal, floor_pct, round_half_up,
)
from store import clock, db, new_row
from ladder import touch, in_force_subscription, plan_of
from timeutil import floor_minutes_between, try_parse_instant

BREACHED_STATES = ("BREACHED_FIRST_RESPONSE", "BREACHED_ONSITE", "CREDITED")


# --------------------------------------------------------------------------
# Coverage counting -- closed form, O(1) in the span length
# --------------------------------------------------------------------------
_DAY_MINUTES = 1440


def _covered_upto(x):
    """#{k in [0, x) : k mod 1440 lies in [540, 1020)} -- the business-hours
    window applies on every calendar day including Saturdays and Sundays
    (PRD 3.6), so there is no weekday term."""
    if x <= 0:
        return 0
    width = BUSINESS_HOURS_END_UTC_MINUTE - BUSINESS_HOURS_START_UTC_MINUTE
    full, rem = divmod(x, _DAY_MINUTES)
    partial = max(0, min(rem, BUSINESS_HOURS_END_UTC_MINUTE) - BUSINESS_HOURS_START_UTC_MINUTE)
    return full * width + partial


def _covered_prefix(first_minute_index, count):
    """Number of k in [first, first+count) with k mod 1440 in [540, 1020)."""
    if count <= 0:
        return 0
    return _covered_upto(first_minute_index + count) - _covered_upto(first_minute_index)


def _segments(ticket, eval_at):
    """The ticket's customer-wait segments as half-open [start, end) minute
    ranges relative to created_at, clipped to [0, total)."""
    created = try_parse_instant(ticket["created_at"])
    out = []
    for seg in ticket.get("_pause_segments", []):
        start = try_parse_instant(seg[0])
        end = try_parse_instant(seg[1]) if seg[1] is not None else eval_at
        if start is None:
            continue
        if end is None or end <= start:
            continue
        out.append((start, end))
    if ticket.get("pause_started_at"):
        start = try_parse_instant(ticket["pause_started_at"])
        if start is not None and eval_at > start:
            out.append((start, eval_at))
    out.sort(key=lambda p: p[0])
    return created, out


def _ceil_div(a, b):
    return -((-a) // b)


def _minute_range(created, start, end, total):
    """Minutes m in [0, total) whose start instant created + 60m lies inside
    the half-open segment [start, end)."""
    lo_secs = int((start - created).total_seconds())
    hi_secs = int((end - created).total_seconds())
    lo = _ceil_div(lo_secs, 60)
    hi = _ceil_div(hi_secs, 60)
    lo = max(0, min(total, lo))
    hi = max(0, min(total, hi))
    return lo, hi


def evaluation_instant(ticket):
    """PRD 3.6: the earlier of the current logical clock and resolved_at when
    resolved_at is set; simply the clock when it is null."""
    now = clock.now()
    resolved = try_parse_instant(ticket.get("resolved_at")) if ticket.get("resolved_at") else None
    if resolved is not None and resolved < now:
        return resolved
    return now


def partition(ticket):
    """Return (counted, paused, uncovered, total) at the evaluation instant."""
    eval_at = evaluation_instant(ticket)
    created, segs = _segments(ticket, eval_at)
    total = floor_minutes_between(created, eval_at)
    if total < 0:
        total = 0
    if total == 0:
        return 0, 0, 0, 0

    # Paused minutes -- the union of the (disjoint, ordered) segments.
    ranges = []
    paused = 0
    for start, end in segs:
        lo, hi = _minute_range(created, start, end, total)
        if hi > lo:
            if ranges and lo <= ranges[-1][1]:
                prev_lo, prev_hi = ranges.pop()
                lo, hi = prev_lo, max(prev_hi, hi)
            ranges.append((lo, hi))
    paused = sum(hi - lo for lo, hi in ranges)

    sub = in_force_subscription(ticket["household_id"])
    plan = plan_of(sub) if sub is not None else None
    coverage = plan.get("coverage_mode") if plan else "TWENTY_FOUR_SEVEN"

    if coverage != "BUSINESS_HOURS":
        # Every minute is covered, so uncovered is always 0.
        uncovered = 0
    else:
        c0 = (created.hour * 60) + created.minute
        covered_all = _covered_prefix(c0, total)
        uncovered_all = total - covered_all
        uncovered_in_paused = 0
        for lo, hi in ranges:
            covered_in_range = _covered_prefix(c0 + lo, hi - lo)
            uncovered_in_paused += (hi - lo) - covered_in_range
        uncovered = uncovered_all - uncovered_in_paused

    counted = total - paused - uncovered
    paused = max(0, paused)
    uncovered = max(0, uncovered)
    counted = max(0, counted)
    return counted, paused, uncovered, total


def recompute(ticket):
    """Write the partition onto the ticket.  Called only by the six operations
    PRD 3.6 lists; the read-only projection never calls this."""
    counted, paused, uncovered, _total = partition(ticket)
    ticket["sla_counted_minutes"] = counted
    ticket["sla_paused_minutes"] = paused
    ticket["sla_uncovered_minutes"] = uncovered
    return counted


def active_target(ticket):
    """PRD 3.5: while first_response_at is null the active target is the
    first-response target; once it is set, the onsite-resolution target."""
    if ticket.get("first_response_at") is None:
        return ticket.get("first_response_target_minutes") or 0
    return ticket.get("onsite_resolution_target_minutes") or 0


# --------------------------------------------------------------------------
# Breach tier and credit
# --------------------------------------------------------------------------
def breach_tier_and_pct(counted, target):
    ratio = (as_decimal(counted) - as_decimal(target)) / as_decimal(target)
    if ratio <= SLA_BREACH_TIER_MINOR_MAX_RATIO:
        return "MINOR", SLA_CREDIT_PCT_MINOR
    if ratio <= SLA_BREACH_TIER_MAJOR_MAX_RATIO:
        return "MAJOR", SLA_CREDIT_PCT_MAJOR
    return "SEVERE", SLA_CREDIT_PCT_SEVERE


def cap_remaining(subscription):
    """PRD 3.6: the cycle cap is the FLOOR of half the monthly fee; the cents
    already issued are summed over this cycle's ServiceCredit rows only."""
    cap = floor_pct(subscription.get("monthly_fee_cents") or 0, CREDIT_CAP_PCT_OF_MONTHLY_FEE)
    cycle = subscription.get("cycle_index")
    issued = 0
    for credit in db.service_credits.values():
        if credit.get("subscription_id") == subscription["id"] and credit.get("cycle_index") == cycle:
            issued += credit.get("amount_cents") or 0
    return max(0, cap - issued)


def issue_credit(subscription, household_id, ticket_id, reason, breach_tier,
                 uncapped_cents):
    """Create the ServiceCredit row when, and only when, amount_cents > 0."""
    room = cap_remaining(subscription)
    amount = min(uncapped_cents, room)
    if amount <= 0:
        return None
    row = new_row()
    row.update({
        "household_id": household_id,
        "subscription_id": subscription["id"],
        "ticket_id": ticket_id,
        "reason": reason,
        "breach_tier": breach_tier,
        "uncapped_amount_cents": uncapped_cents,
        "amount_cents": amount,
        "cycle_index": subscription.get("cycle_index"),
        "applied_to_cycle_index": (subscription.get("cycle_index") or 0) + 1,
    })
    db.service_credits[row["id"]] = row
    subscription["credits_issued_cents_this_cycle"] = (
        subscription.get("credits_issued_cents_this_cycle") or 0) + amount
    subscription["next_invoice_credit_cents"] = (
        subscription.get("next_invoice_credit_cents") or 0) + amount
    return row


def settle_met(ticket):
    """PRD 3.6 'Meeting the target': moves the axis to MET when it stood in
    WITHIN or AT_RISK and the counted minutes are within the onsite target."""
    counted = recompute(ticket)
    if ticket.get("sla_status") in ("WITHIN", "AT_RISK"):
        if counted <= (ticket.get("onsite_resolution_target_minutes") or 0):
            ticket["sla_status"] = "MET"
    return counted
