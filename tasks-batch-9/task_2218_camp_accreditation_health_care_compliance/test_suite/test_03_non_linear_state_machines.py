"""Non-linear lifecycles: the correction revision loop and the two parallel status
dimensions of one standard evaluation row."""

from __future__ import annotations

from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_pct
from test_helpers.factories import self_assessment_payload
from test_helpers.test_users import make_camp_director_headers
from test_helpers.types import (
    AccreditationStatus,
    CampType,
    CompliancePosture,
    CycleStatus,
    DecisionLevel,
    DeficiencyDecision,
    DeficiencySeverity,
    DeficiencyStatus,
    HealthStaffingLevel,
    PopulationServed,
    ScoreSource,
    SelfScore,
    SelfStatus,
    StandardDomain,
    VisitStatus,
    VisitStatusAxis,
    VisitorScore,
)
from prd_bench_local_runner.testing import validate_error

GROVE_STANDARDS = [
    fx.universal_mandatory_standard("SU.1", domain=StandardDomain.SUPERVISION),
    fx.universal_optional_standard("OM.9", domain=StandardDomain.OPERATIONS),
]


def _day_camp(name: str, max_daily_census: int) -> dict:
    return {
        "name": name,
        "camp_type": CampType.DAY,
        "state_code": "OH",
        "population_served": PopulationServed.YOUTH_ONLY,
        "program_elements": [],
        "resident_census": 0,
        "distance_to_hospital_km": 0,
        "max_daily_census": max_daily_census,
        "health_staffing_level": HealthStaffingLevel.FIRST_AIDER_ONLY,
        "prior_accredited_cycle_count": 0,
    }


def _grove_in_correction(api):
    """One SCORED finding on a cycle sitting in IN_CORRECTION."""
    scenario = fx.open_cycle_scenario(
        api,
        edition_code="ACA-2026-G",
        standards=GROVE_STANDARDS,
        camp=_day_camp("Grove Day Camp", 60),
        self_scores={"SU.1": SelfScore.MET, "OM.9": SelfScore.MET},
        submit=True,
    )
    fx.seat_team(api, scenario, confirm=True)
    fx.score_visit(
        api,
        scenario,
        visitor_scores={
            "SU.1": (VisitorScore.MET, ScoreSource.OBSERVED),
            "OM.9": (VisitorScore.NOT_MET, ScoreSource.OBSERVED),
        },
    )
    fx.decide_cycle(api, scenario)
    return scenario, scenario.deficiencies[0]["id"]


def _glade_self_assessment_submitted(api):
    """Both rows self-scored MET and the self-assessment closed."""
    return fx.open_cycle_scenario(
        api,
        edition_code="ACA-2026-G",
        standards=GROVE_STANDARDS,
        camp=_day_camp("Glade Day Camp", 55),
        self_scores={"SU.1": SelfScore.MET, "OM.9": SelfScore.MET},
        submit=True,
    )


