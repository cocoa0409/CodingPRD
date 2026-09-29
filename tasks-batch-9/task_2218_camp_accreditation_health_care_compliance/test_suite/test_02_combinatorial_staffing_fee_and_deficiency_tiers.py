"""Multi-input formulas: the staffing bump, the per-line fee rounding and the
deficiency escalation tier."""

from __future__ import annotations

from test_helpers import fixtures as fx
from test_helpers.assertions import assert_pct, find_by
from test_helpers.types import (
    AccreditationStatus,
    CampType,
    Certification,
    CompliancePosture,
    CycleStatus,
    DecisionLevel,
    DeficiencySeverity,
    DeficiencyStatus,
    HealthIntakeStatus,
    HealthStaffingLevel,
    PlanType,
    PopulationServed,
    ScoreSource,
    SelfScore,
    StandardDomain,
    TeamRole,
    VisitorScore,
)

FAMILY_CAMP = {
    "camp_type": CampType.FAMILY,
    "state_code": "OH",
    "population_served": PopulationServed.ADULT_INCLUSIVE,
    "program_elements": [],
    "distance_to_hospital_km": 10,
    "max_daily_census": 90,
    "health_staffing_level": HealthStaffingLevel.FIRST_AIDER_ONLY,
    "prior_accredited_cycle_count": 0,
}

FERN_STANDARDS = [
    fx.universal_optional_standard("PA.9", domain=StandardDomain.AQUATICS),
    fx.universal_optional_standard("PD.9", domain=StandardDomain.ADVENTURE),
    fx.universal_optional_standard("TR.9", domain=StandardDomain.TRANSPORTATION),
    fx.universal_optional_standard("HW.9", domain=StandardDomain.HEALTH_WELLNESS),
    fx.universal_mandatory_standard("SU.9", domain=StandardDomain.SUPERVISION),
]

FERN_CAMP = {
    "name": "Fern Day Camp",
    "camp_type": CampType.DAY,
    "state_code": "OH",
    "population_served": PopulationServed.YOUTH_ONLY,
    "program_elements": [],
    "resident_census": 0,
    "distance_to_hospital_km": 0,
    "max_daily_census": 70,
    "health_staffing_level": HealthStaffingLevel.FIRST_AIDER_ONLY,
    "prior_accredited_cycle_count": 1,
}

CEDAR_STANDARDS = [
    fx.universal_mandatory_standard(
        "HW.7",
        domain=StandardDomain.HEALTH_WELLNESS,
        written_plan_type_required=PlanType.HEALTH_CARE,
    ),
    fx.universal_mandatory_standard("ER.4", domain=StandardDomain.EMERGENCY_RESPONSE),
    fx.universal_mandatory_standard("SU.1", domain=StandardDomain.SUPERVISION),
]

