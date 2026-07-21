"""Monetary and valuation calculations. All money is whole cents, round half up."""

from decimal import Decimal, ROUND_HALF_UP

import db

CONDITION_MULT = {
    "EXCELLENT": Decimal("1.00"),
    "GOOD": Decimal("0.85"),
    "FAIR": Decimal("0.65"),
    "POOR": Decimal("0.40"),
    "SALVAGE": Decimal("0.15"),
}

ODOMETER_TIER_1_MULT = Decimal("1.00")
ODOMETER_TIER_2_MULT = Decimal("0.85")
ODOMETER_TIER_3_MULT = Decimal("0.70")


def round_half_up(value):
    """Round a Decimal to a whole cent, halves going away from zero (upward)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def odometer_mult(miles):
    if miles is None:
        return ODOMETER_TIER_1_MULT
    if miles <= db.ODOMETER_TIER_1_MAX_MILES:
        return ODOMETER_TIER_1_MULT
    if miles <= db.ODOMETER_TIER_2_MAX_MILES:
        return ODOMETER_TIER_2_MULT
    return ODOMETER_TIER_3_MULT


def vehicle_fmv_estimate(base_book_value_cents, grade, miles, salvage_flag):
    """Full-precision product, one rounding, then the salvage cap, then the floor."""
    cond = CONDITION_MULT.get(grade, Decimal("1.00"))
    raw = Decimal(base_book_value_cents) * cond * odometer_mult(miles)
    rounded = round_half_up(raw)
    capped = min(rounded, db.SALVAGE_FMV_CAP_CENTS) if salvage_flag else rounded
    return max(capped, db.MIN_FMV_CENTS)


def program_fee_rate(gross):
    if gross <= db.PROGRAM_FEE_TIER_1_MAX_CENTS:
        return Decimal(db.PROGRAM_FEE_TIER_1_RATE)
    if gross <= db.PROGRAM_FEE_TIER_2_MAX_CENTS:
        return Decimal(db.PROGRAM_FEE_TIER_2_RATE)
    return Decimal(db.PROGRAM_FEE_TIER_3_RATE)


def donation_net_proceeds(gross, billed_tow_cost_cents):
    """The four-step waterfall of PRD section 3.7. Rounds only at steps one and three."""
    rate = program_fee_rate(gross)
    program_fee = round_half_up(Decimal(gross) * rate)
    program_fee = max(program_fee, db.MIN_PROGRAM_FEE_CENTS)
    program_fee = min(program_fee, gross)

    provisional = gross - program_fee

    ceiling = round_half_up(Decimal(db.TOW_ALLOWANCE_PCT) * Decimal(provisional))
    tow_allowance = min(billed_tow_cost_cents, ceiling)

    net = max(0, provisional - tow_allowance - db.ADMIN_FLAT_FEE_CENTS)
    return {
        "gross_proceeds_cents": gross,
        "program_fee_cents": program_fee,
        "tow_allowance_cents": tow_allowance,
        "net_to_charity_cents": net,
    }


def tax_receipt_valuation(donation):
    """Three-way threshold selection; the gross comparison is strictly greater-than."""
    fmv = donation.get("fmv_estimate_cents")
    if donation.get("exception_type", "NONE") != "NONE":
        return {
            "valuation_variant": "FMV_FULL",
            "form_type": "FORM_1098C_BOX_4B",
            "claimed_amount_cents": fmv,
        }
    if donation.get("gross_proceeds_cents", 0) > db.GROSS_PROCEEDS_THRESHOLD_CENTS:
        return {
            "valuation_variant": "GROSS_PROCEEDS",
            "form_type": "FORM_1098C_BOX_4A",
            "claimed_amount_cents": donation["gross_proceeds_cents"],
        }
    safe = fmv if fmv is not None else 0
    return {
        "valuation_variant": "FMV_SAFE_HARBOR",
        "form_type": "ACKNOWLEDGMENT_ONLY",
        "claimed_amount_cents": min(safe, db.FMV_SAFE_HARBOR_CENTS),
    }


def line_fee(net_cents, pct):
    """Per-line rounded fee for one member donation."""
    return round_half_up(Decimal(str(net_cents)) * Decimal(str(pct)))


def batch_rounded_fee(gross_cents, pct):
    """Provisional fee: sum first, round once."""
    return round_half_up(Decimal(str(gross_cents)) * Decimal(str(pct)))
