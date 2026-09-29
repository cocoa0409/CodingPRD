"""Two arithmetic edges: a weighted percentage landing exactly on the 95.00 threshold,
and a provisional percentage whose denominator is empty."""

from __future__ import annotations

from test_helpers import fixtures as fx
from test_helpers.assertions import assert_pct
from test_helpers.types import (
    AccreditationStatus,
    CampType,
    CycleStatus,
    DecisionLevel,
    HealthStaffingLevel,
    PopulationServed,
    ScoreSource,
    SelfScore,
    StandardDomain,
    VisitStatusAxis,
    VisitorScore,
)

BIRCH_STANDARDS = [
    fx.universal_mandatory_standard("SB.1", domain=StandardDomain.SUPERVISION, scoring_weight=5),
    fx.universal_mandatory_standard("SB.2", domain=StandardDomain.SUPERVISION, scoring_weight=5),
    fx.universal_mandatory_standard("SB.3", domain=StandardDomain.SUPERVISION, scoring_weight=4),
    fx.universal_mandatory_standard("SB.4", domain=StandardDomain.SUPERVISION, scoring_weight=3),
    fx.universal_mandatory_standard("SB.5", domain=StandardDomain.SUPERVISION, scoring_weight=2),
    fx.universal_optional_standard("SB.6", domain=StandardDomain.SUPERVISION, scoring_weight=1),
]

BIRCH_CODES = ("SB.1", "SB.2", "SB.3", "SB.4", "SB.5", "SB.6")

BIRCH_CAMP = {
    "name": "Birch Day Camp",
    "camp_type": CampType.DAY,
    "state_code": "OH",
    "population_served": PopulationServed.YOUTH_ONLY,
    "program_elements": [],
    "resident_census": 0,
    "distance_to_hospital_km": 0,
    "max_daily_census": 65,
    "health_staffing_level": HealthStaffingLevel.FIRST_AIDER_ONLY,
    "prior_accredited_cycle_count": 0,
}

ZEPHYR_STANDARDS = [
    fx.universal_mandatory_standard("SZ.1", domain=StandardDomain.SUPERVISION),
    fx.universal_mandatory_standard("SZ.2", domain=StandardDomain.SUPERVISION),
]

ZEPHYR_CAMP = {
    "name": "Zephyr Day Camp",
    "camp_type": CampType.DAY,
    "state_code": "OH",
    "population_served": PopulationServed.YOUTH_ONLY,
    "program_elements": [],
    "resident_census": 0,
    "distance_to_hospital_km": 0,
    "max_daily_census": 45,
    "health_staffing_level": HealthStaffingLevel.FIRST_AIDER_ONLY,
    "prior_accredited_cycle_count": 0,
}


def _birch_cycle_decided(api):
    """The five mandatory rows are met; the weight-1 optional row is never scored."""
    scenario = fx.open_cycle_scenario(
        api,
        edition_code="ACA-2026-B",
        standards=BIRCH_STANDARDS,
        camp=BIRCH_CAMP,
        self_scores={code: SelfScore.MET for code in BIRCH_CODES},
        submit=True,
    )
    fx.seat_team(api, scenario, confirm=True)
    fx.score_visit(
        api,
        scenario,
        visitor_scores={
            code: (VisitorScore.MET, ScoreSource.OBSERVED)
            for code in ("SB.1", "SB.2", "SB.3", "SB.4", "SB.5")
        },
    )
    return fx.decide_cycle(api, scenario)


def _zephyr_cycle_decided(api):
    """Both mandatory rows are met, but only ever on interview evidence."""
    scenario = fx.open_cycle_scenario(
        api,
        edition_code="ACA-2026-Z",
        standards=ZEPHYR_STANDARDS,
        camp=ZEPHYR_CAMP,
        self_scores={"SZ.1": SelfScore.MET, "SZ.2": SelfScore.MET},
        submit=True,
    )
    fx.seat_team(api, scenario, confirm=True)
    fx.score_visit(
        api,
        scenario,
        visitor_scores={
            "SZ.1": (VisitorScore.MET, ScoreSource.INTERVIEW),
            "SZ.2": (VisitorScore.MET, ScoreSource.INTERVIEW),
        },
    )
    return fx.decide_cycle(api, scenario)


def test_weighted_percentage_of_exactly_95_00_still_earns_full_accreditation(api):
    """PRD §3.7: "Otherwise `ACCREDITED_WITH_CORRECTION` when `final_weighted_pct` is
    below 95.00."

    Design: Difficulty/boundary_precision_check/final_weighted_pct_exactly_95_00_yields_accredited_not_with_correction
    """
    scenario = _birch_cycle_decided(api)

    cycle = fx.read_cycle(api, scenario.cycle_id)
    assert_pct(cycle["final_mandatory_pct"], 100.00)
    # 19 of 20 applicable weight, which is 95.00 to the cent with no rounding at all.
    assert_pct(cycle["final_weighted_pct"], 95.00)
    assert cycle["decision_level"] == DecisionLevel.ACCREDITED
    assert cycle["decision_level"] != DecisionLevel.ACCREDITED_WITH_CORRECTION
    assert cycle["status"] == CycleStatus.CLOSED


