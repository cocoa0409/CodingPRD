"""The quarterly emissions report lifecycle and its compliance certifications
(PRD 3.7).
"""

from flask import Blueprint

from constants import (
    API_PREFIX,
    AVAILABILITY_FLOOR,
    CERTIFICATION_STATUSES,
    MIN_REPORT_YEAR,
    MIN_STATEMENT_LENGTH,
    REPORT_DECISIONS,
    REPORT_STATUSES,
    ROLE_DESIGNATED_REP,
    ROLE_PREPARER,
    ROLE_REGULATORY_REVIEWER,
    SUBMISSION_FORMATS,
)
from db import base_record, db, public, public_list, sort_rows, touch
from errors import fail
from lookup import (
    certifications_of_report,
    facility_of_unit,
    find,
    get,
    reports_of_unit,
    systems_of_unit,
)
from middleware import ANY_ROLE, authenticate
from response import array_response, object_response
from services import calc
from services.allowances import posture_and_dispatch
from services.reports import recompute_report, report_hours
from validation import (
    apply_pagination,
    body_dict,
    check_range,
    enum_field,
    int_field,
    match_filters,
    pagination,
    query_filters,
    str_field,
)
from util import D, rhu

bp = Blueprint("quarterly_reports", __name__)


def _facility_of_report(report):
    return facility_of_unit(db.units.get(report["unit_id"]))


def _refresh_posture(report):
    facility = _facility_of_report(report)
    if facility is not None:
        posture_and_dispatch(facility)


def _signed_certification(report_id):
    rows = [c for c in certifications_of_report(report_id) if c["status"] == "SIGNED"]
    rows = sort_rows(rows)
    return rows[-1] if rows else None


def _debit_unit_ledger(unit, amount):
    unit["certified_so2_lbs_ytd"] = rhu(D(unit["certified_so2_lbs_ytd"]) - D(amount), 1)
    touch(unit)


# ---------------------------------------------------------------------------
# report creation and reads
# ---------------------------------------------------------------------------

@bp.route(API_PREFIX + "/units/<unit_id>/quarterly-reports", methods=["POST"])
def open_report(unit_id):
    authenticate((ROLE_PREPARER,))
    body = body_dict()

    year = int_field(body, "year", required=True)
    quarter = int_field(body, "quarter", required=True)

    unit = get("unit", unit_id)

    for existing in reports_of_unit(unit["id"]):
        if existing["year"] == year and existing["quarter"] == quarter:
            fail(
                "ERR_DUPLICATE_REPORT_PERIOD",
                "A report already exists for this unit and calendar quarter.",
            )

    check_range("year", year, minimum=MIN_REPORT_YEAR)
    check_range("quarter", quarter, minimum=1, maximum=4)

    report = base_record()
    report.update(
        {
            "unit_id": unit["id"],
            "year": year,
            "quarter": quarter,
            "status": "DRAFT",
            "submission_format": None,
            "submitted_by_user_id": None,
            "submitted_utc": None,
            "operating_hour_count": 0,
            "measured_hour_count": 0,
            "substituted_hour_count": 0,
            "monitor_data_availability_pct": 100.0,
            "total_heat_input_mmbtu": 0.0,
            "total_so2_lbs": 0.0,
            "total_so2_tons": 0.0,
            "total_nox_lbs": 0.0,
            "total_co2_tons": 0.0,
            "resubmission_count": 0,
            "rejection_reason": None,
        }
    )
    db.quarterly_reports[report["id"]] = report
    return object_response(public(report), 201)


@bp.route(API_PREFIX + "/quarterly-reports", methods=["GET"])
def list_reports():
    authenticate(ANY_ROLE)
    filters = query_filters(
        {"unit_id": "str", "year": "int", "quarter": "int", "status": REPORT_STATUSES}
    )
    limit, offset = pagination()
    rows = match_filters(list(db.quarterly_reports.values()), filters)
    rows = sort_rows(rows)
    return array_response(
        public_list(apply_pagination(rows, limit, offset)), limit, offset, len(rows)
    )


@bp.route(API_PREFIX + "/quarterly-reports/<report_id>", methods=["GET"])
def read_report(report_id):
    authenticate(ANY_ROLE)
    return object_response(public(get("quarterly_report", report_id)))


# ---------------------------------------------------------------------------
# validate / submit
# ---------------------------------------------------------------------------

