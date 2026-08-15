"""CapitalPlan endpoints (PRD 3.5)."""

from __future__ import annotations

from flask import Blueprint

from db import (
    capital_plans, stress_scenarios, reporting_periods, distribution_requests,
    sub_debt_issuances, stamp_new, touch,
)
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE_TRANSITION,
    ERR_CROSS_BANK_REFERENCE, ERR_INVARIANT_VIOLATION,
    ERR_SEGREGATION_OF_DUTIES_VIOLATION, ERR_PLAN_DISTRIBUTION_EXCEEDS_CAPACITY,
    ERR_PLAN_FAILED_STRESS_FLOOR,
)
from middleware import require_roles
from response import success_object, success_list
from services.core import (
    ser_plan, get_bank, get_plan, refresh_plan_baseline, compute_plan_projections,
    stress_floor_required_bps, proposed_distributions_cents, recompute_mdba,
    supersede_plan, bump_bank, PCA_ADEQUATE_CET1_BPS, IN_FLIGHT_PLAN_STATES,
)
from services.clockwork import activate_plan_if_due
from util import (
    get_body, req_int, apply_filters, sorted_page,
    require_occ_field, check_occ_matches,
)

bp = Blueprint("plans", __name__)


def _check_single_in_flight(bank: dict, exclude_id: str | None = None):
    for p in capital_plans.values():
        if (p["bank_id"] == bank["id"] and p["id"] != exclude_id
                and p["status"] in IN_FLIGHT_PLAN_STATES):
            raise_err(ERR_INVARIANT_VIOLATION,
                      "Bank already has a CapitalPlan in flight")


