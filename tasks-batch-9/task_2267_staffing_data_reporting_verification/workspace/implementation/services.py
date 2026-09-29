"""Domain services: rollups, the finding set, postures, and the cascades.

Everything in here operates on the in-memory store; nothing is persisted
outside the process.
"""

from decimal import Decimal

import calc
from calc import dec, r2, r4, ratio4, sum2
from db import (
    base_record,
    clock_now,
    clock_str,
    db,
    fmt_dt,
    ordered,
    plus_days,
    touch,
)
from errors import ApiError

COUNTED_CENSUS = ("REPORTED", "RECONCILED", "DISPUTED")
DATA_WRITABLE_SUBMISSION = ("DRAFT", "VALIDATED")
OPEN_CASE_STATUSES = ("OPEN", "INFO_REQUESTED", "UNDER_REVIEW")


# --------------------------------------------------------------------------
# collection queries (default ordering is created_at ascending)
# --------------------------------------------------------------------------

def submission_entries(submission_id):
    return ordered([e for e in db.hour_entries.values() if e["submission_id"] == submission_id])


def active_entries(submission_id):
    return [e for e in submission_entries(submission_id) if e["entry_status"] == "ACTIVE"]


def submission_census(submission_id):
    return ordered([c for c in db.census_days.values() if c["submission_id"] == submission_id])


def counted_census(submission_id):
    return [c for c in submission_census(submission_id) if c["status"] in COUNTED_CENSUS]


def submission_findings(submission_id):
    return ordered([f for f in db.findings.values() if f["submission_id"] == submission_id])


def facility_submissions(facility_id):
    return ordered([s for s in db.submissions.values() if s["facility_id"] == facility_id])


def period_of(submission):
    return db.reporting_periods[submission["reporting_period_id"]]


def facility_of(submission):
    return db.facilities[submission["facility_id"]]


# --------------------------------------------------------------------------
# temporal and lifecycle guards
# --------------------------------------------------------------------------

def guard_period_open(period):
    """Step 17."""
    if period is not None and period["status"] != "OPEN":
        raise ApiError("ERR_PERIOD_CLOSED")


def guard_submission_status(submission, allowed):
    """Step 18."""
    if submission["status"] not in allowed:
        raise ApiError("ERR_SUBMISSION_STATE_INVALID")


def guard_correction_window(submission):
    """Step 42 — a write at exactly correction_deadline is still accepted."""
    if clock_now() > submission["_correction_deadline_dt"]:
        raise ApiError("ERR_CORRECTION_WINDOW_CLOSED")


# --------------------------------------------------------------------------
# calculations.submission_hour_census_rollup
# --------------------------------------------------------------------------

def refresh_worker_hours(worker_ids):
    for worker_id in worker_ids:
        worker = db.workers.get(worker_id)
        if worker is None:
            continue
        total = sum2(
            e["raw_hours"]
            for e in db.hour_entries.values()
            if e["worker_id"] == worker_id and e["entry_status"] == "ACTIVE"
        )
        if worker["reported_hours_total"] != total:
            worker["reported_hours_total"] = total
            touch(worker)


def rollup_submission(submission, refresh_workers=True):
    entries = active_entries(submission["id"])
    days = counted_census(submission["id"])

    submission["total_raw_hours"] = sum2(e["raw_hours"] for e in entries)
    submission["total_direct_care_hours"] = sum2(e["direct_care_hours"] for e in entries)
    submission["total_excluded_hours"] = sum2(e["excluded_hours"] for e in entries)
    submission["total_rn_direct_care_hours"] = sum2(e["rn_hours"] for e in entries)
    submission["weekend_direct_care_hours"] = sum2(
        e["direct_care_hours"] for e in entries if e["is_weekend"]
    )
    submission["vendor_sourced_hours"] = sum2(
        e["direct_care_hours"] for e in entries if e["source"] == "VENDOR_SUBMISSION"
    )
    submission["total_resident_days"] = sum(c["resident_count"] for c in days)
    weekend_resident_days = sum(c["resident_count"] for c in days if c["is_weekend"])
    submission["weekend_hprd_reported"] = ratio4(
        submission["weekend_direct_care_hours"], weekend_resident_days
    )

    if refresh_workers:
        touched = set()
        for entry in submission_entries(submission["id"]):
            touched.add(entry["worker_id"])
        refresh_worker_hours(touched)


