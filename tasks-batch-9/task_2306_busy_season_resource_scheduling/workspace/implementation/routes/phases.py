"""EngagementPhase: creation, reads, scope expansion, start / complete and the
auto-staffing selector."""

from flask import Blueprint

import db
import response
import validation
from errors import ApiError
from middleware import (
    ROLE_ENGAGEMENT_PARTNER,
    ROLE_ENGAGEMENT_STAFF,
    ROLE_FIRM_ADMIN,
    ROLE_SCHEDULING_MANAGER,
    authorize,
)
from routes import common
from services import booking, calc, derive, serialize

bp = Blueprint("phases", __name__)

MAX_ALLOCATED_HOURS = calc.D("400.00")


def _phase_state_error(detail):
    raise ApiError("ERR_PHASE_INVALID_STATE", detail)


# =============================================================================
# create / read / list
# =============================================================================
@bp.post("/engagement-phases")
def create_phase():
    authorize(ROLE_SCHEDULING_MANAGER)
    body = validation.json_body()

    engagement = validation.body_fk(
        body, "engagement_id", db.engagements, "ERR_ENGAGEMENT_NOT_FOUND"
    )

    validation.req_string(body, "engagement_id")
    phase_type = validation.req_enum(body, "phase_type", validation.PHASE_TYPES)
    expected_hours = validation.req_number(
        body, "expected_hours", calc.D("0"), None, exclusive_min=True
    )
    window_start_date = validation.req_date(body, "window_start_date")
    window_end_date = validation.req_date(body, "window_end_date")
    required_level = validation.req_enum(body, "required_level", validation.LEVELS)
    required_spec = validation.opt_enum(
        body, "required_industry_specialization", validation.INDUSTRY_CODES
    )
    requires_cpa = validation.opt_boolean(body, "requires_cpa_licensed", False)

    if window_end_date < window_start_date:
        raise ApiError(
            "ERR_INVALID_DATE_RANGE", "window_end_date must be on or after window_start_date."
        )

    common.require_unblocked(engagement)

    if window_end_date > engagement["deadline_date"]:
        raise ApiError(
            "ERR_PHASE_WINDOW_AFTER_DEADLINE",
            "window_end_date must not fall after the engagement deadline.",
        )

    row = db.new_row()
    row.update(
        {
            "engagement_id": engagement["id"],
            "phase_type": phase_type,
            "expected_hours": calc.r2(expected_hours),
            "window_start_date": window_start_date,
            "window_end_date": window_end_date,
            "required_level": required_level,
            "required_industry_specialization": required_spec,
            "requires_cpa_licensed": requires_cpa,
            "staffing_status": "NOT_STAFFED",
        }
    )
    db.phases[row["id"]] = row
    db.mark(engagement)
    db.commit()
    return response.object_response(serialize.phase(row), 201)


@bp.get("/engagement-phases/<engagement_phase_id>")
def read_phase(engagement_phase_id):
    authorize(
        ROLE_FIRM_ADMIN,
        ROLE_SCHEDULING_MANAGER,
        ROLE_ENGAGEMENT_PARTNER,
        ROLE_ENGAGEMENT_STAFF,
    )
    row = validation.path_phase(engagement_phase_id)
    return response.object_response(serialize.phase(row))


@bp.get("/engagement-phases")
def list_phases():
    authorize(
        ROLE_FIRM_ADMIN,
        ROLE_SCHEDULING_MANAGER,
        ROLE_ENGAGEMENT_PARTNER,
        ROLE_ENGAGEMENT_STAFF,
    )
    engagement_id = common.q("engagement_id")
    phase_type = common.q("phase_type")
    staffing_status = common.q("staffing_status")
    rows = db.by_seq(list(db.phases.values()))
    if engagement_id is not None:
        rows = [r for r in rows if r["engagement_id"] == engagement_id]
    if phase_type is not None:
        rows = [r for r in rows if r["phase_type"] == phase_type]
    if staffing_status is not None:
        rows = [r for r in rows if r["staffing_status"] == staffing_status]
    return common.page(rows, serialize.phase)


