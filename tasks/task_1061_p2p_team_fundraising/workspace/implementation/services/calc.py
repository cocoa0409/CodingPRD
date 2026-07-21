"""Pure cent arithmetic (PRD 2.6, 3.3, 3.4, 3.5, 3.6, 3.8)."""
from decimal import Decimal, ROUND_HALF_UP

import config


def round_half_up(value):
    """Round a Decimal to whole cents, half away from zero."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def pct(amount_cents, percentage):
    return round_half_up(Decimal(amount_cents) * Decimal(percentage))


def donation_fee_and_net(amount_cents, cover_fees):
    """PRD 3.4: components rounded independently, sum never re-rounded."""
    platform_component_cents = pct(amount_cents, config.PLATFORM_FEE_PCT)
    processing_component_cents = pct(amount_cents, config.PROCESSING_FEE_PCT)
    fee_cents = (
        platform_component_cents
        + processing_component_cents
        + config.PROCESSING_FEE_FIXED_CENTS
    )
    if cover_fees:
        net_cents = amount_cents
    else:
        net_cents = amount_cents - fee_cents
    return fee_cents, net_cents


def donation_charged_amount(amount_cents, fee_cents, cover_fees):
    """PRD 3.4: exactly one grossing-up pass; fee is a function of amount only."""
    if cover_fees:
        return amount_cents + fee_cents
    return amount_cents


def registration_fee_charged(registration_fee_cents, now_dt, early_bird_ends_at):
    """PRD 3.3: strict less-than qualifies for the early-bird discount."""
    if early_bird_ends_at is not None and now_dt < early_bird_ends_at:
        discount_cents = pct(registration_fee_cents, config.EARLY_BIRD_DISCOUNT_PCT)
        return registration_fee_cents - discount_cents
    return registration_fee_cents


def match_amount(amount_cents, pool):
    """PRD 3.5: rounded raw match capped by the per-donation cap and remainder."""
    raw_match_cents = round_half_up(
        Decimal(amount_cents) * Decimal(str(pool["match_ratio"]))
    )
    return min(
        raw_match_cents,
        pool["per_donation_cap_cents"],
        pool["remaining_cents"],
    )


def basis_points(numerator_cents, denominator_cents):
    """PRD 2.6: basis points are floored, never rounded."""
    if denominator_cents <= 0:
        return 0
    return (numerator_cents * config.BASIS_POINTS_SCALE) // denominator_cents


def receipt_number(seq):
    return "RCPT-" + str(seq).zfill(config.RECEIPT_NUMBER_PAD_WIDTH)