def apply_data_change(submission):
    """PRD 2.9: rollup, revert a VALIDATED submission to DRAFT, bump once."""
    rollup_submission(submission)
    if submission["status"] == "VALIDATED":
        submission["status"] = "DRAFT"
    touch(submission)


# --------------------------------------------------------------------------
# calculations.hprd_reconciliation
# --------------------------------------------------------------------------

def hprd(submission, variant):
    entries = active_entries(submission["id"])
    if variant == "AUDIT_ADJUSTED":
        entries = [e for e in entries if e["verification_status"] == "SUPPORTED"]
    days = counted_census(submission["id"])

    def counted(day):
        if variant == "AUDIT_ADJUSTED" and day["mds_resident_count"] is not None:
            return day["mds_resident_count"]
        return day["resident_count"]

    total_direct = sum2(e["direct_care_hours"] for e in entries)
    total_rn = sum2(e["rn_hours"] for e in entries)
    weekend_direct = sum2(e["direct_care_hours"] for e in entries if e["is_weekend"])

    resident_days = sum(counted(d) for d in days)
    weekend_resident_days = sum(counted(d) for d in days if d["is_weekend"])

    total_nurse_hprd = ratio4(total_direct, resident_days)
    rn_hprd = ratio4(total_rn, resident_days)
    weekend_total_nurse_hprd = ratio4(weekend_direct, weekend_resident_days)

    return {
        "submission_id": submission["id"],
        "variant": variant,
        "total_direct_care_hours": total_direct,
        "total_rn_hours": total_rn,
        "weekend_direct_care_hours": weekend_direct,
        "resident_days": resident_days,
        "weekend_resident_days": weekend_resident_days,
        "total_nurse_hprd": total_nurse_hprd,
        "rn_hprd": rn_hprd,
        "weekend_total_nurse_hprd": weekend_total_nurse_hprd,
        "implausible": total_nurse_hprd is not None and total_nurse_hprd > calc.MAX_PLAUSIBLE_HPRD,
    }


def zero_rn_day_count(submission):
    days = counted_census(submission["id"])
    entries = active_entries(submission["id"])
    dates_with_rn = set(
        e["work_date"] for e in entries if dec(e["rn_hours"]) > Decimal("0.00")
    )
    return sum(1 for d in days if d["census_date"] not in dates_with_rn)


# --------------------------------------------------------------------------
# calculations.audit_support_score
# --------------------------------------------------------------------------

def audit_support_score(submission, variant):
    entries = active_entries(submission["id"])
    if variant == "SAMPLED":
        considered = sorted(entries, key=lambda e: (e["work_date"], e["_seq"]))[: calc.SAMPLE_SIZE]
    else:
        considered = entries

    considered_hours = sum2(e["direct_care_hours"] for e in considered)
    supported_hours = sum2(
        e["direct_care_hours"] for e in considered if e["verification_status"] == "SUPPORTED"
    )
    if considered_hours == Decimal("0.00"):
        support_ratio = Decimal("1.0000")
    else:
        support_ratio = r4(dec(supported_hours) / dec(considered_hours))

    vendor_entries = [e for e in considered if e["source"] == "VENDOR_SUBMISSION"]
    if not vendor_entries:
        vendor_ratio = Decimal("1.0000")
    else:
        attested = 0
        for entry in vendor_entries:
            batch = db.vendor_submissions.get(entry.get("vendor_submission_id"))
            if batch is not None and batch["status"] == "ACCEPTED":
                attested += 1
        vendor_ratio = r4(Decimal(attested) / Decimal(len(vendor_entries)))

    days = counted_census(submission["id"])
    if not days:
        census_ratio = Decimal("0.0000")
    else:
        reconciled = sum(1 for d in days if d["status"] == "RECONCILED")
        census_ratio = r4(Decimal(reconciled) / Decimal(len(days)))

    score = r2(
        Decimal(100)
        * (
            calc.W_SUPPORT * support_ratio
            + calc.W_VENDOR * vendor_ratio
            + calc.W_CENSUS * census_ratio
        )
    )
    return {
        "submission_id": submission["id"],
        "variant": variant,
        "considered_entry_count": len(considered),
        "considered_hours": considered_hours,
        "supported_hours": supported_hours,
        "support_ratio": support_ratio,
        "vendor_attestation_ratio": vendor_ratio,
        "census_reconciled_ratio": census_ratio,
        "score": score,
        "at_risk": score < calc.AUDIT_RISK_FLOOR,
    }


