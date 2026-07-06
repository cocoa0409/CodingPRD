"""Monetary calculations. All amounts are integer cents; use Decimal + ROUND_HALF_UP."""
from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP


def round_half_up(value) -> int:
    """Round to nearest whole cent, half-up. Accepts int/float/Decimal."""
    d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --- helium fill fee -----------------------------------------------------

LATEX_RATE_CENTS = 175
FOIL_RATE_CENTS = 425
LATEX_BULK_TIER = 25
LATEX_BULK_DISCOUNT = Decimal("0.85")  # (1 - 0.15)
FOIL_BULK_TIER = 10
FOIL_BULK_DISCOUNT = Decimal("0.90")  # (1 - 0.10)


def helium_fill_fee(latex_count: int, foil_count: int) -> int:
    # per-line rounding then sum
    latex_rate = LATEX_BULK_DISCOUNT if latex_count >= LATEX_BULK_TIER else Decimal("1")
    latex_line = round_half_up(Decimal(latex_count) * Decimal(LATEX_RATE_CENTS) * latex_rate)
    foil_rate = FOIL_BULK_DISCOUNT if foil_count >= FOIL_BULK_TIER else Decimal("1")
    foil_line = round_half_up(Decimal(foil_count) * Decimal(FOIL_RATE_CENTS) * foil_rate)
    return latex_line + foil_line


def helium_required_cubic_ft(latex_count: int, foil_count: int) -> Decimal:
    return Decimal(latex_count) * Decimal("0.5") + Decimal(foil_count) * Decimal("1.5")


# --- delivery fee --------------------------------------------------------

BASE_FEE_CENTS = 2500
SETUP_FEE_CENTS = 1500
WEEKEND_SURCHARGE_CENTS = 1000


def delivery_fee(window_start_dt, setup_included: bool) -> int:
    is_weekend = window_start_dt.weekday() in (5, 6)
    fee = BASE_FEE_CENTS
    if setup_included:
        fee += SETUP_FEE_CENTS
    if is_weekend:
        fee += WEEKEND_SURCHARGE_CENTS
    return fee


# --- rental deposit ------------------------------------------------------

DEPOSIT_MULT = Decimal("2.0")


def rental_deposit(unit_price_cents: int, qty: int) -> int:
    """Deposit is 2.0 * undiscounted unit price, per unit, times qty."""
    per_unit = round_half_up(Decimal(unit_price_cents) * DEPOSIT_MULT)
    return per_unit * qty


# --- custom print fee ----------------------------------------------------

TIER_1_END_FT = 5
TIER_2_END_FT = 15
RATE_1_CENTS_PER_FT = 800
RATE_2_CENTS_PER_FT = 600
RATE_3_CENTS_PER_FT = 450
REVISION_SURCHARGE_CENTS = 500


def custom_print_fee(banner_length_ft: int, revision_count: int) -> int:
    ft = banner_length_ft
    span_1 = min(ft, TIER_1_END_FT)
    span_2 = max(0, min(ft, TIER_2_END_FT) - TIER_1_END_FT)
    span_3 = max(0, ft - TIER_2_END_FT)
    unrounded = (
        Decimal(span_1) * Decimal(RATE_1_CENTS_PER_FT)
        + Decimal(span_2) * Decimal(RATE_2_CENTS_PER_FT)
        + Decimal(span_3) * Decimal(RATE_3_CENTS_PER_FT)
    )
    unrounded += Decimal(max(0, revision_count - 1)) * Decimal(REVISION_SURCHARGE_CENTS)
    return round_half_up(unrounded)


# --- event deposit -------------------------------------------------------

def event_deposit(base_price_cents: int, deposit_pct) -> int:
    return round_half_up(Decimal(base_price_cents) * Decimal(str(deposit_pct)))
