"""Hour capture, verification, and census reporting."""

from decimal import Decimal

from flask import Blueprint

import calc
import services
from calc import parse_iso_date
from db import base_record, db, find, maybe, ordered, touch
from errors import ApiError
from middleware import auth, facility_scope
from response import apply_filters, created, listing, ok
from validation import (
    allocation_lines,
    body,
    check_enum,
    fk,
    has,
    need_int,
    need_int_min,
    need_str,
    parse_date,
    parse_time,
    resolve_allocation_fks,
)

bp = Blueprint("hours", __name__)

ENTRY_READ_ROLES = (
    "PlatformAdmin",
    "StaffingCoordinator",
    "FacilityAdministrator",
    "StateAuditor",
    "CmsPublisher",
)
ENTRY_LIST_ROLES = ENTRY_READ_ROLES + ("VendorRepresentative",)


# --------------------------------------------------------------------------
# hour entries
# --------------------------------------------------------------------------

@bp.post("/hour-entries")
def create_hour_entry():
    actor = auth("StaffingCoordinator")
    b = body()

    raw_submission = b.get("submission_id")
    pre = db.submissions.get(raw_submission) if isinstance(raw_submission, str) else None
    facility_scope(actor, pre["facility_id"] if pre else None)

    submission = fk(b, "submission_id", db.submissions, "ERR_SUBMISSION_NOT_FOUND")
    worker = fk(b, "worker_id", db.workers, "ERR_WORKER_NOT_FOUND")
    category = fk(b, "job_category_id", db.job_categories, "ERR_JOB_CATEGORY_NOT_FOUND")
    resolve_allocation_fks(b.get("allocations"), db.job_categories)
    payroll = fk(b, "payroll_record_id", db.payroll_records, "ERR_PAYROLL_RECORD_NOT_FOUND")

    if submission is None:
        raise ApiError("ERR_INVALID_REQUEST", message="Body field 'submission_id' is required.")
    if worker is None:
        raise ApiError("ERR_INVALID_REQUEST", message="Body field 'worker_id' is required.")
    if category is None:
        raise ApiError("ERR_INVALID_REQUEST", message="Body field 'job_category_id' is required.")
    need_str(b, "work_date")
    need_str(b, "shift_start")
    need_str(b, "shift_end")
    lines = allocation_lines(b.get("allocations"))
    expected = need_int(b, "expected_submission_version")

    work_day = parse_date(b["work_date"], "work_date")
    start_minutes = parse_time(b["shift_start"], "shift_start")
    end_minutes = parse_time(b["shift_end"], "shift_end")
    work_date = b["work_date"]

    period = services.period_of(submission)
    services.guard_period_open(period)
    services.guard_submission_status(submission, services.DATA_WRITABLE_SUBMISSION)
    if expected != submission["version"]:
        raise ApiError("ERR_STALE_SUBMISSION_VERSION")

    if work_day < parse_iso_date(period["start_date"]) or work_day > parse_iso_date(period["end_date"]):
        raise ApiError("ERR_WORK_DATE_OUTSIDE_PERIOD")
    if work_day < parse_iso_date(worker["hire_date"]):
        raise ApiError("ERR_WORK_DATE_BEFORE_HIRE")
    if end_minutes <= start_minutes:
        raise ApiError("ERR_SHIFT_WINDOW_INVALID")

    interval = (start_minutes, end_minutes)
    for other in services.worker_active_intervals(worker["id"], work_date):
        if services.overlaps(interval, other):
            raise ApiError("ERR_SHIFT_OVERLAP")

    services.guard_correction_window(submission)

    if worker["facility_id"] != submission["facility_id"]:
        raise ApiError("ERR_WORKER_FACILITY_MISMATCH")

    if payroll is not None:
        covers = (
            parse_iso_date(payroll["pay_period_start"])
            <= work_day
            <= parse_iso_date(payroll["pay_period_end"])
        )
        if payroll["worker_id"] != worker["id"] or not covers:
            raise ApiError("ERR_PAYROLL_SUPPORT_MISMATCH")

    if not lines or calc.allocation_percent_total(lines) != calc.ALLOCATION_PERCENT_TOTAL:
        raise ApiError("ERR_ALLOCATION_SUM_INVALID")

    raw_hours = calc.raw_hours_from_minutes(calc.shift_minutes(start_minutes, end_minutes))
    if raw_hours > calc.MAX_SHIFT_HOURS:
        raise ApiError("ERR_SHIFT_LENGTH_EXCEEDED")
    day_total = services.worker_active_raw_hours(worker["id"], work_date) + raw_hours
    if day_total > calc.MAX_REPORTED_HOURS_PER_WORKER_DAY:
        raise ApiError("ERR_DAILY_HOURS_EXCEEDED")

    entry = services.build_hour_entry(
        submission,
        worker,
        category["id"],
        work_date,
        b["shift_start"],
        b["shift_end"],
        start_minutes,
        end_minutes,
        raw_hours,
        lines,
        b["allocations"],
        payroll_record_id=payroll["id"] if payroll else None,
    )
    services.apply_data_change(submission)
    entry["submission_version"] = submission["version"]
    return created(entry)


