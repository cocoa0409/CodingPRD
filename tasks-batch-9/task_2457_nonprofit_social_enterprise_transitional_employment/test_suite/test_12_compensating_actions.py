"""The two compensating actions: voiding a delivered service, releasing a seat."""

from test_helpers import (
    CostEntryStatus,
    ReleasedReason,
    ShiftAssignmentStatus,
    SupportActivityStatus,
    WorkShiftStatus,
    assert_entry_allocation_complements,
    assert_hours,
    assert_instant_equals,
    assert_per_hour_cents,
    assert_period_ledger,
    assert_ratio,
    factories,
    fixtures,
    make_program_director_headers,
    validate_success,
)


class TestVoidingADeliveredSupportActivity:
    """A twelve-hour shift's ledger, plus a coaching session, then the void."""

    def _delivered_coaching_on_a_live_ledger(self, api):
        """A completed twelve-hour shift and one delivered coaching session of 12000."""
        program = fixtures.completed_shift_program(api)
        program["activity"] = fixtures.plan_support_activity(
            api, program["participant"]["id"], duration_minutes=90, cost_cents=12000
        )
        return program

    def test_delivery_adds_the_whole_cost_to_the_mission_side(self, api):
        """A mission-classified entry puts its whole amount on the mission side.

        "An entry classified `MISSION` puts its whole `amount_cents` into
        `allocated_mission_cents` and 0 into `allocated_business_cents`."

        Design: Difficulty/compensating_invariant/void_delivered_support_activity_restores_mission_ledger
        """
        program = self._delivered_coaching_on_a_live_ledger(api)
        period_id = program["subsidy_period"]["id"]

        before = fixtures.read_subsidy_period(api, period_id)
        assert_period_ledger(before, 4570, 15230, 19800)
        assert_ratio(before["mission_share"], 0.2308, "mission_share")
        assert_per_hour_cents(
            before["true_cost_per_trainee_hour_cents"],
            1650.00,
            "true_cost_per_trainee_hour_cents",
        )

        fixtures.deliver_support_activity(api, program["activity"]["id"])

        after = fixtures.read_subsidy_period(api, period_id)
        assert_period_ledger(after, 16570, 15230, 31800)
        assert_ratio(after["mission_share"], 0.2308, "mission_share")

    def test_voiding_restores_the_ledger_and_keeps_the_last_allocation(self, api):
        """A voided entry drops out of the aggregates but keeps its last figures.

        "A voided entry drops out of every period aggregate immediately, the
        period's `mission_cost_cents`, `business_operating_cost_cents`,
        `total_cost_cents` and both true-cost ratios are re-derived, the period's
        `version` is incremented by one, and the participant's
        `support_activity_minutes` and `delivered_coaching_count` are re-derived
        downward."

        Design: Difficulty/compensating_invariant/void_delivered_support_activity_restores_mission_ledger
        """
        program = self._delivered_coaching_on_a_live_ledger(api)
        period_id = program["subsidy_period"]["id"]
        fixtures.deliver_support_activity(api, program["activity"]["id"])
        entry_id = fixtures.list_cost_entries(
            api, {"source_activity_id": program["activity"]["id"]}
        )[0]["id"]

        voided_activity = validate_success(
            api.void_support_activity(
                program["activity"]["id"],
                factories.void_payload(),
                make_program_director_headers(),
            )
        )

        assert voided_activity["status"] == SupportActivityStatus.VOIDED

        entry = fixtures.read_cost_entry(api, entry_id)
        assert entry["status"] == CostEntryStatus.VOIDED
        assert_instant_equals(
            entry["voided_at"], "2026-09-07T20:00:00Z", "voided_at"
        )
        assert entry["allocated_mission_cents"] == 12000
        assert_entry_allocation_complements(entry)

        period = fixtures.read_subsidy_period(api, period_id)
        assert_period_ledger(period, 4570, 15230, 19800)
        assert_ratio(period["mission_share"], 0.2308, "mission_share")
        assert_per_hour_cents(
            period["true_cost_per_trainee_hour_cents"],
            1650.00,
            "true_cost_per_trainee_hour_cents",
        )

    def test_voiding_re_derives_the_participant_support_metrics_downward(self, api):
        """Voided activities never contribute to a participant's progress.

        "Voided activities and released assignments never contribute to anything."

        Design: Difficulty/compensating_invariant/void_delivered_support_activity_restores_mission_ledger
        """
        program = self._delivered_coaching_on_a_live_ledger(api)
        fixtures.deliver_support_activity(api, program["activity"]["id"])

        delivered_state = fixtures.read_participant(api, program["participant"]["id"])
        assert delivered_state["support_activity_minutes"] == 90
        assert delivered_state["delivered_coaching_count"] == 1

        validate_success(
            api.void_support_activity(
                program["activity"]["id"],
                factories.void_payload(),
                make_program_director_headers(),
            )
        )

        participant = fixtures.read_participant(api, program["participant"]["id"])
        assert participant["support_activity_minutes"] == 0
        assert participant["delivered_coaching_count"] == 0


