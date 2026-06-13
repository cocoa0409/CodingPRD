"""Calculation rules (PRD 3.2, 3.5-3.9; scaffold §1.3).

All monetary amounts are integer cents. Decimal is used for fractional-cent
intermediate arithmetic; the final rounding rule is applied per-calc as the
PRD specifies (floor, round-half-up, or exact integer).
"""
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

# --- Constants (scaffold §1.3) ---
CONDITION_HAIRCUT_BPS = {
    "EXCELLENT": 0,
    "GOOD": 500,
    "FAIR": 1500,
    "POOR": 3000,
}

LATE_FEE_BPS = 500
LATE_FEE_FLOOR_CENTS = 1500
LATE_FEE_CAP_CENTS = 5000

REPO_RECOVERY_FEE_CENTS = 25000
SALE_COST_CENTS = 30000

FIRST_DUE_OFFSET_DAYS = 30
DUE_SPACING_DAYS = 30


def _floor_div(numer, denom):
    """Floor of numer/denom using exact integer arithmetic (numer, denom ints)."""
    # Python floor division on ints already floors toward negative infinity;
    # all our values are non-negative, so this is the post-haircut floor.
    return numer // denom


def appraisal_basis_value(raw, condition_grade):
    """basis_value_cents = floor(raw * (10000 - haircut_bps) / 10000)  [PRD 3.2]."""
    haircut_bps = CONDITION_HAIRCUT_BPS[condition_grade]
    return _floor_div(raw * (10000 - haircut_bps), 10000)


def max_principal_from_ltv(basis_value_cents, max_ltv_bps):
    """max_principal_cents = floor(basis_value_cents * max_ltv_bps / 10000)  [PRD 3.2]."""
    return _floor_div(basis_value_cents * max_ltv_bps, 10000)


def effective_apr(contract_apr_bps, max_apr_bps):
    """effective_apr_bps = min(contract_apr_bps, max_apr_bps)  [PRD 3.3]."""
    return min(contract_apr_bps, max_apr_bps)


def _round_half_up(value):
    """Round a Decimal to whole cents, half-up."""
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def amortization_schedule(principal, effective_apr_bps, term_months):
    """Build the per-installment (principal_due, interest_due) list  [PRD 3.5].

    Pinned order: interest rounded per installment (half-up); for every
    installment except the last, principal = round_half_up(pmt) - interest;
    the final installment's principal absorbs the residue.
    """
    P = principal
    n = term_months
    i = (Decimal(effective_apr_bps) / Decimal(10000)) / Decimal(12)

    rows = []
    if i == 0:
        # Zero-interest: level principal split, final absorbs residue.
        pmt = Decimal(P) / Decimal(n)
        pmt_rounded = _round_half_up(pmt)
        balance = P
        for seq in range(1, n + 1):
            interest_due = 0
            if seq < n:
                principal_due = pmt_rounded - interest_due
            else:
                principal_due = balance
            balance -= principal_due
            rows.append({"principal_due_cents": principal_due, "interest_due_cents": interest_due})
        return rows

    # pmt = P * i / (1 - (1 + i) ** (-n)), kept unrounded.
    one_plus_i = Decimal(1) + i
    denom = Decimal(1) - (one_plus_i ** (-n))
    pmt = Decimal(P) * i / denom
    pmt_rounded = _round_half_up(pmt)

    balance = P
    for seq in range(1, n + 1):
        interest_due = _round_half_up(Decimal(balance) * i)
        if seq < n:
            principal_due = pmt_rounded - interest_due
        else:
            principal_due = balance  # final installment absorbs residue
        balance -= principal_due
        rows.append({"principal_due_cents": principal_due, "interest_due_cents": interest_due})
    return rows


def late_fee_for_installment(principal_due_cents):
    """Per-installment late fee  [PRD 3.6].

    floor(principal_due * 500 / 10000), raised to a floor of 1500, capped at 5000.
    """
    pct = _floor_div(principal_due_cents * LATE_FEE_BPS, 10000)
    fee = max(LATE_FEE_FLOOR_CENTS, pct)
    fee = min(fee, LATE_FEE_CAP_CENTS)
    return fee


def payment_allocation(amount, fees_balance, accrued_interest, principal_balance):
    """REGULAR waterfall: fees -> interest -> principal -> overpayment  [PRD 3.6].

    Returns dict with fees_applied, interest_applied, principal_applied, overpayment.
    Exact integer cents.
    """
    remaining = amount
    fees_applied = min(remaining, fees_balance)
    remaining -= fees_applied
    interest_applied = min(remaining, accrued_interest)
    remaining -= interest_applied
    principal_applied = min(remaining, principal_balance)
    remaining -= principal_applied
    overpayment = remaining
    return {
        "fees_applied_cents": fees_applied,
        "interest_applied_cents": interest_applied,
        "principal_applied_cents": principal_applied,
        "overpayment_cents": overpayment,
    }


def redemption_amount(principal_balance, accrued_interest, fees_balance, has_active_repo):
    """Full payoff plus repo recovery when an active repo order exists  [PRD 3.7]."""
    repo_recovery = REPO_RECOVERY_FEE_CENTS if has_active_repo else 0
    return principal_balance + accrued_interest + fees_balance + repo_recovery


def reinstatement_amount(arrears_principal, arrears_interest, fees_balance, is_default):
    """Cure amount: arrears + fees + repo recovery only when in DEFAULT  [PRD 3.7]."""
    repo_recovery = REPO_RECOVERY_FEE_CENTS if is_default else 0
    return arrears_principal + arrears_interest + fees_balance + repo_recovery


def renewal_capitalization(principal_balance, accrued_interest, fees_balance):
    """rolled_fees = interest + fees; new_principal = principal + rolled_fees  [PRD 3.8]."""
    rolled_fees = accrued_interest + fees_balance
    new_principal = principal_balance + rolled_fees
    return rolled_fees, new_principal


def deficiency_balance(principal_balance, accrued_interest, fees_balance, sale_proceeds):
    """Deficiency on sale, floored at 0  [PRD 3.9]."""
    total_owed = principal_balance + accrued_interest + fees_balance + REPO_RECOVERY_FEE_CENTS
    net_proceeds = max(0, sale_proceeds - SALE_COST_CENTS)
    return max(0, total_owed - net_proceeds)