@bp.get("/hour-entries/<ident>")
def get_hour_entry(ident):
    auth(*ENTRY_READ_ROLES)
    return ok(find(db.hour_entries, ident, "ERR_HOUR_ENTRY_NOT_FOUND"))


@bp.get("/hour-entries")
def list_hour_entries():
    auth(*ENTRY_LIST_ROLES)
    rows = apply_filters(
        ordered(db.hour_entries.values()),
        (
            "submission_id",
            "facility_id",
            "reporting_period_id",
            "worker_id",
            "job_category_id",
            "vendor_submission_id",
            "payroll_record_id",
            "work_date",
            "entry_status",
            "verification_status",
            "source",
        ),
    )
    return listing(rows)


@bp.put("/hour-entries/<ident>/allocations")
def replace_allocations(ident):
    actor = auth("StaffingCoordinator")
    target = maybe(db.hour_entries, ident)
    facility_scope(actor, target["facility_id"] if target else None)
    entry = find(db.hour_entries, ident, "ERR_HOUR_ENTRY_NOT_FOUND")

    b = body()
    resolve_allocation_fks(b.get("allocations"), db.job_categories)
    lines = allocation_lines(b.get("allocations"))
    expected = need_int(b, "expected_submission_version")

    submission = db.submissions[entry["submission_id"]]
    services.guard_period_open(services.period_of(submission))
    services.guard_submission_status(submission, services.DATA_WRITABLE_SUBMISSION)
    if entry["entry_status"] != "ACTIVE":
        raise ApiError("ERR_HOUR_ENTRY_VOIDED")
    if expected != submission["version"]:
        raise ApiError("ERR_STALE_SUBMISSION_VERSION")
    services.guard_correction_window(submission)
    if not lines or calc.allocation_percent_total(lines) != calc.ALLOCATION_PERCENT_TOTAL:
        raise ApiError("ERR_ALLOCATION_SUM_INVALID")

    figures = calc.classify_allocations(entry["raw_hours"], lines, db.job_categories)
    entry["allocations"] = b["allocations"]
    entry["direct_care_hours"] = figures["direct_care_hours"]
    entry["excluded_hours"] = figures["excluded_hours"]
    entry["rn_hours"] = figures["rn_hours"]
    entry["lpn_hours"] = figures["lpn_hours"]
    entry["na_hours"] = figures["na_hours"]
    entry["allocation_revision"] += 1
    touch(entry)

    services.apply_data_change(submission)
    entry["submission_version"] = submission["version"]
    return ok(entry)


