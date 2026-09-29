"""Multi-hop cascades: the freeze chain that runs forward out of a closing pass, and
the roster removal that runs backward through a scheduled visit."""

from __future__ import annotations

from test_helpers import fixtures as fx
from test_helpers.assertions import assert_pct
from test_helpers.test_users import OFFICER_ONE_ID
from test_helpers.types import (
    AssignmentStatus,
    CampType,
    Certification,
    CompliancePosture,
    CycleStatus,
    DeficiencySeverity,
    HealthIntakeStatus,
    HealthStaffingLevel,
    PlanType,
    PopulationServed,
    RiskIndexVariant,
    ScoreSource,
    SelfScore,
    SelfStatus,
    StandardDomain,
    TeamRole,
    VisitStatus,
    VisitStatusAxis,
    VisitorScore,
    VisitorStatus,
    WrittenPlanStatus,
)

COVE_STANDARDS = [
    fx.universal_mandatory_standard(
        "HW.7",
        domain=StandardDomain.HEALTH_WELLNESS,
        written_plan_type_required=PlanType.HEALTH_CARE,
    ),
    fx.universal_mandatory_standard("ER.4", domain=StandardDomain.EMERGENCY_RESPONSE),
    fx.universal_mandatory_standard("SU.1", domain=StandardDomain.SUPERVISION),
]

COVE_CAMP = {
    "name": "Cove Day Camp",
    "camp_type": CampType.DAY,
    "state_code": "OH",
    "population_served": PopulationServed.YOUTH_ONLY,
    "program_elements": [],
    "resident_census": 0,
    "distance_to_hospital_km": 0,
    "max_daily_census": 60,
    "health_staffing_level": HealthStaffingLevel.FIRST_AIDER_ONLY,
    "prior_accredited_cycle_count": 0,
}

# The lead carries the health endorsement so the HEALTH_WELLNESS row is scorable.
COVE_TEAM = [
    {
        "key": "lead",
        "full_name": "Lead One",
        "home_state_code": "PA",
        "certifications": [Certification.LEAD_VISITOR, Certification.HEALTH_SPECIALIST],
        "team_role": TeamRole.LEAD,
    },
    {
        "key": "member",
        "full_name": "Member Two",
        "home_state_code": "NY",
        "certifications": [],
        "team_role": TeamRole.MEMBER,
    },
]

GULL_STANDARDS = [
    fx.universal_mandatory_standard("SU.1", domain=StandardDomain.SUPERVISION),
    fx.universal_optional_standard("OM.9", domain=StandardDomain.OPERATIONS),
]

GULL_CAMP = {
    "name": "Gull Day Camp",
    "camp_type": CampType.DAY,
    "state_code": "OH",
    "population_served": PopulationServed.YOUTH_ONLY,
    "program_elements": [],
    "resident_census": 0,
    "distance_to_hospital_km": 0,
    "max_daily_census": 50,
    "health_staffing_level": HealthStaffingLevel.FIRST_AIDER_ONLY,
    "prior_accredited_cycle_count": 0,
}


def _cove_scored_and_frozen(api):
    """Cove's closing pass raises two critical findings, so the freeze cascade runs.

    Returns the scenario together with the id of the verified health care plan the
    HEALTH_WELLNESS row cites.
    """
    scenario = fx.open_cycle_scenario(
        api,
        edition_code="ACA-2026-C",
        standards=COVE_STANDARDS,
        camp=COVE_CAMP,
    )
    plan = fx.file_plan(
        api,
        scenario.camp_id,
        PlanType.HEALTH_CARE,
        body_ref="HC-PLAN-2026-REV3",
        effective_date="2026-06-01",
        expires_at="2027-06-01",
        physician_reviewed=True,
    )
    fx.verify_plan(api, plan["id"], "physician signature on file")

    fx.record_self_score(
        api,
        scenario.evaluation_id("HW.7"),
        scenario.camp_id,
        SelfScore.MET,
        written_plan_id=plan["id"],
        note="health care plan cited",
    )
    for code in ("ER.4", "SU.1"):
        fx.record_self_score(api, scenario.evaluation_id(code), scenario.camp_id, SelfScore.MET)
    fx.submit_self_assessment(api, scenario.cycle_id, scenario.camp_id)

    fx.seat_team(api, scenario, team=COVE_TEAM, confirm=True)
    fx.score_visit(
        api,
        scenario,
        visitor_scores={
            "HW.7": (VisitorScore.NOT_MET, ScoreSource.OBSERVED),
            "ER.4": (VisitorScore.NOT_MET, ScoreSource.OBSERVED),
            "SU.1": (VisitorScore.MET, ScoreSource.OBSERVED),
        },
    )
    return scenario, plan["id"]


