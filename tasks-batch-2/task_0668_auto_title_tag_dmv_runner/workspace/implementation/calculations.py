"""Fee calculations (PRD §3.5, §3.6, §3.7; scaffold §1.3).

All money in integer cents. Two rounded lines only:
  - tax line: ONE round_half_up
  - service_fee line: ONE round_half_up applied to the discounted SUM of service
    components (sum-then-round; per-component rounding is FORBIDDEN).
total is the integer sum of the three whole-cent lines, never rounded again.
"""

from decimal import Decimal, ROUND_HALF_UP

# Constants (scaffold §1.3 / PRD §3.5)
BASE_SERVICE_FEE_CENTS = 4500
EXPEDITE_SURCHARGE_CENTS = 6000
REWORK_SURCHARGE_CENTS = 2500

# Fleet volume discount tiers (PRD §3.6 / scaffold fleet_volume_discount)
TIER1_MIN = 5
TIER1_BPS = 625
TIER2_MIN = 20
TIER2_BPS = 1250
TIER3_MIN = 50
TIER3_BPS = 1875


def _round_half_up(value):
    """Round a Decimal to a whole cent, half-up. Returns int."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fleet_tier_discount_bps_for_count(account_type, n):
    """Fleet volume discount in basis points (PRD §3.6).

    Retail (or any non-FLEET) account never receives a discount. For FLEET,
    at-or-above thresholds select a single flat tier (not marginal).
    """
    if account_type != "FLEET":
        return 0
    if n >= TIER3_MIN:
        return TIER3_BPS
    if n >= TIER2_MIN:
        return TIER2_BPS
    if n >= TIER1_MIN:
        return TIER1_BPS
    return 0


def compute_taxable_base(transaction_type, declared_price_cents,
                         trade_in_allowance_cents, trade_in_credit_allowed):
    """Taxable base (PRD §3.5). Only TITLE & TRANSFER are taxable."""
    if transaction_type in ("TITLE", "TRANSFER"):
        base = declared_price_cents
        if trade_in_credit_allowed:
            base = max(0, declared_price_cents - trade_in_allowance_cents)
        return base
    return 0


def compute_state_fees(transaction_type, schedule, lien_in_play):
    """Sum of applicable flat state fees (PRD §3.5).

    Each transaction type contributes its single matching flat fee; the lien
    recording fee is added on top whenever a lien is in play (LIEN type OR a
    LienPacket exists for the transaction).
    """
    total = 0
    if transaction_type == "TITLE":
        total += schedule["title_fee_cents"]
    elif transaction_type == "TRANSFER":
        total += schedule["transfer_fee_cents"]
    elif transaction_type == "REGISTRATION":
        total += schedule["registration_fee_cents"]
    if transaction_type == "LIEN" or lien_in_play:
        total += schedule["lien_recording_fee_cents"]
    return total


def compute_service_fee(expedite, rejection_round, discount_bps):
    """Service fee with surcharges and a single fleet discount (PRD §3.5).

    Sum the un-discounted components first, apply the single discount to that
    sum, then round half-up ONCE.
    """
    svc = BASE_SERVICE_FEE_CENTS
    if expedite:
        svc += EXPEDITE_SURCHARGE_CENTS
    svc += rejection_round * REWORK_SURCHARGE_CENTS
    discounted = Decimal(svc) * Decimal(10000 - discount_bps) / Decimal(10000)
    return _round_half_up(discounted)


def compute_tax(base, use_tax_rate_bps):
    """Tax line rounded half-up to whole cents (PRD §3.5)."""
    raw = Decimal(base) * Decimal(use_tax_rate_bps) / Decimal(10000)
    return _round_half_up(raw)


def compute_quote_components(transaction, account, schedule, count_for_tier,
                             lien_in_play):
    """Run the fixed five-step order and return component breakdown.

    count_for_tier is the ytd_completed_count to feed the fleet tier:
      - ESTIMATE passes the CURRENT count.
      - FINAL passes the PRE-increment count (excludes this completion).
    """
    base = compute_taxable_base(
        transaction["transaction_type"],
        transaction["declared_price_cents"],
        transaction["trade_in_allowance_cents"],
        schedule["trade_in_credit_allowed"],
    )
    tax_cents = compute_tax(base, schedule["use_tax_rate_bps"])
    state_fees_cents = compute_state_fees(
        transaction["transaction_type"], schedule, lien_in_play
    )
    discount_bps = fleet_tier_discount_bps_for_count(
        account["account_type"], count_for_tier
    )
    service_fee_cents = compute_service_fee(
        transaction["expedite"], transaction["rejection_round"], discount_bps
    )
    total_cents = tax_cents + state_fees_cents + service_fee_cents
    return {
        "tax_cents": tax_cents,
        "state_fees_cents": state_fees_cents,
        "service_fee_cents": service_fee_cents,
        "total_cents": total_cents,
    }