@bp.post("/hour-entries/<ident>/void")
def void_hour_entry(ident):
    actor = auth("StaffingCoordinator")
    target = maybe(db.hour_entries, ident)
    facility_scope(actor, target["facility_id"] if target else None)
    entry = find(db.hour_entries, ident, "ERR_HOUR_ENTRY_NOT_FOUND")

    submission = db.submissions[entry["submission_id"]]
    services.guard_period_open(services.period_of(submission))
    services.guard_submission_status(submission, services.DATA_WRITABLE_SUBMISSION)
    if entry["entry_status"] != "ACTIVE":
        raise ApiError("ERR_HOUR_ENTRY_VOIDED")
    services.guard_correction_window(submission)

    entry["entry_status"] = "VOID"
    touch(entry)
    services.apply_data_change(submission)
    return ok(entry)


@bp.post("/hour-entries/<ident>/verify")
def verify_hour_entry(ident):
    actor = auth("StateAuditor")
    entry = find(db.hour_entries, ident, "ERR_HOUR_ENTRY_NOT_FOUND")

    b = body()
    outcome = need_str(b, "outcome")
    check_enum(outcome, ("SUPPORTED", "UNSUPPORTED"), "outcome")

    if entry["entry_status"] != "ACTIVE":
        raise ApiError("ERR_HOUR_ENTRY_VOIDED")
    if entry["verification_status"] not in ("UNVERIFIED", "UNSUPPORTED"):
        raise ApiError("ERR_SUBMISSION_STATE_INVALID")
    if outcome == "SUPPORTED" and entry["payroll_record_id"] is None:
        raise ApiError("ERR_SUPPORT_DOCUMENT_MISSING")

    submission = db.submissions[entry["submission_id"]]
    entry["verification_status"] = outcome
    entry["verified_by_user_id"] = actor.user_id
    touch(entry)

    if outcome == "SUPPORTED":
        for finding in services.open_findings(submission["id"], "UNSUPPORTED_HOURS", entry["id"]):
            services.resolve_finding(finding)
        for finding in services.open_findings(submission["id"], "MISSING_PAYROLL_SUPPORT"):
            if finding["subject_ref"] != entry["work_date"]:
                continue
            subject = db.hour_entries.get(finding.get("_subject_key"))
            still_holds = (
                subject is not None
                and subject["entry_status"] == "ACTIVE"
                and subject["payroll_record_id"] is None
            )
            if not still_holds:
                services.resolve_finding(finding)
    else:
        services.create_finding(
            submission,
            "UNSUPPORTED_HOURS",
            entry["work_date"],
            "Payroll evidence does not support the hours reported on %s." % entry["work_date"],
            subject_key=entry["id"],
        )

    if services.refresh_finding_counts(submission):
        touch(submission)
    return ok(entry)


# --------------------------------------------------------------------------
# census days
# --------------------------------------------------------------------------

@bp.post("/census-days")
def create_census_day():
    actor = auth("StaffingCoordinator")
    b = body()

    raw_submission = b.get("submission_id")
    pre = db.submissions.get(raw_submission) if isinstance(raw_submission, str) else None
    facility_scope(actor, pre["facility_id"] if pre else None)

    submission = fk(b, "submission_id", db.submissions, "ERR_SUBMISSION_NOT_FOUND")
    if submission is None:
        raise ApiError("ERR_INVALID_REQUEST", message="Body field 'submission_id' is required.")
    need_str(b, "census_date")
    resident_count = need_int_min(b, "resident_count", 0)
    mds_count = None
    if has(b, "mds_resident_count"):
        mds_count = need_int(b, "mds_resident_count")

    census_day = parse_date(b["census_date"], "census_date")
    census_date = b["census_date"]

    period = services.period_of(submission)
    services.guard_period_open(period)
    services.guard_submission_status(submission, services.DATA_WRITABLE_SUBMISSION)
    services.guard_correction_window(submission)

    for existing in services.submission_census(submission["id"]):
        if existing["census_date"] == census_date:
            raise ApiError("ERR_DUPLICATE_CENSUS_DAY")
    if census_day < parse_iso_date(period["start_date"]) or census_day > parse_iso_date(
        period["end_date"]
    ):
        raise ApiError("ERR_CENSUS_DATE_OUTSIDE_PERIOD")

    day = base_record()
    day.update(
        {
            "submission_id": submission["id"],
            "facility_id": submission["facility_id"],
            "reporting_period_id": submission["reporting_period_id"],
            "census_date": census_date,
            "resident_count": resident_count,
            "mds_resident_count": mds_count,
            "variance_pct": None,
            "status": "REPORTED",
            "is_weekend": calc.is_weekend_date(census_day),
            "submission_version": submission["version"],
        }
    )
    db.census_days[day["id"]] = day

    services.apply_data_change(submission)
    day["submission_version"] = submission["version"]
    return created(day)


