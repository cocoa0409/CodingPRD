"""Agency hour batches filed by staffing vendors."""

from decimal import Decimal

from flask import Blueprint

import calc
import services
from calc import parse_iso_date
from db import base_record, clock_str, db, find, maybe, ordered, touch
from errors import ApiError
from middleware import auth, facility_scope, vendor_scope
from response import apply_filters, created, listing, ok
from validation import (
    allocation_lines,
    bad,
    body,
    fk,
    need_list,
    need_str,
    parse_date,
    parse_time,
    resolve_allocation_fks,
)

bp = Blueprint("vendor_submissions", __name__)

READ_ROLES = (
    "PlatformAdmin",
    "StaffingCoordinator",
    "FacilityAdministrator",
    "VendorRepresentative",
    "StateAuditor",
)


def _resolve_line_fks(raw_lines):
    """Step 12 across the batch lines, tolerant of a malformed shape."""
    if not isinstance(raw_lines, list):
        return
    for line in raw_lines:
        if not isinstance(line, dict):
            continue
        worker_id = line.get("worker_id")
        if worker_id is not None and (
            not isinstance(worker_id, str) or worker_id not in db.workers
        ):
            raise ApiError("ERR_WORKER_NOT_FOUND")
        category_id = line.get("job_category_id")
        if category_id is not None and (
            not isinstance(category_id, str) or category_id not in db.job_categories
        ):
            raise ApiError("ERR_JOB_CATEGORY_NOT_FOUND")
        resolve_allocation_fks(line.get("allocations"), db.job_categories)


def _parse_lines(raw_lines):
    """Steps 13 and 16 across the batch lines."""
    parsed = []
    for index, line in enumerate(raw_lines):
        label = "lines[%d]" % index
        if not isinstance(line, dict):
            raise bad(label, "must be an object")
        worker_id = line.get("worker_id")
        category_id = line.get("job_category_id")
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise bad(label + ".worker_id")
        if not isinstance(category_id, str) or not category_id.strip():
            raise bad(label + ".job_category_id")
        if not isinstance(line.get("work_date"), str):
            raise bad(label + ".work_date")
        if not isinstance(line.get("shift_start"), str):
            raise bad(label + ".shift_start")
        if not isinstance(line.get("shift_end"), str):
            raise bad(label + ".shift_end")
        alloc = allocation_lines(line.get("allocations"), label + ".allocations")

        work_date = parse_date(line["work_date"], label + ".work_date")
        start_minutes = parse_time(line["shift_start"], label + ".shift_start")
        end_minutes = parse_time(line["shift_end"], label + ".shift_end")
        parsed.append(
            {
                "worker": db.workers[worker_id],
                "job_category_id": category_id,
                "work_date": line["work_date"],
                "work_day": work_date,
                "shift_start": line["shift_start"],
                "shift_end": line["shift_end"],
                "start_minutes": start_minutes,
                "end_minutes": end_minutes,
                "allocations": alloc,
                "raw_allocations": line["allocations"],
            }
        )
    return parsed


@bp.post("/vendor-submissions")
def create_batch():
    actor = auth("VendorRepresentative", "PlatformAdmin")
    b = body()

    raw_vendor = b.get("vendor_id")
    vendor_scope(actor, raw_vendor if isinstance(raw_vendor, str) else None)

    vendor = fk(b, "vendor_id", db.vendors, "ERR_VENDOR_NOT_FOUND")
    facility = fk(b, "facility_id", db.facilities, "ERR_FACILITY_NOT_FOUND")
    period = fk(b, "reporting_period_id", db.reporting_periods, "ERR_REPORTING_PERIOD_NOT_FOUND")
    _resolve_line_fks(b.get("lines"))

    if vendor is None:
        raise ApiError("ERR_INVALID_REQUEST", message="Body field 'vendor_id' is required.")
    if facility is None:
        raise ApiError("ERR_INVALID_REQUEST", message="Body field 'facility_id' is required.")
    if period is None:
        raise ApiError("ERR_INVALID_REQUEST", message="Body field 'reporting_period_id' is required.")
    raw_lines = need_list(b, "lines")
    attested_by = need_str(b, "attested_by")

    lines = _parse_lines(raw_lines)

    if vendor["status"] != "ACTIVE":
        raise ApiError("ERR_VENDOR_SUSPENDED")

    for line in lines:
        if line["end_minutes"] <= line["start_minutes"]:
            raise ApiError("ERR_SHIFT_WINDOW_INVALID")
    for line in lines:
        worker = line["worker"]
        if worker["worker_type"] != "AGENCY_CONTRACTOR" or worker["vendor_id"] != vendor["id"]:
            raise ApiError("ERR_VENDOR_WORKER_MISMATCH")
    for line in lines:
        if calc.allocation_percent_total(line["allocations"]) != calc.ALLOCATION_PERCENT_TOTAL:
            raise ApiError("ERR_ALLOCATION_SUM_INVALID")
    if not lines:
        raise ApiError("ERR_VENDOR_LINES_EMPTY")

    batch = base_record()
    batch.update(
        {
            "vendor_id": vendor["id"],
            "facility_id": facility["id"],
            "reporting_period_id": period["id"],
            "lines": raw_lines,
            "line_count": len(raw_lines),
            "attested_by": attested_by,
            "status": "DRAFT",
            "accepted_direct_care_hours": Decimal("0.00"),
            "accepted_hour_entry_ids": [],
            "rejection_reason": None,
            "submitted_at": None,
        }
    )
    batch["_target_submission_id"] = None
    db.vendor_submissions[batch["id"]] = batch
    return created(batch)


