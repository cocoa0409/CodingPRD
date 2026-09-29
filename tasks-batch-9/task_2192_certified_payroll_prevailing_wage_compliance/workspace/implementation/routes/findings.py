"""Findings and the adjudication loop."""

from flask import Blueprint, request

import calc
import db
import derive
import serializers as s
import validators as v
from auth import (
    ALL_ROLES,
    CERTIFY_CAPABILITIES,
    acting_staff,
    authenticate,
    require_capability,
    require_ownership,
)
from errors import ApiError
from response import created, ok, paginated, pagination

bp = Blueprint("findings", __name__)

FINDING_TYPES = (
    "UNDERPAYMENT",
    "MISCLASSIFICATION",
    "APPRENTICE_RATIO",
    "FRINGE_CREDIT",
    "MISSING_PAYROLL",
)
SEVERITIES = ("MINOR", "MAJOR", "CRITICAL")
CITABLE_WORKFLOW_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "ACCEPTED", "RETURNED")


def get_finding(finding_id):
    return v.lookup(db.findings, finding_id, "ERR_FINDING_NOT_FOUND")


def _invalid_finding_state(message):
    raise ApiError("ERR_INVALID_FINDING_STATE", message)


def build_finding(project, submission, worker, finding_type, severity, required_cents,
                  raised_by_user_id, source_interview_id=None):
    """Creates an OPEN finding and runs the full cascade of PRD 3.10."""
    row = db.base_row()
    row.update(
        {
            "project_id": project["id"],
            "payroll_submission_id": submission["id"],
            "worker_id": worker["id"] if worker else None,
            "source_interview_id": source_interview_id,
            "finding_type": finding_type,
            "severity": severity,
            "restitution_required_cents": required_cents,
            "restitution_outstanding_cents": required_cents,
            "status": "OPEN",
            "response_round": 0,
            "raised_by_user_id": raised_by_user_id,
            "response_due_at": calc.response_due_at(db.now()),
            "response_narrative": None,
            "_auto_accepted": False,
        }
    )
    db.findings[row["id"]] = row

    derive.compliance_on_finding_open(submission)

    assignment = derive.submission_assignment(submission)
    contractor = db.contractors.get(assignment["contractor_id"]) if assignment else None
    if contractor is not None:
        contractor["last_finding_at"] = db.now()
        db.touch(contractor)

    derive.recompute_assignment(assignment)
    if severity == "CRITICAL" and assignment is not None:
        derive.suspend_assignment(assignment)
    derive.recompute_contractor(contractor)
    derive.recompute_project(project)
    return row


@bp.route("/findings", methods=["POST"])
def raise_finding():
    actor = authenticate(["LaborStandardsAuditor"])
    payload = v.body()
    project = v.resolve_fk(payload, "project_id", db.projects, "ERR_PROJECT_NOT_FOUND")
    worker = v.resolve_fk(payload, "worker_id", db.workers, "ERR_WORKER_NOT_FOUND")
    submission = v.resolve_fk(
        payload, "payroll_submission_id", db.payroll_submissions, "ERR_SUBMISSION_NOT_FOUND"
    )
    if project is None:
        v.bad("project_id is required.")
    if submission is None:
        v.bad("payroll_submission_id is required.")

    finding_type = v.req_enum(payload, "finding_type", FINDING_TYPES)
    severity = v.req_enum(payload, "severity", SEVERITIES)
    required_cents = v.req_int(payload, "restitution_required_cents", minimum=0)

    if submission["workflow_status"] not in CITABLE_WORKFLOW_STATUSES:
        raise ApiError(
            "ERR_INVALID_SUBMISSION_STATE",
            "Only a filed submission may be cited by a finding.",
        )

    if finding_type == "UNDERPAYMENT":
        if required_cents > submission["make_whole_underpayment_cents"]:
            raise ApiError(
                "ERR_RESTITUTION_ABOVE_COMPUTED_UNDERPAYMENT",
                "restitution_required_cents exceeds the submission's make_whole_underpayment_cents.",
            )

    row = build_finding(
        project, submission, worker, finding_type, severity, required_cents, actor.user_id
    )
    return created(s.finding(row))


