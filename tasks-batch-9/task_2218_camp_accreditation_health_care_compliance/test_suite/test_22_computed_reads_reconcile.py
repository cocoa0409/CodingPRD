"""Both computed reads answer over the same stored rows before and after the decision: the summary
carries the provisional and office-final denominators side by side, and the risk read breaks the
stored index into components that sum through the population multiplier."""

from __future__ import annotations

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_compliance_summary,
    assert_pct,
    assert_risk_index_breakdown,
)
from test_helpers.test_users import OFFICER_ONE_HEADERS
from test_helpers.types import (
    AccreditationStatus,
    CampType,
    CycleStatus,
    DecisionLevel,
    HealthStaffingLevel,
    PopulationServed,
    RiskIndexVariant,
    ScoreSource,
    SelfScore,
    StandardDomain,
    VisitorScore,
)

SUMMARY_STANDARDS = [
    fx.universal_mandatory_standard(
        "SU.1", domain=StandardDomain.SUPERVISION, scoring_weight=3
    ),
    fx.universal_mandatory_standard(
        "SU.2", domain=StandardDomain.SUPERVISION, scoring_weight=1
    ),
    fx.universal_optional_standard(
        "OM.3", domain=StandardDomain.OPERATIONS, scoring_weight=2
    ),
]


def _scored_cycle_awaiting_its_decision(api):
    """Three applicable rows scored MET/OBSERVED, MET/INTERVIEW and NOT_MET/OBSERVED."""
    fx.reset_clock(api)
    scenario = fx.open_cycle_scenario(
        api,
        edition_code="ACA-2026-SUM",
        standards=SUMMARY_STANDARDS,
        camp={
            "name": "Summary Camp",
            "camp_type": CampType.DAY,
            "state_code": "OH",
            "population_served": PopulationServed.YOUTH_ONLY,
            "health_staffing_level": HealthStaffingLevel.FIRST_AIDER_ONLY,
        },
        self_scores={"SU.1": SelfScore.MET, "SU.2": SelfScore.MET, "OM.3": SelfScore.PARTIAL},
        submit=True,
    )
    fx.seat_team(
        api,
        scenario,
        window=("2026-08-01", "2026-08-07"),
        travel=("2026-08-01", "2026-08-03"),
        confirm=True,
    )
    return fx.score_visit(
        api,
        scenario,
        visitor_scores={
            "SU.1": fx.ALL_MET_OBSERVED,
            "SU.2": (VisitorScore.MET, ScoreSource.INTERVIEW),
            "OM.3": fx.NOT_MET_OBSERVED,
        },
        clock=None,
    )


def _assert_the_twelve_summary_numbers(summary, cycle_id):
    assert summary["cycle_id"] == cycle_id
    assert summary["applicable_standard_count"] == 3
    assert summary["applicable_mandatory_count"] == 2
    # The INTERVIEW-sourced row is outside the provisional set on both sides.
    assert summary["provisional_denominator"] == 1
    assert summary["provisional_numerator"] == 1
    assert_pct(summary["provisional_mandatory_pct"], 100.00)
    # The office counts it, so the same two rows give a denominator of 2.
    assert summary["final_denominator"] == 2
    assert summary["final_numerator"] == 2
    assert_pct(summary["final_mandatory_pct"], 100.00)
    assert summary["weighted_total"] == 6
    assert summary["weighted_met"] == 4
    assert_pct(summary["final_weighted_pct"], 66.67)


def test_the_summary_carries_both_denominators_before_any_decision_is_issued(api):
    """PRD §3.3: "both compliance variants computed side by side over the very same stored rows,
    so a camp can see the gap between the field team's provisional figure and the office's final
    one before the decision is issued."

    Design: Corner/endpoints/both_computed_reads_reconcile_with_the_stored_rows_before_and_after_the_decision
    """
    scenario = _scored_cycle_awaiting_its_decision(api)
    summary = fx.read_compliance_summary(api, scenario.cycle_id, OFFICER_ONE_HEADERS)

    assert_compliance_summary(summary)
    _assert_the_twelve_summary_numbers(summary, scenario.cycle_id)
    assert summary["open_deficiency_count"] == 1
    assert summary["projected_decision_level"] == DecisionLevel.ACCREDITED_WITH_CORRECTION
    # Nothing has been stamped on the cycle itself yet.
    assert scenario.cycle["decision_level"] is None
    assert scenario.cycle["status"] == CycleStatus.VISIT_COMPLETED


