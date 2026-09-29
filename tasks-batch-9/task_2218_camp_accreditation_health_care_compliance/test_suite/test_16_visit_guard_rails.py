"""Every guard rail around one visit, each answering with its own error: the three window
clauses, the three seating clauses, the team-composition rule and the arrival window."""

from __future__ import annotations

from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import visit_assignment_payload, visit_payload
from test_helpers.test_users import OFFICER_ONE_HEADERS, make_visitor_headers
from test_helpers.types import (
    CampType,
    Certification,
    CycleStatus,
    PopulationServed,
    ProgramElement,
    SelfScore,
    SpecialistDomain,
    StandardDomain,
    TeamRole,
    VisitStatus,
)
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

GUARD_STANDARDS = [
    fx.universal_mandatory_standard(
        "SU.1", domain=StandardDomain.SUPERVISION, scoring_weight=1
    ),
    {
        "code": "PA.2",
        "title": "Pool supervision",
        "domain": StandardDomain.AQUATICS,
        "mandatory": False,
        "scoring_weight": 1,
        "requires_program_elements_any": [ProgramElement.AQUATICS_POOL],
    },
]

GUARD_WINDOW = ("2026-08-05", "2026-08-11")

GUARD_TEAM = [
    {
        "key": "lead",
        "full_name": "Guard Lead",
        "home_state_code": "PA",
        "certifications": [Certification.LEAD_VISITOR],
        "team_role": TeamRole.LEAD,
    },
    {
        "key": "member",
        "full_name": "Guard Member",
        "home_state_code": "PA",
        "certifications": [],
        "team_role": TeamRole.MEMBER,
    },
]


def _draft_visit_awaiting_its_aquatics_seat(api):
    """A DRAFT visit with a lead and a member, plus three visitors still off the team."""
    fx.reset_clock(api)
    scenario = fx.open_cycle_scenario(
        api,
        edition_code="ACA-2026-GRD",
        standards=GUARD_STANDARDS,
        camp={
            "name": "Guard Rail Camp",
            "camp_type": CampType.DAY,
            "state_code": "OH",
            "population_served": PopulationServed.YOUTH_ONLY,
            "program_elements": [ProgramElement.AQUATICS_POOL],
        },
        self_scores={"SU.1": SelfScore.MET, "PA.2": SelfScore.MET},
        submit=True,
    )
    fx.seat_team(
        api,
        scenario,
        team=GUARD_TEAM,
        window=GUARD_WINDOW,
        travel=("2026-08-05", "2026-08-07"),
    )
    scenario.visitors["aquatics"] = fx.add_visitor(
        api,
        full_name="Guard Aquatics",
        home_state_code="PA",
        certifications=[Certification.AQUATICS_SPECIALIST],
    )
    scenario.visitors["lapsed"] = fx.add_visitor(
        api, full_name="Guard Lapsed", home_state_code="PA", trained_through_year=2025
    )
    scenario.visitors["retiree"] = fx.add_visitor(
        api, full_name="Guard Retiree", home_state_code="PA"
    )
    fx.deactivate_visitor(
        api, scenario.visitor_id("retiree"), "retired from the visitor corps"
    )
    return scenario


def _open_visit_attempt(api, scenario, window_start_date, window_end_date):
    """POST one visit for the cycle at its current version and return the raw response."""
    return api.create_visit(
        visit_payload(
            scenario.cycle_id,
            fx.read_cycle(api, scenario.cycle_id)["version"],
            window_start_date=window_start_date,
            window_end_date=window_end_date,
        ),
        OFFICER_ONE_HEADERS,
    )


def _seat_attempt(api, scenario, visitor_key, team_role, travel_start, travel_end):
    """POST one seat on the standing visit and return the raw response."""
    return api.create_visit_assignment(
        visit_assignment_payload(
            scenario.visit_id,
            scenario.visitor_id(visitor_key),
            team_role,
            travel_start,
            travel_end,
        ),
        OFFICER_ONE_HEADERS,
    )


def test_each_window_clause_is_read_separately_and_no_visit_is_created(api):
    """PRD §3.5: "The window must satisfy three conditions together: `window_start_date` on or
    before `window_end_date`, a span of at most fourteen days counting both endpoints, and
    `window_start_date` on or after the logical clock's calendar date. Any violation is
    `ERR_VISIT_WINDOW_INVALID` (HTTP 422)."

    Design: Corner/validations/visit_window_travel_block_and_team_composition_guards_each_return_their_own_error
    """
    scenario = _draft_visit_awaiting_its_aquatics_seat(api)

    # A window that opened before the clock's calendar date of 2026-08-01.
    validate_error(
        _open_visit_attempt(api, scenario, "2026-07-25", "2026-07-30"),
        ApiErrorId.VISIT_WINDOW_INVALID,
        422,
    )
    # A window that ends before it starts.
    validate_error(
        _open_visit_attempt(api, scenario, "2026-08-12", "2026-08-10"),
        ApiErrorId.VISIT_WINDOW_INVALID,
        422,
    )
    # Fifteen inclusive days, one past the fourteen-day span.
    validate_error(
        _open_visit_attempt(api, scenario, "2026-08-05", "2026-08-19"),
        ApiErrorId.VISIT_WINDOW_INVALID,
        422,
    )

    rows, meta = validate_paginated(
        api.list_visits({"cycle_id": scenario.cycle_id}, OFFICER_ONE_HEADERS)
    )
    # No supersede ran: a refused window never reached the standing visit.
    assert meta["total_count"] == 1
    assert rows[0]["id"] == scenario.visit_id
    assert rows[0]["status"] == VisitStatus.DRAFT
    assert scenario.visit["required_specialist_domains"] == [SpecialistDomain.AQUATICS]
    assert scenario.cycle["applicable_standard_count"] == 2


