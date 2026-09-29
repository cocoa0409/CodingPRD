"""Weekly certified payroll: assembly, the wage engine, filing and review."""

from flask import Blueprint, request

import calc
import db
import derive
import engine
import serializers as s
import validators as v
from auth import (
    ALL_ROLES,
    CERTIFY_CAPABILITIES,
    PREPARE_CAPABILITIES,
    acting_staff,
    authenticate,
    require_capability,
    require_ownership,
)
from errors import ApiError
from response import created, ok, paginated, pagination

bp = Blueprint("payroll", __name__)


def get_submission(submission_id):
    return v.lookup(db.payroll_submissions, submission_id, "ERR_SUBMISSION_NOT_FOUND")


def _invalid_state(message):
    raise ApiError("ERR_INVALID_SUBMISSION_STATE", message)


def _guard_posture(project):
    if project is not None and project["posture"] == "FROZEN":
        raise ApiError("ERR_PROJECT_FROZEN", "The owning project's posture is FROZEN.")


def _covered_week(week_ending_date):
    return (week_ending_date - db.days(6), week_ending_date)


def _weeks_intersect(a, b):
    """Both intervals CLOSED on both ends."""
    return a[0] <= b[1] and b[0] <= a[1]


@bp.route("/payroll-submissions", methods=["POST"])
def open_submission():
    actor = authenticate(["PayrollPreparer"])
    payload = v.body()
    assignment = v.resolve_fk(
        payload, "contract_assignment_id", db.contract_assignments, "ERR_ASSIGNMENT_NOT_FOUND"
    )
    preparer = v.resolve_fk(
        payload, "prepared_by_staff_id", db.contractor_staff, "ERR_STAFF_NOT_FOUND"
    )
    superseded = v.resolve_fk(
        payload, "superseded_submission_id", db.payroll_submissions, "ERR_SUBMISSION_NOT_FOUND"
    )
    if assignment is None:
        v.bad("contract_assignment_id is required.")
    if preparer is None:
        v.bad("prepared_by_staff_id is required.")

    staff = acting_staff(actor)
    require_ownership(staff, assignment["contractor_id"])
    require_capability(staff, PREPARE_CAPABILITIES)

    week_ending_date = v.req_instant(payload, "week_ending_date")
    expected_version = v.req_int(payload, "expected_contract_assignment_version", minimum=0)
    no_work_performed = v.req_bool(payload, "no_work_performed", default=False)

    if assignment["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_ASSIGNMENT_STATE", "The owning tier must be ACTIVE.")

    project = db.projects.get(assignment["project_id"])
    _guard_posture(project)

    if expected_version != assignment["version"]:
        raise ApiError(
            "ERR_STALE_ASSIGNMENT_VERSION",
            "expected_contract_assignment_version does not match the tier's current version.",
        )

    if week_ending_date.weekday() != 5 or (
        week_ending_date.hour,
        week_ending_date.minute,
        week_ending_date.second,
        week_ending_date.microsecond,
    ) != (0, 0, 0, 0):
        raise ApiError(
            "ERR_WEEK_ENDING_NOT_SATURDAY",
            "week_ending_date must be a Saturday at exactly 00:00:00.000Z.",
        )

    window = _covered_week(week_ending_date)
    for other in derive.submissions_of_assignment(assignment["id"]):
        if other["workflow_status"] not in calc.LIVE_WORKFLOW_STATUSES:
            continue
        if _weeks_intersect(window, _covered_week(other["week_ending_date"])):
            raise ApiError(
                "ERR_PAYROLL_WEEK_OVERLAP",
                "Another live submission already occupies this payroll week on the tier.",
            )

    if superseded is not None:
        if (
            superseded["contract_assignment_id"] != assignment["id"]
            or superseded["week_ending_date"] != week_ending_date
            or superseded["workflow_status"] != "RETURNED"
        ):
            raise ApiError(
                "ERR_INVALID_SUPERSEDE_TARGET",
                "The superseded submission must be a RETURNED filing on the same tier and week.",
            )

    row = db.base_row()
    row.update(
        {
            "contract_assignment_id": assignment["id"],
            "week_ending_date": week_ending_date,
            "prepared_by_staff_id": preparer["id"],
            "certified_by_staff_id": None,
            "superseded_submission_id": superseded["id"] if superseded else None,
            "no_work_performed": no_work_performed,
            "workflow_status": "DRAFT",
            "compliance_status": "UNVERIFIED",
            "statement_signed_at": None,
            "notary_reference_number": None,
            "submitted_at": None,
            "filing_due_at": None,
            "is_late": False,
            "accepted_by_user_id": None,
            "total_hours_reported": 0,
            "straight_time_underpayment_cents": 0,
            "make_whole_underpayment_cents": 0,
            "excess_apprentice_hours": 0,
        }
    )
    db.payroll_submissions[row["id"]] = row
    db.touch(assignment)
    return created(s.submission(row))