def test_rejecting_a_plan_below_the_revision_limit_returns_the_finding_to_open(api):
    """PRD §3.8: "While `plan_revision_count` is below 3 it moves the finding
    `PLAN_SUBMITTED → OPEN`, stamps `reviewer_user_id` with the acting `X-User-ID`, and
    leaves the balance unchanged because both states are inside the counted set; the
    camp may then file again."

    Design: Difficulty/non_linear_state_machine/deficiency_plan_revision_cycle_returns_to_open_then_escalates_on_third_rejection
    """
    scenario, deficiency_id = _grove_in_correction(api)

    cycle = fx.read_cycle(api, scenario.cycle_id)
    assert cycle["decision_level"] == DecisionLevel.ACCREDITED_WITH_CORRECTION
    assert cycle["status"] == CycleStatus.IN_CORRECTION

    finding = fx.read_deficiency(api, deficiency_id)
    assert finding["severity"] == DeficiencySeverity.SCORED
    assert finding["base_points"] == 2
    assert finding["penalty_points"] == 2
    assert finding["correction_due_date"] == "2026-12-01"

    filed = fx.file_correction_plan(
        api, scenario.camp_id, deficiency_id, "First revision - retrain operations staff"
    )
    assert filed["status"] == DeficiencyStatus.PLAN_SUBMITTED
    assert filed["plan_revision_count"] == 1

    rejected = fx.review_deficiency(
        api, deficiency_id, DeficiencyDecision.REJECT_PLAN, "no evidence attached"
    )
    assert rejected["status"] == DeficiencyStatus.OPEN
    assert rejected["plan_revision_count"] == 1

    refiled = fx.file_correction_plan(
        api, scenario.camp_id, deficiency_id, "Second revision - add records audit"
    )
    assert refiled["plan_revision_count"] == 2
    rejected_again = fx.review_deficiency(
        api, deficiency_id, DeficiencyDecision.REJECT_PLAN, "audit scope too narrow"
    )
    assert rejected_again["status"] == DeficiencyStatus.OPEN
    assert fx.read_camp(api, scenario.camp_id)["penalty_point_balance"] == 2


def test_third_rejection_escalates_the_finding_and_terminates_the_cycle(api):
    """PRD §3.8: "When `plan_revision_count` has reached 3, the same rejection instead
    moves the finding `PLAN_SUBMITTED → ESCALATED`, drives the cycle
    `IN_CORRECTION → TERMINATED`, sets the camp's `accreditation_status` to `REVOKED`,
    and recomputes the camp's `penalty_point_balance` and then its posture, which the
    escalated-finding clause holds at `FROZEN`."

    Design: Difficulty/non_linear_state_machine/deficiency_plan_revision_cycle_returns_to_open_then_escalates_on_third_rejection
    """
    scenario, deficiency_id = _grove_in_correction(api)

    for revision, note in (
        ("First revision - retrain operations staff", "no evidence attached"),
        ("Second revision - add records audit", "audit scope too narrow"),
    ):
        fx.file_correction_plan(api, scenario.camp_id, deficiency_id, revision)
        fx.review_deficiency(api, deficiency_id, DeficiencyDecision.REJECT_PLAN, note)

    third = fx.file_correction_plan(
        api, scenario.camp_id, deficiency_id, "Third revision - full records rebuild"
    )
    assert third["plan_revision_count"] == 3
    assert third["status"] == DeficiencyStatus.PLAN_SUBMITTED

    escalated = fx.review_deficiency(
        api, deficiency_id, DeficiencyDecision.REJECT_PLAN, "third rejection"
    )
    assert escalated["status"] == DeficiencyStatus.ESCALATED

    assert fx.read_cycle(api, scenario.cycle_id)["status"] == CycleStatus.TERMINATED
    camp = fx.read_camp(api, scenario.camp_id)
    assert camp["penalty_point_balance"] == 2
    assert camp["compliance_posture"] == CompliancePosture.FROZEN
    assert camp["accreditation_status"] == AccreditationStatus.REVOKED