@bp.route(API_PREFIX + "/quarterly-reports/<report_id>/validate", methods=["POST"])
def validate_report(report_id):
    authenticate((ROLE_PREPARER,))
    body_dict()

    report = get("quarterly_report", report_id)
    if report["status"] != "DRAFT":
        fail("ERR_INVALID_STATE_TRANSITION", "Only a DRAFT report may be validated.")

    systems = systems_of_unit(report["unit_id"])
    if any(s["qa_status"] == "OUT_OF_CONTROL" for s in systems):
        fail("ERR_MONITOR_OUT_OF_CONTROL", "A monitoring system of this unit is out of control.")
    if any(s["qa_status"] not in ("CERTIFIED", "CONDITIONALLY_VALID") for s in systems):
        fail(
            "ERR_MONITOR_NOT_CERTIFIED",
            "Every monitoring system of this unit must be certified or conditionally valid.",
        )

    for hour in report_hours(report["id"]):
        sample_id = hour.get("fuel_sample_id")
        if not sample_id:
            continue
        sample = db.fuel_samples.get(sample_id)
        if sample is not None and sample["status"] == "INVALIDATED":
            fail(
                "ERR_FUEL_ANALYSIS_INVALIDATED",
                "An hour of this report references an invalidated fuel sample.",
            )

    availability = calc.availability_pct(report["unit_id"], report["year"], report["quarter"])
    if D(availability) < AVAILABILITY_FLOOR:
        fail(
            "ERR_DATA_AVAILABILITY_BELOW_FLOOR",
            "Monitor data availability is below the 80.0 percent floor.",
        )

    recompute_report(report, revert_validated=False, bump=False)
    report["status"] = "VALIDATED"
    touch(report)
    return object_response(public(report))


@bp.route(API_PREFIX + "/quarterly-reports/<report_id>/submit", methods=["POST"])
def submit_report(report_id):
    caller = authenticate((ROLE_PREPARER,))
    body = body_dict()

    submission_format = enum_field(body, "submission_format", SUBMISSION_FORMATS, required=True)

    report = get("quarterly_report", report_id)
    if report["status"] != "VALIDATED":
        fail("ERR_INVALID_STATE_TRANSITION", "Only a VALIDATED report may be submitted.")

    report["submission_format"] = submission_format
    report["submitted_by_user_id"] = caller.user_id
    report["submitted_utc"] = db.now_str()
    report["status"] = "SUBMITTED"
    touch(report)
    _refresh_posture(report)
    return object_response(public(report))


# ---------------------------------------------------------------------------
# certification
# ---------------------------------------------------------------------------

@bp.route(API_PREFIX + "/quarterly-reports/<report_id>/certifications", methods=["POST"])
def sign_certification(report_id):
    caller = authenticate((ROLE_DESIGNATED_REP,))
    body = body_dict()

    report = find("quarterly_report", report_id)
    # Segregation of duties precedes both the shape check and the version guard.
    if report is not None and report.get("submitted_by_user_id") == caller.user_id:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The signer may not be the preparer that submitted this report.",
        )

    expected_version = int_field(body, "expected_quarterly_report_version", required=True)
    statement = str_field(body, "statement_text", required=True, min_len=MIN_STATEMENT_LENGTH)

    report = get("quarterly_report", report_id)

    if expected_version != report["version"]:
        fail(
            "ERR_STALE_REPORT_VERSION",
            "expected_quarterly_report_version does not match the stored version.",
        )
    if report["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE_TRANSITION", "Only a SUBMITTED report may be certified.")

    snapshot = report["total_so2_lbs"]
    certification = base_record()
    certification.update(
        {
            "quarterly_report_id": report["id"],
            "certifier_user_id": caller.user_id,
            "statement_text": statement,
            "status": "SIGNED",
            "signed_utc": db.now_str(),
            "revoked_utc": None,
            "revocation_reason": None,
            "certified_so2_lbs_snapshot": snapshot,
        }
    )
    db.certifications[certification["id"]] = certification

    unit = db.units.get(report["unit_id"])
    if unit is not None:
        unit["certified_so2_lbs_ytd"] = rhu(D(unit["certified_so2_lbs_ytd"]) + D(snapshot), 1)
        touch(unit)

    report["status"] = "CERTIFIED"
    touch(report)
    _refresh_posture(report)
    return object_response(public(certification), 201)