@bp.route("/payroll-submissions", methods=["GET"])
def list_submissions():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    assignment_id = request.args.get("contract_assignment_id")
    project_id = request.args.get("project_id")
    workflow_status = request.args.get("workflow_status")
    compliance_status = request.args.get("compliance_status")
    week_ending_date = request.args.get("week_ending_date")
    prepared_by = request.args.get("prepared_by_staff_id")
    certified_by = request.args.get("certified_by_staff_id")
    superseded = request.args.get("superseded_submission_id")
    is_late = request.args.get("is_late")

    week_instant = None
    if week_ending_date is not None:
        week_instant = db.parse_iso(week_ending_date)
        if week_instant is None:
            v.bad("week_ending_date filter is not a parseable timestamp.")

    def keep(row):
        if assignment_id is not None and row["contract_assignment_id"] != assignment_id:
            return False
        if project_id is not None:
            assignment = db.contract_assignments.get(row["contract_assignment_id"])
            if assignment is None or assignment["project_id"] != project_id:
                return False
        if workflow_status is not None and row["workflow_status"] != workflow_status:
            return False
        if compliance_status is not None and row["compliance_status"] != compliance_status:
            return False
        if week_instant is not None and row["week_ending_date"] != week_instant:
            return False
        if prepared_by is not None and row["prepared_by_staff_id"] != prepared_by:
            return False
        if certified_by is not None and row["certified_by_staff_id"] != certified_by:
            return False
        if superseded is not None and row["superseded_submission_id"] != superseded:
            return False
        if is_late is not None and row["is_late"] != (is_late.lower() == "true"):
            return False
        return True

    return paginated(db.ordered(db.payroll_submissions, keep), s.submission, limit, offset)


@bp.route("/payroll-submissions/<submission_id>", methods=["GET"])
def read_submission(submission_id):
    authenticate(ALL_ROLES)
    return ok(s.submission(get_submission(submission_id)))


