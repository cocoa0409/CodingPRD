"""On-site scoring guards read in their own order: a seated lead still needs the endorsement for
a specialist domain, a row from another camp's cycle is refused outright, and closing waits for
every applicable mandatory row."""

from __future__ import annotations

from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_pct
from test_helpers.factories import visitor_score_payload
from test_helpers.test_users import make_visitor_headers
from test_helpers.types import (
    CampType,
    Certification,
    CycleStatus,
    HealthStaffingLevel,
    PopulationServed,
    ProgramElement,
    ScoreSource,
    SelfScore,
    StandardDomain,
    TeamRole,
    VisitStatus,
    VisitStatusAxis,
    VisitorScore,
)
from prd_bench_local_runner.testing import validate_error, validate_success

SCORING_STANDARDS = [
    fx.universal_mandatory_standard(
        "SU.1", domain=StandardDomain.SUPERVISION, scoring_weight=1
    ),
    {
        "code": "PA.2",
        "title": "Pool supervision",
        "domain": StandardDomain.AQUATICS,
        "mandatory": True,
        "scoring_weight": 1,
        "requires_program_elements_any": [ProgramElement.AQUATICS_POOL],
    },
]

SCORING_TEAM = [
    {
        "key": "lead",
        "full_name": "Scoring Lead",
        "home_state_code": "PA",
        "certifications": [Certification.LEAD_VISITOR],
        "team_role": TeamRole.LEAD,
    },
    {
        "key": "aquatics",
        "full_name": "Scoring Aquatics",
        "home_state_code": "PA",
        "certifications": [Certification.AQUATICS_SPECIALIST],
        "team_role": TeamRole.SPECIALIST_AQUATICS,
    },
]


def _two_camps_scoring_one_visit(api):
    """Camp A's visit is IN_PROGRESS; camp B holds its own cycle on the same edition."""
    fx.reset_clock(api)
    scenario = fx.open_cycle_scenario(
        api,
        edition_code="ACA-2026-SCR",
        standards=SCORING_STANDARDS,
        camp={
            "name": "Scoring Camp A",
            "camp_type": CampType.DAY,
            "state_code": "OH",
            "population_served": PopulationServed.YOUTH_ONLY,
            "program_elements": [ProgramElement.AQUATICS_POOL],
            "health_staffing_level": HealthStaffingLevel.RN_ONSITE,
        },
        self_scores={"SU.1": SelfScore.MET, "PA.2": SelfScore.MET},
        submit=True,
    )
    other_camp = fx.register_camp(
        api,
        name="Scoring Camp B",
        camp_type=CampType.DAY,
        state_code="OH",
        population_served=PopulationServed.YOUTH_ONLY,
        health_staffing_level=HealthStaffingLevel.FIRST_AIDER_ONLY,
    )
    other_cycle = fx.open_cycle(api, other_camp["id"], scenario.edition["id"])
    other_row = fx.evaluation_for_standard(
        api, other_cycle["id"], scenario.standards["SU.1"]["id"], other_camp["id"]
    )
    fx.seat_team(
        api,
        scenario,
        team=SCORING_TEAM,
        window=("2026-08-01", "2026-08-07"),
        travel=("2026-08-01", "2026-08-03"),
        confirm=True,
    )
    fx.score_visit(api, scenario, visitor_scores={}, clock=None, finalize=False)
    return scenario, other_cycle, other_row


def _score_attempt(api, evaluation_id, visitor_id, visitor_score, score_source):
    return api.patch_visitor_score(
        evaluation_id,
        visitor_score_payload(visitor_score, score_source),
        make_visitor_headers(visitor_id),
    )


def test_a_seated_lead_still_needs_the_endorsement_for_an_aquatics_standard(api):
    """PRD §3.6: "One further gate is a certification gate: when the pinned standard's `domain`
    is `AQUATICS`, `ADVENTURE` or `HEALTH_WELLNESS`, the acting visitor must hold
    `AQUATICS_SPECIALIST`, `ADVENTURE_SPECIALIST` or `HEALTH_SPECIALIST` respectively, or the
    write is rejected with `ERR_SPECIALIST_CERTIFICATION_REQUIRED` (HTTP 422); standards in the
    other four domains carry no certification gate."

    Design: Corner/validations/scoring_guards_require_the_matching_specialist_the_right_cycle_and_a_complete_mandatory_sweep
    """
    scenario, _other_cycle, _other_row = _two_camps_scoring_one_visit(api)
    aquatics_row = scenario.evaluation_id("PA.2")

    # The lead holds an ASSIGNED seat on the IN_PROGRESS visit, so only the endorsement fails.
    validate_error(
        _score_attempt(
            api,
            aquatics_row,
            scenario.visitor_id("lead"),
            VisitorScore.MET,
            ScoreSource.OBSERVED,
        ),
        ApiErrorId.SPECIALIST_CERTIFICATION_REQUIRED,
        422,
    )
    assert fx.read_evaluation(api, aquatics_row)["visitor_score"] is None

    scored = validate_success(
        _score_attempt(
            api,
            aquatics_row,
            scenario.visitor_id("aquatics"),
            VisitorScore.MET,
            ScoreSource.OBSERVED,
        )
    )
    assert scored["visitor_score"] == VisitorScore.MET
    assert scored["scored_by_visitor_id"] == scenario.visitor_id("aquatics")
    assert scored["visit_status"] == VisitStatusAxis.SCORED