@bp.route("/banks/<bankId>/capital-plans", methods=["POST"])
@require_roles("CapitalAnalyst")
def create_plan(bankId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    body = get_body()
    plan_year = req_int(body, "plan_year")
    baseline_period_id = body.get("baseline_period_id")
    stress_scenario_id = body.get("stress_scenario_id")
    if not isinstance(baseline_period_id, str) or not baseline_period_id:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: baseline_period_id")
    if not isinstance(stress_scenario_id, str) or not stress_scenario_id:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: stress_scenario_id")
    # Cross-bank referential integrity (priority 4).
    period = reporting_periods.get(baseline_period_id)
    if period is None or period["bank_id"] != bank["id"]:
        raise_err(ERR_CROSS_BANK_REFERENCE, "baseline_period_id not owned by this bank")
    scenario = stress_scenarios.get(stress_scenario_id)
    if scenario is None or scenario["bank_id"] != bank["id"]:
        raise_err(ERR_CROSS_BANK_REFERENCE, "stress_scenario_id not owned by this bank")
    # Single in-flight plan invariant (priority 8).
    _check_single_in_flight(bank)

    plan = {
        "bank_id": bank["id"],
        "plan_year": plan_year,
        "baseline_period_id": baseline_period_id,
        "baseline_cet1_cents": None,
        "baseline_t1_cents": None,
        "baseline_total_capital_cents": None,
        "baseline_rwa_cents": None,
        "projected_cet1_bps_9q": None,
        "stressed_min_cet1_bps_9q": None,
        "stress_scenario_id": stress_scenario_id,
        "prepared_by_user_id": None,
        "status": "DRAFT",
    }
    stamp_new(plan)
    refresh_plan_baseline(plan, bank)
    capital_plans[plan["id"]] = plan
    return success_object(ser_plan(plan), 201)


@bp.route("/banks/<bankId>/capital-plans/<planId>", methods=["GET"])
@require_roles("Any")
def get_one_plan(bankId: str, planId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    return success_object(ser_plan(get_plan(bank, planId)))


@bp.route("/banks/<bankId>/capital-plans", methods=["GET"])
@require_roles("Any")
def list_plans(bankId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    items = [p for p in capital_plans.values() if p["bank_id"] == bank["id"]]
    items = apply_filters(items, {"status": "status", "plan_year": "plan_year"})
    page, limit, offset, total = sorted_page(items)
    return success_list([ser_plan(p) for p in page], limit, offset, total)


@bp.route("/banks/<bankId>/capital-plans/<planId>/submit_board", methods=["POST"])
@require_roles("CapitalAnalyst")
def submit_board(bankId: str, planId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    plan = get_plan(bank, planId)
    if plan["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a DRAFT plan can be submitted to the board")
    period = reporting_periods.get(plan["baseline_period_id"])
    if period is None or period["status"] not in ("ACCEPTED", "RE_ACCEPTED", "CLOSED"):
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Baseline ReportingPeriod must be ACCEPTED, RE_ACCEPTED, or CLOSED")
    scenario = stress_scenarios.get(plan["stress_scenario_id"])
    if scenario is None or scenario["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Referenced StressScenario must be ACTIVE")
    _check_single_in_flight(bank, exclude_id=plan["id"])
    refresh_plan_baseline(plan, bank)
    compute_plan_projections(plan, bank)
    plan["prepared_by_user_id"] = _user_id
    plan["status"] = "BOARD_REVIEW"
    touch(plan)
    return success_object(ser_plan(plan))


@bp.route("/banks/<bankId>/capital-plans/<planId>/board_approve", methods=["POST"])
@require_roles("BoardApprover")
def board_approve(bankId: str, planId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    plan = get_plan(bank, planId)
    if plan["status"] != "BOARD_REVIEW":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a BOARD_REVIEW plan can be board-approved")
    # Segregation of duties (priority 7).
    if plan.get("prepared_by_user_id") is not None and plan["prepared_by_user_id"] == _user_id:
        raise_err(ERR_SEGREGATION_OF_DUTIES_VIOLATION,
                  "BoardApprover must differ from the analyst who submitted the plan")
    # Capacity certification (priority 10).
    sub_debt_headroom = sum(
        s.get("t2_capacity_headroom_cents") or 0
        for s in sub_debt_issuances.values()
        if s["bank_id"] == bank["id"] and s["status"] == "APPROVED"
    )
    if proposed_distributions_cents(plan) > bank["mdba_cents"] + sub_debt_headroom:
        raise_err(ERR_PLAN_DISTRIBUTION_EXCEEDS_CAPACITY,
                  "Plan's proposed distributions exceed mdba_cents plus approved sub-debt headroom")
    plan["status"] = "SUBMITTED"
    touch(plan)
    return success_object(ser_plan(plan))


@bp.route("/banks/<bankId>/capital-plans/<planId>/submit_regulator", methods=["POST"])
@require_roles("CapitalAnalyst")
def submit_regulator(bankId: str, planId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    plan = get_plan(bank, planId)
    # Envelope-level: expected_bank_version presence/type (PRD 2.8 requires it).
    body = get_body()
    expected = require_occ_field(body)
    if plan["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Only a SUBMITTED plan can be filed with the regulator")
    for d in distribution_requests.values():
        if (d["capital_plan_id"] == plan["id"]
                and d["status"] not in ("PROPOSED", "APPROVED_NOT_EXECUTED")):
            raise_err(ERR_INVALID_STATE_TRANSITION,
                      "All attached distribution requests must be PROPOSED or APPROVED_NOT_EXECUTED")
    # OCC (priority 19).
    check_occ_matches(expected, bank)
    plan["status"] = "SUPERVISORY_REVIEW"
    touch(plan)
    bump_bank(bank)
    return success_object(ser_plan(plan))


@bp.route("/banks/<bankId>/capital-plans/<planId>/regulator_approve", methods=["POST"])
@require_roles("RegulatorReviewer")
def regulator_approve(bankId: str, planId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    plan = get_plan(bank, planId)
    if plan["status"] != "SUPERVISORY_REVIEW":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Only a SUPERVISORY_REVIEW plan can be regulator-approved")
    # Stress floor (priority 14).
    stressed_min = plan.get("stressed_min_cet1_bps_9q")
    floor_required = stress_floor_required_bps(plan)
    if stressed_min is None or stressed_min < floor_required:
        raise_err(ERR_PLAN_FAILED_STRESS_FLOOR,
                  "stressed_min_cet1_bps_9q below the applicable stress floor")
    bank["stressed_capital_buffer_bps"] = max(PCA_ADEQUATE_CET1_BPS, stressed_min) - PCA_ADEQUATE_CET1_BPS
    plan["status"] = "APPROVED"
    touch(plan)
    # A newer plan reaching APPROVED supersedes any older APPROVED plan.
    for other in list(capital_plans.values()):
        if (other["bank_id"] == bank["id"] and other["id"] != plan["id"]
                and other["status"] == "APPROVED"):
            supersede_plan(other, bank)
    # If the plan year has already begun, activate immediately.
    activate_plan_if_due(bank, plan)
    recompute_mdba(bank)
    bump_bank(bank)
    return success_object(ser_plan(plan))


@bp.route("/banks/<bankId>/capital-plans/<planId>/regulator_object", methods=["POST"])
@require_roles("RegulatorReviewer")
def regulator_object(bankId: str, planId: str, _user_id: str, _role: str):
    from services.core import release_distribution_reservation
    bank = get_bank(bankId)
    plan = get_plan(bank, planId)
    if plan["status"] != "SUPERVISORY_REVIEW":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Only a SUPERVISORY_REVIEW plan can be objected to")
    plan["status"] = "OBJECTED"
    touch(plan)
    bank["supervisory_status"] = "UNDER_MOU"
    for d in distribution_requests.values():
        if d["capital_plan_id"] == plan["id"] and d["status"] in ("PROPOSED", "APPROVED_NOT_EXECUTED"):
            if d["status"] == "APPROVED_NOT_EXECUTED":
                release_distribution_reservation(d, bank)
            d["status"] = "REJECTED"
            touch(d)
    recompute_mdba(bank)
    bump_bank(bank)
    return success_object(ser_plan(plan))


@bp.route("/banks/<bankId>/capital-plans/<planId>/amend", methods=["POST"])
@require_roles("CapitalAnalyst")
def amend_plan(bankId: str, planId: str, _user_id: str, _role: str):
    bank = get_bank(bankId)
    plan = get_plan(bank, planId)
    if plan["status"] != "OBJECTED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only an OBJECTED plan can be amended")
    plan["status"] = "DRAFT"
    touch(plan)  # increments CapitalPlan.version by 1
    return success_object(ser_plan(plan))