@bp.route("/payroll-submissions/<submission_id>/lines", methods=["POST"])
def add_line(submission_id):
    actor = authenticate(["PayrollPreparer"])
    submission = get_submission(submission_id)
    payload = v.body()
    worker = v.resolve_fk(payload, "worker_id", db.workers, "ERR_WORKER_NOT_FOUND")
    plan = v.resolve_fk(payload, "fringe_plan_id", db.fringe_plans, "ERR_FRINGE_PLAN_NOT_FOUND")
    if worker is None:
        v.bad("worker_id is required.")

    assignment = derive.submission_assignment(submission)
    staff = acting_staff(actor)
    require_ownership(staff, assignment["contractor_id"])
    require_capability(staff, PREPARE_CAPABILITIES)

    classification_code = v.req_string(payload, "classification_code", min_len=1, upper=True)
    straight_hours = v.req_hours(payload, "straight_hours", minimum=0, maximum=40)
    overtime_hours = v.req_hours(payload, "overtime_hours", minimum=0)
    base_rate_paid_cents = v.req_int(payload, "base_rate_paid_cents", minimum=0)
    overtime_rate_paid_cents = v.opt_int(
        payload, "overtime_rate_paid_cents", default=0, minimum=0
    )
    fringe_cash_paid_cents = v.opt_int(payload, "fringe_cash_paid_cents", default=0, minimum=0)
    reported_as_apprentice = v.req_bool(payload, "reported_as_apprentice", default=False)

    if submission["workflow_status"] != "DRAFT":
        _invalid_state("Lines may only be added to a DRAFT submission.")

    project = derive.submission_project(submission)
    _guard_posture(project)

    candidate = {
        "classification_code": classification_code,
        "reported_as_apprentice": reported_as_apprentice,
    }
    engine.check_referential(project, [(candidate, worker)])

    if plan is not None:
        if plan["contractor_id"] != assignment["contractor_id"]:
            raise ApiError(
                "ERR_FRINGE_PLAN_FOREIGN", "The named fringe plan belongs to another contractor."
            )
        if plan["approval_status"] == "REJECTED":
            raise ApiError(
                "ERR_FRINGE_PLAN_NOT_APPROVED", "A REJECTED fringe plan may not be claimed."
            )

    for existing in derive.lines_of_submission(submission["id"]):
        if existing["worker_id"] == worker["id"]:
            raise ApiError(
                "ERR_DUPLICATE_WORKER_LINE",
                "This submission already carries a line for the worker.",
            )

    if plan is not None and plan["plan_type"] == "CASH_IN_LIEU" and fringe_cash_paid_cents > 0:
        raise ApiError(
            "ERR_FRINGE_DOUBLE_COUNT",
            "A CASH_IN_LIEU plan may not be combined with fringe_cash_paid_cents > 0.",
        )

    row = db.base_row(versioned=False)
    row.update(
        {
            "payroll_submission_id": submission["id"],
            "worker_id": worker["id"],
            "fringe_plan_id": plan["id"] if plan else None,
            "classification_code": classification_code,
            "straight_hours": straight_hours,
            "overtime_hours": overtime_hours,
            "base_rate_paid_cents": base_rate_paid_cents,
            "overtime_rate_paid_cents": overtime_rate_paid_cents,
            "fringe_cash_paid_cents": fringe_cash_paid_cents,
            "reported_as_apprentice": reported_as_apprentice,
            "required_base_cents": 0,
            "required_fringe_cents": 0,
            "creditable_fringe_cents": 0,
            "reclassified_journey_hours": 0,
            "line_underpayment_cents": 0,
        }
    )
    db.payroll_lines[row["id"]] = row
    db.touch(submission)
    return created(s.line(row))


@bp.route("/payroll-lines", methods=["GET"])
def list_lines():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    submission_id = request.args.get("payroll_submission_id")
    worker_id = request.args.get("worker_id")
    plan_id = request.args.get("fringe_plan_id")
    classification_code = request.args.get("classification_code")

    def keep(row):
        if submission_id is not None and row["payroll_submission_id"] != submission_id:
            return False
        if worker_id is not None and row["worker_id"] != worker_id:
            return False
        if plan_id is not None and row["fringe_plan_id"] != plan_id:
            return False
        if classification_code is not None and row["classification_code"] != classification_code:
            return False
        return True

    return paginated(db.ordered(db.payroll_lines, keep), s.line, limit, offset)


@bp.route("/payroll-lines/<line_id>", methods=["GET"])
def read_line(line_id):
    authenticate(ALL_ROLES)
    return ok(s.line(v.lookup(db.payroll_lines, line_id, "ERR_LINE_NOT_FOUND")))