@bp.route("/findings", methods=["GET"])
def list_findings():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    project_id = request.args.get("project_id")
    submission_id = request.args.get("payroll_submission_id")
    worker_id = request.args.get("worker_id")
    interview_id = request.args.get("source_interview_id")
    status = request.args.get("status")
    severity = request.args.get("severity")
    finding_type = request.args.get("finding_type")

    def keep(row):
        if project_id is not None and row["project_id"] != project_id:
            return False
        if submission_id is not None and row["payroll_submission_id"] != submission_id:
            return False
        if worker_id is not None and row["worker_id"] != worker_id:
            return False
        if interview_id is not None and row["source_interview_id"] != interview_id:
            return False
        if status is not None and row["status"] != status:
            return False
        if severity is not None and row["severity"] != severity:
            return False
        if finding_type is not None and row["finding_type"] != finding_type:
            return False
        return True

    return paginated(db.ordered(db.findings, keep), s.finding, limit, offset)


@bp.route("/findings/<finding_id>", methods=["GET"])
def read_finding(finding_id):
    authenticate(ALL_ROLES)
    return ok(s.finding(get_finding(finding_id)))


@bp.route("/findings/<finding_id>/response", methods=["POST"])
def file_response(finding_id):
    actor = authenticate(["CertifyingOfficial"])
    finding = get_finding(finding_id)
    payload = v.body()
    assignment = derive.finding_assignment(finding)
    staff = acting_staff(actor)
    require_ownership(staff, assignment["contractor_id"] if assignment else None)
    require_capability(staff, CERTIFY_CAPABILITIES)

    response_narrative = v.req_nonempty_string(payload, "response_narrative")
    expected_version = v.req_int(payload, "expected_finding_version", minimum=0)

    if finding["status"] not in ("OPEN", "RESPONSE_REJECTED"):
        _invalid_finding_state("Only an OPEN or RESPONSE_REJECTED finding accepts a response.")

    if expected_version != finding["version"]:
        raise ApiError(
            "ERR_STALE_FINDING_VERSION",
            "expected_finding_version does not match the finding's current version.",
        )

    finding["response_narrative"] = response_narrative
    finding["response_round"] = finding["response_round"] + 1
    finding["status"] = "RESPONSE_SUBMITTED"
    db.touch(finding)
    return ok(s.finding(finding))


@bp.route("/findings/<finding_id>/review-response", methods=["POST"])
def review_response(finding_id):
    actor = authenticate(["AgencyComplianceOfficer"])
    finding = get_finding(finding_id)
    payload = v.body()
    decision = v.req_enum(payload, "decision", ("ACCEPT", "REJECT"))
    v.opt_string(payload, "reviewer_note")

    if finding["status"] != "RESPONSE_SUBMITTED":
        _invalid_finding_state("Only a RESPONSE_SUBMITTED finding may be adjudicated.")

    submission = derive.finding_submission(finding)
    if submission is not None and submission["accepted_by_user_id"] == actor.user_id:
        raise ApiError(
            "ERR_SOD_REVIEW_CONFLICT",
            "The officer who accepted the cited payroll may not adjudicate this finding.",
        )

    if decision == "REJECT":
        finding["status"] = "RESPONSE_REJECTED"
        db.touch(finding)
        return ok(s.finding(finding))

    if finding["restitution_outstanding_cents"] != 0:
        _invalid_finding_state(
            "A finding with an outstanding restitution balance may not be accepted."
        )

    finding["status"] = "RESPONSE_ACCEPTED"
    finding["_auto_accepted"] = False
    db.touch(finding)
    derive.cascade_finding_change(finding)
    derive.compliance_maybe_remedied(submission)
    return ok(s.finding(finding))


@bp.route("/findings/<finding_id>/withdraw", methods=["POST"])
def withdraw_finding(finding_id):
    authenticate(["LaborStandardsAuditor"])
    finding = get_finding(finding_id)
    payload = v.body()
    v.req_nonempty_string(payload, "withdrawal_reason")

    if finding["status"] not in ("OPEN", "RESPONSE_REJECTED"):
        _invalid_finding_state("Only an OPEN or RESPONSE_REJECTED finding may be withdrawn.")
    for payment in db.ordered(db.restitution_payments):
        if payment["finding_id"] == finding["id"] and payment["status"] == "DISBURSED":
            _invalid_finding_state(
                "A finding carrying a DISBURSED restitution payment may not be withdrawn."
            )

    finding["status"] = "WITHDRAWN"
    finding["restitution_outstanding_cents"] = 0
    db.touch(finding)
    for payment in db.ordered(db.restitution_payments):
        if payment["finding_id"] == finding["id"] and payment["status"] == "PENDING":
            payment["status"] = "VOIDED"
            db.touch(payment)

    derive.cascade_finding_change(finding)
    derive.compliance_maybe_remedied(derive.finding_submission(finding))
    return ok(s.finding(finding))
