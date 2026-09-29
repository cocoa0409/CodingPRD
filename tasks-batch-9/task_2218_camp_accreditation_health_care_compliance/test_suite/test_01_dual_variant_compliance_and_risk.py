"""The two dual-variant computations: mandatory compliance and the camp risk index."""

from __future__ import annotations

from test_helpers import fixtures as fx
from test_helpers.assertions import assert_pct
from test_helpers.types import (
    AccreditationStatus,
    CampType,
    CompliancePosture,
    CycleStatus,
    DecisionLevel,
    HealthStaffingLevel,
    PopulationServed,
    ProgramElement,
    RiskIndexVariant,
    ScoreSource,
    SelfScore,
    TeamRole,
    VisitorScore,
)

PINE_STANDARDS = [
    fx.universal_mandatory_standard("SU.1"),
    fx.universal_mandatory_standard("SU.2"),
    fx.universal_mandatory_standard("SU.3"),
    fx.universal_mandatory_standard("SU.4"),
]

PINE_CAMP = {
    "name": "Pine Day Camp",
    "camp_type": CampType.DAY,
    "state_code": "OH",
    "population_served": PopulationServed.YOUTH_ONLY,
    "program_elements": [],
    "resident_census": 0,
    "distance_to_hospital_km": 0,
    "max_daily_census": 80,
    "health_staffing_level": HealthStaffingLevel.FIRST_AIDER_ONLY,
    "prior_accredited_cycle_count": 0,
}

# One row per evidence channel: observed, interview, a field not-applicable call
# and a documentary check.
PINE_VISITOR_SCORES = {
    "SU.1": (VisitorScore.MET, ScoreSource.OBSERVED),
    "SU.2": (VisitorScore.MET, ScoreSource.INTERVIEW),
    "SU.3": (VisitorScore.NOT_APPLICABLE, ScoreSource.OBSERVED),
    "SU.4": (VisitorScore.MET, ScoreSource.DOCUMENT),
}

RIDGE_STANDARDS = [
    fx.universal_mandatory_standard("SU.1"),
    fx.universal_mandatory_standard("SU.2"),
    fx.universal_mandatory_standard("SU.3"),
]

RIDGE_CAMP = {
    "name": "Ridge Resident Camp",
    "camp_type": CampType.RESIDENT,
    "state_code": "OH",
    "population_served": PopulationServed.MEDICALLY_FRAGILE,
    "program_elements": [ProgramElement.TRANSPORTATION, ProgramElement.TRIP_CAMPING],
    "resident_census": 140,
    "distance_to_hospital_km": 45,
    "max_daily_census": 160,
    "health_staffing_level": HealthStaffingLevel.PHYSICIAN_ONSITE,
    "prior_accredited_cycle_count": 0,
}

RIDGE_TEAM = [
    {
        "key": "lead",
        "full_name": "Lead One",
        "home_state_code": "PA",
        "certifications": ["LEAD_VISITOR"],
        "team_role": TeamRole.LEAD,
    },
    {
        "key": "health",
        "full_name": "Health Spec",
        "home_state_code": "NY",
        "certifications": ["HEALTH_SPECIALIST"],
        "team_role": TeamRole.SPECIALIST_HEALTH,
    },
]


def _pine_visit_scored(api):
    """Pine Day Camp scored on all four mandatory rows, scoring not yet closed."""
    scenario = fx.open_cycle_scenario(
        api,
        edition_code="ACA-2026-D",
        standards=PINE_STANDARDS,
        camp=PINE_CAMP,
        self_scores={code: SelfScore.MET for code in ("SU.1", "SU.2", "SU.3", "SU.4")},
        submit=True,
    )
    fx.seat_team(api, scenario, confirm=True)
    return fx.score_visit(api, scenario, visitor_scores=PINE_VISITOR_SCORES, finalize=False)


def _ridge_visit_scored(api):
    """Ridge Resident Camp with three PARTIAL self scores and one NOT_MET verdict."""
    scenario = fx.open_cycle_scenario(
        api,
        edition_code="ACA-2026-R",
        standards=RIDGE_STANDARDS,
        camp=RIDGE_CAMP,
        self_scores={code: SelfScore.PARTIAL for code in ("SU.1", "SU.2", "SU.3")},
        submit=True,
    )
    fx.seat_team(api, scenario, team=RIDGE_TEAM, confirm=True)
    return fx.score_visit(
        api,
        scenario,
        visitor_scores={
            "SU.1": (VisitorScore.MET, ScoreSource.OBSERVED),
            "SU.2": (VisitorScore.NOT_MET, ScoreSource.OBSERVED),
            "SU.3": (VisitorScore.MET, ScoreSource.OBSERVED),
        },
        finalize=False,
    )