@bp.get("/vendor-submissions/<ident>")
def get_batch(ident):
    auth(*READ_ROLES)
    return ok(find(db.vendor_submissions, ident, "ERR_VENDOR_SUBMISSION_NOT_FOUND"))


@bp.get("/vendor-submissions")
def list_batches():
    auth(*READ_ROLES)
    rows = apply_filters(
        ordered(db.vendor_submissions.values()),
        ("vendor_id", "facility_id", "reporting_period_id", "status"),
    )
    return listing(rows)


@bp.post("/vendor-submissions/<ident>/submit")
def submit_batch(ident):
    actor = auth("VendorRepresentative")
    target = maybe(db.vendor_submissions, ident)
    vendor_scope(actor, target["vendor_id"] if target else None)
    batch = find(db.vendor_submissions, ident, "ERR_VENDOR_SUBMISSION_NOT_FOUND")

    period = db.reporting_periods[batch["reporting_period_id"]]
    services.guard_period_open(period)
    if batch["status"] not in ("DRAFT", "REJECTED"):
        raise ApiError("ERR_VENDOR_SUBMISSION_STATE_INVALID")
    vendor = db.vendors[batch["vendor_id"]]
    if vendor["status"] != "ACTIVE":
        raise ApiError("ERR_VENDOR_SUSPENDED")

    batch["status"] = "SUBMITTED"
    batch["submitted_at"] = clock_str()
    batch["rejection_reason"] = None
    touch(batch)
    return ok(batch)


