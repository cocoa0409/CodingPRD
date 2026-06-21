"""Calculation rules (PRD §2.6, §3.3, §3.4, §3.7, §3.8).

All monetary amounts are integer cents; fractional cents are rounded half up.
"""
import math

import util

# --- order_pricing constants (PRD §3.3, §2.6) ---
GROUP_MIN_QTY = 5
FEE_RATE = 0.03
FEE_CAP_CENTS = 5000

# --- order_refund constants (PRD §3.4) ---
SECONDS_PER_DAY = 86400

# --- waitlist_priority constants (PRD §3.8) ---
LOYALTY_POINTS = {"NONE": 0, "SILVER": 100, "GOLD": 200, "PLATINUM": 300}
EARLY_WINDOW_HOURS = 24
GROUP_FACTOR_PER_HEAD = 5
GROUP_FACTOR_CAP = 60

# --- onsite_window constant (PRD §3.5, §3.7) ---
PICKUP_WINDOW_HOURS = 48

# --- booth_charge zone daily rates in whole cents (PRD §3.7) ---
ZONE_DAILY_RATE = {"STANDARD": 50000, "PREMIUM": 120000, "ENDCAP": 200000}


def group_discount_pct(total_badge_qty):
    """Tiered group-discount breakpoint schedule (PRD §3.3)."""
    if total_badge_qty >= 50:
        return 0.150
    if total_badge_qty >= 25:
        return 0.125
    if total_badge_qty >= 10:
        return 0.100
    if total_badge_qty >= 5:
        return 0.050
    return 0.000


def price_order(lines, base_price_for):
    """Compute order pricing fields (PRD §3.3, §2.6).

    `lines` is a list of line-item dicts. `base_price_for(line)` returns the
    line's ticket type base_price_cents. Rounding order is pinned per-line then
    sum; the fee is then rounded once on its own and capped.

    Returns (per_line_results, ticket_subtotal_cents, processing_fee_cents,
    total_cents, total_badge_qty, is_group, discount_pct).
    """
    total_badge_qty = sum(line["quantity"] for line in lines)
    pct = group_discount_pct(total_badge_qty)

    per_line = []
    for line in lines:
        line_base = base_price_for(line) * line["quantity"]
        line_discounted = util.round_half_up(line_base * (1 - pct))
        per_line.append({"line_base_cents": line_base, "line_discounted_cents": line_discounted})

    ticket_subtotal = sum(pl["line_discounted_cents"] for pl in per_line)
    processing_fee = min(util.round_half_up(ticket_subtotal * FEE_RATE), FEE_CAP_CENTS)
    total = ticket_subtotal + processing_fee
    is_group = total_badge_qty >= GROUP_MIN_QTY
    return per_line, ticket_subtotal, processing_fee, total, total_badge_qty, is_group, pct


def refund_penalty_pct(event_start_utc, current_clock):
    """Forward-looking refund penalty percentage (PRD §3.4).

    days_before = floor((event_start - now) / 86400 seconds).
    """
    delta_seconds = (event_start_utc - current_clock).total_seconds()
    days_before = math.floor(delta_seconds / SECONDS_PER_DAY)
    if days_before > 30:
        return 0.00
    if days_before >= 8:
        return 0.25
    if days_before >= 1:
        return 0.50
    return 1.00  # day-of (days_before <= 0) or after start


def refund_amount(ticket_subtotal_cents, event_start_utc, current_clock):
    """Refund = round_half_up(subtotal * (1 - penalty)); fee never refunded (PRD §3.4)."""
    pct = refund_penalty_pct(event_start_utc, current_clock)
    return util.round_half_up(ticket_subtotal_cents * (1 - pct))


def priority_score(loyalty_tier, created_at_dt, lottery_open_dt, group_size):
    """Weighted priority score (PRD §3.8); also scores session reservations.

    loyalty_points + early_bird_bonus + group_size_factor.
    """
    loyalty = LOYALTY_POINTS.get(loyalty_tier, 0)
    early_bonus = 0
    if lottery_open_dt is not None and created_at_dt is not None:
        from datetime import timedelta
        window_end = lottery_open_dt + timedelta(hours=EARLY_WINDOW_HOURS)
        if lottery_open_dt <= created_at_dt <= window_end:
            early_bonus = 50
    group_factor = min(group_size * GROUP_FACTOR_PER_HEAD, GROUP_FACTOR_CAP)
    return loyalty + early_bonus + group_factor
