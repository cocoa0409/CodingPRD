"""On-site interviews and the audit fork of PRD 3.9.

A scheduled interview occupies a window on the worker that is buffered by a full
hour on each side; conducting one forks on whether the auditor's observation
agrees with the ACCEPTED payroll covering window_start, and the discrepant
branch carries a strictly larger side-effect set than the matched branch.
"""

from datetime import timedelta

from flask import Blueprint, request

import calc
import db
import derive
import serializers as s
import validators as v
from auth import ALL_ROLES, authenticate
from errors import ApiError
from response import created, ok, paginated, pagination
from routes.findings import build_finding

bp = Blueprint("interviews", __name__)

BUFFER = timedelta(minutes=calc.INTERVIEW_BUFFER_MINUTES)
OCCUPYING_STATUSES = ("SCHEDULED", "CONDUCTED_MATCHED", "CONDUCTED_DISCREPANT")


def get_interview(interview_id):
    return v.lookup(db.interviews, interview_id, "ERR_INTERVIEW_NOT_FOUND")


def _invalid_interview_state(message):
    raise ApiError("ERR_INVALID_INTERVIEW_STATE", message)


def _half_open_intersects(a_start, a_end, b_start, b_end):
    """Two half-open intervals [start, end) share at least one instant."""
    return a_start < b_end and b_start < a_end


def _covered_week_contains(submission, instant):
    """The payroll week is closed on both ends (PRD 2.11)."""
    week_end = submission["week_ending_date"]
    return (week_end - db.days(6)) <= instant <= week_end


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------
@bp.route("/interviews", methods=["POST"])
def schedule_interview():
    authenticate(["LaborStandardsAuditor"])
    payload = v.body()
    project = v.resolve_fk(payload, "project_id", db.projects, "ERR_PROJECT_NOT_FOUND")
    assignment = v.resolve_fk(
        payload, "contract_assignment_id", db.contract_assignments, "ERR_ASSIGNMENT_NOT_FOUND"
    )
    worker = v.resolve_fk(payload, "worker_id", db.workers, "ERR_WORKER_NOT_FOUND")

    if project is None:
        v.bad("project_id is required.")
    if assignment is None:
        v.bad("contract_assignment_id is required.")
    if worker is None:
        v.bad("worker_id is required.")
    window_start = v.req_instant(payload, "window_start")
    window_end = v.req_instant(payload, "window_end")
    if window_end <= window_start:
        v.bad("window_end must fall strictly after window_start.")

    # Rung 26 -- the buffered window must not touch another live window on the
    # same worker. The requested span is expanded on BOTH sides; the comparison
    # runs against every other interview's UNEXPANDED window.
    buffered_start = window_start - BUFFER
    buffered_end = window_end + BUFFER
    for other in db.ordered(db.interviews):
        if other["worker_id"] != worker["id"]:
            continue
        if other["status"] not in OCCUPYING_STATUSES:
            continue
        if _half_open_intersects(
            buffered_start, buffered_end, other["window_start"], other["window_end"]
        ):
            raise ApiError(
                "ERR_INTERVIEW_BUFFER_CONFLICT",
                "The buffered interview window intersects another live interview on this worker.",
            )

    row = db.base_row()
    row.update(
        {
            "project_id": project["id"],
            "contract_assignment_id": assignment["id"],
            "worker_id": worker["id"],
            "window_start": window_start,
            "window_end": window_end,
            "observed_classification_code": None,
            "observed_hourly_rate_cents": None,
            "status": "SCHEDULED",
            "compared_submission_id": None,
        }
    )
    db.interviews[row["id"]] = row
    return created(s.interview(row))


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
@bp.route("/interviews", methods=["GET"])
def list_interviews():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    project_id = request.args.get("project_id")
    assignment_id = request.args.get("contract_assignment_id")
    worker_id = request.args.get("worker_id")
    compared_id = request.args.get("compared_submission_id")
    status = request.args.get("status")

    def keep(row):
        if project_id is not None and row["project_id"] != project_id:
            return False
        if assignment_id is not None and row["contract_assignment_id"] != assignment_id:
            return False
        if worker_id is not None and row["worker_id"] != worker_id:
            return False
        if compared_id is not None and row["compared_submission_id"] != compared_id:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return paginated(db.ordered(db.interviews, keep), s.interview, limit, offset)


@bp.route("/interviews/<interview_id>", methods=["GET"])
def read_interview(interview_id):
    authenticate(ALL_ROLES)
    return ok(s.interview(get_interview(interview_id)))


# ---------------------------------------------------------------------------
# The audit fork
# ---------------------------------------------------------------------------
def _compared_submission(interview):
    """Exactly one ACCEPTED submission on the tier must cover window_start."""
    covering = [
        submission
        for submission in derive.submissions_of_assignment(interview["contract_assignment_id"])
        if submission["workflow_status"] == "ACCEPTED"
        and _covered_week_contains(submission, interview["window_start"])
    ]
    if len(covering) != 1:
        raise ApiError(
            "ERR_INVALID_SUBMISSION_STATE",
            "Exactly one ACCEPTED payroll submission on the tier must cover window_start.",
        )
    return covering[0]


def _observation_matches(submission, interview, classification_code, hourly_rate_cents):
    for line in derive.lines_of_submission(submission["id"]):
        if line["worker_id"] != interview["worker_id"]:
            continue
        return (
            line["classification_code"] == classification_code
            and line["base_rate_paid_cents"] >= hourly_rate_cents
        )
    return False


@bp.route("/interviews/<interview_id>/conduct", methods=["POST"])
def conduct_interview(interview_id):
    actor = authenticate(["LaborStandardsAuditor"])
    interview = get_interview(interview_id)
    payload = v.body()
    classification_code = v.req_nonempty_string(payload, "observed_classification_code")
    hourly_rate_cents = v.req_int(payload, "observed_hourly_rate_cents", minimum=0)

    if interview["status"] != "SCHEDULED":
        _invalid_interview_state("Only a SCHEDULED interview may be conducted.")
    if db.now() < interview["window_start"]:
        _invalid_interview_state(
            "The logical clock must read at or after the interview's window_start."
        )
    submission = _compared_submission(interview)

    matched = _observation_matches(
        submission, interview, classification_code, hourly_rate_cents
    )

    interview["observed_classification_code"] = classification_code
    interview["observed_hourly_rate_cents"] = hourly_rate_cents
    interview["compared_submission_id"] = submission["id"]
    interview["status"] = "CONDUCTED_MATCHED" if matched else "CONDUCTED_DISCREPANT"
    db.touch(interview)

    worker = db.workers.get(interview["worker_id"])
    if worker is not None:
        worker["interview_count"] = worker["interview_count"] + 1
        db.touch(worker)

    if not matched:
        # Cascade hop 1: the auto-raised finding, which then cascades exactly as
        # any auditor-raised finding does.
        project = db.projects.get(interview["project_id"])
        build_finding(
            project,
            submission,
            worker,
            "MISCLASSIFICATION",
            "MAJOR",
            0,
            actor.user_id,
            source_interview_id=interview["id"],
        )

    return ok(s.interview(interview))


@bp.route("/interviews/<interview_id>/cancel", methods=["POST"])
def cancel_interview(interview_id):
    authenticate(["LaborStandardsAuditor"])
    interview = get_interview(interview_id)
    payload = v.body()
    v.req_nonempty_string(payload, "cancellation_reason")

    if interview["status"] != "SCHEDULED":
        _invalid_interview_state("Only a SCHEDULED interview may be cancelled.")

    interview["status"] = "CANCELLED"
    db.touch(interview)
    return ok(s.interview(interview))
