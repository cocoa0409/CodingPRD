"""BreakageEstimate endpoints (PRD §3.6)."""
from flask import Blueprint

import calc
import db
import lookup
import serialize
from auth import (ROLE_CONTROLLER, ROLE_LOYALTY_ACCOUNTANT, ROLE_PROGRAM_ADMIN,
                  authorize)
from errors import ApiError
from response import created, ok, paginate
from routes.periods import ROLLFORWARD_PERSISTED
from util import clock, rhu
from validate import field_int, field_ref, field_string, json_body

bp = Blueprint("breakage_estimates", __name__)

READ_ROLES = (ROLE_PROGRAM_ADMIN, ROLE_LOYALTY_ACCOUNTANT, ROLE_CONTROLLER)


@bp.route("/programs/<program_id>/breakage-estimates", methods=["POST"])
def create_breakage_estimate(program_id):
    user_id, _role = authorize(ROLE_LOYALTY_ACCOUNTANT)
    body = json_body()
    period_id = field_ref(body, "period_id")
    cohort_id = field_ref(body, "cohort_id", required=False)
    memo_narrative = field_string(body, "memo_narrative", max_length=2000,
                                  allow_empty=True)
    low_bp = field_int(body, "sensitivity_low_bp", minimum=200, maximum=9800)
    high_bp = field_int(body, "sensitivity_high_bp", minimum=200, maximum=9800)
    program = lookup.program(program_id)
    period = lookup.period(period_id)
    cohort = lookup.cohort(cohort_id) if cohort_id else None
    if period["state"] != "OPEN":
        raise ApiError("ERR_PERIOD_NOT_OPEN", 409)
    if program["status"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_NOT_ACTIVE", 409)
    if period["program_id"] != program["id"]:
        raise ApiError("ERR_PERIOD_PROGRAM_MISMATCH", 409)
    if cohort is not None and cohort["program_id"] != program["id"]:
        raise ApiError("ERR_COHORT_PROGRAM_MISMATCH", 409)
    measured = calc.estimate_measurement(program, cohort)
    rate = measured["estimated_redemption_rate_bp"]
    if low_bp > rate or high_bp < rate:
        raise ApiError("ERR_SENSITIVITY_BAND_INVALID", 409)
    if measured["empty"]:
        raise calc.no_outstanding_points()
    gross = measured["outstanding_gross_ssp_cents_at_estimate"]
    rec = db.new_record(db.store.breakage_estimates, {
        "program_id": program["id"],
        "period_id": period["id"],
        "cohort_id": cohort["id"] if cohort is not None else None,
        "supersedes_estimate_id": None,
        "method_applied": measured["method_applied"],
        "estimated_redemption_rate_bp": rate,
        "breakage_rate_bp": 10000 - rate,
        "outstanding_points_at_estimate": measured["outstanding_points_at_estimate"],
        "outstanding_gross_ssp_cents_at_estimate": gross,
        "required_liability_cents": rhu(gross * rate, 10000),
        "memo_narrative": memo_narrative,
        "sensitivity_low_bp": low_bp,
        "sensitivity_high_bp": high_bp,
        "state": "DRAFT",
        "prepared_by_user_id": user_id,
        "approved_by_user_id": None,
        "rejection_reason": None,
        "revision_count": 0,
        "submitted_at": None,
        "approved_at": None,
    })
    return created(serialize.breakage_estimate(rec))


@bp.route("/breakage-estimates", methods=["GET"])
def list_breakage_estimates():
    authorize(*READ_ROLES)
    rows = lookup.filtered(db.rows(db.store.breakage_estimates), "program_id",
                           "period_id", "cohort_id", "supersedes_estimate_id",
                           "state", "method_applied")
    return paginate(rows, serialize.breakage_estimate)


@bp.route("/breakage-estimates/<estimate_id>", methods=["GET"])
def read_breakage_estimate(estimate_id):
    authorize(*READ_ROLES)
    return ok(serialize.breakage_estimate(lookup.breakage_estimate(estimate_id)))


@bp.route("/breakage-estimates/<estimate_id>/sensitivity", methods=["GET"])
def read_sensitivity(estimate_id):
    authorize(ROLE_LOYALTY_ACCOUNTANT, ROLE_CONTROLLER)
    estimate = lookup.breakage_estimate(estimate_id)
    return ok(calc.sensitivity_bands(estimate))


@bp.route("/breakage-estimates/<estimate_id>/submit", methods=["POST"])
def submit_breakage_estimate(estimate_id):
    authorize(ROLE_LOYALTY_ACCOUNTANT)
    estimate = lookup.breakage_estimate(estimate_id)
    period = lookup.period(estimate["period_id"])
    if period["state"] != "OPEN":
        raise ApiError("ERR_PERIOD_NOT_OPEN", 409)
    if estimate["state"] not in ("DRAFT", "REJECTED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409)
    resubmission = estimate["state"] == "REJECTED"
    if resubmission and estimate["revision_count"] >= 2:
        raise ApiError("ERR_REVISION_LIMIT_EXCEEDED", 409)
    if resubmission:
        estimate["revision_count"] = estimate["revision_count"] + 1
    estimate["state"] = "SUBMITTED"
    estimate["submitted_at"] = clock.now()
    db.touch(estimate)
    return ok(serialize.breakage_estimate(estimate))


@bp.route("/breakage-estimates/<estimate_id>/reject", methods=["POST"])
def reject_breakage_estimate(estimate_id):
    authorize(ROLE_CONTROLLER)
    body = json_body()
    reason = field_string(body, "rejection_reason", max_length=500)
    estimate = lookup.breakage_estimate(estimate_id)
    if estimate["state"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409)
    estimate["rejection_reason"] = reason
    estimate["state"] = "REJECTED"
    db.touch(estimate)
    return ok(serialize.breakage_estimate(estimate))


def reigning_approved_estimate(program_id, exclude_id):
    """The programme's single live APPROVED estimate, if any."""
    best = None
    for candidate in db.rows(db.store.breakage_estimates):
        if candidate["program_id"] != program_id or candidate["id"] == exclude_id:
            continue
        if candidate["state"] != "APPROVED":
            continue
        if best is None:
            best = candidate
            continue
        key = (candidate["approved_at"] or candidate["created_at"],
               candidate["created_at"], candidate["_seq"])
        best_key = (best["approved_at"] or best["created_at"],
                    best["created_at"], best["_seq"])
        if key > best_key:
            best = candidate
    return best


@bp.route("/breakage-estimates/<estimate_id>/approve", methods=["POST"])
def approve_breakage_estimate(estimate_id):
    user_id, _role = authorize(ROLE_CONTROLLER)
    body = json_body()
    expected_version = field_int(body, "expected_program_version", minimum=0)
    estimate = lookup.breakage_estimate(estimate_id)
    program = lookup.program(estimate["program_id"])
    if expected_version != program["version"]:
        raise ApiError("ERR_STALE_PROGRAM_VERSION", 412)
    period = lookup.period(estimate["period_id"])
    if period["state"] != "OPEN":
        raise ApiError("ERR_PERIOD_NOT_OPEN", 409)
    if estimate["state"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409)
    if user_id == estimate["prepared_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409)
    estimate["state"] = "APPROVED"
    estimate["approved_by_user_id"] = user_id
    estimate["approved_at"] = clock.now()
    retired = reigning_approved_estimate(program["id"], estimate["id"])
    if retired is not None:
        estimate["supersedes_estimate_id"] = retired["id"]
    db.touch(estimate)
    program["current_breakage_rate_bp"] = estimate["breakage_rate_bp"]
    db.touch(program)
    if retired is not None:
        retired["state"] = "SUPERSEDED"
        db.touch(retired)
        retired_period = db.store.periods.get(retired["period_id"])
        if retired_period is not None and retired_period["state"] == "SOFT_CLOSED":
            for name in ROLLFORWARD_PERSISTED:
                retired_period[name] = 0
            retired_period["state"] = "OPEN"
            retired_period["soft_closed_at"] = None
            retired_period["reopen_count"] = retired_period["reopen_count"] + 1
            db.touch(retired_period)
    return ok(serialize.breakage_estimate(estimate))