@bp.route("/payroll-submissions/<submission_id>/finalize", methods=["POST"])
def finalize_submission(submission_id):
    actor = authenticate(["PayrollPreparer"])
    submission = get_submission(submission_id)
    assignment = derive.submission_assignment(submission)
    staff = acting_staff(actor)
    require_ownership(staff, assignment["contractor_id"])
    require_capability(staff, PREPARE_CAPABILITIES)

    if submission["workflow_status"] != "DRAFT":
        _invalid_state("Only a DRAFT submission may be finalized.")
    if assignment["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_ASSIGNMENT_STATE", "The owning tier must be ACTIVE.")

    project = derive.submission_project(submission)
    _guard_posture(project)

    lines = derive.lines_of_submission(submission["id"])
    engine.check_referential(
        project, [(line, db.workers.get(line["worker_id"])) for line in lines]
    )

    if db.now() < submission["week_ending_date"]:
        raise ApiError(
            "ERR_PAYROLL_WEEK_NOT_ENDED",
            "The payroll week has not ended on the logical clock.",
        )

    if not lines and not submission["no_work_performed"]:
        raise ApiError(
            "ERR_EMPTY_PAYROLL",
            "A zero-line submission may only be finalized with no_work_performed true.",
        )
    if lines and submission["no_work_performed"]:
        raise ApiError(
            "ERR_EMPTY_PAYROLL",
            "A submission carrying lines may not declare no_work_performed.",
        )

    excess, make_whole = engine.run_wage_engine(submission, project, assignment, lines)
    submission["workflow_status"] = "PENDING_CERTIFICATION"
    submission["compliance_status"] = (
        "COMPLIANT" if (make_whole == 0 and excess == 0) else "DEFICIENT"
    )
    db.touch(submission)
    return ok(s.submission(submission))


@bp.route("/payroll-submissions/<submission_id>/certify", methods=["POST"])
def certify_submission(submission_id):
    actor = authenticate(["CertifyingOfficial"])
    submission = get_submission(submission_id)
    payload = v.body()
    assignment = derive.submission_assignment(submission)
    staff = acting_staff(actor)
    require_ownership(staff, assignment["contractor_id"])
    require_capability(staff, CERTIFY_CAPABILITIES)

    notary_reference_number = v.opt_string(payload, "notary_reference_number")
    note = v.opt_string(payload, "apprentice_ratio_exception_note")

    if submission["workflow_status"] != "PENDING_CERTIFICATION":
        _invalid_state("Only a PENDING_CERTIFICATION submission may be certified.")

    project = derive.submission_project(submission)
    _guard_posture(project)

    if staff["id"] == submission["prepared_by_staff_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The certifying staff row may not be the preparer of the payroll.",
        )

    portal = db.reporting_portals.get(project["reporting_portal_id"]) if project else None
    if portal is not None and portal["requires_notarized_statement"]:
        if (
            notary_reference_number is None
            or notary_reference_number == ""
            or notary_reference_number != staff["notary_reference_number"]
        ):
            raise ApiError(
                "ERR_NOTARIZATION_REQUIRED",
                "The portal requires a notary reference matching the acting staff member's.",
            )

    if calc.dec(submission["excess_apprentice_hours"]) > 0 and not (note or "").strip():
        raise ApiError(
            "ERR_APPRENTICE_RATIO_EXCEEDED",
            "An over-ratio week requires a non-empty apprentice_ratio_exception_note.",
        )

    if db.now() > calc.hard_close_at(submission):
        raise ApiError(
            "ERR_SUBMISSION_WINDOW_CLOSED", "The portal's hard-close instant has passed."
        )

    submission["certified_by_staff_id"] = staff["id"]
    submission["statement_signed_at"] = db.now()
    submission["submitted_at"] = db.now()
    if notary_reference_number is not None:
        submission["notary_reference_number"] = notary_reference_number
    due = submission["filing_due_at"]
    submission["is_late"] = bool(due is not None and submission["submitted_at"] > due)
    submission["workflow_status"] = "SUBMITTED"
    db.touch(submission)
    return ok(s.submission(submission))