# --------------------------------------------------------------------------
# calculations.facility_posture_derivation
# --------------------------------------------------------------------------

def derive_facility(facility):
    """Recomputed from scratch, never incrementally (PRD 2.7)."""
    cases = [c for c in db.cases.values() if c["facility_id"] == facility["id"]]
    substantiated = sum(1 for c in cases if c["status"] == "SUBSTANTIATED")
    open_cases = sum(1 for c in cases if c["status"] in OPEN_CASE_STATUSES)

    if substantiated >= 1:
        posture = "SANCTIONED"
    elif open_cases >= 1:
        posture = "AUDIT_HOLD"
    else:
        posture = "REPORTING_OPEN"

    outstanding = 0
    for submission in db.submissions.values():
        if submission["facility_id"] == facility["id"] and submission["status"] != "VOID":
            outstanding += submission["amendment_surcharge_cents"] - submission["waived_surcharge_cents"]

    published = [
        m
        for m in db.measures.values()
        if m["facility_id"] == facility["id"] and m["publication_status"] == "PUBLISHED"
    ]
    if published:
        published.sort(key=lambda m: (m["published_at"] or "", m["created_at"], m["_seq"]))
        latest_rating = published[-1]["staffing_rating"]
    else:
        latest_rating = None

    changed = (
        facility["posture"] != posture
        or facility["open_case_count"] != open_cases
        or facility["substantiated_case_count"] != substantiated
        or facility["outstanding_surcharge_cents"] != outstanding
        or facility["latest_staffing_rating"] != latest_rating
    )
    facility["posture"] = posture
    facility["open_case_count"] = open_cases
    facility["substantiated_case_count"] = substantiated
    facility["outstanding_surcharge_cents"] = outstanding
    facility["latest_staffing_rating"] = latest_rating
    if changed:
        touch(facility)
    return posture


# --------------------------------------------------------------------------
# validation findings
# --------------------------------------------------------------------------

FINDING_SEVERITY = {
    "CENSUS_INCOMPLETE": "WARNING",
    "CENSUS_VARIANCE": "WARNING",
    "HPRD_IMPLAUSIBLE": "FATAL",
    "MISSING_PAYROLL_SUPPORT": "WARNING",
    "ZERO_DIRECT_CARE_DAY": "WARNING",
    "UNSUPPORTED_HOURS": "WARNING",
    "FACILITY_SANCTIONED": "FATAL",
}


def create_finding(submission, code, subject_ref, detail, subject_key=None):
    finding = base_record()
    finding.update(
        {
            "submission_id": submission["id"],
            "code": code,
            "severity": FINDING_SEVERITY[code],
            "subject_ref": subject_ref,
            "detail": detail,
            "status": "OPEN",
            "waived_by_user_id": None,
            "resolved_at": None,
        }
    )
    finding["_subject_key"] = subject_key if subject_key is not None else subject_ref
    db.findings[finding["id"]] = finding
    return finding


def resolve_finding(finding):
    finding["status"] = "RESOLVED"
    finding["resolved_at"] = clock_str()
    touch(finding)


def open_findings(submission_id, code=None, subject_key=None):
    rows = [f for f in submission_findings(submission_id) if f["status"] == "OPEN"]
    if code is not None:
        rows = [f for f in rows if f["code"] == code]
    if subject_key is not None:
        rows = [f for f in rows if f.get("_subject_key") == subject_key]
    return rows