CEDAR_CAMP = {
    "name": "Cedar Day Camp",
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

# The lead also carries the health endorsement so the HEALTH_WELLNESS row is scorable.
CEDAR_TEAM = [
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


def _two_family_camps(api):
    bump = fx.register_camp(api, name="Bump Family Camp", resident_census=60, **FAMILY_CAMP)
    nobump = fx.register_camp(api, name="Nobump Family Camp", resident_census=30, **FAMILY_CAMP)
    return bump, nobump


def _fern_cycle_decided(api):
    scenario = fx.open_cycle_scenario(
        api,
        edition_code="ACA-2026-F",
        standards=FERN_STANDARDS,
        camp=FERN_CAMP,
        self_scores={code: SelfScore.MET for code in ("PA.9", "PD.9", "TR.9", "HW.9", "SU.9")},
        submit=True,
    )
    fx.seat_team(api, scenario, confirm=True)
    fx.score_visit(
        api,
        scenario,
        visitor_scores={"SU.9": (VisitorScore.MET, ScoreSource.OBSERVED)},
    )
    return fx.decide_cycle(api, scenario)


def _cedar_visit_finalized(api):
    scenario = fx.open_cycle_scenario(
        api,
        edition_code="ACA-2026-C",
        standards=CEDAR_STANDARDS,
        camp=CEDAR_CAMP,
        self_scores={code: SelfScore.PARTIAL for code in ("HW.7", "ER.4", "SU.1")},
        submit=True,
    )
    fx.seat_team(api, scenario, team=CEDAR_TEAM, confirm=True)
    return fx.score_visit(
        api,
        scenario,
        visitor_scores={
            "HW.7": (VisitorScore.NOT_MET, ScoreSource.OBSERVED),
            "ER.4": (VisitorScore.NOT_MET, ScoreSource.OBSERVED),
            "SU.1": (VisitorScore.MET, ScoreSource.OBSERVED),
        },
    )


def test_required_staffing_bump_fires_only_when_three_components_reach_rank_two(api):
    """PRD §3.1: "The required rank is then the largest of those five components, plus
    one further step when at least three of the five components are themselves 2 or
    greater, with the total capped at 4."

    Design: Difficulty/combinatorial_formula/required_health_staffing_level_combination_bump_promotes_family_camp
    """
    bump, nobump = _two_family_camps(api)

    assert (
        fx.read_camp(api, bump["id"])["required_health_staffing_level"]
        == HealthStaffingLevel.RN_ONSITE
    )
    assert (
        fx.read_camp(api, nobump["id"])["required_health_staffing_level"]
        == HealthStaffingLevel.LPN_ONSITE
    )
    assert fx.read_camp(api, bump["id"])["compliance_posture"] == CompliancePosture.RESTRICTED


def test_health_centre_census_revision_recomputes_the_required_staffing_level(api):
    """PRD §3.1: "Any such write recomputes `required_health_staffing_level`, then the
    controlled-substance balance, then the compliance posture, then the risk index,
    and increments the camp's `version` by one."

    Design: Difficulty/combinatorial_formula/required_health_staffing_level_combination_bump_promotes_family_camp
    """
    _bump, nobump = _two_family_camps(api)
    assert (
        fx.read_camp(api, nobump["id"])["required_health_staffing_level"]
        == HealthStaffingLevel.LPN_ONSITE
    )

    revised = fx.revise_health_center(api, nobump["id"], resident_census=130)
    assert revised["required_health_staffing_level"] == HealthStaffingLevel.PHYSICIAN_ONSITE
    assert revised["compliance_posture"] == CompliancePosture.RESTRICTED
    assert revised["version"] == nobump["version"] + 1


def test_fee_rounds_each_line_item_to_whole_cents_before_summing(api):
    """PRD §3.7: "each line item is rounded to whole cents half up first, and only then
    are the four line items added together."

    Design: Difficulty/combinatorial_formula/accreditation_fee_assessment_per_line_rounding_beats_sum_then_round
    """
    scenario = _fern_cycle_decided(api)

    cycle = fx.read_cycle(api, scenario.cycle_id)
    assert cycle["assessed_fee_cents"] == 263389
    assert cycle["assessed_fee_cents"] != 263388
    # 95000 undiscounted + 1663 per-standard + 64126 domain lines + 102600 travel.
    assert cycle["assessed_fee_cents"] == 95000 + 1663 + (17219 + 21019 + 11519 + 14369) + 102600


def test_fee_reads_applicable_standards_and_the_teams_travel_days(api):
    """PRD §3.7: "Then the team travel days are totalled as the sum of `travel_days`
    over the seats of the cycle's non-rescinded visit whose `status` is `ASSIGNED` or
    `COMPLETED`, and the domains present are collected as the distinct set of pinned
    standard `domain` values over the cycle's applicable evaluations."

    Design: Difficulty/combinatorial_formula/accreditation_fee_assessment_per_line_rounding_beats_sum_then_round
    """
    scenario = _fern_cycle_decided(api)

    for key in ("lead", "member"):
        assert fx.read_assignment(api, scenario.assignment_id(key))["travel_days"] == 3

    cycle = fx.read_cycle(api, scenario.cycle_id)
    assert cycle["applicable_standard_count"] == 5
    assert_pct(cycle["final_mandatory_pct"], 100.00)
    assert_pct(cycle["final_weighted_pct"], 20.00)
    assert cycle["decision_level"] == DecisionLevel.ACCREDITED_WITH_CORRECTION
    assert cycle["status"] == CycleStatus.CLOSED
    assert (
        fx.read_camp(api, scenario.camp_id)["accreditation_status"]
        == AccreditationStatus.ACCREDITED_WITH_CORRECTION
    )


def test_escalation_tier_is_chosen_from_the_batch_base_total(api):
    """PRD §3.6: "The escalation tier is then chosen once, from the **base** total of
    this closing pass only, before any `penalty_points` is written; keying the tier on
    the post-surcharge total would be circular and is not the rule."

    Design: Difficulty/combinatorial_formula/deficiency_penalty_and_deadline_tier_from_base_total_not_post_surcharge
    """
    scenario = _cedar_visit_finalized(api)

    rows, meta = fx.list_deficiencies_for_visit(api, scenario.visit_id)
    assert meta["total_count"] == 2

    for code in ("HW.7", "ER.4"):
        finding = find_by(rows, standard_id=scenario.standards[code]["id"])
        assert finding is not None
        assert finding["severity"] == DeficiencySeverity.MANDATORY_CRITICAL
        assert finding["base_points"] == 8
        assert finding["penalty_points"] == 10
        assert finding["penalty_points"] != 13
        assert finding["status"] == DeficiencyStatus.OPEN


def test_correction_window_is_the_tier_window_from_the_logical_clock_date(api):
    """PRD §3.6: "The same tier fixes the correction window: each finding's
    `correction_due_date` is the logical clock's calendar date advanced by 90 days at
    tier 0, 60 days at tier 1 and 30 days at tier 2."

    Design: Difficulty/combinatorial_formula/deficiency_penalty_and_deadline_tier_from_base_total_not_post_surcharge
    """
    scenario = _cedar_visit_finalized(api)

    rows, _ = fx.list_deficiencies_for_visit(api, scenario.visit_id)
    for finding in rows:
        assert finding["correction_due_date"] == "2026-11-01"
        assert finding["correction_due_date"] != "2026-10-02"


def test_finalized_batch_freezes_the_camp_and_writes_the_provisional_percentage(api):
    """PRD §3.6: "Once the batch is written, the camp's `penalty_point_balance` is
    recomputed as the sum of `penalty_points` over every deficiency of the camp whose
    status is `OPEN`, `PLAN_SUBMITTED` or `ESCALATED`."

    Design: Difficulty/combinatorial_formula/deficiency_penalty_and_deadline_tier_from_base_total_not_post_surcharge
    """
    scenario = _cedar_visit_finalized(api)

    camp = fx.read_camp(api, scenario.camp_id)
    assert camp["penalty_point_balance"] == 20
    assert camp["compliance_posture"] == CompliancePosture.FROZEN
    assert camp["health_intake_status"] == HealthIntakeStatus.SUSPENDED

    assert_pct(fx.read_visit(api, scenario.visit_id)["provisional_mandatory_pct"], 33.33)
