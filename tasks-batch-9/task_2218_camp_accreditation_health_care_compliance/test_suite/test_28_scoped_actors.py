"""The role is right and the endpoint is right - only the identity is wrong. A camp identity is
confined to rows that resolve back to its own camp, and the two visitor-scoped shapes differ:
opening and closing scoring demand the lead seat while writing a verdict demands only a seat."""

from __future__ import annotations

from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import self_assessment_payload, visitor_score_payload
from test_helpers.test_users import make_camp_director_headers, make_visitor_headers
from test_helpers.types import (
    CampType,
    HealthStaffingLevel,
    PopulationServed,
    ScoreSource,
    SelfScore,
    SelfStatus,
    StandardDomain,
    VisitStatus,
    VisitorScore,
)
from prd_bench_local_runner.testing import validate_error, validate_success

SCOPE_STANDARDS = [
    fx.universal_mandatory_standard(
        "SU.1", domain=StandardDomain.SUPERVISION, scoring_weight=1
    )
]

CAMP_SHAPE = {
    "camp_type": CampType.DAY,
    "state_code": "OH",
    "population_served": PopulationServed.YOUTH_ONLY,
    "health_staffing_level": HealthStaffingLevel.RN_ONSITE,
}


def _two_camps_one_of_them_awaiting_its_visit(api):
    """Camp A is self-assessed, submitted and scheduled; camp B has nothing but a director."""
    fx.reset_clock(api)
    scenario = fx.open_cycle_scenario(
        api,
        edition_code="ACA-2026-SCP",
        standards=SCOPE_STANDARDS,
        camp={"name": "Scope Camp A", **CAMP_SHAPE},
        self_scores={"SU.1": SelfScore.MET},
        submit=True,
    )
    other_camp = fx.register_camp(api, name="Scope Camp B", **CAMP_SHAPE)
    fx.seat_team(
        api,
        scenario,
        window=("2026-08-01", "2026-08-07"),
        travel=("2026-08-01", "2026-08-03"),
        confirm=True,
    )
    scenario.visitors["outsider"] = fx.add_visitor(api, "Unseated Visitor")
    return scenario, other_camp


def _score_attempt(api, scenario, visitor_id):
    return api.patch_visitor_score(
        scenario.evaluation_id("SU.1"),
        visitor_score_payload(VisitorScore.MET, ScoreSource.OBSERVED),
        make_visitor_headers(visitor_id),
    )


def test_a_directors_reach_stops_at_rows_that_resolve_to_another_camp(api):
    """PRD §2.1: "A director reaching a cycle, an evaluation, a written plan, a deficiency, a
    medication record, an annual report or an incident disclosure that resolves back to a different
    camp is rejected with `ERR_FORBIDDEN_SCOPE` (HTTP 403)."

    Design: Corner/rbac/camp_and_visitor_scoped_actors_are_confined_to_their_own_rows
    """
    scenario, other_camp = _two_camps_one_of_them_awaiting_its_visit(api)
    intruder = make_camp_director_headers(other_camp["id"])

    # The scope comparison answers before the cycle-state rule that would also have refused this.
    validate_error(
        api.patch_self_assessment(
            scenario.evaluation_id("SU.1"),
            self_assessment_payload(SelfScore.NOT_MET),
            intruder,
        ),
        ApiErrorId.FORBIDDEN_SCOPE,
        403,
    )
    # Scope is not a write-only concern: the plain read is refused on the same grounds.
    validate_error(
        api.get_cycle(scenario.cycle_id, intruder), ApiErrorId.FORBIDDEN_SCOPE, 403
    )

    held = fx.read_evaluation(api, scenario.evaluation_id("SU.1"))
    assert held["self_score"] == SelfScore.MET
    # The submission had already carried the row to VERIFIED, and the refusal left it there.
    assert held["self_status"] == SelfStatus.VERIFIED


