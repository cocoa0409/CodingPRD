"""Two interval-overlap rules with deliberately different endpoint semantics.

Monitoring windows are half-open and touch legally; appraisal engagements are
closed intervals widened by a buffer on both ends. Both rules also exclude
intervals held by rows in the wrong status.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    APPRAISER_USER_ID,
    APPRAISER_USER_ID_ALT,
    TEST_USERS,
    ApiErrorId,
    api_client,
    cancel_visit,
    complete_visit,
    engage_appraisal,
    engage_appraisal_payload,
    read_appraisal,
    review_appraisal_payload,
    schedule_visit,
    schedule_visit_payload,
    set_clock,
    setup_filed_application,
    setup_recorded_easement,
    submit_appraisal,
)

ADMIN = TEST_USERS["program_admin_headers"]
OFFICER = TEST_USERS["acquisition_officer_headers"]
REVIEWER = TEST_USERS["appraisal_reviewer_headers"]
MONITOR = TEST_USERS["stewardship_monitor_headers"]


def _easement_with_a_scheduled_window() -> dict:
    """A recorded easement holding one SCHEDULED visit over 06-10 to 06-17."""
    scenario = setup_recorded_easement()
    set_clock("2027-06-01T00:00:00Z")
    scenario["visit"] = schedule_visit(
        scenario["easement"]["id"],
        window_start="2027-06-10T00:00:00Z",
        window_end="2027-06-17T00:00:00Z",
    )
    assert scenario["visit"]["status"] == "SCHEDULED"
    return scenario


def _schedule(easement_id: str, start: str, end: str):
    return api_client.schedule_monitoring_visit(
        schedule_visit_payload(easement_id, window_start=start, window_end=end),
        MONITOR,
    )


class TestMonitoringWindowOverlap:
    """Half-open windows: touching endpoints are allowed, interiors are not."""

    def test_a_window_overlapping_the_interior_is_rejected(self):
        """Strict-before on both sides means a shared interior collides.

        PRD §3.8: "Windows of visits on the same easement may not overlap, and
        because the window is half-open the test is that the new window's start
        falls strictly before an existing window's end while that existing
        window's start falls strictly before the new window's end; back-to-back
        visits touching at a single instant are therefore allowed."

        Design: Difficulty/resource_temporal_overlap/monitoring_visit_windows_are_half_open_and_cancelled_visits_free_the_window
        """
        scenario = _easement_with_a_scheduled_window()
        response = _schedule(
            scenario["easement"]["id"],
            "2027-06-16T00:00:00Z",
            "2027-06-20T00:00:00Z",
        )
        validate_error(response, ApiErrorId.ERR_MONITORING_WINDOW_OVERLAP.value)

    def test_back_to_back_windows_touching_at_one_instant_are_allowed(self):
        """A new window starting exactly at the old end does not overlap.

        PRD §3.8: "back-to-back visits touching at a single instant are therefore
        allowed."

        Design: Difficulty/resource_temporal_overlap/monitoring_visit_windows_are_half_open_and_cancelled_visits_free_the_window
        """
        scenario = _easement_with_a_scheduled_window()
        adjacent = validate_success(
            _schedule(
                scenario["easement"]["id"],
                "2027-06-17T00:00:00Z",
                "2027-06-24T00:00:00Z",
            ),
            201,
        )
        assert adjacent["status"] == "SCHEDULED"
        assert adjacent["window_start"].startswith("2027-06-17")
        assert adjacent["completed_at"] is None
        assert adjacent["observed_impervious_sqft"] is None
        assert adjacent["finding"] is None
        assert adjacent["cancellation_reason"] is None

        # And a window ending exactly at the old start is equally admissible.
        preceding = validate_success(
            _schedule(
                scenario["easement"]["id"],
                "2027-06-03T00:00:00Z",
                "2027-06-10T00:00:00Z",
            ),
            201,
        )
        assert preceding["status"] == "SCHEDULED"

    def test_cancelling_a_visit_frees_its_window(self):
        """A CANCELLED visit stops occupying the interval it held.

        PRD §3.8: "Only visits whose `status` is `SCHEDULED` occupy a window —
        `COMPLETED` and `CANCELLED` visits never block — and an overlap is
        rejected with `ERR_MONITORING_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/monitoring_visit_windows_are_half_open_and_cancelled_visits_free_the_window
        """
        scenario = _easement_with_a_scheduled_window()
        easement_id = scenario["easement"]["id"]

        blocked = _schedule(
            easement_id, "2027-06-16T00:00:00Z", "2027-06-20T00:00:00Z"
        )
        validate_error(blocked, ApiErrorId.ERR_MONITORING_WINDOW_OVERLAP.value)

        cancelled = cancel_visit(scenario["visit"]["id"])
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancellation_reason"] == "weather closed the access lane"

        replacement = validate_success(
            _schedule(easement_id, "2027-06-16T00:00:00Z", "2027-06-20T00:00:00Z"),
            201,
        )
        assert replacement["status"] == "SCHEDULED"

    def test_completing_a_visit_also_frees_its_window(self):
        """A COMPLETED visit stops occupying the interval it held.

        PRD §3.8: "Only visits whose `status` is `SCHEDULED` occupy a window —
        `COMPLETED` and `CANCELLED` visits never block — and an overlap is
        rejected with `ERR_MONITORING_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/monitoring_visit_windows_are_half_open_and_cancelled_visits_free_the_window
        """
        scenario = _easement_with_a_scheduled_window()
        easement_id = scenario["easement"]["id"]

        set_clock("2027-06-12T00:00:00Z")
        completed = complete_visit(scenario["visit"]["id"], 0)
        assert completed["status"] == "COMPLETED"
        assert completed["finding"] == "NO_ISSUE"

        replacement = validate_success(
            _schedule(easement_id, "2027-06-16T00:00:00Z", "2027-06-20T00:00:00Z"),
            201,
        )
        assert replacement["status"] == "SCHEDULED"


def _application_with_one_engagement(program_overrides=None) -> dict:
    """A filed application carrying one ASSIGNED engagement over 08-12 to 08-26."""
    scenario = setup_filed_application(program_overrides=program_overrides)
    scenario["appraisal"] = engage_appraisal(scenario["application"]["id"])
    assert scenario["appraisal"]["status"] == "ASSIGNED"
    assert scenario["appraisal"]["engagement_start"].startswith("2026-08-12")
    assert scenario["appraisal"]["engagement_end"].startswith("2026-08-26")
    return scenario


def _engage(application_id: str, start: str, end: str, appraiser=APPRAISER_USER_ID_ALT):
    return api_client.engage_appraisal(
        application_id,
        engage_appraisal_payload(
            appraiser_user_id=appraiser,
            appraiser_firm="Conestoga Land Economics",
            engagement_start=start,
            engagement_end=end,
        ),
        OFFICER,
    )


class TestAppraisalEngagementBuffer:
    """A closed interval widened forward by `appraisal_engagement_buffer_days`."""

    def test_a_start_inside_the_buffer_conflicts(self):
        """The default three-day buffer pushes the exclusion out to 08-29.

        PRD §3.4: "Two engagements conflict when the new engagement's start falls
        at or before the existing engagement's end extended forward by the buffer,
        and simultaneously the existing engagement's start falls at or before the
        new engagement's end extended forward by the buffer."

        Design: Difficulty/resource_temporal_overlap/appraisal_engagements_are_closed_intervals_widened_by_a_three_day_buffer
        """
        scenario = _application_with_one_engagement()
        assert scenario["program"]["appraisal_engagement_buffer_days"] == 3

        # 2026-08-26 extended forward by three days is 2026-08-29 inclusive.
        response = _engage(
            scenario["application"]["id"],
            "2026-08-29T00:00:00Z",
            "2026-09-05T00:00:00Z",
        )
        validate_error(response, ApiErrorId.ERR_APPRAISAL_ENGAGEMENT_CONFLICT.value)

    def test_a_start_one_day_past_the_buffer_is_admitted(self):
        """One day beyond the widened end clears the test on the first clause.

        PRD §3.4: "Engagements on the same application must not conflict, and the
        conflict test is a closed-interval comparison widened symmetrically by the
        program's `appraisal_engagement_buffer_days`."

        Design: Difficulty/resource_temporal_overlap/appraisal_engagements_are_closed_intervals_widened_by_a_three_day_buffer
        """
        scenario = _application_with_one_engagement()
        second = validate_success(
            _engage(
                scenario["application"]["id"],
                "2026-08-30T00:00:00Z",
                "2026-09-06T00:00:00Z",
            ),
            201,
        )
        assert second["status"] == "ASSIGNED"
        assert second["basis"] == "CERTIFIED_APPRAISAL_BASIS"
        assert second["submission_count"] == 0
        assert second["easement_value_cents"] is None

        appraisals = validate_success(
            api_client.list_appraisals(
                scenario["application"]["id"], ADMIN, {"limit": 100}
            )
        )
        assert len(appraisals) == 2

    def test_a_zero_buffer_narrows_the_exclusion_to_the_closed_interval(self):
        """With the buffer at zero the interval is exactly closed.

        PRD §3.1: "`appraisal_engagement_buffer_days` is the buffer padded
        symmetrically onto both ends of an appraisal engagement for conflict
        detection; it lies between 0 and 30 days and defaults to 3."

        Design: Difficulty/resource_temporal_overlap/appraisal_engagements_are_closed_intervals_widened_by_a_three_day_buffer
        """
        scenario = _application_with_one_engagement(
            program_overrides={"appraisal_engagement_buffer_days": 0}
        )
        application_id = scenario["application"]["id"]

        # The existing end itself is still closed, so 08-26 collides.
        collides = _engage(
            application_id, "2026-08-26T00:00:00Z", "2026-09-02T00:00:00Z"
        )
        validate_error(collides, ApiErrorId.ERR_APPRAISAL_ENGAGEMENT_CONFLICT.value)

        # One day later there is nothing left to widen it.
        admitted = validate_success(
            _engage(application_id, "2026-08-27T00:00:00Z", "2026-09-03T00:00:00Z"),
            201,
        )
        assert admitted["status"] == "ASSIGNED"

    def test_a_rejected_appraisal_occupies_no_interval(self):
        """Only ASSIGNED, SUBMITTED and CERTIFIED appraisals hold an interval.

        PRD §3.4: "Only appraisals whose `status` is `ASSIGNED`, `SUBMITTED` or
        `CERTIFIED` occupy an interval; a `REJECTED` appraisal blocks nothing. A
        conflict is rejected with `ERR_APPRAISAL_ENGAGEMENT_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/appraisal_engagements_are_closed_intervals_widened_by_a_three_day_buffer
        """
        scenario = _application_with_one_engagement()
        application_id = scenario["application"]["id"]
        appraisal_id = scenario["appraisal"]["id"]

        # While it is merely SUBMITTED the interval still blocks.
        set_clock("2026-08-20T00:00:00Z")
        submit_appraisal(appraisal_id, APPRAISER_USER_ID)
        assert read_appraisal(appraisal_id)["status"] == "SUBMITTED"
        blocked = _engage(
            application_id, "2026-08-29T00:00:00Z", "2026-09-05T00:00:00Z"
        )
        validate_error(blocked, ApiErrorId.ERR_APPRAISAL_ENGAGEMENT_CONFLICT.value)

        rejected = validate_success(
            api_client.review_appraisal(
                appraisal_id,
                review_appraisal_payload("REJECT", review_note="comparables too thin"),
                REVIEWER,
            )
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["easement_value_cents"] is None

        admitted = validate_success(
            _engage(application_id, "2026-08-29T00:00:00Z", "2026-09-05T00:00:00Z"),
            201,
        )
        assert admitted["status"] == "ASSIGNED"
