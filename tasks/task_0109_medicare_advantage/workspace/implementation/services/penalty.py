"""Late Enrollment Penalty (LEP) computation."""
from datetime import datetime

from utils import months_between, round_half_up_cents

NATIONAL_AVG_PART_B_PREMIUM_CENTS = 17490   # $174.90
NATIONAL_AVG_PART_D_BASE_PREMIUM_CENTS = 3678  # $36.78
LEP_PARTB_PER_YEAR = 0.10
LEP_PARTD_PER_MONTH = 0.01


def compute_months_late(beneficiary: dict, effective_date: datetime, part: str) -> int:
    """Months between medicare eligibility and effective_date.

    Part B: months_between(elig, effective_date) - 7 (IEP grace), floored at 0.
    Part D: same algorithmic shape — months_uncovered floored at 0. We do not track
    creditable Part D coverage separately and treat any gap between eligibility and
    activation as uncovered months, minus the 7-month IEP grace, floored at 0.
    """
    elig: datetime = beneficiary["_elig_dt"]
    gap = months_between(elig, effective_date) - 7
    return max(0, gap)


def compute_penalty(part: str, months_late: int, base_premium_cents: int) -> tuple[float, int]:
    """Return (penalty_rate_decimal, monthly_penalty_cents) for a Part B or Part D LEP."""
    if part == "PART_B":
        full_years = months_late // 12
        rate = full_years * LEP_PARTB_PER_YEAR
        monthly_cents = round_half_up_cents(NATIONAL_AVG_PART_B_PREMIUM_CENTS * rate)
        return rate, monthly_cents
    elif part == "PART_D":
        rate = months_late * LEP_PARTD_PER_MONTH
        monthly_cents = round_half_up_cents(NATIONAL_AVG_PART_D_BASE_PREMIUM_CENTS * rate)
        return rate, monthly_cents
    else:
        return 0.0, 0