def test_the_seating_clauses_refuse_an_early_block_a_lapsed_and_an_inactive_visitor(api):
    """PRD §3.5: "Last, the travel block must lie wholly inside the visit window —
    `travel_block_start_date` on or after `window_start_date` and `travel_block_end_date` on or
    before `window_end_date` — or the request is rejected with
    `ERR_TRAVEL_BLOCK_OUTSIDE_WINDOW` (HTTP 422)."

    Design: Corner/validations/visit_window_travel_block_and_team_composition_guards_each_return_their_own_error
    """
    scenario = _draft_visit_awaiting_its_aquatics_seat(api)

    # The block opens 2026-08-04, one day before the window.
    validate_error(
        _seat_attempt(
            api,
            scenario,
            "aquatics",
            TeamRole.SPECIALIST_AQUATICS,
            "2026-08-04",
            "2026-08-06",
        ),
        ApiErrorId.TRAVEL_BLOCK_OUTSIDE_WINDOW,
        422,
    )
    # trained_through_year 2025 is below the 2026 window year.
    validate_error(
        _seat_attempt(api, scenario, "lapsed", TeamRole.MEMBER, "2026-08-05", "2026-08-06"),
        ApiErrorId.VISITOR_TRAINING_EXPIRED,
        422,
    )
    # Training is current, but the roster status is read first and it is INACTIVE.
    validate_error(
        _seat_attempt(api, scenario, "retiree", TeamRole.MEMBER, "2026-08-05", "2026-08-06"),
        ApiErrorId.VISITOR_INACTIVE,
        409,
    )

    held = fx.read_visit(api, scenario.visit_id)
    assert held["team_size"] == 2
    assert held["status"] == VisitStatus.DRAFT
    seats, meta = fx.list_seats_for_visit(api, scenario.visit_id)
    assert meta["total_count"] == 2
    assert len(seats) == 2


def test_the_team_rule_blocks_the_schedule_until_the_specialist_domain_has_a_seat(api):
    """PRD §3.5: "And the team must be complete: `lead_visitor_id` must be non-null,
    `team_size` must be at least 2, and for every domain in `required_specialist_domains` an
    `ASSIGNED` seat must exist whose `team_role` is the matching specialist seat and whose
    visitor holds the matching endorsement — `SPECIALIST_AQUATICS` with `AQUATICS_SPECIALIST`
    for `AQUATICS`, `SPECIALIST_ADVENTURE` with `ADVENTURE_SPECIALIST` for `ADVENTURE`, and
    `SPECIALIST_HEALTH` with `HEALTH_SPECIALIST` for `HEALTH_WELLNESS`."

    Design: Corner/validations/visit_window_travel_block_and_team_composition_guards_each_return_their_own_error
    """
    scenario = _draft_visit_awaiting_its_aquatics_seat(api)
    assert scenario.visit["lead_visitor_id"] == scenario.visitor_id("lead")
    assert scenario.visit["team_size"] == 2

    # A lead and a member are seated, and the AQUATICS domain still has no matching seat.
    validate_error(
        api.schedule_visit(scenario.visit_id, OFFICER_ONE_HEADERS),
        ApiErrorId.TEAM_COMPOSITION_INCOMPLETE,
        422,
    )

    seat = validate_success(
        _seat_attempt(
            api,
            scenario,
            "aquatics",
            TeamRole.SPECIALIST_AQUATICS,
            "2026-08-05",
            "2026-08-07",
        ),
        201,
    )
    assert seat["team_role"] == TeamRole.SPECIALIST_AQUATICS

    scheduled = validate_success(api.schedule_visit(scenario.visit_id, OFFICER_ONE_HEADERS))
    assert scheduled["status"] == VisitStatus.SCHEDULED
    assert scheduled["team_size"] == 3
    assert fx.read_cycle(api, scenario.cycle_id)["status"] == CycleStatus.VISIT_SCHEDULED


def test_arrival_after_the_window_closes_is_refused_and_the_visit_stays_scheduled(api):
    """PRD §3.6: "the logical clock's calendar date must fall inside the agreed window counting
    both endpoints, or the request is refused with `ERR_OUTSIDE_VISIT_WINDOW` (HTTP 422)."

    Design: Corner/validations/visit_window_travel_block_and_team_composition_guards_each_return_their_own_error
    """
    scenario = _draft_visit_awaiting_its_aquatics_seat(api)
    validate_success(
        _seat_attempt(
            api,
            scenario,
            "aquatics",
            TeamRole.SPECIALIST_AQUATICS,
            "2026-08-05",
            "2026-08-07",
        ),
        201,
    )
    fx.confirm_visit(api, scenario.visit_id)

    fx.set_clock(api, "2026-08-20T00:00:00Z")
    validate_error(
        api.start_visit(scenario.visit_id, make_visitor_headers(scenario.visitor_id("lead"))),
        ApiErrorId.OUTSIDE_VISIT_WINDOW,
        422,
    )

    held = fx.read_visit(api, scenario.visit_id)
    assert held["status"] == VisitStatus.SCHEDULED
    assert held["scored_at"] is None
