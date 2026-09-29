"""Two contended resources with deliberately opposite interval conventions."""

from test_helpers import (
    ApiErrorId,
    BILLING_ANALYST,
    FIELD_TECHNICIAN,
    activate_agreement,
    api_client,
    assert_agreement_state,
    assert_loop_state,
    capacity_sweep_stack,
    read_agreement,
    read_loop,
    read_work_order,
    submit_permit,
    validate_error,
    work_window_stack,
)


class TestHalfOpenReservationSweep:
    """The oversubscription ceiling is tested at every start-date boundary."""

    def test_the_live_peers_already_hold_twenty_two_thousand_kilowatts(self):
        """Three overlapping customers sit just under the 23000.00 kW ceiling.

        PRD: "A ceiling is first computed as the loop's `rated_capacity_kw`
        multiplied by an oversubscription factor of 1.15, rounded half-up to two
        decimal places — the utility is willing to sell 115 percent of nameplate on
        the assumption that no two buildings peak together."

        Design: Difficulty/resource_temporal_overlap/loop_capacity_ceiling_sweep_over_half_open_reservation_windows
        """
        stack = capacity_sweep_stack()

        assert_loop_state(read_loop(stack["loop"]["id"]), committed_reserved_kw=22000.0)

    def test_one_hundredth_of_a_kilowatt_over_the_ceiling_is_refused(self):
        """A boundary total of 23000.01 kW breaches a ceiling of 23000.00 kW.

        PRD: "If that total is **strictly greater** than the ceiling at any boundary,
        the activation is refused with `ERR_LOOP_CAPACITY_EXCEEDED`; a total exactly
        equal to the ceiling is permitted."

        Design: Difficulty/resource_temporal_overlap/loop_capacity_ceiling_sweep_over_half_open_reservation_windows
        """
        stack = capacity_sweep_stack()

        response = api_client.activate_connection_agreement(
            stack["over_ceiling"]["id"], {}, BILLING_ANALYST
        )

        validate_error(response, ApiErrorId.LOOP_CAPACITY_EXCEEDED)
        assert_agreement_state(
            read_agreement(stack["over_ceiling"]["id"]),
            contract_state="PENDING_CAPACITY",
        )
        assert_loop_state(read_loop(stack["loop"]["id"]), committed_reserved_kw=22000.0)

    def test_a_candidate_landing_exactly_on_the_ceiling_activates(self):
        """Equality passes, because the ceiling test is a strict greater-than.

        PRD: "At each boundary, the concurrent set is every interval whose
        `service_start_date` is at or before the boundary and whose
        `service_end_date` is strictly after it; the `reserved_capacity_kw` of that
        concurrent set is summed and rounded half-up to two decimal places."

        Design: Difficulty/resource_temporal_overlap/loop_capacity_ceiling_sweep_over_half_open_reservation_windows
        """
        stack = capacity_sweep_stack()
        api_client.activate_connection_agreement(
            stack["over_ceiling"]["id"], {}, BILLING_ANALYST
        )

        activated = activate_agreement(stack["at_ceiling"]["id"])

        assert_agreement_state(activated, contract_state="ACTIVE")
        assert_loop_state(read_loop(stack["loop"]["id"]), committed_reserved_kw=27000.0)

    def test_a_peer_ending_on_the_boundary_does_not_count_against_it(self):
        """The 4000 kW customer whose service closes on 1 June is excluded.

        PRD: "Because the intervals are half-open, an agreement ending exactly at a
        boundary does not overlap one starting at that boundary."

        Design: Difficulty/resource_temporal_overlap/loop_capacity_ceiling_sweep_over_half_open_reservation_windows
        """
        stack = capacity_sweep_stack()

        activate_agreement(stack["at_ceiling"]["id"])

        # Counting the departing 4000.00 kW peer would have put the 1 June boundary
        # at 27000.00 kW and refused this activation outright.
        assert_agreement_state(
            read_agreement(stack["ends_on_boundary"]["id"]), contract_state="ACTIVE"
        )
        assert read_agreement(stack["ends_on_boundary"]["id"])[
            "service_end_date"
        ].startswith("2026-06-01T00:00:00")
        assert_agreement_state(
            read_agreement(stack["at_ceiling"]["id"]), contract_state="ACTIVE"
        )


