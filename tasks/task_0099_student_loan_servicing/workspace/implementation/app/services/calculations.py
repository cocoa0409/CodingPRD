"""Calculation rules per SCAFFOLD §1.3 and PRD §3."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from ..money import D, round_half_up_to_int
from ..poverty import poverty_line_cents


IDR_MULTIPLIER: dict[str, Decimal] = {
    "IBR": Decimal("1.50"),
    "PAYE": Decimal("1.50"),
    "SAVE": Decimal("2.25"),
}

IDR_FRACTION: dict[str, Decimal] = {
    "IBR": Decimal("0.15"),
    "PAYE": Decimal("0.10"),
    "SAVE": Decimal("0.05"),
}


# ---------------------------------------------------------------------------
# §3.7 Monthly payment calc
# ---------------------------------------------------------------------------
def compute_monthly_payment(
    plan: dict[str, Any],
    borrower: dict[str, Any],
    loans_in_pool: list[dict[str, Any]],
) -> int:
    """Compute the plan's monthly_payment_cents.

    Pool is the sum over loans whose status is in {REPAYMENT, GRACE} of
    (principal_balance_cents + accrued_interest_cents). Pool excludes loans in
    any other status (DEFAULT, DEFERMENT, FORBEARANCE, PAID_OFF, DISCHARGED).
    """
    eligible = [l for l in loans_in_pool if l["status"] in ("REPAYMENT", "GRACE")]
    pool_cents = sum(
        int(l["principal_balance_cents"]) + int(l["accrued_interest_cents"])
        for l in eligible
    )
    if not eligible:
        return 0

    # weighted average rate in bps
    weighted_num = sum(
        int(l["interest_rate_bps"])
        * (int(l["principal_balance_cents"]) + int(l["accrued_interest_cents"]))
        for l in eligible
    )
    weighted_rate_bps = (
        D(weighted_num) / D(max(pool_cents, 1))
    )

    plan_type = plan["plan_type"]
    if plan_type == "STANDARD_10":
        n = 120
        # monthly rate = bps / 10000 / 12
        r = weighted_rate_bps / D(10000) / D(12)
        pool_d = D(pool_cents)
        if r == 0:
            payment = pool_d / D(n)
        else:
            one_plus_r_n = (D(1) + r) ** n
            payment = pool_d * r * one_plus_r_n / (one_plus_r_n - D(1))
        return round_half_up_to_int(payment)

    # IDR
    if plan_type not in IDR_MULTIPLIER:
        # Unknown plan type — defensive zero.
        return 0
    poverty = D(
        poverty_line_cents(borrower.get("state_code"), int(borrower.get("family_size", 1)))
    )
    multiplier = IDR_MULTIPLIER[plan_type]
    fraction = IDR_FRACTION[plan_type]
    agi = D(int(borrower.get("adjusted_gross_income_cents", 0)))
    discretionary = agi - multiplier * poverty
    if discretionary < 0:
        discretionary = D(0)
    annual = discretionary * fraction
    monthly_cents = round_half_up_to_int(annual / D(12))
    # Floor: IBR/PAYE -> 500 if zero and pool positive; SAVE -> no floor
    if plan_type in ("IBR", "PAYE") and monthly_cents == 0 and pool_cents > 0:
        monthly_cents = 500
    return monthly_cents


# ---------------------------------------------------------------------------
# §3.3 Interest accrual (per loan, per /_clock/advance call)
# ---------------------------------------------------------------------------
SUBSIDIZED_NON_ACCRUAL_STATUSES = {"GRACE", "DEFERMENT"}
ACCRUING_STATUSES = {
    "GRACE",
    "REPAYMENT",
    "DELINQUENT",
    "DEFERMENT",
    "FORBEARANCE",
    "REHABILITATION",
}


def accrue_interest_for_loan(loan: dict[str, Any], elapsed_days: int) -> int:
    """Compute and apply interest to the loan. Returns the cents added.

    Subsidy filter: DIRECT_SUBSIDIZED in GRACE or DEFERMENT accrues 0.
    Rounding: half-up to integer cents, once per loan per call.
    """
    if elapsed_days <= 0:
        return 0
    status = loan["status"]
    if status not in ACCRUING_STATUSES:
        return 0
    if (
        loan["loan_type"] == "DIRECT_SUBSIDIZED"
        and status in SUBSIDIZED_NON_ACCRUAL_STATUSES
    ):
        return 0
    rate_bps = D(int(loan["interest_rate_bps"]))
    principal = D(int(loan["principal_balance_cents"]))
    daily_rate = rate_bps / D(10000) / D(365)
    accrued = principal * daily_rate * D(elapsed_days)
    cents = round_half_up_to_int(accrued)
    if cents > 0:
        loan["accrued_interest_cents"] = int(loan["accrued_interest_cents"]) + cents
    return cents


# ---------------------------------------------------------------------------
# §3.10 Risk score
# ---------------------------------------------------------------------------
def compute_risk_score(
    borrower: dict[str, Any],
    loans: list[dict[str, Any]],
    cumulative_forbearance_days: int,
    days_since_agi_cert: int,
) -> int:
    max_dpd = max((int(l.get("days_past_due", 0)) for l in loans), default=0)
    delinquency = min(100, max_dpd)
    forbearance_burden = min(
        100, int(round_half_up_to_int(D(cumulative_forbearance_days) / D(1095) * D(100)))
    )
    days_overdue = max(0, days_since_agi_cert - 365)
    recert_sub = min(100, int(round_half_up_to_int(D(days_overdue) / D(365) * D(100))))
    composite = D("0.5") * D(delinquency) + D("0.3") * D(forbearance_burden) + D("0.2") * D(recert_sub)
    if composite < 0:
        composite = D(0)
    if composite > 100:
        composite = D(100)
    return round_half_up_to_int(composite)
