"""Redetermination routes (PRD §3.4)."""

from decimal import Decimal

from flask import Blueprint, request

from core.auth import require_roles
from core.clock import CLOCK
from core.envelope import success_object, success_array
from core.errors import raise_error
from core.store import STORE, lock
from core.timeutils import iso_format, days, parse_iso
from core.validation import require_body, require_field, require_enum, parse_pagination
from services.mutations import bump
from services.money import round2_float, to_decimal
from services.calculations import (
    fpl_threshold_amount,
    compute_fpl_percent,
    effective_household_size,
)
from services.projections import (
    project_redetermination,
    find_policy_by_state,
    list_applicants_of_household,
)


bp = Blueprint("redeterminations", __name__)


def _enrollment_and_household(redet):
    enrollment = STORE.enrollments.get(redet["enrollment_id"])
    if enrollment is None:
        raise_error("ERR_NOT_FOUND", "Enrollment not found")
    applicant = STORE.applicants.get(enrollment["applicant_id"])
    if applicant is None:
        raise_error("ERR_NOT_FOUND", "Applicant not found")
    household = STORE.households.get(applicant["household_id"])
    if household is None:
        raise_error("ERR_NOT_FOUND", "Household not found")
    return enrollment, household


@bp.route("/redeterminations/<redetermination_id>", methods=["GET"])
@require_roles("IntakeWorker", "EligibilityCaseworker", "PolicyAdmin")
def get_redetermination(redetermination_id):
    row = STORE.redeterminations.get(redetermination_id)
    if row is None:
        raise_error("ERR_NOT_FOUND", "Redetermination not found")
    return success_object(project_redetermination(row))


@bp.route("/redeterminations", methods=["GET"])
@require_roles("IntakeWorker", "EligibilityCaseworker", "PolicyAdmin")
def list_redeterminations():
    """List Redeterminations with optional filters.

    PRD §3.4 names the Redetermination resource created by the
    /_sweep/redeterminations transition but does not pin a single
    discovery channel for clients to locate it. Exposing a list endpoint
    with an enrollment_id filter is consistent with the other list
    endpoints in §4 (e.g., GET /emergency-declarations, GET /enrollments)
    and lets the standard "sweep, then find the PENDING redetermination"
    workflow proceed without inventing surface area outside the PRD's
    described resource model.
    """
    limit, offset = parse_pagination(request)
    enrollment_id = request.args.get("enrollment_id")
    status_filter = request.args.get("status")
    if enrollment_id is not None and enrollment_id not in STORE.enrollments:
        raise_error("ERR_NOT_FOUND", "enrollment_id not found")
    rows = list(STORE.redeterminations.values())
    if enrollment_id is not None:
        rows = [r for r in rows if r["enrollment_id"] == enrollment_id]
    if status_filter is not None:
        rows = [r for r in rows if r["status"] == status_filter]
    rows.sort(key=lambda r: r["created_at"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_array(
        [project_redetermination(r) for r in page], limit, offset, total,
    )


@bp.route("/redeterminations/<redetermination_id>/submit", methods=["POST"])
@require_roles("EligibilityCaseworker")
def submit_redetermination(redetermination_id):
    row = STORE.redeterminations.get(redetermination_id)
    if row is None:
        raise_error("ERR_NOT_FOUND", "Redetermination not found")
    if row["status"] != "PENDING":
        raise_error("ERR_INVALID_STATE", "Redetermination must be PENDING to submit")
    body = require_body(request)
    decision = require_enum(body, "decision", {"RENEW", "TERMINATE"})
    new_magi = require_field(body, "new_snapshot_magi", kind="number")

    enrollment, household = _enrollment_and_household(row)
    if enrollment["coverage_status"] != "REDETERMINATION_DUE":
        raise_error("ERR_INVALID_STATE", "Parent enrollment must be REDETERMINATION_DUE")
    policy = find_policy_by_state(household["state_code"])
    if policy is None:
        raise_error("ERR_HOUSEHOLD_INCOMPLETE", "No StatePolicy for household")
    applicants = list_applicants_of_household(household["id"])
    eff_size = effective_household_size(applicants)
    if eff_size <= 0:
        raise_error("ERR_FPL_THRESHOLD_INVALID", "Effective household size is zero")
    threshold = fpl_threshold_amount(eff_size, policy)
    if threshold <= 0:
        raise_error("ERR_FPL_THRESHOLD_INVALID", "FPL threshold is zero")
    new_fpl = compute_fpl_percent(to_decimal(new_magi), threshold)
    eligible = (new_fpl is not None and new_fpl <= to_decimal(policy["magi_income_limit_pct"]))

    # 90-day grace from due_date
    try:
        due_dt = parse_iso(row["due_date"], "due_date")
    except Exception:
        due_dt = None
    past_grace = False
    if due_dt is not None:
        past_grace = CLOCK.now() > (due_dt + days(90))

    if decision == "RENEW":
        if not eligible:
            raise_error("ERR_NOT_ELIGIBLE", "new_snapshot_fpl_percent exceeds magi_income_limit_pct")
        # Enrollment overlap check is unnecessary here because we're renewing the
        # same enrollment in place. PRD §3.4 resets coverage_start to clock_now.
        with lock():
            row["new_snapshot_magi"] = float(new_magi)
            row["new_snapshot_fpl_percent"] = round2_float(new_fpl)
            row["status"] = "RENEWED"
            row["decision"] = "RENEWED"
            bump(row)
            now = CLOCK.now()
            enrollment["coverage_start"] = iso_format(now)
            enrollment["coverage_end"] = iso_format(now + days(365))
            enrollment["redetermination_due_at"] = iso_format(now + days(365))
            enrollment["coverage_status"] = "ACTIVE"
            bump(enrollment)
            bump(household)
        return success_object(project_redetermination(row))
    else:  # TERMINATE
        # Per PRD §3.4: terminate requires either fail-eligibility OR past-grace
        if eligible and not past_grace:
            raise_error("ERR_INVALID_STATE",
                        "Cannot terminate a renewable redetermination still within grace")
        with lock():
            row["new_snapshot_magi"] = float(new_magi)
            row["new_snapshot_fpl_percent"] = round2_float(new_fpl) if new_fpl is not None else None
            row["status"] = "TERMINATED"
            row["decision"] = "TERMINATED"
            bump(row)
            enrollment["coverage_status"] = "TERMINATED"
            bump(enrollment)
            bump(household)
        return success_object(project_redetermination(row))


@bp.route("/redeterminations/<redetermination_id>/withdraw", methods=["POST"])
@require_roles("IntakeWorker")
def withdraw_redetermination(redetermination_id):
    row = STORE.redeterminations.get(redetermination_id)
    if row is None:
        raise_error("ERR_NOT_FOUND", "Redetermination not found")
    if row["status"] != "PENDING":
        raise_error("ERR_INVALID_STATE", "Redetermination must be PENDING to withdraw")
    with lock():
        row["status"] = "WITHDRAWN"
        bump(row)
    return success_object(project_redetermination(row, include_premium=False))
