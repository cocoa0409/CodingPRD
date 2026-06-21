"""Calculation rules — SCAFFOLD §1.3 / PRD §3.2, §3.5, §3.4, §3.7.

All money is integer cents (PRD §2.8). round-half-up at the per-ticket step only.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

# SCAFFOLD §1.3 constants
MAX_FREEZE_DAYS = 30
SECONDS_PER_DAY = 86400
SECONDS_PER_HOUR = 3600
GREEN_MIN_CM = 122
YELLOW_MIN_CM = 107


def round_half_up_cents(value):
    """Round a Decimal to whole cents using round-half-up (PRD §2.8)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def quote_order(order, policy, guest, park):
    """quote_order calc (SCAFFOLD §1.3 / PRD §3.2).

    Discounts are NOT stacked — effective_pct = max(resident_pct, group_pct).
    Round-half-up PER TICKET first, then add combo, then multiply by party_size.
    Wallet credit applied AFTER subtotal, capped at subtotal and at balance.
    Returns a dict of computed fields.
    """
    base = policy["base_price_cents"]

    resident_rate_applied = any(
        isinstance(guest["zip_code"], str) and guest["zip_code"].startswith(p)
        for p in park["resident_zip_prefixes"]
    )
    group_rate_applied = order["party_size"] >= policy["group_threshold"]

    resident_pct = policy["resident_discount_pct"] if resident_rate_applied else 0
    group_pct = policy["group_discount_pct"] if group_rate_applied else 0
    effective_pct = max(resident_pct, group_pct)

    # round-half-up at this per-ticket step only.
    discounted_per_ticket = round_half_up_cents(
        Decimal(base) * (Decimal(1) - Decimal(str(effective_pct)))
    )
    combo_add = policy["combo_price_cents"] if order["food_beverage_combo"] else 0
    per_ticket = discounted_per_ticket + combo_add
    subtotal_cents = per_ticket * order["party_size"]

    wallet_credit_used_cents = min(guest["wallet_credit_cents"], subtotal_cents)
    total_cents = subtotal_cents - wallet_credit_used_cents

    return {
        "resident_rate_applied": resident_rate_applied,
        "group_rate_applied": group_rate_applied,
        "subtotal_cents": subtotal_cents,
        "wallet_credit_used_cents": wallet_credit_used_cents,
        "total_cents": total_cents,
    }


def locker_charge(starts_dt, ends_dt, hourly_rate_cents):
    """locker_rental_charge (SCAFFOLD §1.3 / PRD §3.7).

    hours_billed = ceil(duration_seconds / 3600); each STARTED hour bills a full hour.
    """
    elapsed_seconds = (ends_dt - starts_dt).total_seconds()
    hours_billed = math.ceil(elapsed_seconds / SECONDS_PER_HOUR)
    price_cents = hours_billed * hourly_rate_cents
    return hours_billed, price_cents


def freeze_episode_days(frozen_at_dt, current_dt):
    """freeze_days_accounting (SCAFFOLD §1.3 / PRD §3.5).

    episode_days = ceil(elapsed_seconds / 86400); any partial day counts as a full day.
    """
    elapsed_seconds = (current_dt - frozen_at_dt).total_seconds()
    return math.ceil(elapsed_seconds / SECONDS_PER_DAY)


def band_color(height_cm):
    """band_color_assignment (SCAFFOLD §1.3 / PRD §3.4).

    >= 122 -> GREEN; >= 107 (and < 122) -> YELLOW; else RED. >= at each floor.
    """
    if height_cm >= GREEN_MIN_CM:
        return "GREEN"
    if height_cm >= YELLOW_MIN_CM:
        return "YELLOW"
    return "RED"
