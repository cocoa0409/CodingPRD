"""Quarterly submissions, the validation pass, state review, and findings."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import services
from db import base_record, clock_now, clock_str, db, find, maybe, ordered, touch
from errors import ApiError
from middleware import auth, facility_scope
from response import apply_filters, created, listing, ok
from validation import body, check_enum, fk, need_str

bp = Blueprint("submissions", __name__)

READ_ROLES = (
    "PlatformAdmin",
    "StaffingCoordinator",
    "FacilityAdministrator",
    "StateAuditor",
    "CmsPublisher",
    "AppealsReviewer",
)

HPRD_VARIANTS = ("AS_SUBMITTED", "AUDIT_ADJUSTED")


@bp.post("/submissions")
def create_submission():
    actor = auth("StaffingCoordinator", "PlatformAdmin")
    b = body()

    raw_facility = b.get("facility_id")
    facility_scope(actor, raw_facility if isinstance(raw_facility, str) else None)

    facility = fk(b, "facility_id", db.facilities, "ERR_FACILITY_NOT_FOUND")
    period = fk(b, "reporting_period_id", db.reporting_periods, "ERR_REPORTING_PERIOD_NOT_FOUND")
    if facility is None:
        raise ApiError("ERR_INVALID_REQUEST", message="Body field 'facility_id' is required.")
    if period is None:
        raise ApiError("ERR_INVALID_REQUEST", message="Body field 'reporting_period_id' is required.")

    services.guard_period_open(period)

    for existing in db.submissions.values():
        if (
            existing["facility_id"] == facility["id"]
            and existing["reporting_period_id"] == period["id"]
            and existing["status"] != "VOID"
        ):
            raise ApiError("ERR_DUPLICATE_SUBMISSION")

    submission = base_record()
    submission.update(
        {
            "facility_id": facility["id"],
            "reporting_period_id": period["id"],
            "status": "DRAFT",
            "total_raw_hours": Decimal("0.00"),
            "total_direct_care_hours": Decimal("0.00"),
            "total_excluded_hours": Decimal("0.00"),
            "total_rn_direct_care_hours": Decimal("0.00"),
            "weekend_direct_care_hours": Decimal("0.00"),
            "vendor_sourced_hours": Decimal("0.00"),
            "total_resident_days": 0,
            "hprd_reported": None,
            "weekend_hprd_reported": None,
            "open_fatal_finding_count": 0,
            "open_warning_finding_count": 0,
            "audit_support_score": None,
            "validated_by_worker_id": None,
            "attested_by_worker_id": None,
            "accepted_by_user_id": None,
            "submitted_at": None,
            "accepted_at": None,
            "correction_deadline": period["correction_window_end"],
            "amendment_index": 0,
            "amendment_surcharge_cents": 0,
            "waived_surcharge_cents": 0,
            "rejection_reason": None,
        }
    )
    submission["_correction_deadline_dt"] = period["_correction_window_end_dt"]
    db.submissions[submission["id"]] = submission
    return created(submission)


@bp.get("/submissions/<ident>")
def get_submission(ident):
    auth(*READ_ROLES)
    return ok(find(db.submissions, ident, "ERR_SUBMISSION_NOT_FOUND"))


@bp.get("/submissions")
def list_submissions():
    auth(*READ_ROLES)
    rows = apply_filters(
        ordered(db.submissions.values()),
        (
            "facility_id",
            "reporting_period_id",
            "validated_by_worker_id",
            "attested_by_worker_id",
            "status",
        ),
    )
    return listing(rows)


@bp.get("/submissions/<ident>/findings")
def list_submission_findings(ident):
    auth(*READ_ROLES)
    submission = find(db.submissions, ident, "ERR_SUBMISSION_NOT_FOUND")
    rows = apply_filters(
        services.submission_findings(submission["id"]), ("code", "severity", "status")
    )
    return listing(rows)


@bp.get("/validation-findings/<ident>")
def get_finding(ident):
    auth(*READ_ROLES)
    return ok(find(db.findings, ident, "ERR_FINDING_NOT_FOUND"))


@bp.get("/submissions/<ident>/hprd")
def submission_hprd(ident):
    auth(*READ_ROLES)
    submission = find(db.submissions, ident, "ERR_SUBMISSION_NOT_FOUND")
    variant = request.args.get("variant")
    if variant is None or variant == "":
        variant = "AS_SUBMITTED"
    check_enum(variant, HPRD_VARIANTS, "variant")
    return ok(services.hprd(submission, variant))


@bp.post("/submissions/<ident>/validate")
def validate_submission(ident):
    actor = auth("StaffingCoordinator")
    target = maybe(db.submissions, ident)
    facility_scope(actor, target["facility_id"] if target else None)
    submission = find(db.submissions, ident, "ERR_SUBMISSION_NOT_FOUND")

    services.guard_period_open(services.period_of(submission))
    services.guard_submission_status(submission, ("DRAFT",))
    if not services.counted_census(submission["id"]):
        raise ApiError("ERR_NO_CENSUS_DATA")
    facility = services.facility_of(submission)
    if facility["posture"] == "SANCTIONED":
        raise ApiError("ERR_FACILITY_SANCTIONED")

    services.rollup_submission(submission)
    figures = services.hprd(submission, "AS_SUBMITTED")
    submission["hprd_reported"] = figures["total_nurse_hprd"]
    services.rebuild_finding_set(submission)
    submission["validated_by_worker_id"] = actor.worker_id
    submission["status"] = "VALIDATED"
    touch(submission)
    return ok(submission)


@bp.post("/submissions/<ident>/submit")
def submit_submission(ident):
    actor = auth("FacilityAdministrator")
    target = maybe(db.submissions, ident)
    facility_scope(actor, target["facility_id"] if target else None)
    if target is not None and target["validated_by_worker_id"] == actor.worker_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    submission = find(db.submissions, ident, "ERR_SUBMISSION_NOT_FOUND")

    services.guard_period_open(services.period_of(submission))
    services.guard_submission_status(submission, ("VALIDATED",))
    facility = services.facility_of(submission)
    if facility["posture"] != "REPORTING_OPEN":
        if facility["posture"] == "SANCTIONED":
            raise ApiError("ERR_FACILITY_UNDER_HOLD")
        raise ApiError("ERR_FACILITY_UNDER_HOLD")
    if submission["open_fatal_finding_count"] != 0:
        raise ApiError("ERR_FATAL_FINDINGS_OPEN")
    services.guard_correction_window(submission)

    submission["attested_by_worker_id"] = actor.worker_id
    submission["submitted_at"] = clock_str()
    submission["status"] = "SUBMITTED"
    touch(submission)
    return ok(submission)


@bp.post("/submissions/<ident>/accept")
def accept_submission(ident):
    actor = auth("StateAuditor")
    target = maybe(db.submissions, ident)
    if target is not None:
        for entry in services.submission_entries(target["id"]):
            if entry["verified_by_user_id"] == actor.user_id:
                raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    submission = find(db.submissions, ident, "ERR_SUBMISSION_NOT_FOUND")

    services.guard_period_open(services.period_of(submission))
    services.guard_submission_status(submission, ("SUBMITTED",))

    score = services.audit_support_score(submission, "SAMPLED")["score"]
    submission["status"] = "ACCEPTED"
    submission["accepted_by_user_id"] = actor.user_id
    submission["accepted_at"] = clock_str()
    submission["audit_support_score"] = score
    touch(submission)

    facility = services.facility_of(submission)
    if score < calc.AUDIT_RISK_FLOOR:
        case = base_record()
        case.update(
            {
                "facility_id": facility["id"],
                "submission_id": submission["id"],
                "staffing_measure_id": None,
                "trigger_reason": "AUDIT_SCORE_BELOW_FLOOR",
                "detail": "Audit readiness score %s fell below the risk floor of 70.00 on acceptance."
                % score,
                "status": "OPEN",
                "auto_opened": True,
                "opened_by_user_id": "SYSTEM",
                "info_request_count": 0,
                "facility_response_count": 0,
                "last_request_note": None,
                "last_response_note": None,
                "substantiated_by_user_id": None,
                "resolution_note": None,
            }
        )
        db.cases[case["id"]] = case
        services.derive_facility(facility)
    return ok(submission)


@bp.post("/submissions/<ident>/reject")
def reject_submission(ident):
    actor = auth("StateAuditor")
    submission = find(db.submissions, ident, "ERR_SUBMISSION_NOT_FOUND")
    b = body()
    reason = need_str(b, "rejection_reason")

    services.guard_period_open(services.period_of(submission))
    services.guard_submission_status(submission, ("SUBMITTED",))

    submission["status"] = "REJECTED"
    submission["rejection_reason"] = reason
    submission["accepted_by_user_id"] = actor.user_id
    touch(submission)
    return ok(submission)


@bp.post("/submissions/<ident>/reopen")
def reopen_submission(ident):
    actor = auth("StaffingCoordinator")
    target = maybe(db.submissions, ident)
    facility_scope(actor, target["facility_id"] if target else None)
    submission = find(db.submissions, ident, "ERR_SUBMISSION_NOT_FOUND")

    period = services.period_of(submission)
    services.guard_period_open(period)
    services.guard_submission_status(submission, ("ACCEPTED", "REJECTED"))
    services.guard_correction_window(submission)

    assessed = calc.amendment_surcharge_cents(
        submission["status"],
        submission["amendment_index"],
        period["_submission_deadline_dt"],
        clock_now(),
    )
    facility = services.facility_of(submission)
    if facility["outstanding_surcharge_cents"] + assessed > calc.SURCHARGE_CAP_CENTS:
        raise ApiError("ERR_SURCHARGE_CAP_EXCEEDED")

    submission["amendment_index"] += 1
    submission["amendment_surcharge_cents"] += assessed
    submission["status"] = "DRAFT"
    submission["validated_by_worker_id"] = None
    submission["attested_by_worker_id"] = None
    touch(submission)
    services.derive_facility(facility)
    return ok(submission)


@bp.post("/submissions/<ident>/findings/<finding_id>/waive")
def waive_finding(ident, finding_id):
    actor = auth("StateAuditor")
    submission = find(db.submissions, ident, "ERR_SUBMISSION_NOT_FOUND")
    finding = db.findings.get(finding_id)
    if finding is None or finding["submission_id"] != submission["id"]:
        raise ApiError("ERR_FINDING_NOT_FOUND")

    b = body()
    note = need_str(b, "waiver_note")

    if submission["status"] in ("FINAL", "VOID"):
        raise ApiError("ERR_SUBMISSION_STATE_INVALID")
    if finding["status"] != "OPEN":
        raise ApiError("ERR_FINDING_NOT_OPEN")

    finding["status"] = "WAIVED"
    finding["waived_by_user_id"] = actor.user_id
    finding["resolved_at"] = clock_str()
    finding["detail"] = "%s %s" % (finding["detail"], note)
    touch(finding)

    services.refresh_finding_counts(submission)
    touch(submission)
    return ok(finding)