def test_the_risk_read_breaks_the_stored_index_into_its_components(api):
    """PRD §2.9: "Finally, the base and the five components are added together, the sum is
    multiplied by a population multiplier — 1.4 for `MEDICALLY_FRAGILE`, 1.1 for
    `ADULT_INCLUSIVE` and 1.0 for `YOUTH_ONLY` — the product is capped at 100.00, and the capped
    value is rounded half up to two decimal places to give `risk_index`."

    Design: Corner/endpoints/both_computed_reads_reconcile_with_the_stored_rows_before_and_after_the_decision
    """
    scenario = _scored_cycle_awaiting_its_decision(api)
    components = fx.read_risk_index(api, scenario.camp_id, scenario.director_headers)

    assert_risk_index_breakdown(components)
    assert components["camp_id"] == scenario.camp_id
    assert components["risk_index_variant"] == RiskIndexVariant.POST_VISIT
    assert float(components["incident_component"]) == 0.00
    assert float(components["program_component"]) == 0.00
    assert float(components["staffing_gap_penalty"]) == 0.00
    # An unlicensed camp carries 6, and the only finding is non-mandatory.
    assert float(components["license_penalty"]) == 6.00
    assert float(components["compliance_component"]) == 0.00
    assert float(components["population_multiplier"]) == 1.00
    assert float(components["risk_index"]) == 16.00
    assert float(components["risk_index"]) == float(scenario.camp["risk_index"])


def test_the_decision_stamps_the_level_the_summary_had_already_projected(api):
    """PRD §3.7: "24,000 cents per visitor travel day, taken at three quarters of that rate — so
    18,000 cents of billable value per day — multiplied by the total team travel days and then by
    one minus the discount fraction."

    Design: Corner/endpoints/both_computed_reads_reconcile_with_the_stored_rows_before_and_after_the_decision
    """
    scenario = fx.decide_cycle(api, _scored_cycle_awaiting_its_decision(api))

    assert scenario.cycle["decision_level"] == DecisionLevel.ACCREDITED_WITH_CORRECTION
    assert_pct(scenario.cycle["final_mandatory_pct"], 100.00)
    assert_pct(scenario.cycle["final_weighted_pct"], 66.67)
    assert scenario.cycle["status"] == CycleStatus.IN_CORRECTION
    # 95000 base + 3 x 350 standards + no surcharged domain + 6 travel days x 18000.
    assert scenario.cycle["assessed_fee_cents"] == 204050
    assert scenario.camp["accreditation_status"] == (
        AccreditationStatus.ACCREDITED_WITH_CORRECTION
    )


def test_the_summary_never_drifts_from_the_row_the_decision_stamped(api):
    """PRD §3.7: "All four branches stamp `decision_issued_at` with the current logical clock
    instant and `decision_issued_by_user_id` with the acting `X-User-ID`, and all four compute
    the same four figures: the office-final percentage, the weighted percentage, the decision
    level and the assessed fee."

    Design: Corner/endpoints/both_computed_reads_reconcile_with_the_stored_rows_before_and_after_the_decision
    """
    scenario = fx.decide_cycle(api, _scored_cycle_awaiting_its_decision(api))
    summary = fx.read_compliance_summary(api, scenario.cycle_id, scenario.director_headers)

    _assert_the_twelve_summary_numbers(summary, scenario.cycle_id)
    assert summary["open_deficiency_count"] == 1
    assert summary["projected_decision_level"] == scenario.cycle["decision_level"]
