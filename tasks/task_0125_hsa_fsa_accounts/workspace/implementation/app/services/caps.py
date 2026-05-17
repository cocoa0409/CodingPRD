"""Plan-year cap calculation (SCAFFOLD §1.3 plan_year_cap)."""
from __future__ import annotations

import datetime as _dt

from ..clock import age_in_years

HSA_CAP_SELF_ONLY_CENTS = 412_500
HSA_CAP_FAMILY_CENTS = 830_000
HSA_CATCH_UP_CENTS = 100_000
HEALTH_FSA_CAP_CENTS = 320_000
DCFSA_CAP_FAMILY_CENTS = 500_000
DCFSA_CAP_MARRIED_SEPARATE_CENTS = 250_000

CARRYOVER_CAP_CENTS = 64_000
HSA_PENALTY_RATE_BPS = 2_000  # 20.00 %


def compute_caps(*, account_type: str, coverage_tier: str | None,
                 tax_filing_status: str, birth_date: _dt.datetime,
                 calendar_year: int) -> tuple[int, int]:
    """Return (contribution_cap_cents, catch_up_cap_cents)."""
    if account_type == "HSA":
        if coverage_tier == "SELF_ONLY":
            cap = HSA_CAP_SELF_ONLY_CENTS
        else:  # FAMILY
            cap = HSA_CAP_FAMILY_CENTS
        # Catch-up eligibility on Dec 31 23:59:59Z of calendar_year.
        eligibility = _dt.datetime(calendar_year, 12, 31, 23, 59, 59, tzinfo=_dt.timezone.utc)
        catch_up = HSA_CATCH_UP_CENTS if age_in_years(birth_date, eligibility) >= 55 else 0
        return cap, catch_up
    if account_type == "HEALTH_FSA":
        return HEALTH_FSA_CAP_CENTS, 0
    # DEPENDENT_CARE_FSA
    if tax_filing_status == "MARRIED_SEPARATE":
        return DCFSA_CAP_MARRIED_SEPARATE_CENTS, 0
    return DCFSA_CAP_FAMILY_CENTS, 0
