"""Exactly on the line, and one unit past it."""
from test_helpers import (
    TEST_USERS,
    book_run,
    complete_run,
    post_change_order,
    read_budget_position,
    read_capacity_summary,
    read_ledger,
    read_project,
    set_logical_clock,
    setup_program_at_technical_rehearsal,
    setup_program_with_approved_package,
    validate_success,
)

OWNER = TEST_USERS["owner_rep_headers"]
CONTRACTOR = TEST_USERS["contractor_pm_headers"]
DESIGNER = TEST_USERS["creative_director_headers"]

BOUNDARY_STANDARD_SEGMENT = {
    "segment_label": "Switchback A", "length_meters": 106.25,
    "width_meters": 2.6, "routing_type": "STANDARD", "position_index": 1,
}
BOUNDARY_ACCESSIBLE_SEGMENT = {
    "segment_label": "Accessible Return", "length_meters": 56.25,
    "width_meters": 2.0, "routing_type": "ACCESSIBLE", "position_index": 2,
}


class TestRestrictedUtilisationThreshold:
    """3240000000 is OPEN; 3240000001 is RESTRICTED."""

    def test_committed_cost_exactly_on_the_threshold_leaves_the_posture_open(self):
        """Both comparisons are strict, so a committed cost exactly equal to the restricted-utilisation threshold leaves the programme `OPEN`, and a committed cost exactly equal to the ceiling does not freeze it.

        First the server computes the restricted-utilisation threshold,
        `restricted_utilisation_cents`, as the authorised `budget_ceiling_cents`
        multiplied by ninety percent and then rounded down to a whole number of
        cents.

        The approval committed 3080000000 against a 3600000000 ceiling, so a
        160000000 change order lands the committed cost exactly on the 3240000000
        threshold and the programme is still OPEN with 360000000 of headroom.

        Design: Difficulty/boundary_precision_check/restricted_utilisation_threshold_exact_equality_keeps_posture_open
        """
        ctx = setup_program_with_approved_package()

        post_change_order(ctx["project"]["id"], 160000000,
                          memo="Change order landing exactly on the utilisation threshold")

        budget = read_budget_position(ctx["project"]["id"])
        assert budget["restricted_utilisation_cents"] == 3240000000
        assert budget["committed_cost_cents"] == 3240000000
        assert budget["headroom_cents"] == 360000000
        assert budget["readiness_posture"] == "OPEN"
        assert read_project(ctx["project"]["id"])["readiness_posture"] == "OPEN"

    def test_one_cent_past_the_threshold_flips_the_posture_to_restricted(self):
        """Otherwise, if `open_major_finding_count` is greater than zero, or `committed_cost_cents` is strictly greater than `restricted_utilisation_cents`, the posture is `RESTRICTED`.

        The **committed basis** is a chronological replay: starting from zero, the
        server walks every ledger entry of the programme ordered by `created_at`
        ascending and then by `sequence_no` ascending, adding each entry's
        `amount_cents` to a running total, and the final total is
        `committed_cost_cents`.

        A single further cent carries the replayed total to 3240000001, one cent
        strictly above the threshold, which is all it takes to move the programme off
        OPEN; three entries now stand in the ledger.

        Design: Difficulty/boundary_precision_check/restricted_utilisation_threshold_exact_equality_keeps_posture_open
        """
        ctx = setup_program_with_approved_package()
        post_change_order(ctx["project"]["id"], 160000000,
                          memo="Change order landing exactly on the utilisation threshold")

        post_change_order(ctx["project"]["id"], 1,
                          memo="One cent past the utilisation threshold")

        programme = read_project(ctx["project"]["id"])
        budget = read_budget_position(ctx["project"]["id"])
        rows, meta = read_ledger(ctx["project"]["id"])
        assert programme["committed_cost_cents"] == 3240000001
        assert programme["readiness_posture"] == "RESTRICTED"
        assert budget["restricted_utilisation_cents"] == 3240000000
        assert budget["headroom_cents"] == 359999999
        assert len(rows) == 3
        assert meta["total_count"] == 3