@bp.get("/census-days/<ident>")
def get_census_day(ident):
    auth(*ENTRY_READ_ROLES)
    return ok(find(db.census_days, ident, "ERR_CENSUS_DAY_NOT_FOUND"))


@bp.get("/census-days")
def list_census_days():
    auth(*ENTRY_READ_ROLES)
    rows = apply_filters(
        ordered(db.census_days.values()),
        ("submission_id", "facility_id", "reporting_period_id", "status", "census_date"),
    )
    return listing(rows)


@bp.patch("/census-days/<ident>")
def patch_census_day(ident):
    actor = auth("StaffingCoordinator")
    target = maybe(db.census_days, ident)
    facility_scope(actor, target["facility_id"] if target else None)
    day = find(db.census_days, ident, "ERR_CENSUS_DAY_NOT_FOUND")

    b = body()
    resident_count = None
    if has(b, "resident_count"):
        resident_count = need_int_min(b, "resident_count", 0)
    mds_count = None
    if has(b, "mds_resident_count"):
        mds_count = need_int(b, "mds_resident_count")

    submission = db.submissions[day["submission_id"]]
    services.guard_period_open(services.period_of(submission))
    services.guard_submission_status(submission, services.DATA_WRITABLE_SUBMISSION)
    services.guard_correction_window(submission)

    if resident_count is not None:
        day["resident_count"] = resident_count
    if mds_count is not None:
        day["mds_resident_count"] = mds_count
    if day["mds_resident_count"] is not None:
        day["variance_pct"] = calc.census_variance(
            day["resident_count"], day["mds_resident_count"]
        )
    touch(day)

    services.apply_data_change(submission)
    day["submission_version"] = submission["version"]
    return ok(day)


@bp.post("/census-days/<ident>/reconcile")
def reconcile_census_day(ident):
    actor = auth("StaffingCoordinator")
    target = maybe(db.census_days, ident)
    facility_scope(actor, target["facility_id"] if target else None)
    day = find(db.census_days, ident, "ERR_CENSUS_DAY_NOT_FOUND")

    submission = db.submissions[day["submission_id"]]
    services.guard_period_open(services.period_of(submission))
    services.guard_submission_status(submission, services.DATA_WRITABLE_SUBMISSION)
    if day["mds_resident_count"] is None:
        raise ApiError("ERR_MDS_COUNT_MISSING")
    services.guard_correction_window(submission)

    variance = calc.census_variance(day["resident_count"], day["mds_resident_count"])
    day["variance_pct"] = variance
    if variance <= calc.CENSUS_VARIANCE_TOLERANCE:
        day["status"] = "RECONCILED"
        for finding in services.open_findings(
            submission["id"], "CENSUS_VARIANCE", day["census_date"]
        ):
            services.resolve_finding(finding)
    else:
        day["status"] = "DISPUTED"
        if not services.open_findings(submission["id"], "CENSUS_VARIANCE", day["census_date"]):
            services.create_finding(
                submission,
                "CENSUS_VARIANCE",
                day["census_date"],
                "Reported census of %d differs from the MDS count of %d by %s."
                % (day["resident_count"], day["mds_resident_count"], variance),
            )
    touch(day)

    services.refresh_finding_counts(submission)
    services.apply_data_change(submission)
    return ok(day)