def test_provisional_variant_drops_interview_and_field_not_applicable_rows(api):
    """PRD §3.6: "Its denominator is the number of applicable mandatory rows whose
    `score_source` is `OBSERVED` or `DOCUMENT` and whose `visitor_score` is non-null
    and is not `NOT_APPLICABLE`; its numerator is the number of those same rows whose
    `visitor_score` is `MET`."

    Design: Difficulty/dual_variant_calc/mandatory_compliance_score_provisional_versus_office_final_diverge
    """
    scenario = _pine_visit_scored(api)
    fx.close_scoring(api, scenario.visit_id, scenario.visitor_id("lead"))

    visit = fx.read_visit(api, scenario.visit_id)
    cycle = fx.read_cycle(api, scenario.cycle_id)
    assert_pct(visit["provisional_mandatory_pct"], 100.00)
    assert_pct(cycle["provisional_mandatory_pct"], 100.00)

    summary = fx.read_compliance_summary(api, scenario.cycle_id)
    assert summary["provisional_denominator"] == 2
    assert summary["provisional_numerator"] == 2
    assert summary["final_denominator"] == 4
    assert summary["final_numerator"] == 3


def test_office_final_variant_counts_every_mandatory_row_and_denies_the_cycle(api):
    """PRD §3.7: "An `INTERVIEW`-sourced `MET` row now counts in the numerator, and a
    row the visitor marked `NOT_APPLICABLE` or left unscored stays in the denominator
    with no numerator credit, because the office does not accept a field
    not-applicable call on a mandatory standard."

    Design: Difficulty/dual_variant_calc/mandatory_compliance_score_provisional_versus_office_final_diverge
    """
    scenario = _pine_visit_scored(api)
    fx.close_scoring(api, scenario.visit_id, scenario.visitor_id("lead"))
    fx.issue_decision(api, scenario.cycle_id)

    cycle = fx.read_cycle(api, scenario.cycle_id)
    assert_pct(cycle["final_mandatory_pct"], 75.00)
    assert_pct(cycle["final_weighted_pct"], 75.00)
    assert cycle["decision_level"] == DecisionLevel.DENIED
    assert cycle["status"] == CycleStatus.TERMINATED
    assert cycle["assessed_fee_cents"] == 204400

    camp = fx.read_camp(api, scenario.camp_id)
    assert camp["accreditation_status"] == AccreditationStatus.REVOKED

    rows, meta = fx.list_deficiencies_for_visit(api, scenario.visit_id)
    assert meta["total_count"] == 0
    assert rows == []


def test_risk_index_pre_visit_variant_reads_the_camps_own_self_scores(api):
    """PRD §2.9: "Under `PRE_VISIT`, count the newest cycle's evaluations that are
    applicable and mandatory and whose `self_score` is either absent or something
    other than `MET`; multiply that count by 30; divide by the larger of 1 and the
    cycle's `applicable_mandatory_count`; and round the quotient half up to two
    decimal places."

    Design: Difficulty/dual_variant_calc/camp_risk_index_pre_visit_versus_post_visit_diverge
    """
    scenario = _ridge_visit_scored(api)

    components = fx.read_risk_index(api, scenario.camp_id)
    assert components["risk_index_variant"] == RiskIndexVariant.PRE_VISIT
    assert_pct(components["compliance_component"], 30.00)
    assert components["program_component"] == 7
    assert components["license_penalty"] == 6
    assert components["staffing_gap_penalty"] == 0
    assert float(components["population_multiplier"]) == 1.4
    assert_pct(components["risk_index"], 74.20)


def test_risk_index_post_visit_variant_ignores_self_scores_and_reads_open_findings(api):
    """PRD §2.9: "Under `POST_VISIT`, self scores are ignored entirely. Count instead
    the deficiencies raised on that cycle's non-rescinded visit whose `severity` is
    `MANDATORY_CRITICAL` or `MANDATORY` and whose `status` is `OPEN`,
    `PLAN_SUBMITTED` or `ESCALATED`; multiply that count by 30; divide by the larger
    of 1 and the cycle's `applicable_mandatory_count`; and round the quotient half up
    to two decimal places."

    Design: Difficulty/dual_variant_calc/camp_risk_index_pre_visit_versus_post_visit_diverge
    """
    scenario = _ridge_visit_scored(api)
    fx.close_scoring(api, scenario.visit_id, scenario.visitor_id("lead"))

    components = fx.read_risk_index(api, scenario.camp_id)
    assert components["risk_index_variant"] == RiskIndexVariant.POST_VISIT
    assert_pct(components["compliance_component"], 10.00)
    assert_pct(components["risk_index"], 46.20)

    camp = fx.read_camp(api, scenario.camp_id)
    assert_pct(camp["risk_index"], 46.20)
    assert camp["risk_index_variant"] == RiskIndexVariant.POST_VISIT
    assert camp["penalty_point_balance"] == 5
    assert camp["compliance_posture"] == CompliancePosture.RESTRICTED

    for code in ("SU.1", "SU.2", "SU.3"):
        evaluation = fx.read_evaluation(api, scenario.evaluation_id(code))
        assert evaluation["self_score"] == SelfScore.PARTIAL
