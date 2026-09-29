"""Logical clock, facilities, reporting periods, job categories, workers, vendors."""

import re
from decimal import Decimal

from flask import Blueprint, request

import calc
import services
from calc import date_range, parse_iso_date, r2
from db import base_record, clock_now, db, find, fmt_dt, maybe, ordered, touch
from errors import ApiError
from middleware import AUTHORIZED_ROLE_VALUES, auth, facility_scope
from response import apply_filters, created, listing, ok
from validation import (
    body,
    check_enum,
    fk,
    need_int,
    need_int_min,
    need_num,
    need_str,
    opt_bool,
    parse_date,
    parse_dt,
)

bp = Blueprint("reference", __name__)

ALL_ROLES = (
    "PlatformAdmin",
    "StaffingCoordinator",
    "FacilityAdministrator",
    "VendorRepresentative",
    "StateAuditor",
    "CmsPublisher",
    "AppealsReviewer",
)

STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")

DIRECT_CARE_CLASSES = ("DIRECT_CARE", "DIRECT_CARE_SPLIT", "ADMINISTRATIVE", "NON_DIRECT_CARE")
NURSE_GROUPS = ("RN", "LPN", "NA", "NONE")
WORKER_TYPES = ("EMPLOYEE", "AGENCY_CONTRACTOR", "INDIVIDUAL_CONTRACTOR")
AUDIT_VARIANTS = ("SAMPLED", "FULL")


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    auth("PlatformAdmin")
    b = body()
    need_str(b, "to_iso8601")
    instant = parse_dt(b["to_iso8601"], "to_iso8601")
    db.clock = instant
    return ok({"current_utc": fmt_dt(instant)})


# --------------------------------------------------------------------------
# facilities
# --------------------------------------------------------------------------

@bp.post("/facilities")
def create_facility():
    auth("PlatformAdmin")
    b = body()
    ccn = need_str(b, "ccn")
    name = need_str(b, "name")
    state_code = need_str(b, "state_code")
    bed_count = need_int(b, "certified_bed_count")

    if len(ccn) != 6:
        raise ApiError("ERR_INVALID_REQUEST", message="Body field 'ccn' must be exactly 6 characters.")
    if not STATE_CODE_RE.match(state_code):
        raise ApiError(
            "ERR_INVALID_REQUEST", message="Body field 'state_code' must be exactly two uppercase letters."
        )
    if bed_count < 1:
        raise ApiError("ERR_INVALID_REQUEST", message="Body field 'certified_bed_count' must be >= 1.")

    for existing in db.facilities.values():
        if existing["ccn"] == ccn:
            raise ApiError("ERR_DUPLICATE_CCN")

    facility = base_record()
    facility.update(
        {
            "ccn": ccn,
            "name": name,
            "state_code": state_code,
            "certified_bed_count": bed_count,
            "posture": "REPORTING_OPEN",
            "open_case_count": 0,
            "substantiated_case_count": 0,
            "outstanding_surcharge_cents": 0,
            "latest_staffing_rating": None,
        }
    )
    db.facilities[facility["id"]] = facility
    return created(facility)


@bp.get("/facilities/<ident>")
def get_facility(ident):
    auth(
        "PlatformAdmin",
        "StaffingCoordinator",
        "FacilityAdministrator",
        "StateAuditor",
        "CmsPublisher",
        "AppealsReviewer",
    )
    return ok(find(db.facilities, ident, "ERR_FACILITY_NOT_FOUND"))


@bp.get("/facilities")
def list_facilities():
    auth("PlatformAdmin", "StateAuditor", "CmsPublisher", "AppealsReviewer")
    rows = apply_filters(ordered(db.facilities.values()), ("state_code", "posture"))
    return listing(rows)


@bp.get("/facilities/<ident>/audit-readiness")
def facility_audit_readiness(ident):
    auth("PlatformAdmin", "StaffingCoordinator", "FacilityAdministrator", "StateAuditor")
    find(db.facilities, ident, "ERR_FACILITY_NOT_FOUND")

    raw = request.args.get("submission_id")
    if raw is not None:
        submission = db.submissions.get(raw)
        if submission is None:
            raise ApiError("ERR_SUBMISSION_NOT_FOUND")
    else:
        raise ApiError("ERR_INVALID_REQUEST", message="Query parameter 'submission_id' is required.")

    variant = request.args.get("variant")
    if variant is None or variant == "":
        variant = "SAMPLED"
    check_enum(variant, AUDIT_VARIANTS, "variant")
    return ok(services.audit_support_score(submission, variant))


# --------------------------------------------------------------------------
# reporting periods
# --------------------------------------------------------------------------