def test_unscored_optional_row_locks_without_raising_a_finding(api):
    """PRD §3.6: "Every applicable evaluation's `visit_status` becomes `LOCKED` — rows
    already `SCORED` move `SCORED → LOCKED`, and a non-mandatory applicable row left
    unscored moves `UNSCORED → LOCKED` with its `visitor_score` still null."

    Design: Difficulty/boundary_precision_check/final_weighted_pct_exactly_95_00_yields_accredited_not_with_correction
    """
    scenario = _birch_cycle_decided(api)

    optional_row = fx.read_evaluation(api, scenario.evaluation_id("SB.6"))
    assert optional_row["visit_status"] == VisitStatusAxis.LOCKED
    assert optional_row["visitor_score"] is None
    assert optional_row["scoring_weight"] == 1

    _rows, meta = fx.list_deficiencies_for_visit(api, scenario.visit_id)
    assert meta["total_count"] == 0
    assert fx.read_cycle(api, scenario.cycle_id)["open_deficiency_count"] == 0

    visit = fx.read_visit(api, scenario.visit_id)
    assert visit["mandatory_scored_count"] == 5
    assert_pct(visit["provisional_mandatory_pct"], 100.00)


def test_closing_an_accredited_cycle_increments_the_camps_loyalty_counters(api):
    """PRD §3.7: "A move to `ACCREDITED` on this branch additionally increments the camp's
    `prior_accredited_cycle_count` by one and sets `last_accredited_year` to the cycle's
    `cycle_year`."

    Design: Difficulty/boundary_precision_check/final_weighted_pct_exactly_95_00_yields_accredited_not_with_correction
    """
    scenario = _birch_cycle_decided(api)

    camp = fx.read_camp(api, scenario.camp_id)
    assert camp["accreditation_status"] == AccreditationStatus.ACCREDITED
    assert camp["prior_accredited_cycle_count"] == 1
    assert camp["last_accredited_year"] == 2026

    # 95000 undiscounted base + 350 per applicable standard + 18000 per travel day.
    cycle = fx.read_cycle(api, scenario.cycle_id)
    assert cycle["assessed_fee_cents"] == 205100
    assert cycle["assessed_fee_cents"] == 95000 + 6 * 350 + 6 * 18000


def test_empty_provisional_denominator_reads_one_hundred_percent(api):
    """PRD §3.6: "The percentage is one hundred times the numerator divided by the
    denominator, rounded half up to two decimal places; when the denominator is zero the
    result is 100.00."

    Design: Difficulty/boundary_precision_check/zero_denominator_provisional_score_yields_100_00_and_no_deficiency
    """
    scenario = _zephyr_cycle_decided(api)

    visit = fx.read_visit(api, scenario.visit_id)
    assert_pct(visit["provisional_mandatory_pct"], 100.00)
    assert float(visit["provisional_mandatory_pct"]) != 0.00
    assert visit["mandatory_scored_count"] == 2
    assert visit["mandatory_met_count"] == 2

    summary = fx.read_compliance_summary(api, scenario.cycle_id)
    assert summary["provisional_denominator"] == 0
    assert summary["provisional_numerator"] == 0
    assert_pct(summary["provisional_mandatory_pct"], 100.00)


def test_office_final_variant_divides_normally_over_the_same_interview_rows(api):
    """PRD §3.7: "Its denominator is every applicable mandatory row on the cycle; its
    numerator is those whose `visitor_score` is `MET`."

    Design: Difficulty/boundary_precision_check/zero_denominator_provisional_score_yields_100_00_and_no_deficiency
    """
    scenario = _zephyr_cycle_decided(api)

    summary = fx.read_compliance_summary(api, scenario.cycle_id)
    assert summary["final_denominator"] == 2
    assert summary["final_numerator"] == 2
    assert_pct(summary["final_mandatory_pct"], 100.00)

    cycle = fx.read_cycle(api, scenario.cycle_id)
    assert_pct(cycle["final_weighted_pct"], 100.00)
    assert cycle["decision_level"] == DecisionLevel.ACCREDITED
    assert cycle["status"] == CycleStatus.CLOSED
    assert cycle["open_deficiency_count"] == 0
    assert cycle["assessed_fee_cents"] == 203700

    camp = fx.read_camp(api, scenario.camp_id)
    assert camp["prior_accredited_cycle_count"] == 1
    assert camp["last_accredited_year"] == 2026
