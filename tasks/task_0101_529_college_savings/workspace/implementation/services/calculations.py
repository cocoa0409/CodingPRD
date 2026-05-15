"""The four scaffold calculations:
  - withdrawal_basis_earnings_split
  - state_tax_benefit_credit
  - k12_cap_application
  - non_qualified_penalty
  - tax_report_aggregation
"""

from decimal import Decimal
from services.money import round_half_up, proportional_share


K12_ANNUAL_CAP_CENTS = 1_000_000     # $10,000 in cents
ANNUAL_GIFT_EXCLUSION_CENTS = 1_800_000  # $18,000 in cents
PENALTY_RATE = Decimal("0.10")


def withdrawal_basis_earnings_split(account_total_balance_cents: int,
                                    account_earnings_balance_cents: int,
                                    requested_amount_cents: int):
    """Compute (basis_portion_cents, earnings_portion_cents).

    earnings_portion = round_half_up(requested * earnings/total)
    basis_portion    = requested - earnings_portion  (residual; never separately rounded)
    """
    if account_total_balance_cents <= 0:
        # Caller is expected to raise ERR_INSUFFICIENT_BALANCE before getting here.
        return requested_amount_cents, 0
    earnings_portion = proportional_share(
        account_earnings_balance_cents,
        account_total_balance_cents,
        requested_amount_cents,
    )
    # Safety: earnings_portion cannot exceed requested.
    if earnings_portion > requested_amount_cents:
        earnings_portion = requested_amount_cents
    basis_portion = requested_amount_cents - earnings_portion
    return basis_portion, earnings_portion


def state_tax_benefit_credit(donor, account, state_rule):
    """Return credit_cents to add to donor.ytd_state_deduction_used_cents.

    The rule used is the donor's state_of_residence rule.
    """
    contribution_amount = None  # caller provides via separate call below
    # parity check first
    if state_rule["parity"] == "IN_STATE_ONLY" and account["state_plan_code"] != donor["state_of_residence"]:
        return 0
    # otherwise: min(amount, max(0, cap - used))
    return None  # caller-driven


def compute_state_credit(donor_amount_cents: int, donor, account, state_rule) -> int:
    if state_rule["parity"] == "IN_STATE_ONLY" and account["state_plan_code"] != donor["state_of_residence"]:
        return 0
    room = max(0, state_rule["deduction_cap_cents"] - donor["ytd_state_deduction_used_cents"])
    return min(donor_amount_cents, room)


def k12_cap_application(withdrawal, receipts_total_cents: int, beneficiary_k12_ytd_cents: int):
    """Return (qualified_amount_cents, non_qualified_amount_cents)."""
    requested = withdrawal["requested_amount_cents"]
    category = withdrawal["expense_category"]
    if category == "NON_QUALIFIED":
        qualified = 0
    elif category == "K_12":
        cap_room = K12_ANNUAL_CAP_CENTS - beneficiary_k12_ytd_cents
        if cap_room < 0:
            cap_room = 0
        qualified = min(requested, receipts_total_cents, cap_room)
    else:
        qualified = min(requested, receipts_total_cents)
    non_qualified = requested - qualified
    return qualified, non_qualified


def non_qualified_penalty(earnings_portion_cents: int,
                          non_qualified_amount_cents: int,
                          requested_amount_cents: int) -> int:
    """Return penalty_cents.

    Two-step nested rounding per scaffold:
      earnings_share = round_half_up(earnings_portion * non_qualified / requested)
      penalty       = round_half_up(earnings_share * 0.10)
    """
    if requested_amount_cents == 0 or non_qualified_amount_cents == 0:
        return 0
    earnings_share = proportional_share(
        non_qualified_amount_cents,
        requested_amount_cents,
        earnings_portion_cents,
    )
    penalty = round_half_up(Decimal(earnings_share) * PENALTY_RATE)
    return penalty