@bp.route(API_PREFIX + "/quarterly-reports/<report_id>/certifications", methods=["GET"])
def list_report_certifications(report_id):
    authenticate(ANY_ROLE)
    filters = query_filters({"status": CERTIFICATION_STATUSES})
    limit, offset = pagination()
    report = get("quarterly_report", report_id)
    rows = match_filters(certifications_of_report(report["id"]), filters)
    rows = sort_rows(rows, descending=True)
    return array_response(
        public_list(apply_pagination(rows, limit, offset)), limit, offset, len(rows)
    )


@bp.route(API_PREFIX + "/certifications", methods=["GET"])
def list_certifications():
    authenticate(ANY_ROLE)
    filters = query_filters(
        {
            "quarterly_report_id": "str",
            "status": CERTIFICATION_STATUSES,
            "certifier_user_id": "str",
        }
    )
    limit, offset = pagination()
    rows = match_filters(list(db.certifications.values()), filters)
    rows = sort_rows(rows)
    return array_response(
        public_list(apply_pagination(rows, limit, offset)), limit, offset, len(rows)
    )


@bp.route(API_PREFIX + "/certifications/<certification_id>", methods=["GET"])
def read_certification(certification_id):
    authenticate(ANY_ROLE)
    return object_response(public(get("certification", certification_id)))


@bp.route(API_PREFIX + "/certifications/<certification_id>/revoke", methods=["POST"])
def revoke_certification(certification_id):
    authenticate((ROLE_DESIGNATED_REP,))
    body = body_dict()
    reason = str_field(body, "revocation_reason")

    certification = get("certification", certification_id)
    if certification["status"] != "SIGNED":
        fail("ERR_INVALID_STATE_TRANSITION", "Only a SIGNED certification may be revoked.")
    if reason is None or not reason.strip():
        fail("ERR_REASON_REQUIRED", "revocation_reason is required.")

    certification["status"] = "REVOKED"
    certification["revoked_utc"] = db.now_str()
    certification["revocation_reason"] = reason
    touch(certification)

    report = db.quarterly_reports.get(certification["quarterly_report_id"])
    if report is not None:
        unit = db.units.get(report["unit_id"])
        if unit is not None:
            _debit_unit_ledger(unit, certification["certified_so2_lbs_snapshot"])
        if report["status"] == "CERTIFIED":
            report["status"] = "SUBMITTED"
        touch(report)
        _refresh_posture(report)

    return object_response(public(certification))


# ---------------------------------------------------------------------------
# disposition / reopen
# ---------------------------------------------------------------------------

@bp.route(API_PREFIX + "/quarterly-reports/<report_id>/disposition", methods=["POST"])
def dispose_report(report_id):
    authenticate((ROLE_REGULATORY_REVIEWER,))
    body = body_dict()

    decision = enum_field(body, "decision", REPORT_DECISIONS, required=True)
    reason = str_field(body, "reason")

    report = get("quarterly_report", report_id)
    if report["status"] != "CERTIFIED":
        fail("ERR_INVALID_STATE_TRANSITION", "Only a CERTIFIED report may be disposed.")

    if decision == "ACCEPT":
        report["status"] = "ACCEPTED"
        touch(report)
    else:
        if reason is None or not reason.strip():
            fail("ERR_REASON_REQUIRED", "reason is required to reject a report.")
        certification = _signed_certification(report["id"])
        if certification is not None:
            certification["status"] = "REVOKED"
            certification["revoked_utc"] = db.now_str()
            touch(certification)
            unit = db.units.get(report["unit_id"])
            if unit is not None:
                _debit_unit_ledger(unit, certification["certified_so2_lbs_snapshot"])
        report["rejection_reason"] = reason
        report["status"] = "REJECTED"
        touch(report)

    _refresh_posture(report)
    return object_response(public(report))


@bp.route(API_PREFIX + "/quarterly-reports/<report_id>/reopen", methods=["POST"])
def reopen_report(report_id):
    authenticate((ROLE_PREPARER,))
    body_dict()

    report = get("quarterly_report", report_id)
    if report["status"] != "REJECTED":
        fail("ERR_INVALID_STATE_TRANSITION", "Only a REJECTED report may be reopened.")

    report["resubmission_count"] = report["resubmission_count"] + 1
    report["submission_format"] = None
    report["submitted_by_user_id"] = None
    report["submitted_utc"] = None
    report["rejection_reason"] = None
    report["status"] = "DRAFT"
    touch(report)
    return object_response(public(report))