class TestRehearsalPassThreshold:
    """1003 guests an hour passes; 1002 does not."""

    def _two_booked_runs(self):
        ctx = setup_program_at_technical_rehearsal()
        ctx["run_pass"] = book_run(ctx["project"]["id"])
        ctx["run_fail"] = book_run(
            ctx["project"]["id"], run_kind="CAST_REHEARSAL",
            window_start_utc="2026-08-01T15:00:00Z",
            window_end_utc="2026-08-01T17:00:00Z",
        )
        set_logical_clock("2026-08-01T17:00:00Z")
        return ctx

    def test_throughput_equal_to_the_threshold_passes(self):
        """And `result` is `PASS` when the measured throughput is greater than or equal to the threshold — the comparison is inclusive, so hitting the threshold exactly passes — and `FAIL` otherwise.

        `pass_threshold_guests` is the selected system's
        `operational_hourly_capacity_guests` multiplied by eighty-five percent,
        rounded *up* to a whole guest per hour.

        The commissioned system runs 1179 guests an hour derated, so the threshold
        rounds up to 1003; 1003 guests cycled in sixty minutes measures exactly 1003
        and the verdict is PASS.

        Design: Difficulty/boundary_precision_check/rehearsal_pass_threshold_inclusive_at_exact_equality
        """
        ctx = self._two_booked_runs()

        completed = complete_run(ctx["run_pass"]["id"], guests_cycled=1003,
                                 duration_minutes=60)

        assert completed["pass_threshold_guests"] == 1003
        assert completed["measured_hourly_throughput_guests"] == 1003
        assert completed["result"] == "PASS"
        assert completed["status"] == "COMPLETED"

    def test_one_guest_short_of_the_threshold_fails(self, api):
        """`measured_hourly_throughput_guests` is `guests_cycled` multiplied by sixty and divided by `duration_minutes`, rounded down to a whole guest per hour.

        When a run's `run_kind` is `SOFT_OPEN` and its `result` is `PASS`, the
        programme's `soft_open_validated` flag is set true and the programme's
        `version` advances by one; no other combination of kind and result touches
        it.

        The cast rehearsal cycles one guest fewer against the same 1003 threshold and
        fails, and neither verdict touches the programme's soft-open flag because
        neither run is a soft open.

        Design: Difficulty/boundary_precision_check/rehearsal_pass_threshold_inclusive_at_exact_equality
        """
        ctx = self._two_booked_runs()
        complete_run(ctx["run_pass"]["id"], guests_cycled=1003, duration_minutes=60)

        completed = complete_run(ctx["run_fail"]["id"], guests_cycled=1002,
                                 duration_minutes=60)

        assert completed["pass_threshold_guests"] == 1003
        assert completed["measured_hourly_throughput_guests"] == 1002
        assert completed["result"] == "FAIL"
        passing = validate_success(api.get_rehearsal_run(ctx["run_pass"]["id"], CONTRACTOR))
        assert passing["result"] == "PASS"
        assert read_project(ctx["project"]["id"])["soft_open_validated"] is False


class TestAccessibleShareThreshold:
    """A share of exactly 15.00 percent opens the rehearsal rung."""

    def _programme_on_the_accessible_boundary(self):
        return setup_program_at_technical_rehearsal(
            standard_segment=BOUNDARY_STANDARD_SEGMENT,
            accessible_segment=BOUNDARY_ACCESSIBLE_SEGMENT,
            project_overrides={"virtual_queue_share_pct": 25},
        )

    def test_a_share_of_exactly_fifteen_percent_permits_the_advance(self, api):
        """At least one segment of the programme must be `ACCEPTED` with `routing_type` `ACCESSIBLE`, or the advance is refused with `ERR_ACCESSIBLE_ROUTE_MISSING`; and the `accessible_share_pct` computed as above must be at least fifteen percent, or the advance is refused with `ERR_ACCESSIBLE_SHARE_INSUFFICIENT`.

        `accessible_share_pct` is exactly 0.00 when the total is zero, and otherwise
        the accessible capacity divided by the total capacity, multiplied by one
        hundred, rounded half up to two decimal places.

        A 425-guest standard switchback beside a 75-guest accessible return makes a
        500-guest queue whose accessible share is exactly 15.00, which is enough for
        the programme to reach technical rehearsal.

        Design: Difficulty/boundary_precision_check/accessible_share_exact_fifteen_percent_permits_technical_rehearsal
        """
        ctx = self._programme_on_the_accessible_boundary()

        standard = validate_success(
            api.get_queue_segment(ctx["standard_segment"]["id"], DESIGNER))
        accessible = validate_success(
            api.get_queue_segment(ctx["accessible_segment"]["id"], DESIGNER))
        programme = read_project(ctx["project"]["id"])
        summary = read_capacity_summary(ctx["project"]["id"])

        assert standard["capacity_guests"] == 425
        assert accessible["capacity_guests"] == 75
        assert programme["queue_capacity_total_guests"] == 500
        assert programme["design_phase"] == "TECHNICAL_REHEARSAL"
        assert summary["accessible_capacity_guests"] == 75
        assert float(summary["accessible_share_pct"]) == 15.00

    def test_the_summary_reports_the_queue_roll_ups_at_the_boundary(self):
        """`virtual_queue_allocation_guests` is the total capacity multiplied by `virtual_queue_share_pct` divided by one hundred, rounded down to a whole guest.

        `posted_wait_minutes` is exactly 0.0 when `selected_ride_system_id` is null or
        when the selected system's `operational_hourly_capacity_guests` is zero, and
        otherwise the total queue capacity divided by that derated hourly capacity,
        multiplied by sixty minutes, rounded half up to one decimal place.

        A quarter of the 500-guest queue is 125 virtual places, and the 500 guests
        against the derated 1179 an hour post a 25.4-minute wait.

        Design: Difficulty/boundary_precision_check/accessible_share_exact_fifteen_percent_permits_technical_rehearsal
        """
        ctx = self._programme_on_the_accessible_boundary()

        summary = read_capacity_summary(ctx["project"]["id"])

        assert summary["virtual_queue_allocation_guests"] == 125
        assert float(summary["posted_wait_minutes"]) == 25.4
        assert summary["operational_hourly_capacity_guests"] == 1179
