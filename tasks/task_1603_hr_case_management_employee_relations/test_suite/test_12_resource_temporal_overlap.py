"""Resource temporal overlap tests (Difficulty rule 8)."""
import pytest

from test_helpers import (
    api_client,
    TEST_USERS,
    make_investigator_headers,
    setup_intake_channel,
    setup_employee,
    setup_investigator,
    setup_investigating_case,
    schedule_interview,
    setup_holiday,
    set_clock,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
)


class TestInterviewHalfOpenOverlap:
    def test_adjacent_endpoints_do_not_overlap(self):
        """PRD §3.3: "Overlap is judged on half-open windows — each window
        contains its start instant but not its end instant — so the windows
        overlap precisely when each one's start falls strictly before the
        other's end, while two windows that merely touch at an endpoint do not
        conflict."

        Design: Difficulty/resource_temporal_overlap/interview_half_open_adjacency_not_overlap
        """
        set_clock("2026-08-05T00:00:00Z")
        channel = setup_intake_channel(
            channel_code="HOTLINE", display_name="Hotline N",
            default_category="HARASSMENT", default_severity="MEDIUM",
            sla_business_days=10,
        )
        reporter = setup_employee()
        subject = setup_employee()
        witness = setup_employee()
        _, inv1 = setup_investigator()
        case = setup_investigating_case(
            channel["id"], subject["id"], inv1["id"],
            reporter_employee_id=reporter["id"],
            category="HARASSMENT", severity="MEDIUM",
        )
        # Existing interview 09:00-10:00
        iv1 = schedule_interview(case["id"], inv1["id"], subject["id"],
                                   scheduled_start="2026-07-31T09:00:00Z",
                                   scheduled_end="2026-07-31T10:00:00Z")
        # Adjacent 10:00-11:00 — should succeed (boundary touch, not overlap)
        resp = api_client.create_interview(
            case["id"],
            {"interviewee_employee_id": witness["id"],
             "scheduled_start": "2026-07-31T10:00:00Z",
             "scheduled_end": "2026-07-31T11:00:00Z"},
            make_investigator_headers(inv1["id"]),
        )
        iv2 = validate_success(resp, 201)
        assert iv2["status"] == "SCHEDULED"

    def test_true_overlap_rejected(self):
        """PRD §3.3: "Two window rules apply, and both fail with
        `ERR_INTERVIEW_OVERLAP` (HTTP 422): the end must fall strictly after
        the start, and the new window must not overlap any existing `SCHEDULED`
        interview of the same interviewer."

        Design: Difficulty/resource_temporal_overlap/interview_half_open_adjacency_not_overlap
        """
        set_clock("2026-08-05T00:00:00Z")
        channel = setup_intake_channel(
            channel_code="HOTLINE", display_name="Hotline N",
            default_category="HARASSMENT", default_severity="MEDIUM",
            sla_business_days=10,
        )
        reporter = setup_employee()
        subject = setup_employee()
        witness = setup_employee()
        _, inv1 = setup_investigator()
        case = setup_investigating_case(
            channel["id"], subject["id"], inv1["id"],
            reporter_employee_id=reporter["id"],
            category="HARASSMENT", severity="MEDIUM",
        )
        schedule_interview(case["id"], inv1["id"], subject["id"],
                            scheduled_start="2026-07-31T09:00:00Z",
                            scheduled_end="2026-07-31T10:00:00Z")
        # Overlapping 09:30-10:30 — must fail
        resp = api_client.create_interview(
            case["id"],
            {"interviewee_employee_id": witness["id"],
             "scheduled_start": "2026-07-31T09:30:00Z",
             "scheduled_end": "2026-07-31T10:30:00Z"},
            make_investigator_headers(inv1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INTERVIEW_OVERLAP, 422)


class TestHolidayPointCollision:
    def test_adjacent_date_accepted(self):
        """PRD §2.5: "Registering a holiday records a `holiday_date` — an ISO
        8601 date at UTC midnight — together with a human-readable `label`.
        Holiday dates are unique across the calendar; a duplicate registration
        is rejected with `ERR_DUPLICATE` (HTTP 409)."

        An adjacent date is not a duplicate; it must be accepted.

        Design: Difficulty/resource_temporal_overlap/holiday_exact_date_collision_vs_adjacency
        """
        setup_holiday("2026-09-07T00:00:00Z", "Labor Day")
        resp = api_client.create_holiday(
            {"holiday_date": "2026-09-08T00:00:00Z", "label": "Day After"},
            TEST_USERS["er_manager_headers"],
        )
        h2 = validate_success(resp, 201)
        assert h2["holiday_date"].startswith("2026-09-08")

    def test_exact_date_rejected_as_duplicate(self):
        """PRD §2.5: "Holiday dates are unique across the calendar; a duplicate
        registration is rejected with `ERR_DUPLICATE` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/holiday_exact_date_collision_vs_adjacency
        """
        setup_holiday("2026-09-07T00:00:00Z", "Labor Day")
        resp = api_client.create_holiday(
            {"holiday_date": "2026-09-07T00:00:00Z", "label": "Duplicate Labor Day"},
            TEST_USERS["er_manager_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE, 409)
