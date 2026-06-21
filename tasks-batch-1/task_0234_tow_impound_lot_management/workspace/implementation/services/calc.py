"""Pure calculation rules (scaffold §1.3 / PRD §2.6, §3.5-§3.9)."""
import math
from decimal import Decimal, ROUND_HALF_UP

from clock import now, parse_iso

SUSPENSION_PENALTY_PCT = Decimal("20.0")
TIER1_CENTS = 50000
TIER2_CENTS = 150000


def days_between(start_dt, end_dt):
    """Whole calendar days via ceil(hours/24). PRD §2.6: 24.0h -> 1 day,
    24.01h -> 2 days. The day boundary is strict on hours ('>')."""
    if start_dt is None or end_dt is None:
        return 0
    seconds = (end_dt - start_dt).total_seconds()
    if seconds <= 0:
        return 0
    hours = seconds / 3600.0
    return int(math.ceil(hours / 24.0))


def segment_end_dt(order, seg):
    """Resolve the effective end instant of a ledger segment for accrual.
    Open segments (segment_end None) count to accrual_frozen_at if frozen,
    else to the current clock."""
    end = seg.get("_segment_end_dt")
    if end is not None:
        return end
    frozen = order.get("_accrual_frozen_dt")
    if frozen is not None:
        return frozen
    return now()


def accrued(order, lot, segments):
    """ACCRUED storage variant (scaffold storage_fee_accrual). Sums per-segment
    day counts over accrual segments (origin kind ACCRUAL or RESUME). A closed
    segment contributes its stored days/charge; the single open segment is
    computed live to the freeze instant (if frozen) or the current clock.
    Returns (accrued_days, cents)."""
    rate = lot["daily_storage_rate_cents"]
    total_days = 0
    total_cents = 0
    for seg in segments:
        if seg.get("_accrual_kind") not in ("ACCRUAL", "RESUME"):
            continue
        if seg.get("_segment_end_dt") is not None:
            # Closed segment: use its finalized stored values.
            total_days += seg.get("days_counted") or 0
            total_cents += seg.get("segment_charge_cents") or 0
        else:
            # Open segment: compute live.
            start = seg.get("_segment_start_dt")
            end = segment_end_dt(order, seg)
            d = days_between(start, end)
            total_days += d
            total_cents += d * rate
    return total_days, total_cents


def estimated_storage(lot):
    """ESTIMATE variant fixed at intake: rate * statutory_hold_days."""
    return lot["daily_storage_rate_cents"] * lot["statutory_hold_days"]


def balance_due(order, lot):
    """release_fee_breakdown: per-component whole-cent values summed in the
    pinned order storage -> admin -> lien."""
    c_storage = order["accrued_storage_cents"]
    c_admin = lot["admin_fee_cents"]
    c_lien = lot["lien_processing_fee_cents"] if order.get("lienholder_id") else 0
    return c_storage + c_admin + c_lien


def net_due(balance_due_cents, waiver_credit_cents):
    return max(0, balance_due_cents - waiver_credit_cents)


def waiver_cap(pre_waiver_balance_cents):
    """Tiered cap on a waiver, evaluated against the pre-waiver balance.
    floor(balance * cap_pct / 100)."""
    if pre_waiver_balance_cents < TIER1_CENTS:
        cap_pct = 100
    elif pre_waiver_balance_cents < TIER2_CENTS:
        cap_pct = 50
    else:
        cap_pct = 25
    return (pre_waiver_balance_cents * cap_pct) // 100


def pct_round_half_up(numerator, denominator):
    """percentage to 2 dp, round_half_up, clamped 0.00..100.00.
    denominator == 0 -> 100.00 (defined that way for raw standing)."""
    if denominator == 0:
        return Decimal("100.00")
    val = (Decimal(numerator) / Decimal(denominator) * Decimal(100)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    if val < Decimal("0.00"):
        val = Decimal("0.00")
    if val > Decimal("100.00"):
        val = Decimal("100.00")
    return val


def waterfall(order, lot, sale_price_cents):
    """auction_proceeds_distribution for a single sold order. Returns
    (lot_recovery, lien_payoff, surplus). Conservation: the three sum to price."""
    lot_recovery = min(sale_price_cents, order["accrued_storage_cents"] + lot["admin_fee_cents"])
    remaining = sale_price_cents - lot_recovery
    lien_cap = lot["lien_processing_fee_cents"] if order.get("lienholder_id") else 0
    lien_payoff = min(remaining, lien_cap)
    remaining -= lien_payoff
    surplus = max(0, remaining)
    return lot_recovery, lien_payoff, surplus
