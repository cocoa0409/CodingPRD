"""Logging hours, closing a phase, delivering, and the locks that follow."""

from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    assert_hours,
    assert_money,
    assert_pct,
    complete_phase,
    create_assignment,
    create_client,
    create_engagement,
    create_partner,
    create_phase,
    create_senior,
    create_time_entry,
    create_time_entry_payload,
    deliver_engagement,
    drive_assignment_to_active,
    make_engagement_staff_headers,
    read_assignment,
    read_engagement,
    read_phase,
    read_realization,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def _active_booking_world(
    api,
    expected_hours=20.00,
    allocated_hours=20.00,
    end_date="2026-08-10",
    clock="2026-08-05T09:00:00Z",
):
    """One senior booked onto one fieldwork phase and driven to ACTIVE."""

    set_clock(api, clock)
    client = create_client(api, name="Meridian Manufacturing")
    partner = create_partner(api)
    senior = create_senior(api)
    engagement = create_engagement(api, client["id"], partner["id"])
    phase = create_phase(
        api,
        engagement["id"],
        expected_hours=expected_hours,
        window_start_date="2026-08-03",
        window_end_date="2026-08-31",
    )
    assignment = create_assignment(
        api,
        phase["id"],
        senior["id"],
        start_date="2026-08-03",
        end_date=end_date,
        allocated_hours=allocated_hours,
    )
    drive_assignment_to_active(api, engagement["id"], phase["id"], assignment["id"])
    return {
        "client": client,
        "partner": partner,
        "senior": senior,
        "engagement": engagement,
        "phase": phase,
        "assignment": assignment,
    }


class TestDeliveryPreconditions:
    """Delivery is a transition out of IN_FIELDWORK and nowhere else."""

    def test_the_signing_partner_may_not_deliver_a_setup_engagement(
        self, api, partner_headers_for
    ):
        """Ownership is satisfied, so the refusal can only be about the state.

        PRD 3.9: "The engagement's own partner closes the season by delivering an
        `IN_FIELDWORK` engagement, advancing it to `DELIVERED`. Every phase of the
        engagement must be `COMPLETE` first, and the acting `X-User-ID` must equal
        the engagement's `engagement_partner_staff_id`."

        PRD 2.10: "`ERR_ENGAGEMENT_INVALID_STATE` when an engagement is not in a
        state its requested transition allows (including `DELIVERED` terminal
        lockdown)"

        Design: Corner/state_machines/deliver_from_setup_engagement_rejected_with_engagement_invalid_state
        """

        set_clock(api, "2026-08-03T09:00:00Z")
        client = create_client(api, name="Meridian Manufacturing")
        partner = create_partner(api)
        engagement = create_engagement(api, client["id"], partner["id"])
        assert engagement["status"] == "SETUP"

        validate_error(
            api.deliver_engagement(
                engagement["id"], partner_headers_for(partner["id"])
            ),
            ApiErrorId.ENGAGEMENT_INVALID_STATE.value,
            409,
        )

        after = read_engagement(api, engagement["id"])
        assert after["status"] == "SETUP"
        assert after["version"] == 1


class TestDeliveredIsTerminal:
    """Once delivered, the engagement accepts nothing further."""

    def test_a_delivered_engagement_refuses_a_client_block(self, api, manager_headers):
        """Reporting a block is legal from two states, and DELIVERED is not one.

        PRD 3.9: "`DELIVERED` is terminal: the engagement accepts no further
        transition, and a delivered engagement also stops counting toward its
        client's `engagement_count`."

        PRD 2.10: "`ERR_ENGAGEMENT_INVALID_STATE` when an engagement is not in a
        state its requested transition allows (including `DELIVERED` terminal
        lockdown)"

        Design: Corner/state_machines/delivered_engagement_terminal_state_rejects_client_block
        """

        world = _active_booking_world(api)
        complete_phase(api, world["phase"]["id"])
        delivered = deliver_engagement(
            api, world["engagement"]["id"], world["partner"]["id"]
        )
        assert delivered["status"] == "DELIVERED"

        validate_error(
            api.report_client_block(
                world["engagement"]["id"],
                manager_headers,
                reason_note="Client cannot produce the trial balance",
            ),
            ApiErrorId.ENGAGEMENT_INVALID_STATE.value,
            409,
        )

        after = read_engagement(api, world["engagement"]["id"])
        assert after["status"] == "DELIVERED"
        assert after["client_block_count"] == 0
        assert after["pre_block_status"] is None


