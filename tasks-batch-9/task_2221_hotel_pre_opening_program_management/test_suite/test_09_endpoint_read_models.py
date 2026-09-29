"""Endpoint read models and action responses.

Each test drives one documented endpoint and checks that the body it answers
with is the recomputed read model the PRD describes — the readiness breakdown,
the three-way budget split, the two ends of an orientation enrolment, a
schedule replay and the guarantee gate on the commercial dimension.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import fixtures
from test_helpers.api_client import PreOpeningApiClient
from test_helpers.api_errors import ERR_BOOKING_NOT_OPEN
from test_helpers.assertions import (
    assert_cents,
    assert_page,
    assert_program_dimensions,
    assert_ratio,
)
from test_helpers.constants import CODE_CONSTRUCTION_COMPLETE, DEFAULT_NOW
from test_helpers.factories import (
    assign_orientation_payload,
    budget_line_payload,
    hire_payload,
    hiring_plan_payload,
    training_session_payload,
)
from test_helpers.test_users import (
    COMMERCIAL_DIRECTOR,
    CONSTRUCTION_MANAGER,
    PROGRAM_DIRECTOR,
    QUALITY_INSPECTOR,
    TALENT_MANAGER,
)

# The instant the single construction milestone is completed at.
COMPLETION_INSTANT = "2026-10-01T00:00:00Z"

# Thirty days of construction from 2026-09-01 finish on 2026-10-01, and the
# program's fourteen licensing buffer days carry the projection to 2026-10-15.
PROJECTED_OPENING = "2026-10-15"


def _cobalt_at_construction_complete(api: PreOpeningApiClient) -> Dict[str, Any]:
    """The Cobalt Bay program driven to CONSTRUCTION_COMPLETE on one milestone.

    A single thirty-day CONSTRUCTION_COMPLETE milestone planned from
    2026-09-01, baselined by one director, started at the anchor instant and
    completed once the clock has moved to 2026-10-01.
    """
    fixtures.set_clock(api, DEFAULT_NOW)
    return fixtures.construction_complete_program(
        api, finish_iso=COMPLETION_INSTANT, duration_days=30
    )


class TestReadinessReadModel:
    """The computed readiness breakdown on a program with no children."""

    def test_readiness_components_are_recomputed_from_empty_denominators(
        self, api: PreOpeningApiClient
    ) -> None:
        """A program that has finished construction but registered no system, no
        hiring plan and no permit still answers the readiness read. All three
        empty-denominator ratios read 0.0 while the schedule term reads 1.0, so
        the weighted score is exactly the schedule weight.

        `readiness_score` is the systems ratio weighted at 0.30, plus the staffing ratio weighted at 0.25, plus the permit ratio weighted at 0.25, plus the schedule term weighted at 0.20, rounded half up to four decimal places.

        Design: Corner/endpoints/readiness_read_model_matches_the_recomputed_components_after_baselining
        """
        built = _cobalt_at_construction_complete(api)
        program_id = built["program"]["id"]

        readiness = validate_success(
            api.get_readiness(program_id, QUALITY_INSPECTOR), 200
        )

        assert_ratio(readiness["systems_ratio"], 0.0)
        assert_ratio(readiness["staffing_ratio"], 0.0)
        assert_ratio(readiness["permit_ratio"], 0.0)
        assert readiness["schedule_slip_days"] == 0
        assert_ratio(readiness["schedule_term"], 1.0)
        assert_ratio(readiness["readiness_score"], 0.2)
        assert readiness["readiness_posture"] == "MOBILIZING"
        assert readiness["projected_opening_date_optimistic"] == PROJECTED_OPENING
        assert readiness["projected_opening_date_committed"] == PROJECTED_OPENING
        assert readiness["variant_gap_days"] == 0
        assert_cents(readiness["cost_at_completion_commitment_cents"], 0)
        assert_cents(readiness["cost_at_completion_accrual_cents"], 0)
        assert_cents(readiness["payroll_accrual_cents"], 0)
        assert_cents(readiness["contingency_liability_cents"], 0)
        assert readiness["committed_room_nights"] == 0


class TestBudgetLineReadModel:
    """Authorizing budget lines and reading them back through the filter."""

    def test_category_filter_narrows_the_budget_line_listing(
        self, api: PreOpeningApiClient
    ) -> None:
        """Two spend categories are authorized on one program, a payroll line of
        three million cents and a marketing line of five hundred thousand. Read
        back with the category filter, the listing carries only the marketing
        row and counts only the rows matching that filter.

        The budget lines of a program can be read with that three-way split, filtered by `category`.

        Design: Corner/endpoints/budget_line_create_then_list_filtered_by_category
        """
        fixtures.set_clock(api, DEFAULT_NOW)
        program = fixtures.make_program(api)

        payroll = validate_success(
            api.create_budget_line(
                budget_line_payload(
                    program["id"], category="PAYROLL", authorized_cents=3000000
                ),
                PROGRAM_DIRECTOR,
            ),
            201,
        )
        assert_cents(payroll["authorized_cents"], 3000000)
        assert_cents(payroll["available_cents"], 3000000)
        assert_cents(payroll["committed_cents"], 0)
        assert_cents(payroll["spent_cents"], 0)

        marketing = validate_success(
            api.create_budget_line(
                budget_line_payload(
                    program["id"], category="MARKETING", authorized_cents=500000
                ),
                PROGRAM_DIRECTOR,
            ),
            201,
        )
        assert_cents(marketing["available_cents"], 500000)

        rows, meta = validate_paginated(
            api.list_budget_lines(
                program["id"], PROGRAM_DIRECTOR, {"category": "MARKETING"}
            )
        )
        assert_page(meta, total_count=1, has_more=False)
        assert [row["id"] for row in rows] == [marketing["id"]]
        assert rows[0]["category"] == "MARKETING"


class TestOrientationAssignmentLink:
    """One call writes both ends of a hire-to-session enrolment."""

    def test_assigning_an_orientation_links_the_hire_and_fills_a_seat(
        self, api: PreOpeningApiClient
    ) -> None:
        """A rooms hire is offered without an orientation seat, then enrolled in
        the rooms orientation session after the fact. The hire gains the session
        identifier and the session's seat count rises from zero to one, and both
        ends are visible from their own read endpoints.

        Assigning an orientation to a hire supplies a new `orientation_session_id`; the previous session's `enrolled_count` falls by one and the new session's rises by one.

        Design: Corner/endpoints/assign_orientation_links_hire_to_session_and_bumps_enrolled_count
        """
        fixtures.set_clock(api, DEFAULT_NOW)
        program = fixtures.make_program(api)
        plan = validate_success(
            api.create_hiring_plan(
                hiring_plan_payload(
                    program["id"],
                    department="ROOMS",
                    headcount_target=4,
                    wave_start_date="2026-09-10",
                ),
                TALENT_MANAGER,
            ),
            201,
        )
        session = validate_success(
            api.create_training_session(
                training_session_payload(
                    program["id"],
                    title="Rooms orientation",
                    training_room_code="TR-1",
                    starts_at="2026-09-14T09:00:00Z",
                    ends_at="2026-09-14T12:00:00Z",
                    capacity=5,
                    department="ROOMS",
                ),
                TALENT_MANAGER,
            ),
            201,
        )
        assert session["enrolled_count"] == 0

        hire = validate_success(
            api.create_hire(
                hire_payload(
                    plan["id"],
                    full_name="A. Keeper",
                    hourly_rate_cents=2500,
                    scheduled_hours_per_day=8,
                    start_date="2026-09-15",
                ),
                TALENT_MANAGER,
            ),
            201,
        )
        assert hire["orientation_session_id"] is None

        assigned = validate_success(
            api.assign_orientation(
                hire["id"],
                assign_orientation_payload(session["id"]),
                TALENT_MANAGER,
            ),
            200,
        )
        assert assigned["orientation_session_id"] == session["id"]

        sessions, _ = validate_paginated(
            api.list_training_sessions(program["id"], TALENT_MANAGER)
        )
        enrolled = next(row for row in sessions if row["id"] == session["id"])
        assert enrolled["enrolled_count"] == 1

        hires, hires_meta = validate_paginated(
            api.list_hires(TALENT_MANAGER, {"orientation_session_id": session["id"]})
        )
        assert_page(hires_meta, total_count=1, has_more=False)
        assert [row["id"] for row in hires] == [hire["id"]]


class TestScheduleRecompute:
    """Replaying the schedule arithmetic over unchanged rows."""

    def test_recompute_repeats_the_dates_and_leaves_the_delivery_state_alone(
        self, api: PreOpeningApiClient
    ) -> None:
        """The schedule of a program that has finished construction is replayed
        over exactly the same stored rows. Both projections and the slip come
        back unchanged and the delivery dimension does not move, yet the replay
        is a write that advances the program's version by one.

        A separate recomputation capability, available to both the `ProgramDirector` and the `ConstructionManager`, re-runs the same schedule arithmetic in both variants **without** changing the delivery dimension, refreshing the floats, the slip, the posture, the contingency liability and both cost-at-completion figures, and likewise incrementing the program's `version` by one.

        Design: Corner/endpoints/recompute_schedule_reproduces_the_same_dates_without_changing_schedule_state
        """
        built = _cobalt_at_construction_complete(api)
        program_id = built["program"]["id"]
        milestone_id = built["milestones"][CODE_CONSTRUCTION_COMPLETE]["id"]
        version_before = fixtures.program_version(api, program_id)

        recomputed = validate_success(
            api.recompute_schedule(program_id, CONSTRUCTION_MANAGER), 200
        )

        assert recomputed["projected_opening_date_committed"] == PROJECTED_OPENING
        assert recomputed["projected_opening_date_optimistic"] == PROJECTED_OPENING
        assert recomputed["schedule_slip_days"] == 0
        assert recomputed["critical_path_milestone_count"] == 1
        assert recomputed["schedule_state"] == "CONSTRUCTION_COMPLETE"
        assert recomputed["version"] == version_before + 1

        milestone = validate_success(
            api.get_milestone(milestone_id, CONSTRUCTION_MANAGER), 200
        )
        assert milestone["earliest_finish_date"] == "2026-10-01"
        assert milestone["is_critical"] is True


class TestGuaranteeGate:
    """A guarantee needs the commercial dimension to be accepting bookings."""

    def test_guarantee_waits_for_booking_to_reopen_then_adds_the_penalty(
        self, api: PreOpeningApiClient
    ) -> None:
        """A crew block of five rooms for two nights is accepted while booking is
        open, then booking is suspended. The unchanged guarantee call is refused
        while the property is not selling and succeeds once booking reopens,
        adding the flat guarantee penalty on top of the relocation subtotal.

        Guaranteeing a block moves it `ACCEPTED → GUARANTEED`, requires the commercial dimension to be `BOOKING_OPEN` (else `ERR_BOOKING_NOT_OPEN`) and the posture not to be `FROZEN` (else `ERR_PROGRAM_FROZEN`), and reruns the contingency computation so that this block's `contingency_cents` gains the program's `guarantee_penalty_cents` and the program's `contingency_liability_cents` is recomputed.

        Design: Corner/endpoints/guarantee_is_allowed_only_while_the_commercial_dimension_is_booking_open
        """
        built = _cobalt_at_construction_complete(api)
        program_id = built["program"]["id"]
        fixtures.open_booking(api, program_id)
        block = fixtures.make_block(
            api,
            program_id,
            account_name="Harborline Crew",
            arrival_date="2026-10-05",
            night_count=2,
            room_count=5,
            rate_cents=20000,
        )
        # Ten room-nights at 25000 cents give a base of 250000, below the five
        # thousand dollar tier limit, so the fee is five percent: 12500 cents.
        assert_cents(block["contingency_cents"], 262500)
        fixtures.suspend_booking(api, program_id)

        refused = api.guarantee_block(block["id"], COMMERCIAL_DIRECTOR)
        validate_error(refused, ERR_BOOKING_NOT_OPEN, 409)

        reopened = validate_success(
            api.open_booking(program_id, COMMERCIAL_DIRECTOR), 200
        )
        assert reopened["commercial_state"] == "BOOKING_OPEN"

        guaranteed = validate_success(
            api.guarantee_block(block["id"], COMMERCIAL_DIRECTOR), 200
        )
        assert guaranteed["state"] == "GUARANTEED"
        assert_cents(guaranteed["contingency_cents"], 412500)

        program = fixtures.read_program(api, program_id)
        assert_program_dimensions(
            program,
            schedule_state="CONSTRUCTION_COMPLETE",
            commercial_state="BOOKING_OPEN",
        )
        assert_cents(program["contingency_liability_cents"], 412500)
        assert program["committed_room_nights"] == 10
