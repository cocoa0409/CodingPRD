"""Pure-function calculation rules from SCAFFOLD §1.3 / PRD §3.6 + §3.8.

All money is integer cents. Every rounding step uses round_half_up via
Decimal, per PRD §2.6.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

K12_ANNUAL_CAP_CENTS = 1_000_000
FEDERAL_PENALTY_RATE = Decimal("0.10")

CA_CAP_CENTS = 600_000
CA_RATE = Decimal("0.10")

NY_TIER1_CENTS = 500_000
NY_TIER1_RATE = Decimal("0.05")
NY_TIER2_CENTS = 1_000_000
NY_TIER2_RATE = Decimal("0.02")


def round_half_up(value: Decimal) -> int:
    """Round a Decimal half-up to the nearest integer cent."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# earnings_ratio
# ---------------------------------------------------------------------------

def earnings_ratio_split(amount_cents: int, account_balance_cents: int, total_earnings_cents: int) -> tuple[int, int]:
    """Split a withdrawal into (basis_portion_cents, earnings_portion_cents).

    Edge cases per PRD §3.6:
    - total_earnings_cents <= 0 -> earnings_portion = 0, basis_portion = amount.
    - account_balance_cents == 0 would have been rejected upstream by the
      insufficient-balance precondition, so this fn is never called with that.
    """
    if total_earnings_cents <= 0:
        return amount_cents, 0
    earnings_portion = round_half_up(
        Decimal(amount_cents) * Decimal(total_earnings_cents) / Decimal(account_balance_cents)
    )
    basis_portion = amount_cents - earnings_portion
    return basis_portion, earnings_portion


# ---------------------------------------------------------------------------
# k12_excess_calc
# ---------------------------------------------------------------------------

def k12_excess_cents(expense_class: str, ytd_qualified_k12_cents: int, amount_cents: int) -> int:
    if expense_class != "K_12_TUITION":
        return 0
    projected = ytd_qualified_k12_cents + amount_cents
    excess = projected - K12_ANNUAL_CAP_CENTS
    return excess if excess > 0 else 0


# ---------------------------------------------------------------------------
# excess_withdrawal_penalty
# ---------------------------------------------------------------------------

def excess_withdrawal_penalty_cents(
    expense_class: str,
    amount_cents: int,
    earnings_portion_cents: int,
    k12_excess_cents_val: int,
) -> int:
    """Federal 10% penalty per PRD §3.6 — round inner ratio first, then outer rate."""
    if expense_class == "NON_QUALIFIED":
        penalty_base = earnings_portion_cents
    elif expense_class == "K_12_TUITION" and k12_excess_cents_val > 0:
        penalty_base = round_half_up(
            Decimal(earnings_portion_cents) * Decimal(k12_excess_cents_val) / Decimal(amount_cents)
        )
    else:
        penalty_base = 0
    return round_half_up(Decimal(penalty_base) * FEDERAL_PENALTY_RATE)


# ---------------------------------------------------------------------------
# state_tax_incentive_match
# ---------------------------------------------------------------------------

def state_tax_match_cents(state_code: str, contributions_eligible_cents: int) -> int:
    """Per-state schedule, per-tier rounding."""
    if state_code == "CA":
        eligible = min(contributions_eligible_cents, CA_CAP_CENTS)
        return round_half_up(Decimal(eligible) * CA_RATE)
    if state_code == "NY":
        tier1 = min(contributions_eligible_cents, NY_TIER1_CENTS)
        tier2 = max(
            0,
            min(contributions_eligible_cents, NY_TIER2_CENTS) - NY_TIER1_CENTS,
        )
        return round_half_up(Decimal(tier1) * NY_TIER1_RATE) + round_half_up(
            Decimal(tier2) * NY_TIER2_RATE
        )
    # IL / TX / FL / OH and anything else supported but unscheduled.
    return 0