def test_a_row_from_another_camps_cycle_is_refused_as_a_cycle_mismatch(api):
    """PRD §3.6: "and that the row belong to the same cycle as the visit on which the visitor
    holds their seat, or it is rejected with `ERR_VISIT_CYCLE_MISMATCH` (HTTP 422)."

    Design: Corner/validations/scoring_guards_require_the_matching_specialist_the_right_cycle_and_a_complete_mandatory_sweep
    """
    scenario, other_cycle, other_row = _two_camps_scoring_one_visit(api)

    validate_error(
        _score_attempt(
            api,
            other_row["id"],
            scenario.visitor_id("lead"),
            VisitorScore.MET,
            ScoreSource.OBSERVED,
        ),
        ApiErrorId.VISIT_CYCLE_MISMATCH,
        422,
    )

    untouched = fx.read_evaluation(api, other_row["id"])
    assert untouched["visitor_score"] is None
    assert untouched["visit_status"] == VisitStatusAxis.UNSCORED
    assert fx.read_cycle(api, other_cycle["id"])["status"] == CycleStatus.SELF_ASSESSMENT


def test_closing_scoring_waits_for_every_applicable_mandatory_row(api):
    """PRD §3.6: "every applicable mandatory evaluation on the cycle must already carry a
    non-null `visitor_score`, or the request is refused with
    `ERR_MANDATORY_SCORING_INCOMPLETE` (HTTP 422)."

    Design: Corner/validations/scoring_guards_require_the_matching_specialist_the_right_cycle_and_a_complete_mandatory_sweep
    """
    scenario, _other_cycle, _other_row = _two_camps_scoring_one_visit(api)
    fx.record_visitor_score(
        api,
        scenario.evaluation_id("PA.2"),
        scenario.visitor_id("aquatics"),
        VisitorScore.MET,
        ScoreSource.OBSERVED,
    )

    validate_error(
        api.finalize_scoring(
            scenario.visit_id, make_visitor_headers(scenario.visitor_id("lead"))
        ),
        ApiErrorId.MANDATORY_SCORING_INCOMPLETE,
        422,
    )
    assert fx.read_visit(api, scenario.visit_id)["status"] == VisitStatus.IN_PROGRESS

    # A SUPERVISION standard carries no endorsement gate, and INTERVIEW is a legal channel.
    interviewed = fx.record_visitor_score(
        api,
        scenario.evaluation_id("SU.1"),
        scenario.visitor_id("lead"),
        VisitorScore.MET,
        ScoreSource.INTERVIEW,
    )
    assert interviewed["score_source"] == ScoreSource.INTERVIEW

    closed = validate_success(
        api.finalize_scoring(
            scenario.visit_id, make_visitor_headers(scenario.visitor_id("lead"))
        )
    )
    assert closed["status"] == VisitStatus.SCORED


def test_an_interview_row_leaves_the_provisional_denominator_untouched(api):
    """PRD §3.6: "Its denominator is the number of applicable mandatory rows whose
    `score_source` is `OBSERVED` or `DOCUMENT` and whose `visitor_score` is non-null and is not
    `NOT_APPLICABLE`; its numerator is the number of those same rows whose `visitor_score` is
    `MET`."

    Design: Corner/validations/scoring_guards_require_the_matching_specialist_the_right_cycle_and_a_complete_mandatory_sweep
    """
    scenario, _other_cycle, _other_row = _two_camps_scoring_one_visit(api)
    fx.record_visitor_score(
        api,
        scenario.evaluation_id("PA.2"),
        scenario.visitor_id("aquatics"),
        VisitorScore.MET,
        ScoreSource.OBSERVED,
    )
    fx.record_visitor_score(
        api,
        scenario.evaluation_id("SU.1"),
        scenario.visitor_id("lead"),
        VisitorScore.MET,
        ScoreSource.INTERVIEW,
    )
    validate_success(
        api.finalize_scoring(
            scenario.visit_id, make_visitor_headers(scenario.visitor_id("lead"))
        )
    )
    scenario.refresh(api)

    # Only the OBSERVED aquatics row is inside the provisional set: one of one is MET.
    assert_pct(scenario.visit["provisional_mandatory_pct"], 100.00)
    assert_pct(scenario.cycle["provisional_mandatory_pct"], 100.00)
    assert scenario.visit["mandatory_scored_count"] == 2
    assert scenario.visit["mandatory_met_count"] == 2
    assert scenario.cycle["status"] == CycleStatus.VISIT_COMPLETED
    assert fx.list_deficiencies_for_visit(api, scenario.visit_id)[1]["total_count"] == 0
