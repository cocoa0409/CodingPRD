"""Medicare eligibility window calculation."""
from datetime import datetime

from utils import add_months, add_years, first_of_month, last_of_month


def compute_eligibility(beneficiary: dict) -> dict:
    """Compute medicare_eligibility_date, iep_start_date, iep_end_date for a beneficiary row.

    Returns the same three fields with a `medicare_eligibility_date`, `iep_start_date`,
    `iep_end_date` keyed in.
    """
    dob: datetime = beneficiary["_dob_dt"]
    has_esrd: bool = beneficiary.get("has_esrd", False)
    has_disability: bool = beneficiary.get("has_disability", False)
    ssdi_start = beneficiary.get("_ssdi_dt")

    if has_esrd:
        elig = first_of_month(dob)
    elif has_disability and ssdi_start is not None:
        elig = first_of_month(add_months(ssdi_start, 24))
    else:
        elig = first_of_month(add_years(dob, 65))

    iep_start = first_of_month(add_months(elig, -3))
    iep_end = last_of_month(add_months(elig, 3))

    return {
        "medicare_eligibility_date": elig,
        "iep_start_date": iep_start,
        "iep_end_date": iep_end,
    }
