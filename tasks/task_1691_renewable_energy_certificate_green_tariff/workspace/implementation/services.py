"""Shared derived-field computations, cascades and calculation engines."""

import calendar
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from store import STORE, clock_now, now_ts


# --------------------------------------------------------- derived fields

def account_holdings(account_id):
    active = 0
    locked = 0
    for c in STORE["certificates"].values():
        if c["account_id"] != account_id:
            continue
        if c["status"] == "ACTIVE":
            active += c["quantity_mwh"]
        elif c["status"] == "LOCKED":
            locked += c["quantity_mwh"]
    return active, locked


def generator_cumulative_accepted_kwh(generator_id):
    total = 0
    for r in STORE["readings"].values():
        if r["generator_id"] == generator_id and r["status"] == "ACCEPTED":
            total += r["metered_kwh"]
    return total


def program_committed_capacity_kw(program_id):
    # A SUSPENDED subscription retains its capacity allocation, so both
    # ACTIVE and SUSPENDED subscriptions count toward committed capacity.
    total = 0
    for s in STORE["subscriptions"].values():
        if s["program_id"] == program_id and s["status"] in ("ACTIVE", "SUSPENDED"):
            total += s["allocation_kw"]
    return total


def program_retired_mwh_current_year(program_id):
    year = clock_now().year
    total = 0
    for r in STORE["retirements"].values():
        if (r["purpose"] == "VOLUNTARY_PROGRAM" and r.get("program_id") == program_id
                and r["_created_dt"].year == year):
            total += r["quantity_mwh"]
    return total


def obligation_covered_mwh(obligation_id):
    total = 0
    for r in STORE["retirements"].values():
        if r["purpose"] == "COMPLIANCE" and r.get("obligation_id") == obligation_id:
            total += r["quantity_mwh"]
    return total


def touch(rec):
    rec["updated_at"] = now_ts()
    rec["version"] += 1


# -------------------------------------------------------------- cascades

def cancel_proposed_trades_of_seller(account_id):
    for t in STORE["trades"].values():
        if t["from_account_id"] == account_id and t["status"] == "PROPOSED":
            t["status"] = "CANCELLED"
            touch(t)


def suspend_account(account):
    """ACTIVE -> SUSPENDED; cancels every PROPOSED trade it sells."""
    account["status"] = "SUSPENDED"
    cancel_proposed_trades_of_seller(account["id"])


def add_strike(account):
    """One settlement-failure strike; auto-suspends at the 3-strike limit.

    The strike increment and a threshold-triggered suspension are one atomic
    account mutation for the triggering request (a single version bump).
    """
    account["failure_strikes"] += 1
    if account["failure_strikes"] >= 3 and account["status"] == "ACTIVE":
        suspend_account(account)
    touch(account)


def waitlist_promotion_scan(program):
    """Promote WAITLISTED subscriptions while capacity fits, in
    waitlisted_at ASC / created_at ASC order, skipping candidates that do
    not fit without blocking later ones."""
    cap = program["capacity_cap_kw"]
    remaining = cap - program_committed_capacity_kw(program["id"])
    candidates = [
        s for s in STORE["subscriptions"].values()
        if s["program_id"] == program["id"] and s["status"] == "WAITLISTED"
    ]
    candidates.sort(key=lambda s: (s.get("waitlisted_at") or "", s.get("created_at", ""), s.get("_seq", 0)))
    for cand in candidates:
        if cand["allocation_kw"] <= remaining:
            cand["status"] = "ACTIVE"
            cand["activated_at"] = now_ts()
            cand["_activated_dt"] = clock_now()
            cand["waitlisted_at"] = None
            touch(cand)
            remaining -= cand["allocation_kw"]
            touch(program)


# ------------------------------------------------------------ calculators

def marginal_tier_sum(kwh, rate_tiers):
    """Marginal tier pricing: walk tiers ascending by up_to_kwh (null =
    unbounded), each tier contributes min(remaining, tier_width) * rate.
    Exact integer cents."""
    remaining = int(kwh)
    if remaining <= 0:
        return 0
    tiers = sorted(
        rate_tiers,
        key=lambda t: (t.get("up_to_kwh") is None,
                       t.get("up_to_kwh") if t.get("up_to_kwh") is not None else 0),
    )
    total = 0
    prev = 0
    for tier in tiers:
        if remaining <= 0:
            break
        up_to = tier.get("up_to_kwh")
        if up_to is None:
            width = remaining
        else:
            width = up_to - prev
            if width <= 0:
                prev = up_to
                continue
        take = min(remaining, width)
        total += take * int(tier["rate_cents_per_kwh"])
        remaining -= take
        if up_to is not None:
            prev = up_to
    return total