def _gull_visit_scheduled(api):
    """Gull's self-assessment is closed and its two-visitor visit is confirmed."""
    scenario = fx.open_cycle_scenario(
        api,
        edition_code="ACA-2026-G",
        standards=GULL_STANDARDS,
        camp=GULL_CAMP,
        self_scores={"SU.1": SelfScore.MET, "OM.9": SelfScore.MET},
        submit=True,
    )
    return fx.seat_team(api, scenario, confirm=True)


def test_closing_pass_freezes_the_camp_and_revalidates_its_verified_plan(api):
    """PRD §3.6: "One deficiency is raised for each applicable evaluation whose
    `visitor_score` is `NOT_MET`, the camp's `penalty_point_balance` is recomputed and
    then its posture, and if the posture lands on `FROZEN` the cascade of §2.8 runs —
    `health_intake_status` to `SUSPENDED`, `VERIFIED` plans to `REVALIDATION_REQUIRED`,
    and their citing evaluations with `self_status` `VERIFIED` knocked to `REJECTED`.
    Finally the camp's risk index is recomputed, now under the post-visit variant."

    Design: Difficulty/transitive_cascade/finalize_scoring_cascade_freezes_camp_and_rejects_verified_self_assessment
    """
    scenario, plan_id = _cove_scored_and_frozen(api)

    assert fx.read_visit(api, scenario.visit_id)["status"] == VisitStatus.SCORED
    assert fx.read_cycle(api, scenario.cycle_id)["status"] == CycleStatus.VISIT_COMPLETED

    findings, meta = fx.list_deficiencies_for_visit(api, scenario.visit_id)
    assert meta["total_count"] == 2
    for finding in findings:
        assert finding["severity"] == DeficiencySeverity.MANDATORY_CRITICAL
        assert finding["penalty_points"] == 10

    camp = fx.read_camp(api, scenario.camp_id)
    assert camp["penalty_point_balance"] == 20
    assert camp["compliance_posture"] == CompliancePosture.FROZEN
    assert camp["health_intake_status"] == HealthIntakeStatus.SUSPENDED

    assert fx.read_plan(api, plan_id)["status"] == WrittenPlanStatus.REVALIDATION_REQUIRED

    components = fx.read_risk_index(api, scenario.camp_id)
    assert components["risk_index_variant"] == RiskIndexVariant.POST_VISIT
    assert_pct(components["compliance_component"], 20.00)
    assert components["license_penalty"] == 6
    assert components["staffing_gap_penalty"] == 0
    assert_pct(components["risk_index"], 36.00)


def test_freeze_knocks_back_only_the_plan_citing_evaluation_row(api):
    """PRD §2.8: "For each plan so moved, every standard evaluation whose
    `written_plan_id` names that plan and whose `self_status` is `VERIFIED` is knocked
    back to `self_status` `REJECTED`. The cycle's `self_assessment_submitted_at` is
    deliberately left untouched by this knock-back."

    Design: Difficulty/transitive_cascade/finalize_scoring_cascade_freezes_camp_and_rejects_verified_self_assessment
    """
    scenario, plan_id = _cove_scored_and_frozen(api)

    citing_row = fx.read_evaluation(api, scenario.evaluation_id("HW.7"))
    assert citing_row["self_status"] == SelfStatus.REJECTED
    assert citing_row["visit_status"] == VisitStatusAxis.LOCKED
    assert citing_row["self_score"] == SelfScore.MET
    assert citing_row["written_plan_id"] == plan_id

    for code in ("ER.4", "SU.1"):
        untouched = fx.read_evaluation(api, scenario.evaluation_id(code))
        assert untouched["self_status"] == SelfStatus.VERIFIED
        assert untouched["written_plan_id"] is None

    assert fx.read_cycle(api, scenario.cycle_id)["self_assessment_submitted_at"] is not None


