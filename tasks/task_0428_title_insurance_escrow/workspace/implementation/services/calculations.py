"""Premium, split, reserve, and escrow calculations (PRD §3.6, §3.8, §3.9, §3.7;
scaffold §1.3).

All money is integer cents. round_half_up is the only rounding convention
(PRD §2.6). Each function states the exact rounding point because rounding order
is part of the contract.
"""

from decimal import Decimal

from helpers import round_half_up

# --- owner / lender premium tier constants (scaffold §1.3) ---
RATE1_PER_1000 = Decimal("5.00")   # first $100,000
RATE2_PER_1000 = Decimal("4.00")   # $100,000.01 .. $500,000
RATE3_PER_1000 = Decimal("3.00")   # above $500,000
TIER1_CEIL_DOLLARS = Decimal("100000")
TIER2_CEIL_DOLLARS = Decimal("500000")
REISSUE_FACTOR = Decimal("0.60")
CO_ISSUE_FLAT_CENTS = 2500
LOSS_LOADING_FACTOR = Decimal("1.15")


def _tiered_base_cents(coverage_amount_cents):
    """Return the UN-ROUNDED tiered base in cents (Decimal) for the given coverage.

    Tiers are computed on coverage expressed in dollars (cents / 100):
      first $100,000          @ 5.00 / $1,000
      $100,000.01..$500,000   @ 4.00 / $1,000
      above $500,000          @ 3.00 / $1,000
    Each band contributes (band_dollars / 1000) * band_rate; the sum (dollars) is
    converted to cents by multiplying by 100. No rounding here.
    """
    cov_dollars = Decimal(coverage_amount_cents) / Decimal(100)
    base = Decimal(0)

    tier1 = min(cov_dollars, TIER1_CEIL_DOLLARS)
    base += (tier1 / Decimal(1000)) * RATE1_PER_1000
    if cov_dollars > TIER1_CEIL_DOLLARS:
        tier2 = min(cov_dollars, TIER2_CEIL_DOLLARS) - TIER1_CEIL_DOLLARS
        base += (tier2 / Decimal(1000)) * RATE2_PER_1000
    if cov_dollars > TIER2_CEIL_DOLLARS:
        tier3 = cov_dollars - TIER2_CEIL_DOLLARS
        base += (tier3 / Decimal(1000)) * RATE3_PER_1000

    return base * Decimal(100)  # dollars -> cents, un-rounded


def owner_premium(coverage_amount_cents, is_reissue):
    """OWNER policy premium (scaffold owner_premium calc).

    Standard: round_half_up(tiered base in cents).
    Reissue:  multiply the UN-ROUNDED base by REISSUE_FACTOR (0.60), then round
              ONCE — yields a strictly lower premium for identical coverage.
    """
    base_cents = _tiered_base_cents(coverage_amount_cents)
    if is_reissue:
        base_cents = base_cents * REISSUE_FACTOR
    return round_half_up(base_cents)


def lender_premium(coverage_amount_cents, co_issued_with_owner):
    """LENDER policy premium (scaffold lender_premium calc).

    Standalone: round_half_up(same tiered base as owner, no reissue factor).
    Co-issued:  flat CO_ISSUE_FLAT_CENTS (2500) regardless of the tiered base.
    """
    if co_issued_with_owner:
        return CO_ISSUE_FLAT_CENTS
    base_cents = _tiered_base_cents(coverage_amount_cents)
    return round_half_up(base_cents)


def premium_split(gross_premium_cents, remit_split_pct):
    """Pinned-order split (scaffold premium_split calc / PRD §3.8).

    agency_retained_cents  = round_half_up(gross * remit_split_pct)  # ROUND FIRST
    underwriter_remit_cents = gross - agency_retained_cents          # THEN SUBTRACT

    Guarantees agency_retained + underwriter_remit == gross with zero drift.
    """
    agency_retained = round_half_up(Decimal(gross_premium_cents) * Decimal(str(remit_split_pct)))
    underwriter_remit = gross_premium_cents - agency_retained
    return agency_retained, underwriter_remit


def claim_reserve(estimated_loss_cents, coverage_amount_cents):
    """Provisional reserve (scaffold claim_reserve calc / PRD §3.9).

    loaded = estimated_loss_cents * LOSS_LOADING_FACTOR (1.15)
    reserve = min(round_half_up(loaded), coverage_amount_cents)  # capped at coverage
    """
    loaded = Decimal(estimated_loss_cents) * LOSS_LOADING_FACTOR
    reserve = round_half_up(loaded)
    if reserve > coverage_amount_cents:
        reserve = coverage_amount_cents
    return reserve


def claim_payout(settled_loss_cents, coverage_amount_cents):
    """Final payout (scaffold claim_reserve final variant / PRD §3.9):
    paid_cents = min(settled_loss_cents, coverage_amount_cents). No loading."""
    return min(settled_loss_cents, coverage_amount_cents)


def endorsement_charge(gross_premium_cents, charge_pct):
    """charge_cents = round_half_up(gross_premium_cents * charge_pct) (PRD §3.6)."""
    return round_half_up(Decimal(gross_premium_cents) * Decimal(str(charge_pct)))
