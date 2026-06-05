"""LifeEvent endpoints (PRD §3.6, §3.7, §2.8, §2.9, §2.10).

Approval is the heaviest operation: it mints a new ACTIVE Enrollment, supersedes
the prior ACTIVE enrollment of the same benefit_type, emits TERM + ADD carrier
feed records, and (if RETROACTIVE) posts RETRO_ADJUSTMENT deduction lines.
"""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

import clock
import db
import errors as E
from middleware import (
    authenticate, authorize, current_user_id,
    BENEFITS_ADMIN, COMPLIANCE_OFFICER, PAYROLL_OFFICER,
)
import response
from services import common as C
from services import domain as D
from routes._helpers import get_or_404

bp = Blueprint("life_events", __name__)

EVENT_TYPES = {"BIRTH", "MARRIAGE", "DIVORCE", "LOSS_OF_COVERAGE"}
ADJUSTMENT_MODES = {"PROSPECTIVE", "RETROACTIVE"}


@bp.route("/employees/<emp_id>/life-events", methods=["POST"])
def create_life_event(emp_id):
    role = authenticate()
    authorize(role, {BENEFITS_ADMIN})
    emp = get_or_404(db.employees, emp_id, "Employee")
    body = C.get_body()
    C.require_fields(body, ["event_type", "event_date", "requested_plan_tier_id", "adjustment_mode"])
    event_type = C.require_enum(body, "event_type", EVENT_TYPES)
    event_date = body["event_date"]
    C.parse_iso(event_date)  # validate ISO 8601
    tier_id = body["requested_plan_tier_id"]
    if not C.is_str(tier_id):
        raise E.invalid_request("requested_plan_tier_id must be a string")
    tier = get_or_404(db.plan_tiers, tier_id, "PlanTier")
    adjustment_mode = C.require_enum(body, "adjustment_mode", ADJUSTMENT_MODES)

    requested_coverage = body.get("requested_coverage_amount_cents", 0)
    if requested_coverage is None:
        requested_coverage = 0
    if not C.is_int(requested_coverage) or requested_coverage < 0:
        raise E.invalid_request("requested_coverage_amount_cents must be a non-negative integer")

    le = C.new_common_fields()
    le.update({
        "employee_id": emp_id,
        "event_type": event_type,
        "event_date": event_date,
        "requested_plan_tier_id": tier_id,
        "requested_coverage_amount_cents": requested_coverage,
        "submitted_by_user_id": current_user_id(),
        "adjustment_mode": adjustment_mode,
        "status": "SUBMITTED",
    })
    db.life_events[le["id"]] = le
    return response.ok_object(C.serialize(le), 201)


@bp.route("/life-events/<le_id>", methods=["GET"])
def get_life_event(le_id):
    role = authenticate()
    authorize(role, {BENEFITS_ADMIN, COMPLIANCE_OFFICER, PAYROLL_OFFICER})
    le = get_or_404(db.life_events, le_id, "LifeEvent")
    return response.ok_object(C.serialize(le), 200)


@bp.route("/life-events", methods=["GET"])
def list_life_events():
    role = authenticate()
    authorize(role, {BENEFITS_ADMIN, COMPLIANCE_OFFICER, PAYROLL_OFFICER})
    limit, offset = C.parse_pagination()
    args = request.args
    items = list(db.life_events.values())
    for key in ("employee_id", "requested_plan_tier_id", "status"):
        val = args.get(key)
        if val is not None:
            items = [e for e in items if e.get(key) == val]
    items = C.order_by_created(items)
    page, total = C.paginate(items, limit, offset)
    return response.ok_array(C.serialize_list(page), limit, offset, total, 200)


@bp.route("/life-events/<le_id>/reject", methods=["POST"])
def reject_life_event(le_id):
    role = authenticate()
    authorize(role, {BENEFITS_ADMIN})
    le = get_or_404(db.life_events, le_id, "LifeEvent")
    # State (priority 5) then segregation (priority 6).
    if le["status"] != "SUBMITTED":
        raise E.invalid_state("LifeEvent must be SUBMITTED to reject")
    if current_user_id() == le["submitted_by_user_id"]:
        raise E.segregation("Rejecter must differ from submitter")
    le["status"] = "REJECTED"
    C.touch(le)
    return response.ok_object(C.serialize(le), 200)


