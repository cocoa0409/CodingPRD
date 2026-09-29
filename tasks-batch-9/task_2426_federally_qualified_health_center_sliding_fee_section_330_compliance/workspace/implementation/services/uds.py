"""Uniform data system aggregations (PRD 3.9)."""

from datetime import datetime, timezone

import db
from services import charge
from services import health_center as hc_svc
from validation import dec


def measures_of(report_id):
    rows = [m for m in db.db.quality_measure_results.values() if m["uds_report_id"] == report_id]
    return db.in_creation_order(rows)


def _counted_verification(patient_id, reporting_year):
    cutoff = datetime(reporting_year + 1, 1, 1, tzinfo=timezone.utc)
    candidates = [
        v
        for v in db.db.income_verifications.values()
        if v["patient_id"] == patient_id
        and v["status"] in ("VERIFIED", "SUPERSEDED", "EXPIRED")
        and v["effective_date"] < cutoff
    ]
    ranked = sorted(
        candidates,
        key=lambda v: (v["effective_date"], v["created_at"], v["_seq"]),
        reverse=True,
    )
    return ranked[0] if ranked else None


def income_distribution(report):
    hc_id = report["health_center_id"]
    year = report["reporting_year"]

    patient_ids = set()
    for enc in hc_svc.encounters_of_hc(hc_id):
        if enc["pps_claim_status"] == "VOID":
            continue
        if enc["encounter_date"].astimezone(timezone.utc).year != year:
            continue
        patient_ids.add(enc["patient_id"])

    counts = {
        "total_patient_count": len(patient_ids),
        "patients_at_or_below_100_count": 0,
        "patients_101_to_150_count": 0,
        "patients_151_to_200_count": 0,
        "patients_over_200_count": 0,
        "unverified_patient_count": 0,
    }

    for patient_id in patient_ids:
        verification = _counted_verification(patient_id, year)
        if verification is None or verification["uds_fpg_percent"] is None:
            counts["unverified_patient_count"] += 1
            continue
        pct = dec(verification["uds_fpg_percent"])
        # The reporting bands are CLOSED ABOVE.
        if pct <= dec("100.00"):
            counts["patients_at_or_below_100_count"] += 1
        elif pct <= dec("150.00"):
            counts["patients_101_to_150_count"] += 1
        elif pct <= dec("200.00"):
            counts["patients_151_to_200_count"] += 1
        else:
            counts["patients_over_200_count"] += 1
    return counts


def composite_quality_rate(report):
    included_rates = []
    for measure in measures_of(report["id"]):
        if measure["denominator"] == 0:
            measure["rate_pct"] = None
            measure["inclusion_status"] = "EXCLUDED_ZERO_DENOMINATOR"
            measure["meets_benchmark"] = None
        else:
            rate = charge.measure_rate_pct(measure["numerator"], measure["denominator"])
            measure["rate_pct"] = rate
            measure["inclusion_status"] = "INCLUDED"
            measure["meets_benchmark"] = dec(rate) >= dec(measure["benchmark_pct"])
            included_rates.append(rate)
        db.touch(measure)

    return {
        "included_measure_count": len(included_rates),
        "composite_quality_rate_pct": charge.composite_rate_pct(included_rates),
    }