def round_half_up_div(numerator, denominator):
    """Integer result of numerator/denominator rounded half up."""
    q = (Decimal(int(numerator)) / Decimal(int(denominator))).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


def broker_fee_bps(quantity_mwh):
    if quantity_mwh < 100:
        return 50
    if quantity_mwh < 1000:
        return 35
    return 20


def month_bounds(year, month):
    """[start, end) datetimes of a calendar month, and its day count."""
    from datetime import datetime, timezone
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    days = calendar.monthrange(year, month)[1]
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end, days


def proration_active_days(subscription, period_month):
    """Days of period_month during which the subscription was ACTIVE or
    SUSPENDED for any part of the day, derived from activated_at /
    terminated_at against the period bounds."""
    y, m = int(period_month[:4]), int(period_month[5:7])
    start, end, days_in_period = month_bounds(y, m)
    activated = subscription.get("_activated_dt")
    terminated = subscription.get("_terminated_dt")
    if activated is None:
        return 0, days_in_period
    active_days = 0
    for d in range(days_in_period):
        day_start = start + timedelta(days=d)
        day_end = day_start + timedelta(days=1)
        if activated < day_end and (terminated is None or terminated > day_start):
            active_days += 1
    return active_days, days_in_period


def compute_final_credit(bill, subscription, program):
    """FINAL variant: actual usage, calendar-day proration, charges cap."""
    deemed_kwh = subscription["allocation_kw"] * program["kwh_per_kw_monthly"]
    eligible = min(bill["usage_kwh"], deemed_kwh)
    base = marginal_tier_sum(eligible, program["rate_tiers"])
    active_days, days_in_period = proration_active_days(subscription, bill["period_month"])
    prorated = round_half_up_div(base * active_days, days_in_period)
    credit = min(prorated, bill["charges_cents"])
    return credit, active_days, days_in_period


def compute_provisional_credit(subscription, program):
    """PROVISIONAL variant: estimated usage, no proration, no charges cap."""
    deemed_kwh = subscription["allocation_kw"] * program["kwh_per_kw_monthly"]
    eligible = min(subscription["estimated_usage_kwh"], deemed_kwh)
    return marginal_tier_sum(eligible, program["rate_tiers"])


# ----------------------------------------------------------- claim pinning

def pin_retirements(scope, program_id, obligation_id, report_year):
    """The pinned set: unclaimed retirements matching the scope whose
    retired-at year equals report_year, in creation order."""
    out = []
    for r in STORE["retirements"].values():
        if r.get("claimed_in_report_id") is not None:
            continue
        if r["_created_dt"].year != report_year:
            continue
        if scope == "VOLUNTARY_PROGRAM":
            if r["purpose"] == "VOLUNTARY_PROGRAM" and r.get("program_id") == program_id:
                out.append(r)
        else:
            if r["purpose"] == "COMPLIANCE" and r.get("obligation_id") == obligation_id:
                out.append(r)
    out.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return out


def totalize(retirements):
    total = 0
    by_tech = {}
    by_region = {}
    for r in retirements:
        q = r["quantity_mwh"]
        total += q
        by_tech[r["technology"]] = by_tech.get(r["technology"], 0) + q
        by_region[r["region_code"]] = by_region.get(r["region_code"], 0) + q
    return total, by_tech, by_region


def repin_report(report):
    pinned = pin_retirements(report["scope"], report.get("program_id"),
                             report.get("obligation_id"), report["report_year"])
    total, by_tech, by_region = totalize(pinned)
    report["retirement_ids"] = [r["id"] for r in pinned]
    report["total_mwh"] = total
    report["totals_by_technology"] = by_tech
    report["totals_by_region"] = by_region


def accepted_report_exists(scope, program_id, obligation_id, report_year, exclude_id=None):
    for rep in STORE["reports"].values():
        if rep["id"] == exclude_id:
            continue
        if rep["status"] != "ACCEPTED":
            continue
        if rep["report_year"] != report_year or rep["scope"] != scope:
            continue
        if scope == "VOLUNTARY_PROGRAM" and rep.get("program_id") == program_id:
            return True
        if scope == "COMPLIANCE_OBLIGATION" and rep.get("obligation_id") == obligation_id:
            return True
    return False


def generator_account(generator_id):
    for a in STORE["accounts"].values():
        if a["account_type"] == "GENERATOR" and a.get("generator_id") == generator_id:
            return a
    return None