# =============================================================================
# transitions
# =============================================================================
@bp.post("/engagement-phases/<engagement_phase_id>/expand-scope")
def expand_scope(engagement_phase_id):
    authorize(ROLE_SCHEDULING_MANAGER)
    phase = validation.path_phase(engagement_phase_id)
    body = validation.json_body()
    additional = validation.req_number(
        body, "additional_expected_hours", calc.D("0"), None, exclusive_min=True
    )
    validation.opt_string(body, "reason_note", 1, 500)

    if phase["staffing_status"] == "COMPLETE":
        _phase_state_error("A COMPLETE phase accepts no scope expansion.")

    engagement = common.engagement_of(phase)
    common.require_unblocked(engagement)

    phase["expected_hours"] = calc.r2(calc.D(phase["expected_hours"]) + additional)
    db.mark(phase)
    derive.refresh_phase_status(phase)

    engagement["scope_change_count"] = engagement["scope_change_count"] + 1
    db.mark(engagement)
    derive.bubble_engagement(engagement)

    db.commit()
    return response.object_response(serialize.phase(phase))


@bp.post("/engagement-phases/<engagement_phase_id>/start")
def start_phase(engagement_phase_id):
    authorize(ROLE_SCHEDULING_MANAGER)
    phase = validation.path_phase(engagement_phase_id)

    if phase["staffing_status"] not in ("PARTIALLY_STAFFED", "FULLY_STAFFED"):
        _phase_state_error("Only a staffed phase may be started.")

    engagement = common.engagement_of(phase)
    if engagement is None or engagement["status"] != "IN_FIELDWORK":
        _phase_state_error("The owning engagement must be IN_FIELDWORK.")

    if not calc.assignments_of_phase(phase["id"], ("CONFIRMED",)):
        _phase_state_error("At least one CONFIRMED assignment is required to start the phase.")

    phase["staffing_status"] = "IN_PROGRESS"
    db.mark(phase)
    db.commit()
    return response.object_response(serialize.phase(phase))


@bp.post("/engagement-phases/<engagement_phase_id>/complete")
def complete_phase(engagement_phase_id):
    authorize(ROLE_SCHEDULING_MANAGER)
    phase = validation.path_phase(engagement_phase_id)

    if phase["staffing_status"] != "IN_PROGRESS":
        _phase_state_error("Only an IN_PROGRESS phase may be completed.")

    active = calc.assignments_of_phase(phase["id"], ("ACTIVE",))
    if not active:
        _phase_state_error("At least one ACTIVE assignment is required to complete the phase.")
    if any(a["review_status"] not in ("NOT_REQUIRED", "REVIEW_ACCEPTED") for a in active):
        _phase_state_error(
            "Every ACTIVE assignment must have passed review before the phase completes."
        )

    for assignment in active:
        assignment["staffing_status"] = "COMPLETED"
        db.mark(assignment)

    phase["staffing_status"] = "COMPLETE"
    db.mark(phase)
    db.commit()
    return response.object_response(serialize.phase(phase))


# =============================================================================
# the auto-staffing selector
# =============================================================================
@bp.post("/engagement-phases/<engagement_phase_id>/auto-staff")
def auto_staff(engagement_phase_id):
    authorize(ROLE_SCHEDULING_MANAGER)
    phase = validation.path_phase(engagement_phase_id)
    body = validation.json_body()

    start_date = validation.req_date(body, "start_date")
    end_date = validation.req_date(body, "end_date")
    allocated_hours = validation.req_number(
        body, "allocated_hours", calc.D("0"), MAX_ALLOCATED_HOURS, exclusive_min=True
    )

    if end_date <= start_date:
        raise ApiError("ERR_INVALID_DATE_RANGE", "end_date must fall after start_date.")

    engagement = common.engagement_of(phase)
    common.require_unblocked(engagement)

    if not (
        phase["window_start_date"] <= start_date
        and end_date <= phase["window_end_date"] + calc.ONE_DAY
    ):
        raise ApiError(
            "ERR_ASSIGNMENT_OUTSIDE_PHASE_WINDOW",
            "The requested window does not sit inside the phase window.",
        )

    if phase["staffing_status"] not in ("NOT_STAFFED", "PARTIALLY_STAFFED") or calc.phase_unstaffed_hours(
        phase
    ) <= calc.ZERO:
        raise ApiError(
            "ERR_PHASE_FULLY_STAFFED",
            "The phase carries no unstaffed hours for the selector to fill.",
        )

    staff, score, _daily = calc.select_candidate(
        phase, engagement, start_date, end_date, allocated_hours
    )
    if staff is None:
        raise ApiError("ERR_NO_ELIGIBLE_STAFF", "No eligible domestic candidate was found.")

    plan = booking.onshore_plan(start_date, end_date, allocated_hours)
    row = booking.write_assignment(
        phase, staff, start_date, end_date, allocated_hours, None, plan, score
    )
    derive.refresh_phase_status(phase)
    db.mark(phase)
    db.commit()
    return response.object_response(serialize.assignment(row), 201)
