"""Closing a period can suspend a line, cancel its future shifts and free their seats."""

from test_helpers import (
    AllocationBasis,
    BusinessLineStatus,
    IntakePosture,
    ReleasedReason,
    ShiftAssignmentStatus,
    SubsidyPeriodStatus,
    WorkShiftStatus,
    assert_hours,
    assert_ratio,
    fixtures,
    validate_paginated,
    make_case_manager_headers,
)


def _line_about_to_burn_its_cap(api):
    """A line whose lifetime subsidy ceiling is only 2000 cents.

    A completed twelve-hour shift in September builds the ledger, and a seated
    October shift stands ready to be cancelled once the line is suspended.
    """
    program = fixtures.completed_shift_program(
        api, line_overrides={"subsidy_cap_cents": 2000}
    )
    october_shift = fixtures.create_work_shift(
        api,
        program["business_line"]["id"],
        "2026-10-02T08:00:00Z",
        "2026-10-02T12:00:00Z",
    )
    fixtures.set_clock(api, "2026-10-01T00:00:00Z")
    october_assignment = fixtures.seat_participant(
        api, october_shift["id"], program["participant"]["id"]
    )
    program["october_shift"] = october_shift
    program["october_assignment"] = october_assignment
    return program


class TestPeriodCloseCascade:
    """The five hops of a close, on a line that breaches its subsidy cap."""

    def test_close_freezes_the_basis_and_computes_the_draw(self, api):
        """The first hop closes the period and computes margin, rate and draw.

        "The first hop sets `status` to `CLOSED`, stamps `closed_at` from the
        logical clock, stores `revenue_cents`, freezes `allocation_basis` to the
        requested basis, re-derives `mission_share` and every posted entry's
        `allocated_mission_cents` and `allocated_business_cents` under that final
        basis, re-derives `mission_cost_cents`, `business_operating_cost_cents`,
        `total_cost_cents` and both per-trainee-hour ratios, and increments the
        period's `version` by one."

        Design: Difficulty/transitive_cascade/period_close_suspends_line_cancels_shift_releases_seat
        """
        program = _line_about_to_burn_its_cap(api)

        closed = fixtures.close_subsidy_period(
            api, program["subsidy_period"]["id"], AllocationBasis.HOURS, 250000
        )

        assert closed["status"] == SubsidyPeriodStatus.CLOSED
        assert closed["allocation_basis"] == AllocationBasis.HOURS
        assert closed["revenue_cents"] == 250000
        assert_ratio(closed["mission_share"], 0.2308, "mission_share")
        assert closed["mission_cost_cents"] == 4570
        assert closed["business_operating_cost_cents"] == 15230
        assert closed["total_cost_cents"] == 19800
        assert_ratio(closed["margin_pct"], 0.9391, "margin_pct")
        assert closed["subsidy_rate"] == 0.50
        assert closed["subsidy_draw_cents"] == 2285

    def test_a_draw_past_the_cap_suspends_the_line_and_shuts_intake(self, api):
        """The third hop fires only when the running total strictly exceeds the cap.

        "The third hop fires only when that running total now **strictly exceeds**
        the line's `subsidy_cap_cents`: the line moves `LAUNCHED → SUSPENDED`, its
        `intake_posture` is re-derived to `CLOSED` because posture only opens for a
        launched line, and its `version` is incremented by one."

        Design: Difficulty/transitive_cascade/period_close_suspends_line_cancels_shift_releases_seat
        """
        program = _line_about_to_burn_its_cap(api)

        fixtures.close_subsidy_period(
            api, program["subsidy_period"]["id"], AllocationBasis.HOURS, 250000
        )

        line = fixtures.read_business_line(api, program["business_line"]["id"])
        assert line["cumulative_subsidy_cents"] == 2285
        assert line["subsidy_cap_cents"] == 2000
        assert line["status"] == BusinessLineStatus.SUSPENDED
        assert line["intake_posture"] == IntakePosture.CLOSED

    def test_suspension_cancels_future_shifts_and_releases_their_seats(self, api):
        """The fourth and fifth hops reach the shift calendar and the week hours.

        "The fourth hop follows from the suspension: every work shift of that line
        still in `SCHEDULED` status whose `starts_at` is after the logical clock's
        current instant moves `SCHEDULED → CANCELLED`, processed in order of
        `starts_at` ascending and then `created_at` ascending." and "The fifth hop
        follows from those cancellations: on each cancelled shift, every assignment
        still in `ASSIGNED` status moves `ASSIGNED → RELEASED` with
        `released_reason` set to `SHIFT_CANCELLED`, and each affected participant's
        `scheduled_hours_current_week` is re-derived."

        Design: Difficulty/transitive_cascade/period_close_suspends_line_cancels_shift_releases_seat
        """
        program = _line_about_to_burn_its_cap(api)
        before = fixtures.read_participant(api, program["participant"]["id"])
        assert_hours(
            before["scheduled_hours_current_week"],
            4.000,
            "scheduled_hours_current_week",
        )

        fixtures.close_subsidy_period(
            api, program["subsidy_period"]["id"], AllocationBasis.HOURS, 250000
        )

        october_shift = fixtures.read_work_shift(api, program["october_shift"]["id"])
        assert october_shift["status"] == WorkShiftStatus.CANCELLED

        assignment = fixtures.read_shift_assignment(
            api, program["october_assignment"]["id"]
        )
        assert assignment["status"] == ShiftAssignmentStatus.RELEASED
        assert assignment["released_reason"] == ReleasedReason.SHIFT_CANCELLED

        after = fixtures.read_participant(api, program["participant"]["id"])
        assert_hours(
            after["scheduled_hours_current_week"],
            0.000,
            "scheduled_hours_current_week",
        )

    def test_the_already_worked_september_shift_is_left_alone(self, api):
        """A shift that has already started keeps the work it recorded.

        "Shifts that have already started are left alone so that work genuinely
        performed can still be recorded."

        Design: Difficulty/transitive_cascade/period_close_suspends_line_cancels_shift_releases_seat
        """
        program = _line_about_to_burn_its_cap(api)

        fixtures.close_subsidy_period(
            api, program["subsidy_period"]["id"], AllocationBasis.HOURS, 250000
        )

        september_shift = fixtures.read_work_shift(api, program["work_shift"]["id"])
        assert september_shift["status"] == WorkShiftStatus.CLOSED
        assert september_shift["billable_labor_cost_cents"] == 19800

        assignment = fixtures.read_shift_assignment(api, program["assignment"]["id"])
        assert assignment["status"] == ShiftAssignmentStatus.COMPLETED
        assert assignment["wage_cost_cents"] == 19800

        rows, meta = validate_paginated(
            api.list_shift_assignments(
                make_case_manager_headers(),
                {"work_shift_id": program["work_shift"]["id"]},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == program["assignment"]["id"]
