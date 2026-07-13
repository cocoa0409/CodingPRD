"""Repository-appointment scheduling: researcher buffered-exclusive interval and
repository aggregate-capacity interval."""
from test_helpers import (
    validate_error, get_success_data, TEST_USERS,
    setup_project_with_booked_appointment, setup_repo_capacity_scenario, book_appointment,
    api_client,
)

PM = TEST_USERS["project_manager_headers"]


# ==========================================================================
# resource_temporal_overlap / researcher_buffered_exclusive_overlap
# ==========================================================================
class TestResearcherBufferedExclusive:
    """PRD §3.6: a booking within 30 minutes of another BOOKED appointment for the
    same researcher is rejected with ERR_RESEARCHER_UNAVAILABLE."""

    def test_booking_15_minutes_after_within_buffer_rejected(self):
        """PRD §3.6: "a new booking may not fall within 30 minutes — the researcher
        buffer — of another `BOOKED` appointment for that researcher, so a proposed
        window whose start-to-end interval, padded by that buffer, touches an
        existing booked interval for the researcher is rejected with
        `ERR_RESEARCHER_UNAVAILABLE`."

        Design: Difficulty/resource_temporal_overlap/researcher_buffered_exclusive_overlap
        """
        client, researcher, project, repo, appt = setup_project_with_booked_appointment(
            concurrent_capacity=5, start_utc="2026-04-01T09:00:00Z",
            end_utc="2026-04-01T10:00:00Z")
        # Second booking starts 10:15 — 15 minutes after the first ends (inside 30-min buffer).
        resp = book_appointment(project["id"], researcher["id"], repo["id"],
                                start_utc="2026-04-01T10:15:00Z", end_utc="2026-04-01T11:00:00Z")
        validate_error(resp, "ERR_RESEARCHER_UNAVAILABLE")

    def test_booking_15_minutes_before_within_buffer_rejected(self):
        """PRD §3.6: "a new booking may not fall within 30 minutes — the researcher
        buffer — of another `BOOKED` appointment for that researcher, so a proposed
        window whose start-to-end interval, padded by that buffer, touches an
        existing booked interval for the researcher is rejected with
        `ERR_RESEARCHER_UNAVAILABLE`."

        Design: Difficulty/resource_temporal_overlap/researcher_buffered_exclusive_overlap
        """
        client, researcher, project, repo, appt = setup_project_with_booked_appointment(
            concurrent_capacity=5, start_utc="2026-04-01T09:00:00Z",
            end_utc="2026-04-01T10:00:00Z")
        # Second booking ends 08:45 — 15 minutes before the first starts (inside 30-min buffer).
        resp = book_appointment(project["id"], researcher["id"], repo["id"],
                                start_utc="2026-04-01T08:00:00Z", end_utc="2026-04-01T08:45:00Z")
        validate_error(resp, "ERR_RESEARCHER_UNAVAILABLE")


# ==========================================================================
# resource_temporal_overlap / repository_aggregate_capacity_overlap
# ==========================================================================
class TestRepositoryAggregateCapacity:
    """PRD §3.6: a booking that would push time-overlapping BOOKED appointments at a
    repository above its concurrent_capacity is rejected with
    ERR_REPOSITORY_AT_CAPACITY (a distinct researcher, so no buffer interaction)."""

    def test_partial_overlap_over_capacity_rejected(self):
        """PRD §3.6: "a booking that would push the count of time-overlapping
        `BOOKED` appointments at that repository above the repository's
        `concurrent_capacity` is rejected with `ERR_REPOSITORY_AT_CAPACITY`."

        Design: Difficulty/resource_temporal_overlap/repository_aggregate_capacity_overlap
        """
        client, r1, r2, project, repo, appt1 = setup_repo_capacity_scenario(
            concurrent_capacity=1, start_utc="2026-04-01T09:00:00Z",
            end_utc="2026-04-01T10:00:00Z")
        # Different researcher, window partially overlaps the first -> exceeds capacity 1.
        resp = book_appointment(project["id"], r2["id"], repo["id"],
                                start_utc="2026-04-01T09:30:00Z", end_utc="2026-04-01T10:30:00Z")
        validate_error(resp, "ERR_REPOSITORY_AT_CAPACITY")

    def test_contained_overlap_over_capacity_rejected(self):
        """PRD §3.6: "a booking that would push the count of time-overlapping
        `BOOKED` appointments at that repository above the repository's
        `concurrent_capacity` is rejected with `ERR_REPOSITORY_AT_CAPACITY`."

        Design: Difficulty/resource_temporal_overlap/repository_aggregate_capacity_overlap
        """
        client, r1, r2, project, repo, appt1 = setup_repo_capacity_scenario(
            concurrent_capacity=1, start_utc="2026-04-01T09:00:00Z",
            end_utc="2026-04-01T10:00:00Z")
        # Different researcher, window fully inside the first -> still exceeds capacity 1.
        resp = book_appointment(project["id"], r2["id"], repo["id"],
                                start_utc="2026-04-01T09:15:00Z", end_utc="2026-04-01T09:45:00Z")
        validate_error(resp, "ERR_REPOSITORY_AT_CAPACITY")