@bp.post("/reporting-periods")
def create_period():
    auth("PlatformAdmin")
    b = body()
    period_code = need_str(b, "period_code")
    state_code = need_str(b, "state_code")
    need_str(b, "start_date")
    need_str(b, "end_date")
    need_str(b, "submission_deadline")
    need_str(b, "correction_window_end")

    if not STATE_CODE_RE.match(state_code):
        raise ApiError(
            "ERR_INVALID_REQUEST", message="Body field 'state_code' must be exactly two uppercase letters."
        )

    start = parse_date(b["start_date"], "start_date")
    end = parse_date(b["end_date"], "end_date")
    deadline = parse_dt(b["submission_deadline"], "submission_deadline")
    window_end = parse_dt(b["correction_window_end"], "correction_window_end")

    if end < start:
        raise ApiError("ERR_INVALID_REQUEST", message="'end_date' must be on or after 'start_date'.")

    for existing in db.reporting_periods.values():
        if existing["state_code"] != state_code:
            continue
        other_start = parse_iso_date(existing["start_date"])
        other_end = parse_iso_date(existing["end_date"])
        if start <= other_end and other_start <= end:
            raise ApiError("ERR_PERIOD_OVERLAP")

    for existing in db.reporting_periods.values():
        if existing["state_code"] == state_code and existing["period_code"] == period_code:
            raise ApiError("ERR_DUPLICATE_PERIOD_CODE")
    if window_end <= deadline:
        raise ApiError("ERR_DUPLICATE_PERIOD_CODE")

    period = base_record()
    period.update(
        {
            "period_code": period_code,
            "state_code": state_code,
            "start_date": b["start_date"],
            "end_date": b["end_date"],
            "submission_deadline": fmt_dt(deadline),
            "correction_window_end": fmt_dt(window_end),
            "day_count": (end - start).days + 1,
            "status": "OPEN",
        }
    )
    period["_submission_deadline_dt"] = deadline
    period["_correction_window_end_dt"] = window_end
    db.reporting_periods[period["id"]] = period
    return created(period)


@bp.get("/reporting-periods/<ident>")
def get_period(ident):
    auth(*ALL_ROLES)
    return ok(find(db.reporting_periods, ident, "ERR_REPORTING_PERIOD_NOT_FOUND"))


@bp.get("/reporting-periods")
def list_periods():
    auth(*ALL_ROLES)
    rows = apply_filters(
        ordered(db.reporting_periods.values()), ("state_code", "status", "period_code")
    )
    return listing(rows)


@bp.post("/reporting-periods/<ident>/close")
def close_period(ident):
    auth("PlatformAdmin")
    period = find(db.reporting_periods, ident, "ERR_REPORTING_PERIOD_NOT_FOUND")
    if period["status"] != "OPEN":
        raise ApiError("ERR_PERIOD_CLOSED")

    for submission in ordered(db.submissions.values()):
        if submission["reporting_period_id"] != period["id"]:
            continue
        if submission["status"] == "ACCEPTED":
            submission["status"] = "FINAL"
        elif submission["status"] in ("DRAFT", "VALIDATED", "REJECTED"):
            submission["status"] = "VOID"
        else:
            continue
        touch(submission)

    period["status"] = "CLOSED"
    touch(period)
    return ok(period)


# --------------------------------------------------------------------------
# job categories
# --------------------------------------------------------------------------

@bp.post("/job-categories")
def create_job_category():
    auth("PlatformAdmin")
    b = body()
    code = need_str(b, "code")
    cms_job_code = need_int(b, "cms_job_code")
    direct_care_class = need_str(b, "direct_care_class")
    nurse_group = need_str(b, "nurse_group")
    credit = need_num(b, "direct_care_credit_pct")
    weekend_countable = opt_bool(b, "weekend_countable", True)

    check_enum(direct_care_class, DIRECT_CARE_CLASSES, "direct_care_class")
    check_enum(nurse_group, NURSE_GROUPS, "nurse_group")

    if cms_job_code < 1 or cms_job_code > 40:
        raise ApiError("ERR_INVALID_REQUEST", message="Body field 'cms_job_code' must be between 1 and 40.")
    if credit < Decimal("0.00") or credit > Decimal("1.00"):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            message="Body field 'direct_care_credit_pct' must be between 0.00 and 1.00.",
        )

    for existing in db.job_categories.values():
        if existing["code"] == code:
            raise ApiError("ERR_DUPLICATE_JOB_CATEGORY")
    if direct_care_class in ("ADMINISTRATIVE", "NON_DIRECT_CARE") and credit != Decimal("0.00"):
        raise ApiError("ERR_DUPLICATE_JOB_CATEGORY")

    category = base_record()
    category.update(
        {
            "code": code,
            "cms_job_code": cms_job_code,
            "direct_care_class": direct_care_class,
            "nurse_group": nurse_group,
            "direct_care_credit_pct": r2(credit),
            "weekend_countable": weekend_countable,
        }
    )
    db.job_categories[category["id"]] = category
    return created(category)


