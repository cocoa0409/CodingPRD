"""Imaging dose flag and retention horizon (calculations.imaging_retention_until)."""
from services.domain import (ADULT_AGE_YEARS, DOSE_REFERENCE_LEVELS,
                             IMAGING_RETENTION_YEARS, JUSTIFICATION_BY_MODALITY)
from timeutil import add_years, dec, fmt_dt, parse_date, whole_years


def justification_allowed(modality, justification_code):
    return justification_code in JUSTIFICATION_BY_MODALITY.get(modality, [])


def dose_flag_for(modality, dose_mgy_cm2):
    reference = DOSE_REFERENCE_LEVELS[modality]
    return "ABOVE_REFERENCE_LEVEL" if dec(dose_mgy_cm2) > reference else "WITHIN_PROTOCOL"


def retention_until(patient, acquired_at_raw):
    acquired = parse_date(acquired_at_raw)
    dob = parse_date(patient.get("date_of_birth"))
    acquisition_floor = add_years(acquired, IMAGING_RETENTION_YEARS)
    if dob is None:
        return fmt_dt(acquisition_floor)
    age_at_acquisition = whole_years(dob, acquired)
    if age_at_acquisition >= ADULT_AGE_YEARS:
        return fmt_dt(acquisition_floor)
    majority_floor = add_years(add_years(dob, ADULT_AGE_YEARS), IMAGING_RETENTION_YEARS)
    return fmt_dt(max(acquisition_floor, majority_floor))