def test_self_status_dimension_walks_to_verified_and_then_refuses_further_self_writes(api):
    """PRD §3.4: "Each evaluation row carries two status dimensions that evolve
    entirely independently: `self_status`, which moves on camp-side and plan-side
    events, and `visit_status`, which moves only on visitor events."

    Design: Difficulty/non_linear_state_machine/standard_evaluation_parallel_dimensions_evolve_independently
    """
    edition, standards = fx.publish_edition_with_standards(
        api, "ACA-2026-G", GROVE_STANDARDS
    )
    camp = fx.register_camp(api, **_day_camp("Glade Day Camp", 55))
    cycle = fx.open_cycle(api, camp["id"], edition["id"], 2026, camp["version"])
    evaluations = fx.evaluations_by_code(api, cycle["id"], camp["id"], standards)

    assert evaluations["SU.1"]["self_status"] == SelfStatus.DRAFT
    assert evaluations["SU.1"]["visit_status"] == VisitStatusAxis.UNSCORED

    submitted = fx.record_self_score(
        api, evaluations["SU.1"]["id"], camp["id"], SelfScore.MET, note="ratios documented"
    )
    assert submitted["self_status"] == SelfStatus.SUBMITTED
    assert submitted["visit_status"] == VisitStatusAxis.UNSCORED

    fx.record_self_score(api, evaluations["OM.9"]["id"], camp["id"], SelfScore.MET)
    fx.submit_self_assessment(api, cycle["id"], camp["id"])
    for code in ("SU.1", "OM.9"):
        row = fx.read_evaluation(api, evaluations[code]["id"])
        assert row["self_status"] == SelfStatus.VERIFIED
        assert row["visit_status"] == VisitStatusAxis.UNSCORED

    locked = api.patch_self_assessment(
        evaluations["SU.1"]["id"],
        self_assessment_payload(SelfScore.PARTIAL),
        make_camp_director_headers(camp["id"]),
    )
    validate_error(locked, ApiErrorId.EVALUATION_LOCKED, 409)

    unchanged = fx.read_evaluation(api, evaluations["SU.1"]["id"])
    assert unchanged["self_score"] == SelfScore.MET
    assert unchanged["visit_status"] == VisitStatusAxis.UNSCORED


def test_visit_status_dimension_rescores_then_locks_while_self_status_stays_verified(api):
    """PRD §3.6: "Every applicable evaluation's `visit_status` becomes `LOCKED` — rows
    already `SCORED` move `SCORED → LOCKED`, and a non-mandatory applicable row left
    unscored moves `UNSCORED → LOCKED` with its `visitor_score` still null."

    Design: Difficulty/non_linear_state_machine/standard_evaluation_parallel_dimensions_evolve_independently
    """
    scenario = _glade_self_assessment_submitted(api)
    fx.seat_team(api, scenario, confirm=True)
    fx.set_clock(api, fx.IN_WINDOW_CLOCK)
    lead_id = scenario.visitor_id("lead")
    fx.open_scoring(api, scenario.visit_id, lead_id)

    first = fx.record_visitor_score(
        api,
        scenario.evaluation_id("SU.1"),
        lead_id,
        VisitorScore.NOT_MET,
        ScoreSource.INTERVIEW,
    )
    assert first["visit_status"] == VisitStatusAxis.SCORED
    assert first["self_status"] == SelfStatus.VERIFIED

    second = fx.record_visitor_score(
        api,
        scenario.evaluation_id("SU.1"),
        lead_id,
        VisitorScore.MET,
        ScoreSource.OBSERVED,
        note="re-scored after walkthrough",
    )
    assert second["visit_status"] == VisitStatusAxis.SCORED
    assert second["visitor_score"] == VisitorScore.MET
    assert second["score_source"] == ScoreSource.OBSERVED
    assert second["self_status"] == SelfStatus.VERIFIED

    fx.close_scoring(api, scenario.visit_id, lead_id)

    mandatory_row = fx.read_evaluation(api, scenario.evaluation_id("SU.1"))
    assert mandatory_row["visit_status"] == VisitStatusAxis.LOCKED
    assert mandatory_row["self_status"] == SelfStatus.VERIFIED

    optional_row = fx.read_evaluation(api, scenario.evaluation_id("OM.9"))
    assert optional_row["visit_status"] == VisitStatusAxis.LOCKED
    assert optional_row["visitor_score"] is None
    assert optional_row["self_status"] == SelfStatus.VERIFIED

    assert fx.read_visit(api, scenario.visit_id)["status"] == VisitStatus.SCORED
    assert fx.read_cycle(api, scenario.cycle_id)["status"] == CycleStatus.VISIT_COMPLETED
    assert_pct(fx.read_visit(api, scenario.visit_id)["provisional_mandatory_pct"], 100.00)