def refresh_finding_counts(submission):
    rows = submission_findings(submission["id"])
    fatal = sum(1 for f in rows if f["severity"] == "FATAL" and f["status"] == "OPEN")
    warning = sum(1 for f in rows if f["severity"] == "WARNING" and f["status"] == "OPEN")
    changed = (
        submission["open_fatal_finding_count"] != fatal
        or submission["open_warning_finding_count"] != warning
    )
    submission["open_fatal_finding_count"] = fatal
    submission["open_warning_finding_count"] = warning
    return changed


def rebuild_finding_set(submission):
    """The validation pass recomputes findings from scratch on every run."""
    period = period_of(submission)
    start = calc.parse_iso_date(period["start_date"])
    end = calc.parse_iso_date(period["end_date"])

    entries = active_entries(submission["id"])
    days = submission_census(submission["id"])
    census_dates = set(d["census_date"] for d in days)

    dates_with_direct_care = set(
        e["work_date"] for e in entries if dec(e["direct_care_hours"]) > Decimal("0.00")
    )

    desired = []

    for day in calc.date_range(start, end):
        text = day.isoformat()
        if text not in census_dates:
            desired.append(
                (
                    "CENSUS_INCOMPLETE",
                    text,
                    text,
                    "No census day reported for %s." % text,
                )
            )

    for day in days:
        if day["status"] == "DISPUTED":
            desired.append(
                (
                    "CENSUS_VARIANCE",
                    day["census_date"],
                    day["census_date"],
                    "Reported census disputes the MDS count for %s." % day["census_date"],
                )
            )

    reported = submission["hprd_reported"]
    if reported is not None and dec(reported) > calc.MAX_PLAUSIBLE_HPRD:
        desired.append(
            (
                "HPRD_IMPLAUSIBLE",
                "PERIOD",
                "PERIOD",
                "As-submitted hours per resident day of %s exceeds the plausible maximum." % reported,
            )
        )

    for entry in entries:
        if entry["payroll_record_id"] is None:
            desired.append(
                (
                    "MISSING_PAYROLL_SUPPORT",
                    entry["work_date"],
                    entry["id"],
                    "Hour entry on %s has no payroll document support." % entry["work_date"],
                )
            )

    for day in days:
        if day["census_date"] not in dates_with_direct_care:
            desired.append(
                (
                    "ZERO_DIRECT_CARE_DAY",
                    day["census_date"],
                    day["census_date"],
                    "No direct care hours reported for %s." % day["census_date"],
                )
            )

    desired_keys = set((code, key) for code, _ref, key, _detail in desired)

    for finding in open_findings(submission["id"]):
        code = finding["code"]
        key = finding.get("_subject_key")
        if code == "UNSUPPORTED_HOURS":
            entry = db.hour_entries.get(key)
            holds = (
                entry is not None
                and entry["entry_status"] == "ACTIVE"
                and entry["verification_status"] == "UNSUPPORTED"
            )
        elif code == "FACILITY_SANCTIONED":
            # validate requires a non-SANCTIONED posture, so this never holds here
            holds = False
        else:
            holds = (code, key) in desired_keys
        if not holds:
            resolve_finding(finding)

    still_open = set(
        (f["code"], f.get("_subject_key")) for f in open_findings(submission["id"])
    )
    for code, subject_ref, key, detail in desired:
        if (code, key) in still_open:
            continue
        create_finding(submission, code, subject_ref, detail, subject_key=key)
        still_open.add((code, key))

    refresh_finding_counts(submission)


def sanction_cascade(facility):
    """PRD 2.7 / 3.9: every VALIDATED submission reverts and gains a FATAL."""
    for submission in facility_submissions(facility["id"]):
        if submission["status"] != "VALIDATED":
            continue
        submission["status"] = "DRAFT"
        create_finding(
            submission,
            "FACILITY_SANCTIONED",
            facility["ccn"],
            "Facility %s is SANCTIONED by a substantiated discrepancy investigation." % facility["ccn"],
            subject_key="FACILITY",
        )
        refresh_finding_counts(submission)
        touch(submission)


# --------------------------------------------------------------------------
# staffing measures
# --------------------------------------------------------------------------