class TestPhaseCompletion:
    """Closing a phase carries its live bookings and the fee analysis with it."""

    def test_completing_the_phase_bubbles_its_active_booking(self, api, manager_headers):
        """The booking reaches COMPLETED without anyone calling it directly.

        PRD 3.7: "On success every `ACTIVE` booking on the phase advances `ACTIVE →
        COMPLETED` and increments its own `version`, the engagement's
        `realization_pct_provisional` and `realization_pct_final` are both
        recomputed, and the phase's `version` increments. `COMPLETE` is terminal
        for a phase."

        Design: Corner/state_machines/phase_complete_bubbles_active_assignment_to_completed_and_reconciles_realization
        """

        world = _active_booking_world(api)
        create_time_entry(
            api,
            world["assignment"]["id"],
            world["senior"]["id"],
            work_date="2026-08-04",
            hours=10.00,
        )

        completed = validate_success(
            api.complete_phase(world["phase"]["id"], manager_headers)
        )
        assert completed["staffing_status"] == "COMPLETE"
        assert_hours(completed["staffed_hours"], 20.00)
        assert_hours(completed["unstaffed_hours"], 0.00)

        booking = read_assignment(api, world["assignment"]["id"])
        assert booking["staffing_status"] == "COMPLETED"
        assert booking["review_status"] == "NOT_REQUIRED"

    def test_completion_reconciles_both_realization_variants(self, api):
        """Twenty booked hours and ten logged hours give two different answers.

        PRD 3.9: "It draws **one line per booking**: the booking's
        `allocated_hours` multiplied by its effective rate, rounded to two
        decimals. Those per-booking lines are summed and the sum rounded to two
        decimals to give the provisional standard value; the percentage is the
        engagement's `budget_fee_amount` divided by that value, multiplied by 100,
        rounded to two decimals."

        PRD 3.9: "It draws **one line per time entry**: the entry's `hours`
        multiplied by the effective rate of its booking, rounded to two decimals.
        Those per-entry lines are summed and the sum rounded to two decimals to
        give the final standard value, and the percentage is computed the same
        way."

        PRD 3.9: "Onshore work carries a factor of 1.00; offshore and
        shared-service work is valued at 0.55, a little over half the standard
        rate, which is exactly why the staffing model changes the reported answer."

        Design: Corner/state_machines/phase_complete_bubbles_active_assignment_to_completed_and_reconciles_realization
        """

        world = _active_booking_world(api)
        create_time_entry(
            api,
            world["assignment"]["id"],
            world["senior"]["id"],
            work_date="2026-08-04",
            hours=10.00,
        )
        complete_phase(api, world["phase"]["id"])

        analysis = read_realization(api, world["engagement"]["id"])
        assert_hours(analysis["committed_hours_total"], 20.00)
        assert_money(analysis["standard_value_provisional"], 3600.00)
        assert_pct(analysis["realization_pct_provisional"], 166.67)
        assert_hours(analysis["logged_hours_total"], 10.00)
        assert_money(analysis["standard_value_final"], 1800.00)
        assert_pct(analysis["realization_pct_final"], 333.33)


class TestCompletedBookingIsLocked:
    """A booking that completed through the phase cannot be unwound."""

    def test_releasing_a_completed_booking_runs_no_compensation(
        self, api, manager_headers
    ):
        """Release is reachable from PROPOSED or CONFIRMED, never from COMPLETED.

        PRD 2.10: "`ERR_ASSIGNMENT_INVALID_STATE` for a booking's staffing
        dimension (including `COMPLETED` and `RELEASED` lockdown, and covering a
        time entry logged against a booking that is neither `ACTIVE` nor
        `COMPLETED`)"

        PRD 3.7: "On success every `ACTIVE` booking on the phase advances `ACTIVE →
        COMPLETED` and increments its own `version`, the engagement's
        `realization_pct_provisional` and `realization_pct_final` are both
        recomputed, and the phase's `version` increments. `COMPLETE` is terminal
        for a phase."

        Design: Corner/state_machines/release_of_completed_assignment_rejected_by_terminal_lockdown
        """

        world = _active_booking_world(api)
        complete_phase(api, world["phase"]["id"])

        validate_error(
            api.release_assignment(
                world["assignment"]["id"],
                manager_headers,
                reason_note="Client asked to drop the senior",
            ),
            ApiErrorId.ASSIGNMENT_INVALID_STATE.value,
            409,
        )

        assert read_assignment(api, world["assignment"]["id"])["staffing_status"] == (
            "COMPLETED"
        )
        phase_after = read_phase(api, world["phase"]["id"])
        assert_hours(phase_after["staffed_hours"], 20.00)
        assert_hours(phase_after["unstaffed_hours"], 0.00)


