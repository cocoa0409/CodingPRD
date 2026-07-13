"""Bandwidth overage — the two variants (PRD 3.6, calculations.hosting_bandwidth_overage)."""

from decimal import Decimal

import config
import db
from services.money import dec, round_half_up


def records_of_period(period):
    """Usage rows of the subscription whose recorded_at falls in [start, end)."""
    rows = [
        r
        for r in db.usage_records.values()
        if r["subscription_id"] == period["subscription_id"]
        and period["_period_start"] <= r["_recorded_at"] < period["_period_end"]
    ]
    rows.sort(key=lambda r: (r["_recorded_at"], r["_seq"]))
    return rows


def bandwidth_used(period):
    return sum(r["amount_mb"] for r in records_of_period(period))


def provisional_overage(period, plan):
    """Chronological, flat rate, rounded PER RECORD."""
    quota = dec(plan["bandwidth_quota_mb"])
    rate = dec(plan["overage_rate_cents_per_gb"])
    mb_per_gb = dec(config.MB_PER_GB)
    remaining = quota
    total = 0
    for record in records_of_period(period):
        amount = dec(record["amount_mb"])
        over = amount - remaining
        if over < 0:
            over = Decimal("0")
        remaining = remaining - amount
        if remaining < 0:
            remaining = Decimal("0")
        total += round_half_up(over / mb_per_gb * rate)
    return total


def final_overage(period, plan):
    """Aggregate first, tiered rate curve, rounded exactly ONCE at the end."""
    rate = dec(plan["overage_rate_cents_per_gb"])
    mb_per_gb = dec(config.MB_PER_GB)
    total_mb = Decimal("0")
    for record in records_of_period(period):
        total_mb += dec(record["amount_mb"])
    excess_mb = total_mb - dec(plan["bandwidth_quota_mb"])
    if excess_mb < 0:
        excess_mb = Decimal("0")
    excess_gb = excess_mb / mb_per_gb

    tier1_cap = dec(config.OVERAGE_TIER1_GB)
    tier2_cap = dec(config.OVERAGE_TIER2_GB)
    t1 = min(excess_gb, tier1_cap)
    t2 = min(max(excess_gb - tier1_cap, Decimal("0")), tier2_cap)
    t3 = max(excess_gb - tier1_cap - tier2_cap, Decimal("0"))

    charge = (
        t1 * rate
        + t2 * rate * Decimal(config.OVERAGE_TIER2_FACTOR)
        + t3 * rate * Decimal(config.OVERAGE_TIER3_FACTOR)
    )
    return round_half_up(charge)