@bp.get("/job-categories/<ident>")
def get_job_category(ident):
    auth(*ALL_ROLES)
    return ok(find(db.job_categories, ident, "ERR_JOB_CATEGORY_NOT_FOUND"))


@bp.get("/job-categories")
def list_job_categories():
    auth(*ALL_ROLES)
    rows = apply_filters(
        ordered(db.job_categories.values()), ("direct_care_class", "nurse_group", "code")
    )
    return listing(rows)


# --------------------------------------------------------------------------
# workers
# --------------------------------------------------------------------------

@bp.post("/workers")
def create_worker():
    actor = auth("PlatformAdmin", "FacilityAdministrator")
    b = body()

    raw_facility = b.get("facility_id")
    facility_scope(actor, raw_facility if isinstance(raw_facility, str) else None)

    facility = fk(b, "facility_id", db.facilities, "ERR_FACILITY_NOT_FOUND")
    category = fk(b, "primary_job_category_id", db.job_categories, "ERR_JOB_CATEGORY_NOT_FOUND")
    vendor = fk(b, "vendor_id", db.vendors, "ERR_VENDOR_NOT_FOUND")

    if facility is None:
        raise ApiError("ERR_INVALID_REQUEST", message="Body field 'facility_id' is required.")
    full_name = need_str(b, "full_name")
    worker_type = need_str(b, "worker_type")
    if category is None:
        raise ApiError("ERR_INVALID_REQUEST", message="Body field 'primary_job_category_id' is required.")
    need_str(b, "hire_date")

    roles = b.get("authorized_roles")
    if roles is None:
        roles = []
    if not isinstance(roles, list):
        raise ApiError("ERR_INVALID_REQUEST", message="Body field 'authorized_roles' must be an array.")

    check_enum(worker_type, WORKER_TYPES, "worker_type")
    for element in roles:
        check_enum(element, AUTHORIZED_ROLE_VALUES, "authorized_roles")

    parse_date(b["hire_date"], "hire_date")

    if worker_type == "AGENCY_CONTRACTOR":
        if vendor is None:
            raise ApiError("ERR_VENDOR_LINKAGE_INVALID")
    elif vendor is not None:
        raise ApiError("ERR_VENDOR_LINKAGE_INVALID")

    worker = base_record()
    worker.update(
        {
            "facility_id": facility["id"],
            "full_name": full_name,
            "worker_type": worker_type,
            "primary_job_category_id": category["id"],
            "vendor_id": vendor["id"] if vendor else None,
            "hire_date": b["hire_date"],
            "authorized_roles": list(roles),
            "status": "ACTIVE",
            "reported_hours_total": Decimal("0.00"),
        }
    )
    db.workers[worker["id"]] = worker
    return created(worker)


@bp.get("/workers/<ident>")
def get_worker(ident):
    auth(
        "PlatformAdmin",
        "StaffingCoordinator",
        "FacilityAdministrator",
        "StateAuditor",
        "CmsPublisher",
        "AppealsReviewer",
    )
    return ok(find(db.workers, ident, "ERR_WORKER_NOT_FOUND"))


@bp.get("/workers")
def list_workers():
    auth(*ALL_ROLES)
    rows = apply_filters(
        ordered(db.workers.values()),
        ("facility_id", "primary_job_category_id", "vendor_id", "worker_type", "status"),
    )
    return listing(rows)


@bp.post("/workers/<ident>/terminate")
def terminate_worker(ident):
    actor = auth("PlatformAdmin", "FacilityAdministrator")
    target = maybe(db.workers, ident)
    facility_scope(actor, target["facility_id"] if target else None)
    worker = find(db.workers, ident, "ERR_WORKER_NOT_FOUND")
    worker["status"] = "TERMINATED"
    touch(worker)
    return ok(worker)


# --------------------------------------------------------------------------
# staffing vendors
# --------------------------------------------------------------------------

@bp.post("/vendors")
def create_vendor():
    actor = auth("PlatformAdmin", "FacilityAdministrator")
    b = body()

    raw_facility = b.get("facility_id")
    facility_scope(actor, raw_facility if isinstance(raw_facility, str) else None)

    facility = fk(b, "facility_id", db.facilities, "ERR_FACILITY_NOT_FOUND")
    if facility is None:
        raise ApiError("ERR_INVALID_REQUEST", message="Body field 'facility_id' is required.")
    vendor_name = need_str(b, "vendor_name")
    tax_id = need_str(b, "tax_id")
    contact = need_str(b, "attestation_contact")

    for existing in db.vendors.values():
        if existing["facility_id"] == facility["id"] and existing["tax_id"] == tax_id:
            raise ApiError("ERR_DUPLICATE_VENDOR_TAX_ID")

    vendor = base_record()
    vendor.update(
        {
            "facility_id": facility["id"],
            "vendor_name": vendor_name,
            "tax_id": tax_id,
            "attestation_contact": contact,
            "status": "ACTIVE",
            "accepted_hours_total": Decimal("0.00"),
        }
    )
    db.vendors[vendor["id"]] = vendor
    return created(vendor)


