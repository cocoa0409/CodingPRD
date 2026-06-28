"""Distinct device-day recomputation for OPEN billing periods (PRD §3.5).

distinct_device_days = count of distinct VitalsReading.service_date values
across the patient's devices within the period's month.
"""
from db import db
from services import lookups, periods


def recompute_distinct_device_days(period):
    """Recompute and return the count of distinct service_date values for the
    patient's readings that fall within the period's month."""
    patient_id = period["patient_id"]
    year = period["period_year"]
    month = period["period_month"]
    dates = set()
    for v in lookups.vitals_of(patient_id):
        sd = v["service_date"]  # YYYY-MM-DD
        try:
            y, m, _d = sd.split("-")
            if int(y) == year and int(m) == month:
                dates.add(sd)
        except (ValueError, AttributeError):
            continue
    return len(dates)