def test_completed_seats_leave_the_visitors_travel_commitment_untouched(api):
    """PRD §2.8: "A visitor's `committed_travel_days` is always the sum of `travel_days`
    over that visitor's team seats whose `status` is `ASSIGNED` or `COMPLETED`;
    consequently an assign-then-withdraw pair returns the visitor to exactly the value
    held before the assignment, while a seat moving from `ASSIGNED` to `COMPLETED` at
    scoring finalisation leaves the quantity deliberately unchanged because `COMPLETED`
    remains inside the counted set."

    Design: Difficulty/transitive_cascade/finalize_scoring_cascade_freezes_camp_and_rejects_verified_self_assessment
    """
    scenario, _plan_id = _cove_scored_and_frozen(api)

    for key in ("lead", "member"):
        seat = fx.read_assignment(api, scenario.assignment_id(key))
        assert seat["status"] == AssignmentStatus.COMPLETED
        assert seat["travel_days"] == 3
        assert fx.read_visitor(api, scenario.visitor_id(key))["committed_travel_days"] == 3


def test_deactivating_the_lead_withdraws_the_seat_and_clears_the_lead_slot(api):
    """PRD §3.5: "The removal cascades: every seat of that visitor whose `status` is
    `ASSIGNED` moves `ASSIGNED → WITHDRAWN`, each withdrawal decrements the visitor's
    `committed_travel_days` by that seat's `travel_days`, each withdrawal decrements its
    visit's `team_size` by one, and a withdrawn `LEAD` seat clears that visit's
    `lead_visitor_id` to null."

    Design: Difficulty/transitive_cascade/visitor_deactivation_cascade_reverts_visit_and_cycle
    """
    scenario = _gull_visit_scheduled(api)
    lead_id = scenario.visitor_id("lead")

    before = fx.read_visit(api, scenario.visit_id)
    assert before["status"] == VisitStatus.SCHEDULED
    assert before["lead_visitor_id"] == lead_id
    assert before["team_size"] == 2
    assert fx.read_visitor(api, lead_id)["committed_travel_days"] == 3

    deactivated = fx.deactivate_visitor(api, lead_id, "training lapse discovered")
    assert deactivated["status"] == VisitorStatus.INACTIVE

    seat = fx.read_assignment(api, scenario.assignment_id("lead"))
    assert seat["status"] == AssignmentStatus.WITHDRAWN
    assert fx.read_visitor(api, lead_id)["committed_travel_days"] == 0

    after = fx.read_visit(api, scenario.visit_id)
    assert after["lead_visitor_id"] is None
    assert after["team_size"] == 1

    member_seat = fx.read_assignment(api, scenario.assignment_id("member"))
    assert member_seat["status"] == AssignmentStatus.ASSIGNED
    assert fx.read_visitor(api, scenario.visitor_id("member"))["committed_travel_days"] == 3


def test_broken_team_completeness_reverts_the_visit_and_reopens_the_cycle(api):
    """PRD §3.5: "Where such a withdrawal breaks team completeness on a visit that was
    `SCHEDULED`, the visit reverts `SCHEDULED → DRAFT` with its `scheduled_by_user_id`
    cleared to null, and that reversion in turn drives the owning cycle
    `VISIT_SCHEDULED → SELF_ASSESSMENT`."

    Design: Difficulty/transitive_cascade/visitor_deactivation_cascade_reverts_visit_and_cycle
    """
    scenario = _gull_visit_scheduled(api)

    before_visit = fx.read_visit(api, scenario.visit_id)
    assert before_visit["scheduled_by_user_id"] == OFFICER_ONE_ID
    before_cycle = fx.read_cycle(api, scenario.cycle_id)
    assert before_cycle["status"] == CycleStatus.VISIT_SCHEDULED
    submitted_at = before_cycle["self_assessment_submitted_at"]

    fx.deactivate_visitor(api, scenario.visitor_id("lead"), "training lapse discovered")

    visit = fx.read_visit(api, scenario.visit_id)
    assert visit["status"] == VisitStatus.DRAFT
    assert visit["scheduled_by_user_id"] is None

    cycle = fx.read_cycle(api, scenario.cycle_id)
    assert cycle["status"] == CycleStatus.SELF_ASSESSMENT
    assert cycle["self_assessment_submitted_at"] == submitted_at

    for code in ("SU.1", "OM.9"):
        row = fx.read_evaluation(api, scenario.evaluation_id(code))
        assert row["self_status"] == SelfStatus.VERIFIED
        assert row["visit_status"] == VisitStatusAxis.UNSCORED
