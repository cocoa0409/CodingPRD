"""Enrollment routes (PRD §3.4)."""

from flask import Blueprint, request

from core.auth import require_roles
from core.envelope import success_object, success_array
from core.errors import raise_error
from core.store import STORE, lock
from core.validation import parse_pagination
from services.mutations import bump
from services.projections import project_enrollment


bp = Blueprint("enrollments", __name__)


_COVERAGE_STATUSES = {
    "ACTIVE", "CONTINUOUS_COVERAGE", "REDETERMINATION_DUE",
    "SUSPENDED", "TERMINATED",
}


@bp.route("/enrollments/<enrollment_id>", methods=["GET"])
@require_roles("IntakeWorker", "EligibilityCaseworker", "PolicyAdmin")
def get_enrollment(enrollment_id):
    row = STORE.enrollments.get(enrollment_id)
    if row is None:
        raise_error("ERR_NOT_FOUND", "Enrollment not found")
    return success_object(project_enrollment(row))


@bp.route("/enrollments", methods=["GET"])
@require_roles("IntakeWorker", "EligibilityCaseworker", "PolicyAdmin")
def list_enrollments():
    limit, offset = parse_pagination(request)
    applicant_id = request.args.get("applicant_id")
    coverage_status = request.args.get("coverage_status")
    if coverage_status is not None and coverage_status not in _COVERAGE_STATUSES:
        raise_error("ERR_INVALID_REQUEST", "coverage_status filter invalid")
    if applicant_id is not None and applicant_id not in STORE.applicants:
        raise_error("ERR_NOT_FOUND", "applicant_id not found")
    rows = list(STORE.enrollments.values())
    if applicant_id is not None:
        rows = [r for r in rows if r["applicant_id"] == applicant_id]
    if coverage_status is not None:
        rows = [r for r in rows if r["coverage_status"] == coverage_status]
    rows.sort(key=lambda r: r["created_at"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_array([project_enrollment(r) for r in page], limit, offset, total)


def _bump_household_for_enrollment(enrollment):
    applicant = STORE.applicants.get(enrollment["applicant_id"])
    if applicant is None:
        return
    household = STORE.households.get(applicant["household_id"])
    if household is not None:
        bump(household)


@bp.route("/enrollments/<enrollment_id>/suspend", methods=["POST"])
@require_roles("PolicyAdmin")
def suspend_enrollment(enrollment_id):
    row = STORE.enrollments.get(enrollment_id)
    if row is None:
        raise_error("ERR_NOT_FOUND", "Enrollment not found")
    if row["coverage_status"] != "ACTIVE":
        raise_error("ERR_INVALID_STATE", "Enrollment must be ACTIVE to suspend")
    with lock():
        row["coverage_status"] = "SUSPENDED"
        bump(row)
        _bump_household_for_enrollment(row)
    return success_object(project_enrollment(row))


@bp.route("/enrollments/<enrollment_id>/reactivate", methods=["POST"])
@require_roles("PolicyAdmin")
def reactivate_enrollment(enrollment_id):
    row = STORE.enrollments.get(enrollment_id)
    if row is None:
        raise_error("ERR_NOT_FOUND", "Enrollment not found")
    if row["coverage_status"] != "SUSPENDED":
        raise_error("ERR_INVALID_STATE", "Enrollment must be SUSPENDED to reactivate")
    with lock():
        row["coverage_status"] = "ACTIVE"
        bump(row)
        _bump_household_for_enrollment(row)
    return success_object(project_enrollment(row))