@bp.get("/vendors/<ident>")
def get_vendor(ident):
    auth(*ALL_ROLES)
    return ok(find(db.vendors, ident, "ERR_VENDOR_NOT_FOUND"))


@bp.get("/vendors")
def list_vendors():
    auth(*ALL_ROLES)
    rows = apply_filters(ordered(db.vendors.values()), ("facility_id", "status"))
    return listing(rows)


@bp.post("/vendors/<ident>/suspend")
def suspend_vendor(ident):
    auth("PlatformAdmin", "StateAuditor")
    vendor = find(db.vendors, ident, "ERR_VENDOR_NOT_FOUND")
    vendor["status"] = "SUSPENDED"
    touch(vendor)
    return ok(vendor)


# --------------------------------------------------------------------------
# payroll records
# --------------------------------------------------------------------------

@bp.post("/payroll-records")
def create_payroll_record():
    actor = auth("PlatformAdmin", "StaffingCoordinator")
    b = body()

    raw_facility = b.get("facility_id")
    facility_scope(actor, raw_facility if isinstance(raw_facility, str) else None)

    facility = fk(b, "facility_id", db.facilities, "ERR_FACILITY_NOT_FOUND")
    worker = fk(b, "worker_id", db.workers, "ERR_WORKER_NOT_FOUND")

    if facility is None:
        raise ApiError("ERR_INVALID_REQUEST", message="Body field 'facility_id' is required.")
    if worker is None:
        raise ApiError("ERR_INVALID_REQUEST", message="Body field 'worker_id' is required.")
    need_str(b, "pay_period_start")
    need_str(b, "pay_period_end")
    paid_hours = need_num(b, "paid_hours")
    support_type = need_str(b, "support_type")
    document_ref = need_str(b, "document_ref")

    check_enum(support_type, ("TIMECARD", "PAYROLL_JOURNAL", "INVOICE"), "support_type")

    start = parse_date(b["pay_period_start"], "pay_period_start")
    end = parse_date(b["pay_period_end"], "pay_period_end")
    if end < start:
        raise ApiError(
            "ERR_INVALID_REQUEST", message="'pay_period_end' must be on or after 'pay_period_start'."
        )
    if paid_hours <= Decimal("0.00"):
        raise ApiError("ERR_INVALID_REQUEST", message="Body field 'paid_hours' must be greater than 0.00.")

    # step 41 — aggregate daily paid-hours capacity across intersecting documents
    total = r2(paid_hours)
    days = set(date_range(start, end))
    for existing in db.payroll_records.values():
        if existing["worker_id"] != worker["id"]:
            continue
        other_start = parse_iso_date(existing["pay_period_start"])
        other_end = parse_iso_date(existing["pay_period_end"])
        if start <= other_end and other_start <= end:
            total = r2(total + calc.dec(existing["paid_hours"]))
            days.update(date_range(other_start, other_end))
    if total > calc.MAX_HOURS_PER_DAY * Decimal(len(days)):
        raise ApiError("ERR_PAYROLL_CAPACITY_EXCEEDED")

    for existing in db.payroll_records.values():
        if existing["facility_id"] == facility["id"] and existing["document_ref"] == document_ref:
            raise ApiError("ERR_DUPLICATE_DOCUMENT_REF")

    record = base_record(versioned=False)
    record.update(
        {
            "facility_id": facility["id"],
            "worker_id": worker["id"],
            "pay_period_start": b["pay_period_start"],
            "pay_period_end": b["pay_period_end"],
            "paid_hours": r2(paid_hours),
            "support_type": support_type,
            "document_ref": document_ref,
        }
    )
    db.payroll_records[record["id"]] = record
    return created(record)


@bp.get("/payroll-records/<ident>")
def get_payroll_record(ident):
    auth("PlatformAdmin", "StaffingCoordinator", "FacilityAdministrator", "StateAuditor")
    return ok(find(db.payroll_records, ident, "ERR_PAYROLL_RECORD_NOT_FOUND"))


@bp.get("/payroll-records")
def list_payroll_records():
    auth("PlatformAdmin", "StaffingCoordinator", "FacilityAdministrator", "StateAuditor")
    rows = apply_filters(
        ordered(db.payroll_records.values()), ("facility_id", "worker_id", "support_type")
    )
    return listing(rows)
