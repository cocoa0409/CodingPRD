"""Calculation rules (scaffold §1.3 / PRD §2.7, §3.6, §3.8, §3.9)."""
from decimal import Decimal, ROUND_HALF_UP

from services.common import round_half_up_div

# Constants from the scaffold.
BPS_DENOMINATOR = 10000
SAG_PH_BPS = 1850  # SAG pension & health 18.5%
MAX_ROUNDS = 8
SLOT_BUFFER_MINUTES = 15
MEDIA_MULTIPLIER_BPS = {
    "BROADCAST_TV": 3000,
    "CABLE": 2000,
    "STREAMING": 1500,
    "PRINT": 1000,
    "DIGITAL": 1200,
}


def gross_fee_cents(agreed_day_rate_cents, day_span):
    """Exact integer cents: day_rate * inclusive day span. No rounding."""
    return int(agreed_day_rate_cents) * int(day_span)


def commission_cents(gross_cents, commission_rate_bps):
    """round_half_up(gross * rate_bps / 10000) — provisional & final share this."""
    return round_half_up_div(
        Decimal(gross_cents) * Decimal(commission_rate_bps), Decimal(BPS_DENOMINATOR)
    )


def net_to_talent(gross_amount_cents, commission_rate_bps, union_status):
    """Pinned multi-step rounding (PRD §3.8 / scaffold payment_net_to_talent).

    Step 1: commission_withheld = round_half_up(gross * rate / 10000).
    Step 2: SAG pension+health = round_half_up(gross * SAG_PH_BPS / 10000); else 0.
    Step 3: net = gross - commission_withheld - ph (both already rounded).
    Returns (commission_withheld_cents, ph_cents, net_to_talent_cents).
    """
    commission_withheld = round_half_up_div(
        Decimal(gross_amount_cents) * Decimal(commission_rate_bps), Decimal(BPS_DENOMINATOR)
    )
    if union_status == "SAG":
        ph = round_half_up_div(
            Decimal(gross_amount_cents) * Decimal(SAG_PH_BPS), Decimal(BPS_DENOMINATOR)
        )
    else:
        ph = 0
    net = int(gross_amount_cents) - commission_withheld - ph
    return commission_withheld, ph, net


def residual_amount_cents(union_status, base_gross_fee_cents, media_type, period_index):
    """SAG tiered/media residual; NON_UNION -> 0 (scaffold sag_residual).

    Single round_half_up at the FINAL step:
      base * media_mult / 10000 * period_mult / 10000
    """
    if union_status == "NON_UNION":
        return 0
    media_mult = MEDIA_MULTIPLIER_BPS[media_type]
    if period_index == 1:
        period_mult = 10000
    elif period_index == 2:
        period_mult = 7500
    elif period_index == 3:
        period_mult = 5000
    else:
        period_mult = 2500
    raw = (
        Decimal(base_gross_fee_cents)
        * Decimal(media_mult)
        / Decimal(BPS_DENOMINATOR)
        * Decimal(period_mult)
        / Decimal(BPS_DENOMINATOR)
    )
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
