"""Pinned, deterministic calculation rules (PRD §3.3-§3.10, scaffold §1.3).

All monetary math is integer cents. Rounding directions are explicit per the PRD:
floor for fees/percent rebates/market value, ceil only for first-cycle proration.
"""

import datetime


# --- (1) Round-up effective amount (PRD §3.4) ---
def roundup_amounts(purchase_amount_cents, multiplier):
    """base_roundup_cents = (100 - (purchase mod 100)) mod 100; whole-dollar -> 0.
    effective = base * multiplier (multiplier frozen from the card at accrual time)."""
    base = (100 - (purchase_amount_cents % 100)) % 100
    effective = base * multiplier
    return base, effective


# --- (2) Subscription fee (PRD §3.3) ---
def subscription_fee(monthly_fee_cents, months_billed):
    """First charge (months_billed == 0, leaving TRIAL): ceil(monthly_fee/2).
    Steady-state (months_billed >= 1): full monthly_fee_cents."""
    if months_billed == 0:
        return -(-monthly_fee_cents // 2)  # ceil division
    return monthly_fee_cents


# --- (3) Invest settlement math (PRD §3.7) ---
def invest_fee_and_net(gross, management_fee_bps):
    """Pinned eval order: management_fee = floor(gross * bps / 10000);
    net_principal = gross - fee."""
    management_fee_cents = (gross * management_fee_bps) // 10000
    net_principal = gross - management_fee_cents
    return management_fee_cents, net_principal


# --- (4) Withdraw settlement: per-lot market value (PRD §3.7) ---
def lot_market_value(remaining_basis_cents, unit_gain_ratio_bps):
    """floor(remaining_basis * (10000 + unit_gain_ratio_bps) / 10000)."""
    return (remaining_basis_cents * (10000 + unit_gain_ratio_bps)) // 10000


# --- (5) Found-money rebate (PRD §3.10) ---
def found_money_rebate(offer, qualifying_spend_cents):
    """FLAT -> rebate_flat_cents. PERCENT -> min(floor(spend*bps/10000), max_rebate)."""
    if offer["rebate_mode"] == "FLAT":
        return offer["rebate_flat_cents"]
    raw = (qualifying_spend_cents * offer["rebate_percent_bps"]) // 10000
    return min(raw, offer["max_rebate_cents"])


# --- Clock arithmetic for hold/window computations ---
def add_days(dt, days):
    return dt + datetime.timedelta(days=days)
