"""Calculation rules (SCAFFOLD §1.3 / PRD §3). Integer cents, ROUND_HALF_UP.

Pinned rounding orders:
  - royalty: round per bracket, then sum
  - crew pay: round once per line, then sum
  - per-diem ACTUAL_DAYS: round the half-day rate first, then multiply
"""

from datetime import timedelta

from util import rhu, dec, date_to_dt

# Royalty basis-point rates (SCAFFOLD calc_licensor_royalty constants)
PRE_T1_BPS, PRE_T2_BPS = 600, 900
POST_T1_BPS, POST_T2_BPS = 800, 1100


def calc_provisional_settlement_estimate(guarantee_cents, split_pct, advance_sales_cents):
    """Frozen at ADVANCED->READY. Advance sales ARE the adjusted-gross proxy."""
    split_amount = rhu(dec(split_pct) / Decimal100 * advance_sales_cents)
    return max(guarantee_cents, split_amount)


Decimal100 = dec(100)
Decimal10000 = dec(10000)


def waterfall_adjusted_gross(audited_gross_cents, taxes_cents, levies_cents):
    """Deduction order pinned: taxes first, levies second."""
    return audited_gross_cents - taxes_cents - levies_cents


def waterfall_venue_payment(guarantee_cents, split_pct, adjusted_gross_cents):
    """Only waterfall step that rounds; venue-favorable guarantee-vs-split."""
    split_amount = rhu(dec(split_pct) / Decimal100 * adjusted_gross_cents)
    return max(guarantee_cents, split_amount)


def waterfall_producer_share(adjusted_gross_cents, venue_payment_cents):
    """May legitimately go negative (producer covers shortfall)."""
    return adjusted_gross_cents - venue_payment_cents


def calc_licensor_royalty(producer_share_cents, threshold_cents, recouped):
    """Strictly marginal two-bracket royalty; per-bracket rounding, then sum."""
    if producer_share_cents <= 0:
        return 0
    t1_bps, t2_bps = (POST_T1_BPS, POST_T2_BPS) if recouped else (PRE_T1_BPS, PRE_T2_BPS)
    share = dec(producer_share_cents)
    t = dec(threshold_cents)
    bracket1 = rhu(dec(t1_bps) / Decimal10000 * min(share, t))
    bracket2 = rhu(dec(t2_bps) / Decimal10000 * max(dec(0), share - t))
    return bracket1 + bracket2


def calc_per_diem(policy, daily_rate_cents, days_present, travel_days):
    """FULL_WEEK ignores days entirely; ACTUAL_DAYS rounds the half rate first."""
    if policy == "FULL_WEEK":
        return 7 * daily_rate_cents
    half_rate = rhu(dec(daily_rate_cents) / dec(2))
    return (days_present - travel_days) * daily_rate_cents + travel_days * half_rate


def bump_unit_cents(principal_weekly_salary_cents):
    """Per-show bump unit: principal weekly salary / 8, rounded half-up."""
    return rhu(dec(principal_weekly_salary_cents) / dec(8))


def crew_line_pay(hours_worked, rate_cents_per_hour):
    """8h straight / next 4h at 1.5x / beyond 12h at 2x; round ONCE per line."""
    h = dec(hours_worked)
    rate = dec(rate_cents_per_hour)
    eight, four, twelve = dec(8), dec(4), dec(12)
    regular = min(h, eight) * rate
    ot1 = min(max(h - eight, dec(0)), four) * rate * dec("1.5")
    ot2 = max(h - twelve, dec(0)) * rate * dec(2)
    return rhu(regular + ot1 + ot2)


def crew_cancellation_penalty(lines, scheduled_start_dt, clock_dt):
    """< 24h before scheduled_start: 4h x rate per line (round per line, sum).
    Exactly 24h remaining pays 0."""
    if scheduled_start_dt - clock_dt < timedelta(hours=24):
        return sum(rhu(dec(4) * dec(l["rate_cents_per_hour"])) for l in lines)
    return 0


def calc_cancellation_penalty(prior_status, guarantee_cents, play_week_start_date, clock_dt):
    """days_out = whole days (floor) between the logical clock and play_week_start."""
    if prior_status == "TENTATIVE":
        return 0
    days_out = (date_to_dt(play_week_start_date) - clock_dt).days  # timedelta.days floors
    if days_out > 60:
        return 0
    if days_out >= 31:
        return rhu(dec("0.25") * guarantee_cents)
    return rhu(dec("0.50") * guarantee_cents)
