"""Calculation rules per scaffold §1.3. Integer cents, round_half_up."""

from decimal import Decimal, ROUND_HALF_UP

from db import whole_days_between


def rhu(value) -> int:
    """Round half-up to nearest integer."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------- claim_provisional_total
def claim_provisional_total(lines, payer_type: str) -> int:
    """Per-line rounding, then sum. factor = 1.00 VR else 0.80 INSURANCE."""
    factor = Decimal("1.00") if payer_type == "VR" else Decimal("0.80")
    total = 0
    for line in lines:
        cents = Decimal(line["unit_price_cents"]) * Decimal(line["quantity"]) * factor
        total += int(cents.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return total


# ---------------------------------------------------------------- payer_responsibility
def payer_responsibility(allowed_amount_cents: int, payer_type: str,
                         remaining_amount_cents: int, provisional_total_cents: int,
                         copay_tier: str):
    """Returns (payer_pays_cents, client_pays_cents)."""
    available_cents = remaining_amount_cents + provisional_total_cents
    if payer_type == "VR":
        base_cents = allowed_amount_cents
    else:  # INSURANCE
        base_cents = rhu(Decimal(allowed_amount_cents) * Decimal("0.80"))
    payer_pays_cents = min(base_cents, available_cents)
    client_pays_cents = allowed_amount_cents - payer_pays_cents
    if copay_tier == "LOW_INCOME" and payer_type == "INSURANCE":
        client_pays_cents = rhu(Decimal(client_pays_cents) * Decimal("0.5"))
        payer_pays_cents = allowed_amount_cents - client_pays_cents
    return payer_pays_cents, client_pays_cents


# ---------------------------------------------------------------- outcome_composite
def outcome_provisional_composite(task_score: int, satisfaction_score: int) -> int:
    return rhu(Decimal("0.5") * task_score + Decimal("0.5") * satisfaction_score)


def outcome_final_composite(acuity_delta: int, task_score: int, satisfaction_score: int) -> int:
    return rhu(Decimal("0.3") * acuity_delta + Decimal("0.4") * task_score
               + Decimal("0.3") * satisfaction_score)


# ---------------------------------------------------------------- trial_conversion_fee
def trial_conversion_fee(list_price_cents: int, warranty_cents: int,
                         trial_days: int, dispensed_at, now) -> int:
    """Pinned evaluation order. For PURCHASE orders trial_days/dispensed_at produce days_used=0."""
    if dispensed_at is None or trial_days is None:
        days_used = 0
    else:
        days_used = whole_days_between(dispensed_at, now)
        if days_used < 0:
            days_used = 0
        if days_used > trial_days:
            days_used = trial_days
    price = Decimal(list_price_cents)
    daily_credit = (price * Decimal("0.02") * days_used).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    cap = (price * Decimal("0.30")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    trial_credit = int(min(daily_credit, cap))
    device_subtotal = list_price_cents - trial_credit
    service_fee = int((Decimal(device_subtotal) * Decimal("0.12")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return device_subtotal + service_fee + warranty_cents


# ---------------------------------------------------------------- subscription_loyalty_fee
def subscription_loyalty_fee(total_paid_cents: int, monthly_cents: int) -> int:
    if total_paid_cents >= 100000:
        tier = Decimal("0.10")
    elif total_paid_cents >= 50000:
        tier = Decimal("0.05")
    else:
        tier = Decimal("0.0")
    return int((Decimal(monthly_cents) * (Decimal("1") - tier)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------- subscription_cancel_credit
def subscription_cancel_credit(monthly_cents: int, period_end, now) -> int:
    days_remaining = whole_days_between(now, period_end)
    if days_remaining < 0:
        days_remaining = 0
    if days_remaining > 30:
        days_remaining = 30
    return int((Decimal(monthly_cents) * Decimal(days_remaining) / Decimal(30)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))