def test_opening_scoring_on_site_demands_the_lead_seat_and_not_merely_a_seat(api):
    """PRD §3.6: "Only the visitor whose `id` equals the visit's `lead_visitor_id` may do so;
    anyone else is refused with `ERR_FORBIDDEN_SCOPE`."

    Design: Corner/rbac/camp_and_visitor_scoped_actors_are_confined_to_their_own_rows
    """
    scenario, _other_camp = _two_camps_one_of_them_awaiting_its_visit(api)

    # The MEMBER holds a real ASSIGNED seat on this very visit and is still refused.
    validate_error(
        api.start_visit(
            scenario.visit_id, make_visitor_headers(scenario.visitor_id("member"))
        ),
        ApiErrorId.FORBIDDEN_SCOPE,
        403,
    )
    assert fx.read_visit(api, scenario.visit_id)["status"] == VisitStatus.SCHEDULED

    opened = fx.open_scoring(api, scenario.visit_id, scenario.visitor_id("lead"))
    assert opened["status"] == VisitStatus.IN_PROGRESS
    assert opened["lead_visitor_id"] == scenario.visitor_id("lead")


def test_writing_a_verdict_demands_any_assigned_seat_on_the_visit(api):
    """PRD §3.6: "The write requires that the cycle's non-rescinded visit be `IN_PROGRESS`
    (`ERR_VISIT_INVALID_STATE`), that the acting visitor hold an `ASSIGNED` seat on that visit
    (`ERR_FORBIDDEN_SCOPE`)"

    Design: Corner/rbac/camp_and_visitor_scoped_actors_are_confined_to_their_own_rows
    """
    scenario, _other_camp = _two_camps_one_of_them_awaiting_its_visit(api)
    fx.open_scoring(api, scenario.visit_id, scenario.visitor_id("lead"))

    # The right role and a real roster row, but no seat on this visit.
    validate_error(
        _score_attempt(api, scenario, scenario.visitor_id("outsider")),
        ApiErrorId.FORBIDDEN_SCOPE,
        403,
    )

    # The same request from the seated MEMBER who could not open scoring is accepted here.
    scored = validate_success(_score_attempt(api, scenario, scenario.visitor_id("member")))
    assert scored["visitor_score"] == VisitorScore.MET
    assert scored["score_source"] == ScoreSource.OBSERVED
    assert scored["scored_by_visitor_id"] == scenario.visitor_id("member")
    assert scored["visit_id"] == scenario.visit_id


def test_closing_scoring_narrows_back_to_the_lead_that_opened_it(api):
    """PRD §2.1: "Opening scoring on site and closing it both require `X-User-ID` to equal the
    visit's `lead_visitor_id`; writing a visitor verdict onto an evaluation requires the acting
    visitor to hold an `ASSIGNED` seat on the cycle's `IN_PROGRESS` visit. Either failure is
    `ERR_FORBIDDEN_SCOPE`."

    Design: Corner/rbac/camp_and_visitor_scoped_actors_are_confined_to_their_own_rows
    """
    scenario, _other_camp = _two_camps_one_of_them_awaiting_its_visit(api)
    fx.open_scoring(api, scenario.visit_id, scenario.visitor_id("lead"))
    validate_success(_score_attempt(api, scenario, scenario.visitor_id("member")))

    # The MEMBER whose verdict was just accepted cannot close the visit.
    validate_error(
        api.finalize_scoring(
            scenario.visit_id, make_visitor_headers(scenario.visitor_id("member"))
        ),
        ApiErrorId.FORBIDDEN_SCOPE,
        403,
    )
    assert fx.read_visit(api, scenario.visit_id)["status"] == VisitStatus.IN_PROGRESS

    closed = fx.close_scoring(api, scenario.visit_id, scenario.visitor_id("lead"))
    assert closed["status"] == VisitStatus.SCORED
    # The seat that carried the verdict was the MEMBER's, not the lead's.
    assert (
        fx.read_evaluation(api, scenario.evaluation_id("SU.1"))["scored_by_visitor_id"]
        == scenario.visitor_id("member")
    )
