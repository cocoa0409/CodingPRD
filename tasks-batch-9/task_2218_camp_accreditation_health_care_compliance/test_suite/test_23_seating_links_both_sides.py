"""One seating write lands on three rows at once - the seat, the visit's lead pointer and team
size, and the visitor's travel ledger - and the closed-interval day count is what every counter
agrees on."""

from __future__ import annotations

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_travel_days_conserved,
    assert_visit_assignment,
    find_by,
)
from test_helpers.test_users import OFFICER_ONE_HEADERS
from test_helpers.types import (
    AssignmentStatus,
    CampType,
    Certification,
    HealthStaffingLevel,
    PopulationServed,
    StandardDomain,
    TeamRole,
    VisitStatus,
)
from prd_bench_local_runner.testing import validate_paginated

SEAT_STANDARDS = [
    fx.universal_mandatory_standard(
        "SU.1", domain=StandardDomain.SUPERVISION, scoring_weight=1
    )
]


def _draft_visit_with_no_seats_yet(api):
    """A DRAFT visit on a SELF_ASSESSMENT cycle and two ACTIVE visitors off the roster."""
    fx.reset_clock(api)
    scenario = fx.open_cycle_scenario(
        api,
        edition_code="ACA-2026-SEAT",
        standards=SEAT_STANDARDS,
        camp={
            "name": "Seating Camp",
            "camp_type": CampType.DAY,
            "state_code": "OH",
            "population_served": PopulationServed.YOUTH_ONLY,
            "health_staffing_level": HealthStaffingLevel.FIRST_AIDER_ONLY,
        },
    )
    scenario.visit = fx.open_visit(
        api, scenario.cycle_id, window_start_date="2026-08-01", window_end_date="2026-08-07"
    )
    scenario.visitors["lead"] = fx.add_visitor(
        api, "Seat Lead", certifications=[Certification.LEAD_VISITOR]
    )
    scenario.visitors["member"] = fx.add_visitor(api, "Seat Member")
    assert scenario.visit["team_size"] == 0
    assert scenario.visit["lead_visitor_id"] is None
    return scenario


def _seat_the_lead(api, scenario):
    return fx.seat_visitor(
        api,
        scenario.visit_id,
        scenario.visitor_id("lead"),
        TeamRole.LEAD,
        "2026-08-01",
        "2026-08-03",
    )


def _seat_the_member(api, scenario):
    return fx.seat_visitor(
        api,
        scenario.visit_id,
        scenario.visitor_id("member"),
        TeamRole.MEMBER,
        "2026-08-02",
        "2026-08-06",
    )


def test_the_lead_seat_sets_the_visit_pointer_and_the_visitors_ledger_together(api):
    """PRD §3.5: "Seats begin in `status` `ASSIGNED` with `withdrawal_reason` null; creating one
    recomputes the visitor's `committed_travel_days` and the visit's `team_size`, and a `LEAD`
    seat sets the visit's `lead_visitor_id`."

    Design: Corner/endpoints/seating_a_visitor_links_both_sides_and_the_derived_counters_agree
    """
    scenario = _draft_visit_with_no_seats_yet(api)
    seat = _seat_the_lead(api, scenario)

    assert_visit_assignment(seat)
    assert seat["visit_id"] == scenario.visit_id
    assert seat["visitor_id"] == scenario.visitor_id("lead")
    assert seat["team_role"] == TeamRole.LEAD
    assert seat["status"] == AssignmentStatus.ASSIGNED
    assert seat["withdrawal_reason"] is None
    assert seat["travel_days"] == 3

    visit = fx.read_visit(api, scenario.visit_id)
    assert visit["team_size"] == 1
    assert visit["lead_visitor_id"] == scenario.visitor_id("lead")
    assert visit["status"] == VisitStatus.DRAFT
    assert fx.read_visitor(api, scenario.visitor_id("lead"))["committed_travel_days"] == 3


def test_a_travel_block_is_counted_on_the_closed_interval(api):
    """PRD §3.5: "The seat's `travel_days` is computed as the inclusive day count from the start
    of the block to its end, that is the difference in whole days plus one, and is therefore
    always at least 1."

    Design: Corner/endpoints/seating_a_visitor_links_both_sides_and_the_derived_counters_agree
    """
    scenario = _draft_visit_with_no_seats_yet(api)
    _seat_the_lead(api, scenario)
    seat = _seat_the_member(api, scenario)

    # 2026-08-02 through 2026-08-06 counts both endpoints, so five days and not four.
    assert seat["travel_days"] == 5
    assert seat["team_role"] == TeamRole.MEMBER

    visit = fx.read_visit(api, scenario.visit_id)
    assert visit["team_size"] == 2
    # A MEMBER seat never moves the lead pointer.
    assert visit["lead_visitor_id"] == scenario.visitor_id("lead")


def test_the_seat_collection_is_reachable_from_the_visit_it_belongs_to(api):
    """PRD §2.3: "Visits accept `cycle_id`, `lead_visitor_id` and `status`; team seats accept
    `visit_id`, `visitor_id`, `team_role` and `status`."

    Design: Corner/endpoints/seating_a_visitor_links_both_sides_and_the_derived_counters_agree
    """
    scenario = _draft_visit_with_no_seats_yet(api)
    lead_seat = _seat_the_lead(api, scenario)
    member_seat = _seat_the_member(api, scenario)

    rows, meta = validate_paginated(
        api.list_visit_assignments(
            {"visit_id": scenario.visit_id, "status": AssignmentStatus.ASSIGNED},
            OFFICER_ONE_HEADERS,
        )
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert len(rows) == 2
    assert find_by(rows, id=lead_seat["id"], team_role=TeamRole.LEAD) is not None
    assert find_by(rows, id=member_seat["id"], travel_days=5) is not None


def test_each_visitor_accumulates_only_the_days_of_their_own_seats(api):
    """PRD §2.8: "A visitor's `committed_travel_days` is always the sum of `travel_days` over
    that visitor's team seats whose `status` is `ASSIGNED` or `COMPLETED`"

    Design: Corner/endpoints/seating_a_visitor_links_both_sides_and_the_derived_counters_agree
    """
    scenario = _draft_visit_with_no_seats_yet(api)
    _seat_the_lead(api, scenario)
    _seat_the_member(api, scenario)

    lead = fx.read_visitor(api, scenario.visitor_id("lead"))
    member = fx.read_visitor(api, scenario.visitor_id("member"))
    assert lead["committed_travel_days"] == 3
    assert member["committed_travel_days"] == 5

    assert_travel_days_conserved(
        lead, fx.list_seats_for_visitor(api, scenario.visitor_id("lead"))[0]
    )
    assert_travel_days_conserved(
        member, fx.list_seats_for_visitor(api, scenario.visitor_id("member"))[0]
    )