class TestReleasingASeat:
    """Seating commits a seat and the week's hours; releasing gives both back."""

    def _seatable_twelve_hour_shift(self, api):
        program = fixtures.enrolled_participant_program(api)
        program["work_shift"] = fixtures.create_work_shift(
            api,
            program["business_line"]["id"],
            "2026-09-07T08:00:00Z",
            "2026-09-07T20:00:00Z",
        )
        return program

    def test_seating_commits_the_seat_and_the_week_hours(self, api):
        """A successful seating re-derives both counters at once.

        "A successful seating creates an assignment in `ASSIGNED` status with
        `actual_hours`, `wage_cost_cents` and `released_reason` all null and both
        `quality_defect_count` and `customer_complaint_count` at 0, then re-derives
        the shift's `assigned_count` and the participant's
        `scheduled_hours_current_week`."

        Design: Difficulty/compensating_invariant/release_shift_assignment_restores_seat_and_week_hours
        """
        program = self._seatable_twelve_hour_shift(api)

        before_shift = fixtures.read_work_shift(api, program["work_shift"]["id"])
        assert before_shift["assigned_count"] == 0
        before_participant = fixtures.read_participant(
            api, program["participant"]["id"]
        )
        assert_hours(
            before_participant["scheduled_hours_current_week"],
            0.000,
            "scheduled_hours_current_week",
        )

        assignment = fixtures.seat_participant(
            api, program["work_shift"]["id"], program["participant"]["id"]
        )

        assert assignment["status"] == ShiftAssignmentStatus.ASSIGNED
        assert assignment["actual_hours"] is None
        assert assignment["wage_cost_cents"] is None
        assert assignment["released_reason"] is None

        shift = fixtures.read_work_shift(api, program["work_shift"]["id"])
        assert shift["assigned_count"] == 1
        participant = fixtures.read_participant(api, program["participant"]["id"])
        assert_hours(
            participant["scheduled_hours_current_week"],
            12.000,
            "scheduled_hours_current_week",
        )

    def test_releasing_gives_the_seat_back_and_touches_no_cost(self, api):
        """Releasing an unworked seat leaves the mission ledger completely untouched.

        "Crucially, **no cost entry is created and none is voided** — releasing an
        unworked seat leaves the mission ledger completely untouched, because
        nothing was ever spent."

        Design: Difficulty/compensating_invariant/release_shift_assignment_restores_seat_and_week_hours
        """
        program = self._seatable_twelve_hour_shift(api)
        assignment = fixtures.seat_participant(
            api, program["work_shift"]["id"], program["participant"]["id"]
        )

        released = fixtures.release_assignment(api, assignment["id"])

        assert released["status"] == ShiftAssignmentStatus.RELEASED
        assert released["released_reason"] == ReleasedReason.MANUAL_RELEASE
        assert released["actual_hours"] is None
        assert released["wage_cost_cents"] is None

        shift = fixtures.read_work_shift(api, program["work_shift"]["id"])
        assert shift["assigned_count"] == 0
        assert shift["status"] == WorkShiftStatus.SCHEDULED

        participant = fixtures.read_participant(api, program["participant"]["id"])
        assert_hours(
            participant["scheduled_hours_current_week"],
            0.000,
            "scheduled_hours_current_week",
        )
        assert_hours(
            participant["transitional_hours_worked"],
            0.000,
            "transitional_hours_worked",
        )

        period_id = program["subsidy_period"]["id"]
        assert fixtures.cost_entry_count(api, {"subsidy_period_id": period_id}) == 0
        period = fixtures.read_subsidy_period(api, period_id)
        assert period["total_cost_cents"] == 0