@bp.route("/life-events/<le_id>/approve", methods=["POST"])
def approve_life_event(le_id):
    role = authenticate()
    authorize(role, {BENEFITS_ADMIN})
    le = get_or_404(db.life_events, le_id, "LifeEvent")
    body = C.get_body()
    # Body shape (priority 4).
    C.require_fields(body, ["expected_employee_version"])
    expected_version = body["expected_employee_version"]
    if not C.is_int(expected_version):
        raise E.invalid_request("expected_employee_version must be an integer")

    # State (priority 5).
    if le["status"] != "SUBMITTED":
        raise E.invalid_state("LifeEvent must be SUBMITTED to approve")

    emp = db.employees[le["employee_id"]]

    # Segregation (priority 6).
    if current_user_id() == le["submitted_by_user_id"]:
        raise E.segregation("Approver must differ from submitter")

    # Employee eligible (priority 8).
    if emp["eligibility_status"] != "ELIGIBLE":
        raise E.employee_not_eligible()

    # Life-event window (priority 9): event_date not more than 30 days before clock.
    clock_date = C.date_of(clock.now())
    event_date = C.date_of(C.parse_iso(le["event_date"]))
    if (clock_date - event_date).days > D.LIFE_EVENT_WINDOW_DAYS:
        raise E.life_event_window_expired()

    # OCC (priority 13).
    if expected_version != emp["version"]:
        raise E.stale_employee_version()

    # ----- side-effect cascade (PRD §3.6) -----
    tier = db.plan_tiers[le["requested_plan_tier_id"]]
    offering = D.offering_for_tier(tier)
    benefit_type = offering["benefit_type"] if offering else None

    # Hop 1: new ACTIVE enrollment for requested tier, coverage_start = event_date.
    new_enr = C.new_common_fields()
    new_enr.update({
        "employee_id": emp["id"],
        "plan_tier_id": le["requested_plan_tier_id"],
        "benefit_type": benefit_type,
        "coverage_amount_cents": le.get("requested_coverage_amount_cents", 0),
        "coverage_start_date": le["event_date"],
        "coverage_end_date": None,
        "monthly_employee_cost_cents": 0,
        "per_paycheck_deduction_cents": 0,
        "covered_dependent_count": 0,
        "source_life_event_id": le["id"],
        "superseded_by_enrollment_id": None,
        "status": "ACTIVE",
    })
    D.recompute_enrollment_costs(new_enr, emp)
    db.enrollments[new_enr["id"]] = new_enr

    # Hop 2: prior ACTIVE enrollment of same benefit_type -> SUPERSEDED.
    prior = D.active_enrollment_of_benefit_type(emp["id"], benefit_type)
    # Exclude the just-created one (it is ACTIVE too).
    if prior is not None and prior["id"] == new_enr["id"]:
        prior = None
    if prior is not None:
        end_str = D.date_minus_one_day_str(new_enr["coverage_start_date"])
        D.supersede_enrollment(prior, end_str, new_enr["id"])

    # Hop 3: new enrollment emits ADD (prior already emitted TERM in supersede).
    D.emit_carrier_feed(new_enr, "ADD")

    # Hop 4: RETROACTIVE retro adjustment lines (PRD §3.7).
    if le["adjustment_mode"] == "RETROACTIVE" and prior is not None:
        _post_retro_lines(le, emp, prior, new_enr)

    # Finally bump versions.
    C.touch(le)
    le["status"] = "APPROVED"
    C.touch(emp)
    return response.ok_object(C.serialize(le), 200)


def _post_retro_lines(le, emp, prior, new_enr):
    """Walk already-processed pay periods in ascending pay_period_index; for each
    period whose billed coverage date falls on/after event_date, post one
    RETRO_ADJUSTMENT line of (new_pp - old_pp). (PRD §3.7 retroactive variant.)
    """
    old_pp = prior["per_paycheck_deduction_cents"]
    new_pp = new_enr["per_paycheck_deduction_cents"]
    delta = new_pp - old_pp
    event_date = C.date_of(C.parse_iso(le["event_date"]))

    # Find prior enrollment's REGULAR lines (already-processed periods), sorted by
    # pay_period_index ascending. These represent the periods already billed under
    # the old per-paycheck amount.
    prior_lines = [
        ln for ln in db.deduction_lines.values()
        if ln["enrollment_id"] == prior["id"] and ln["line_type"] == "REGULAR"
    ]
    prior_lines.sort(key=lambda ln: (ln["pay_period_index"], ln.get("_seq", 0)))

    for ln in prior_lines:
        billed = ln.get("_billed_date")
        if billed is None:
            continue
        billed_date = C.parse_iso(billed).date() if "T" in billed else _parse_date(billed)
        if billed_date >= event_date:
            D.post_retro_adjustment(new_enr, emp, ln["pay_period_index"], delta)


def _parse_date(s):
    from datetime import date
    parts = s.split("-")
    return date(int(parts[0]), int(parts[1]), int(parts[2]))
