"""Difficulty Rule 8 — resource_temporal_overlap.

Half-open interval overlap on the LeaveCase parent (adjacency allowed; pairwise
overlap rejected), and aggregate-capacity (count of RECORDED intervals per
calendar month bounded by intermittent_frequency_per_month).
"""
from test_helpers import (
    ApiErrorId,
    create_interval_payload,
    record_interval,
    set_clock,
    setup_active_case_with_first_interval,
    setup_approved_case,
    TEST_USERS,
    validate_error,
)


class TestLeaveIntervalOverlapHalfOpenWithAdjacencyAllowed:
    """PRD §3.6: HALF-OPEN semantics — start_datetime == other.end_datetime is
    allowed (adjacent); start strictly before other.end AND end strictly after
    other.start is rejected.
    """

    def test_adjacent_interval_at_other_end_is_accepted(self, api):
        """PRD §3.6: "the rule rejects any new interval whose `start_datetime` is strictly before another's `end_datetime` and whose `end_datetime` is strictly after the other's `start_datetime`, returning `ERR_INTERVAL_OVERLAP`; adjacency (where the new `start_datetime` equals an existing `end_datetime`) is allowed."

        Design: Difficulty/resource_temporal_overlap/leave_interval_overlap_half_open_with_adjacency_allowed
        """
        bundle = setup_active_case_with_first_interval(
            employer_state="FED",
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-08-15T00:00:00.000Z",
            interval_start="2026-06-01T00:00:00.000Z",
            interval_end="2026-06-08T00:00:00.000Z",
            interval_hours=40,
            cert_expected_duration_weeks=10,
        )
        # Adjacent interval [2026-06-08T00:00, 2026-06-15T00:00) — start equals
        # the existing end. Must be ACCEPTED.
        second = record_interval(
            bundle["case"]["id"],
            "2026-06-08T00:00:00.000Z",
            "2026-06-15T00:00:00.000Z",
            40,
        )
        assert second["id"], "adjacent interval (start == other.end) must be accepted"
        assert second["status"] == "RECORDED"

    def test_overlapping_interval_by_one_minute_is_rejected(self, api):
        """PRD §3.6: "the rule rejects any new interval whose `start_datetime` is strictly before another's `end_datetime` and whose `end_datetime` is strictly after the other's `start_datetime`, returning `ERR_INTERVAL_OVERLAP`"

        Design: Difficulty/resource_temporal_overlap/leave_interval_overlap_half_open_with_adjacency_allowed
        """
        bundle = setup_active_case_with_first_interval(
            employer_state="FED",
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-08-15T00:00:00.000Z",
            interval_start="2026-06-01T00:00:00.000Z",
            interval_end="2026-06-08T00:00:00.000Z",
            interval_hours=40,
            cert_expected_duration_weeks=10,
        )
        # Overlapping by 1 minute: [2026-06-07T23:59, 2026-06-09T00:00).
        # start < other.end (2026-06-08) AND end > other.start (2026-06-01) → reject.
        res = api.create_interval(
            create_interval_payload(
                bundle["case"]["id"],
                "2026-06-07T23:59:00.000Z",
                "2026-06-09T00:00:00.000Z",
                8,
            ),
            TEST_USERS["hr_admin_headers"],
        )
        validate_error(res, ApiErrorId.ERR_INTERVAL_OVERLAP)


class TestIntermittentMonthlyFrequencyCap:
    """PRD §3.6: count of RECORDED intervals in the calendar month containing
    start_datetime, including the new interval, must not exceed
    CertificationRecord.intermittent_frequency_per_month.
    """

    def test_third_interval_in_month_exceeds_frequency_cap(self, api):
        """PRD §3.6: "For `INTERMITTENT` and `REDUCED_SCHEDULE` cases, the count of `RECORDED` intervals already in the calendar month containing `start_datetime`, including this new interval, must not exceed the authoritative certification's `intermittent_frequency_per_month` — otherwise the call is rejected with `ERR_INTERMITTENT_FREQUENCY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/intermittent_monthly_frequency_cap_aggregate_overlap
        """
        bundle = setup_approved_case(
            employer_state="FED",
            qualifying_reason="OWN_SERIOUS_HEALTH_CONDITION",
            leave_type="INTERMITTENT",
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-12-01T00:00:00.000Z",
            cert_expected_duration_weeks=26,
            cert_intermittent_frequency_per_month=2,
            cert_intermittent_hours_per_episode=8,
        )
        set_clock("2026-06-01T00:00:00.000Z")
        # Two existing RECORDED intervals in 2026-06.
        record_interval(
            bundle.case["id"],
            "2026-06-02T00:00:00.000Z",
            "2026-06-02T08:00:00.000Z",
            8,
        )
        record_interval(
            bundle.case["id"],
            "2026-06-16T00:00:00.000Z",
            "2026-06-16T08:00:00.000Z",
            8,
        )
        # Third interval in 2026-06 — count including this one (3) > 2 — must reject.
        res = api.create_interval(
            create_interval_payload(
                bundle.case["id"],
                "2026-06-25T00:00:00.000Z",
                "2026-06-25T08:00:00.000Z",
                8,
            ),
            TEST_USERS["hr_admin_headers"],
        )
        validate_error(res, ApiErrorId.ERR_INTERMITTENT_FREQUENCY_EXCEEDED)

    def test_third_interval_in_next_month_succeeds(self, api):
        """PRD §3.6: "the count of `RECORDED` intervals already in the calendar month containing `start_datetime`, including this new interval, must not exceed the authoritative certification's `intermittent_frequency_per_month`"

        Design: Difficulty/resource_temporal_overlap/intermittent_monthly_frequency_cap_aggregate_overlap
        """
        # Same setup but the third interval falls in a DIFFERENT calendar month —
        # the per-month cap resets and the interval succeeds.
        bundle = setup_approved_case(
            employer_state="FED",
            qualifying_reason="OWN_SERIOUS_HEALTH_CONDITION",
            leave_type="INTERMITTENT",
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-12-01T00:00:00.000Z",
            cert_expected_duration_weeks=26,
            cert_intermittent_frequency_per_month=2,
            cert_intermittent_hours_per_episode=8,
        )
        set_clock("2026-06-01T00:00:00.000Z")
        record_interval(
            bundle.case["id"],
            "2026-06-02T00:00:00.000Z",
            "2026-06-02T08:00:00.000Z",
            8,
        )
        record_interval(
            bundle.case["id"],
            "2026-06-16T00:00:00.000Z",
            "2026-06-16T08:00:00.000Z",
            8,
        )
        # Third interval in 2026-07: must be accepted (new month).
        third = record_interval(
            bundle.case["id"],
            "2026-07-02T00:00:00.000Z",
            "2026-07-02T08:00:00.000Z",
            8,
        )
        assert third["id"], (
            "first interval of a new calendar month under per-month cap must succeed"
        )
        assert third["status"] == "RECORDED"