class TestClosedWorkWindowWithRefillBuffer:
    """One excavation per segment, with six hours added for refilling.

    The exclusion zone is closed at both ends, which is the opposite endpoint
    convention to the half-open reservation calendar.
    """

    def test_the_peer_job_is_in_the_conflict_input_set(self):
        """A permit-pending peer blocks; only drafts and closed jobs do not.

        PRD: "The peer set is every other work order on the same `segment_id` whose
        `work_state` is `PERMIT_PENDING`, `SCHEDULED`, `EXCAVATING`, `REPAIRING` or
        `BACKFILLED`; orders in `DRAFT`, `COMPLETED` or `CANCELLED` do not block."

        Design: Difficulty/resource_temporal_overlap/work_window_single_occupancy_with_six_hour_refill_buffer
        """
        stack = work_window_stack()

        assert read_work_order(stack["peer"]["id"])["work_state"] == "PERMIT_PENDING"

    def test_a_candidate_starting_exactly_on_the_buffered_end_conflicts(self):
        """Touching endpoints of closed intervals overlap, so 22:00 sharp is refused.

        PRD: "Two orders conflict when the candidate's `window_start` is at or before
        the peer's buffered end **and** the peer's `window_start` is at or before the
        candidate's buffered end; both comparisons are inclusive, so a candidate
        starting exactly at a peer's buffered end does conflict."

        Design: Difficulty/resource_temporal_overlap/work_window_single_occupancy_with_six_hour_refill_buffer
        """
        stack = work_window_stack()

        response = api_client.submit_work_order_permit(
            stack["on_buffer_end"]["id"], {}, FIELD_TECHNICIAN
        )

        validate_error(response, ApiErrorId.WORK_WINDOW_CONFLICT)

    def test_the_refused_candidate_stays_a_draft_with_a_pending_permit(self):
        """A blocked submission moves neither the work state nor the permit field.

        PRD: "**Submitting for permit** advances the order from `DRAFT` to
        `PERMIT_PENDING` and sets `permit_decision` to `PENDING`."

        Design: Difficulty/resource_temporal_overlap/work_window_single_occupancy_with_six_hour_refill_buffer
        """
        stack = work_window_stack()

        api_client.submit_work_order_permit(
            stack["on_buffer_end"]["id"], {}, FIELD_TECHNICIAN
        )

        refused = read_work_order(stack["on_buffer_end"]["id"])
        assert refused["work_state"] == "DRAFT"
        assert refused["permit_decision"] == "PENDING"

    def test_one_minute_past_the_buffered_end_clears_the_segment(self):
        """The six-hour refill window closes at 22:00, so 22:01 is free.

        PRD: "Each window's `window_end` is extended by a six-hour refill buffer —
        the time it takes to re-fill and re-pressurise the segment after the ground
        is closed — before the overlap test."

        Design: Difficulty/resource_temporal_overlap/work_window_single_occupancy_with_six_hour_refill_buffer
        """
        stack = work_window_stack()
        api_client.submit_work_order_permit(
            stack["on_buffer_end"]["id"], {}, FIELD_TECHNICIAN
        )

        submitted = submit_permit(stack["after_buffer_end"]["id"], FIELD_TECHNICIAN)

        assert submitted["work_state"] == "PERMIT_PENDING"
        assert submitted["permit_decision"] == "PENDING"

    def test_the_stranded_draft_never_blocks_the_later_candidate(self):
        """Its window overlaps, but a draft is not in the conflict input set.

        PRD: "orders in `DRAFT`, `COMPLETED` or `CANCELLED` do not block."

        Design: Difficulty/resource_temporal_overlap/work_window_single_occupancy_with_six_hour_refill_buffer
        """
        stack = work_window_stack()
        api_client.submit_work_order_permit(
            stack["on_buffer_end"]["id"], {}, FIELD_TECHNICIAN
        )

        submit_permit(stack["after_buffer_end"]["id"], FIELD_TECHNICIAN)

        assert read_work_order(stack["on_buffer_end"]["id"])["work_state"] == "DRAFT"
        assert (
            read_work_order(stack["after_buffer_end"]["id"])["work_state"]
            == "PERMIT_PENDING"
        )