class TestTimeEntryImmutability:
    """A logged entry is a fact, not a row to be edited."""

    def test_a_logged_entry_carries_no_version_and_no_updated_at(
        self, api, manager_headers
    ):
        """The sub-resource listing exposes only what was worked, nothing revisable.

        PRD 3.7: "An `EngagementStaff` logs a **TimeEntry** against their own
        booking, supplying the `assignment_id`, the `work_date` on which the hours
        were worked, the `hours` (between 0.25 and 16.00 inclusive), and an
        `entry_type` of `EXECUTION`, `REVIEW` or `REWORK`."

        PRD 3.7: "Time entries are immutable and append-only."

        Design: Corner/entities/time_entry_is_immutable_with_no_version_field
        """

        world = _active_booking_world(api)
        entry = create_time_entry(
            api,
            world["assignment"]["id"],
            world["senior"]["id"],
            work_date="2026-08-04",
            hours=4.00,
        )

        rows, meta = validate_paginated(
            api.list_assignment_time_entries(
                world["assignment"]["id"], manager_headers
            )
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1

        row = rows[0]
        assert row["id"] == entry["id"]
        assert row["assignment_id"] == world["assignment"]["id"]
        assert row["work_date"] == "2026-08-04"
        assert_hours(row["hours"], 4.00)
        assert row["entry_type"] == "EXECUTION"
        assert "version" not in row
        assert "updated_at" not in row


class TestTimeEntryGates:
    """The occupied dates and the quarter-overrun ceiling each stand alone."""

    def _logging_world(self, api):
        world = _active_booking_world(
            api,
            expected_hours=12.00,
            allocated_hours=12.00,
            end_date="2026-08-08",
            clock="2026-08-03T09:00:00Z",
        )
        create_time_entry(
            api,
            world["assignment"]["id"],
            world["senior"]["id"],
            work_date="2026-08-03",
            hours=12.00,
        )
        return world

    def test_the_end_date_itself_is_not_an_occupied_date(self, api):
        """A booking running to the eighth was never worked on the eighth.

        PRD 3.7: "The `work_date` must be one of the booking's occupied dates — on
        or after `start_date` and strictly before `end_date` — or the entry is
        refused with `ERR_TIME_ENTRY_OUT_OF_WINDOW`."

        PRD 2.5: "A booking's occupation of a staff member's calendar is
        **half-open**: it covers `start_date` through the day before `end_date`,
        and `end_date` itself is never occupied."

        Design: Corner/validations/time_entry_window_and_allocation_ceiling_each_reject_their_own_case
        """

        world = self._logging_world(api)

        validate_error(
            api.create_time_entry(
                create_time_entry_payload(
                    world["assignment"]["id"],
                    work_date="2026-08-08",
                    hours=1.00,
                ),
                make_engagement_staff_headers(world["senior"]["id"]),
            ),
            ApiErrorId.TIME_ENTRY_OUT_OF_WINDOW.value,
            422,
        )

        rows, meta = validate_paginated(
            api.list_assignment_time_entries(
                world["assignment"]["id"],
                make_engagement_staff_headers(world["senior"]["id"]),
            )
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1

    def test_the_quarter_overrun_ceiling_bites_one_hour_before_it_is_reached(
        self, api, manager_headers
    ):
        """Twelve plus four breaks the fifteen-hour ceiling; twelve plus three sits on it.

        PRD 3.7: "Finally, the firm tolerates a quarter of overrun but no more: the
        total logged `hours` for the booking including the new entry may not exceed
        its `allocated_hours` multiplied by 1.25, and a breach is refused with
        `ERR_TIME_ENTRY_EXCEEDS_ALLOCATION`."

        Design: Corner/validations/time_entry_window_and_allocation_ceiling_each_reject_their_own_case
        """

        world = self._logging_world(api)
        staff_headers = make_engagement_staff_headers(world["senior"]["id"])

        validate_error(
            api.create_time_entry(
                create_time_entry_payload(
                    world["assignment"]["id"],
                    work_date="2026-08-04",
                    hours=4.00,
                ),
                staff_headers,
            ),
            ApiErrorId.TIME_ENTRY_EXCEEDS_ALLOCATION.value,
            409,
        )

        accepted = validate_success(
            api.create_time_entry(
                create_time_entry_payload(
                    world["assignment"]["id"],
                    work_date="2026-08-04",
                    hours=3.00,
                ),
                staff_headers,
            ),
            201,
        )
        assert_hours(accepted["hours"], 3.00)

        rows, meta = validate_paginated(
            api.list_assignment_time_entries(
                world["assignment"]["id"], manager_headers
            )
        )
        assert meta["total_count"] == 2
        assert len(rows) == 2