@bp.route("/payroll-submissions/<submission_id>/begin-review", methods=["POST"])
def begin_review(submission_id):
    authenticate(["AgencyComplianceOfficer"])
    submission = get_submission(submission_id)
    if submission["workflow_status"] != "SUBMITTED":
        _invalid_state("Only a SUBMITTED submission may be picked up for review.")
    submission["workflow_status"] = "UNDER_REVIEW"
    db.touch(submission)
    return ok(s.submission(submission))


@bp.route("/payroll-submissions/<submission_id>/accept", methods=["POST"])
def accept_submission(submission_id):
    actor = authenticate(["AgencyComplianceOfficer"])
    submission = get_submission(submission_id)
    if submission["workflow_status"] != "UNDER_REVIEW":
        _invalid_state("Only an UNDER_REVIEW submission may be accepted.")
    if submission["compliance_status"] == "DEFICIENT":
        raise ApiError(
            "ERR_UNDERPAYMENT_UNRESOLVED", "A DEFICIENT submission may not be accepted."
        )
    submission["workflow_status"] = "ACCEPTED"
    submission["accepted_by_user_id"] = actor.user_id
    db.touch(submission)
    assignment = derive.submission_assignment(submission)
    assignment["cumulative_certified_hours"] = calc.round_hours(
        calc.dec(assignment["cumulative_certified_hours"])
        + calc.dec(submission["total_hours_reported"])
    )
    db.touch(assignment)
    return ok(s.submission(submission))


@bp.route("/payroll-submissions/<submission_id>/return", methods=["POST"])
def return_submission(submission_id):
    authenticate(["AgencyComplianceOfficer"])
    submission = get_submission(submission_id)
    payload = v.body()
    v.req_nonempty_string(payload, "return_reason")
    if submission["workflow_status"] != "UNDER_REVIEW":
        _invalid_state("Only an UNDER_REVIEW submission may be returned.")
    submission["workflow_status"] = "RETURNED"
    db.touch(submission)
    db.touch(derive.submission_assignment(submission))
    return ok(s.submission(submission))


@bp.route("/payroll-submissions/<submission_id>/rescind-acceptance", methods=["POST"])
def rescind_acceptance(submission_id):
    authenticate(["AgencyComplianceOfficer"])
    submission = get_submission(submission_id)
    payload = v.body()
    v.req_nonempty_string(payload, "rescission_reason")
    if submission["workflow_status"] != "ACCEPTED":
        _invalid_state("Only an ACCEPTED submission may have its acceptance rescinded.")
    for interview in db.ordered(db.interviews):
        if interview["compared_submission_id"] == submission["id"] and interview["status"] in (
            "CONDUCTED_MATCHED",
            "CONDUCTED_DISCREPANT",
        ):
            _invalid_state(
                "An interview has already been compared against this submission."
            )
    submission["workflow_status"] = "UNDER_REVIEW"
    submission["accepted_by_user_id"] = None
    db.touch(submission)
    assignment = derive.submission_assignment(submission)
    assignment["cumulative_certified_hours"] = calc.round_hours(
        calc.dec(assignment["cumulative_certified_hours"])
        - calc.dec(submission["total_hours_reported"])
    )
    db.touch(assignment)
    return ok(s.submission(submission))


@bp.route("/payroll-submissions/<submission_id>/underpayment-summary", methods=["GET"])
def underpayment_summary(submission_id):
    authenticate(ALL_ROLES)
    submission = get_submission(submission_id)
    straight = submission["straight_time_underpayment_cents"]
    make_whole = submission["make_whole_underpayment_cents"]
    return ok(
        {
            "payroll_submission_id": submission["id"],
            "straight_time_underpayment_cents": straight,
            "make_whole_underpayment_cents": make_whole,
            "variant_delta_cents": make_whole - straight,
            "excess_apprentice_hours": s.num(submission["excess_apprentice_hours"]),
            "line_count": len(derive.lines_of_submission(submission["id"])),
        }
    )