@bp.post("/vendor-submissions/<ident>/accept")
def accept_batch(ident):
    actor = auth("StaffingCoordinator")
    target = maybe(db.vendor_submissions, ident)
    facility_scope(actor, target["facility_id"] if target else None)
    batch = find(db.vendor_submissions, ident, "ERR_VENDOR_SUBMISSION_NOT_FOUND")

    b = body()
    submission = fk(b, "submission_id", db.submissions, "ERR_SUBMISSION_NOT_FOUND")
    if submission is None:
        raise ApiError("ERR_INVALID_REQUEST", message="Body field 'submission_id' is required.")

    period = db.reporting_periods[batch["reporting_period_id"]]
    services.guard_period_open(period)
    services.guard_submission_status(submission, services.DATA_WRITABLE_SUBMISSION)
    if (
        submission["facility_id"] != batch["facility_id"]
        or submission["reporting_period_id"] != batch["reporting_period_id"]
    ):
        raise ApiError("ERR_SUBMISSION_STATE_INVALID")
    if batch["status"] != "SUBMITTED":
        raise ApiError("ERR_VENDOR_SUBMISSION_STATE_INVALID")
    vendor = db.vendors[batch["vendor_id"]]
    if vendor["status"] != "ACTIVE":
        raise ApiError("ERR_VENDOR_SUSPENDED")

    lines = _parse_lines(batch["lines"])
    for line in lines:
        line["raw_hours"] = calc.raw_hours_from_minutes(
            calc.shift_minutes(line["start_minutes"], line["end_minutes"])
        )

    start = parse_iso_date(period["start_date"])
    end = parse_iso_date(period["end_date"])

    # per-line guards, in the pinned priority order, each swept across all lines
    for line in lines:
        if line["work_day"] < start or line["work_day"] > end:
            raise ApiError("ERR_WORK_DATE_OUTSIDE_PERIOD")
    for line in lines:
        if line["work_day"] < parse_iso_date(line["worker"]["hire_date"]):
            raise ApiError("ERR_WORK_DATE_BEFORE_HIRE")

    pending = {}
    for line in lines:
        key = (line["worker"]["id"], line["work_date"])
        interval = (line["start_minutes"], line["end_minutes"])
        stored = services.worker_active_intervals(line["worker"]["id"], line["work_date"])
        for other in stored + pending.get(key, []):
            if services.overlaps(interval, other):
                raise ApiError("ERR_SHIFT_OVERLAP")
        pending.setdefault(key, []).append(interval)

    for line in lines:
        if line["worker"]["facility_id"] != submission["facility_id"]:
            raise ApiError("ERR_WORKER_FACILITY_MISMATCH")
    for line in lines:
        worker = line["worker"]
        if worker["worker_type"] != "AGENCY_CONTRACTOR" or worker["vendor_id"] != vendor["id"]:
            raise ApiError("ERR_VENDOR_WORKER_MISMATCH")
    for line in lines:
        if line["raw_hours"] > calc.MAX_SHIFT_HOURS:
            raise ApiError("ERR_SHIFT_LENGTH_EXCEEDED")

    running = {}
    for line in lines:
        key = (line["worker"]["id"], line["work_date"])
        if key not in running:
            running[key] = services.worker_active_raw_hours(line["worker"]["id"], line["work_date"])
        running[key] = running[key] + line["raw_hours"]
        if running[key] > calc.MAX_REPORTED_HOURS_PER_WORKER_DAY:
            raise ApiError("ERR_DAILY_HOURS_EXCEEDED")

    entries = []
    for line in lines:
        entry = services.build_hour_entry(
            submission,
            line["worker"],
            line["job_category_id"],
            line["work_date"],
            line["shift_start"],
            line["shift_end"],
            line["start_minutes"],
            line["end_minutes"],
            line["raw_hours"],
            line["allocations"],
            line["raw_allocations"],
            payroll_record_id=None,
            source="VENDOR_SUBMISSION",
            vendor_submission_id=batch["id"],
        )
        entries.append(entry)

    batch["status"] = "ACCEPTED"
    batch["accepted_hour_entry_ids"] = [e["id"] for e in entries]
    batch["accepted_direct_care_hours"] = calc.sum2(e["direct_care_hours"] for e in entries)
    batch["_target_submission_id"] = submission["id"]
    touch(batch)

    services.refresh_vendor_total(vendor)
    # PRD 3.5: "The target submission's rollups and its as-submitted
    # hours-per-resident-day figures are then recomputed".
    services.rollup_submission(submission)
    submission["hprd_reported"] = services.hprd(submission, "AS_SUBMITTED")[
        "total_nurse_hprd"
    ]
    services.apply_data_change(submission)
    for entry in entries:
        entry["submission_version"] = submission["version"]
    return ok(batch)


@bp.post("/vendor-submissions/<ident>/reject")
def reject_batch(ident):
    actor = auth("StaffingCoordinator")
    target = maybe(db.vendor_submissions, ident)
    facility_scope(actor, target["facility_id"] if target else None)
    batch = find(db.vendor_submissions, ident, "ERR_VENDOR_SUBMISSION_NOT_FOUND")

    b = body()
    reason = need_str(b, "rejection_reason")
    if batch["status"] != "SUBMITTED":
        raise ApiError("ERR_VENDOR_SUBMISSION_STATE_INVALID")

    batch["status"] = "REJECTED"
    batch["rejection_reason"] = reason
    touch(batch)
    return ok(batch)


@bp.post("/vendor-submissions/<ident>/revoke")
def revoke_batch(ident):
    actor = auth("VendorRepresentative")
    target = maybe(db.vendor_submissions, ident)
    vendor_scope(actor, target["vendor_id"] if target else None)
    batch = find(db.vendor_submissions, ident, "ERR_VENDOR_SUBMISSION_NOT_FOUND")

    period = db.reporting_periods[batch["reporting_period_id"]]
    services.guard_period_open(period)
    submission = db.submissions.get(batch.get("_target_submission_id"))
    if submission is not None:
        services.guard_submission_status(submission, services.DATA_WRITABLE_SUBMISSION)
    if batch["status"] != "ACCEPTED":
        raise ApiError("ERR_VENDOR_SUBMISSION_STATE_INVALID")

    for entry_id in batch["accepted_hour_entry_ids"]:
        entry = db.hour_entries.get(entry_id)
        if entry is not None and entry["entry_status"] != "VOID":
            entry["entry_status"] = "VOID"
            touch(entry)

    batch["status"] = "REVOKED"
    batch["accepted_direct_care_hours"] = Decimal("0.00")
    touch(batch)

    services.refresh_vendor_total(db.vendors[batch["vendor_id"]])
    if submission is not None:
        services.apply_data_change(submission)
    return ok(batch)