def apply_measure_figures(measure, submission, variant):
    figures = hprd(submission, variant)
    measure["total_nurse_hprd"] = figures["total_nurse_hprd"]
    measure["rn_hprd"] = figures["rn_hprd"]
    measure["weekend_total_nurse_hprd"] = figures["weekend_total_nurse_hprd"]
    zero_rn = zero_rn_day_count(submission)
    total_points, rn_points, rating = calc.star_rating(
        figures["total_nurse_hprd"],
        figures["rn_hprd"],
        figures["weekend_total_nurse_hprd"],
        zero_rn,
    )
    measure["total_nurse_points"] = total_points
    measure["rn_points"] = rn_points
    measure["days_with_zero_rn_hours"] = zero_rn
    measure["staffing_rating"] = rating


def measures_of_submission(submission_id):
    return ordered([m for m in db.measures.values() if m["submission_id"] == submission_id])


def refresh_vendor_total(vendor):
    total = sum2(
        b["accepted_direct_care_hours"]
        for b in db.vendor_submissions.values()
        if b["vendor_id"] == vendor["id"] and b["status"] == "ACCEPTED"
    )
    if vendor["accepted_hours_total"] != total:
        vendor["accepted_hours_total"] = total
        touch(vendor)


# --------------------------------------------------------------------------
# shared hour-entry construction and per-line guards
# --------------------------------------------------------------------------

def shift_interval(start_minutes, end_minutes):
    return (start_minutes, end_minutes)


def overlaps(a, b):
    """Half-open intervals: touching endpoints do not intersect."""
    return a[0] < b[1] and b[0] < a[1]


def worker_active_intervals(worker_id, work_date, exclude_entry_id=None):
    result = []
    for entry in db.hour_entries.values():
        if entry["worker_id"] != worker_id:
            continue
        if entry["work_date"] != work_date or entry["entry_status"] != "ACTIVE":
            continue
        if exclude_entry_id is not None and entry["id"] == exclude_entry_id:
            continue
        result.append((entry["_start_minutes"], entry["_end_minutes"]))
    return result


def worker_active_raw_hours(worker_id, work_date):
    total = Decimal(0)
    for entry in db.hour_entries.values():
        if entry["worker_id"] != worker_id:
            continue
        if entry["work_date"] != work_date or entry["entry_status"] != "ACTIVE":
            continue
        total += dec(entry["raw_hours"])
    return total


def build_hour_entry(submission, worker, job_category_id, work_date, start_text, end_text,
                     start_minutes, end_minutes, raw_hours, alloc_lines, alloc_payload,
                     payroll_record_id=None, source="PAYROLL", vendor_submission_id=None):
    figures = calc.classify_allocations(raw_hours, alloc_lines, db.job_categories)
    entry = base_record()
    entry.update(
        {
            "submission_id": submission["id"],
            "facility_id": submission["facility_id"],
            "reporting_period_id": submission["reporting_period_id"],
            "worker_id": worker["id"],
            "job_category_id": job_category_id,
            "vendor_submission_id": vendor_submission_id,
            "payroll_record_id": payroll_record_id,
            "work_date": work_date,
            "shift_start": start_text,
            "shift_end": end_text,
            "raw_hours": raw_hours,
            "allocations": alloc_payload,
            "direct_care_hours": figures["direct_care_hours"],
            "excluded_hours": figures["excluded_hours"],
            "rn_hours": figures["rn_hours"],
            "lpn_hours": figures["lpn_hours"],
            "na_hours": figures["na_hours"],
            "is_weekend": calc.is_weekend_date(calc.parse_iso_date(work_date)),
            "source": source,
            "entry_status": "ACTIVE",
            "verification_status": "UNVERIFIED",
            "verified_by_user_id": None,
            "submission_version": submission["version"],
            "allocation_revision": 0,
        }
    )
    entry["_start_minutes"] = start_minutes
    entry["_end_minutes"] = end_minutes
    db.hour_entries[entry["id"]] = entry
    return entry


def set_appeal_deadline(measure):
    published = clock_now()
    measure["published_at"] = fmt_dt(published)
    deadline = plus_days(published, calc.APPEAL_WINDOW_DAYS)
    measure["appeal_deadline"] = fmt_dt(deadline)
    measure["_appeal_deadline_dt"] = deadline
