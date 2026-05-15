"""Calendar helpers — YTD year extraction and the annual-reset bookkeeping for
Donor.ytd_contribution_total_cents, Donor.ytd_state_deduction_used_cents, and
Beneficiary.k12_ytd_qualified_cents."""

from datetime import datetime


def year_from_iso(iso: str) -> int:
    return int(iso[:4])


def ensure_donor_year(donor, current_year: int):
    """Reset donor YTD totals if a new calendar year has begun."""
    if donor.get("_ytd_year") != current_year:
        donor["_ytd_year"] = current_year
        donor["ytd_contribution_total_cents"] = 0
    if donor.get("_ytd_deduction_year") != current_year:
        donor["_ytd_deduction_year"] = current_year
        donor["ytd_state_deduction_used_cents"] = 0


def ensure_beneficiary_year(beneficiary, current_year: int):
    if beneficiary.get("_k12_ytd_year") != current_year:
        beneficiary["_k12_ytd_year"] = current_year
        beneficiary["k12_ytd_qualified_cents"] = 0
