"""Reviewer calendars are closed intervals padded by a mandatory 24-hour rest buffer
on both sides, so a booking that starts exactly one day after the incumbent ends still
collides and one starting a second later does not."""

import pytest

from test_helpers import (
    ANALYST_HEADERS,
    ASSIGNMENT_ASSIGNED,
    ApiErrorId,
    assert_assignment_fields,
    assert_evaluator_fields,
    review_assignment_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


@pytest.fixture
def reviewer_booked_to_the_twelfth(setup):
    """Three submitted nursing files and one reviewer with three slots, whose calendar
    is occupied from 2026-08-10 to 2026-08-12 inclusive."""
    profession = setup.profession()
    applications = []
    for name, license_number in (
        ("Yusuf Demir", "OK-70091"),
        ("Elif Kaya", "OK-70092"),
        ("Mateo Ruiz", "OK-70093"),
    ):
        applicant = setup.applicant(full_name=name, state_code="TX", residency_months=24)
        credential = setup.credential(
            applicant["id"],
            license_number=license_number,
            scope_elements=["ASSESS", "TREAT", "SUPERVISE"],
        )
        application = setup.application(applicant["id"], profession["id"], credential["id"])
        setup.submit(application["id"], applicant["id"])
        applications.append(application["id"])

    evaluator = setup.evaluator(
        full_name="Vera Holt", profession_code="RN", max_concurrent_reviews=3
    )
    first = setup.review_assignment(
        evaluator["id"], applications[0], "2026-08-10T00:00:00Z", "2026-08-12T00:00:00Z"
    )
    return {
        "app_ids": applications,
        "evr_id": evaluator["id"],
        "first_assignment": first,
        "evr_version": setup.evaluator_version(evaluator["id"]),
    }


class TestEvaluatorSlotBuffer:
    def test_a_window_opening_exactly_twenty_four_hours_later_still_collides(
        self, api, reviewer_booked_to_the_twelfth
    ):
        """PRD §3.6: "A booking is refused when any review assignment of the same
        evaluator whose `status` is `ASSIGNED` satisfies both of the following: the new
        window's `window_start_at` reduced by 24 hours is at or before the existing
        assignment's `window_end_at`, and the existing assignment's `window_start_at`
        is at or before the new window's `window_end_at` increased by 24 hours."

        Design: Difficulty/resource_temporal_overlap/evaluator_slot_buffer_blocks_exact_24_hour_gap_admits_one_second_more
        """
        env = reviewer_booked_to_the_twelfth
        response = api.create_review_assignment(
            review_assignment_payload(
                env["evr_id"],
                env["app_ids"][1],
                "2026-08-13T00:00:00Z",
                "2026-08-15T00:00:00Z",
                env["evr_version"],
            ),
            ANALYST_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_EVALUATOR_SLOT_CONFLICT.value, 409)

    def test_one_second_beyond_the_buffer_is_admitted(
        self, api, reviewer_booked_to_the_twelfth
    ):
        """PRD §3.6: "Because both comparisons are inclusive and the buffer is applied
        on both sides, windows that merely touch, and even windows separated by exactly
        24 hours, do collide; the rejection is `ERR_EVALUATOR_SLOT_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/evaluator_slot_buffer_blocks_exact_24_hour_gap_admits_one_second_more
        """
        env = reviewer_booked_to_the_twelfth
        second = validate_success(
            api.create_review_assignment(
                review_assignment_payload(
                    env["evr_id"],
                    env["app_ids"][2],
                    "2026-08-13T00:00:01Z",
                    "2026-08-15T00:00:00Z",
                    env["evr_version"],
                ),
                ANALYST_HEADERS,
            ),
            201,
        )

        assert_assignment_fields(
            second,
            status=ASSIGNMENT_ASSIGNED,
            window_start_at="2026-08-13T00:00:01Z",
            window_end_at="2026-08-15T00:00:00Z",
            closed_at=None,
        )

    def test_the_refused_booking_leaves_the_reviewers_version_untouched(
        self, api, reviewer_booked_to_the_twelfth
    ):
        """PRD §3.6: "A successful booking creates the assignment with `status`
        `ASSIGNED` and `closed_at` null, recomputes the evaluator's
        `open_assignment_count`, and increments the evaluator's `version`."  PRD §2.6:
        "Creating a review assignment requires a non-optional
        `expected_evaluator_version` field carrying the client's last observed
        `version` of the target `Evaluator`. If that value does not equal the
        evaluator's current `version`, the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Difficulty/resource_temporal_overlap/evaluator_slot_buffer_blocks_exact_24_hour_gap_admits_one_second_more
        """
        env = reviewer_booked_to_the_twelfth
        api.create_review_assignment(
            review_assignment_payload(
                env["evr_id"],
                env["app_ids"][1],
                "2026-08-13T00:00:00Z",
                "2026-08-15T00:00:00Z",
                env["evr_version"],
            ),
            ANALYST_HEADERS,
        )

        validate_success(
            api.create_review_assignment(
                review_assignment_payload(
                    env["evr_id"],
                    env["app_ids"][2],
                    "2026-08-13T00:00:01Z",
                    "2026-08-15T00:00:00Z",
                    env["evr_version"],
                ),
                ANALYST_HEADERS,
            ),
            201,
        )

    def test_spare_capacity_never_speaks_for_a_calendar_collision(
        self, api, reviewer_booked_to_the_twelfth, setup
    ):
        """PRD §3.6: "Capacity is the last gate. The evaluator's
        `open_assignment_count` plus the one new booking must not exceed their
        `max_concurrent_reviews`, or the request is refused with
        `ERR_EVALUATOR_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/evaluator_slot_buffer_blocks_exact_24_hour_gap_admits_one_second_more
        """
        env = reviewer_booked_to_the_twelfth
        assert_evaluator_fields(
            setup.read_evaluator(env["evr_id"]), max_concurrent_reviews=3, open_assignment_count=1
        )

        response = api.create_review_assignment(
            review_assignment_payload(
                env["evr_id"],
                env["app_ids"][1],
                "2026-08-13T00:00:00Z",
                "2026-08-15T00:00:00Z",
                env["evr_version"],
            ),
            ANALYST_HEADERS,
        )
        assert (
            response.json()["data"]["error_id"]
            != ApiErrorId.ERR_EVALUATOR_CAPACITY_EXCEEDED.value
        ), "two of the three slots are still free, so capacity cannot be the reason"

    def test_only_assigned_rows_occupy_the_calendar_and_the_count_follows_them(
        self, api, reviewer_booked_to_the_twelfth, setup
    ):
        """PRD §3.6: "That count is itself derived rather than stored by hand: it is
        the number of review assignments of that evaluator whose `status` is
        `ASSIGNED`, with `COMPLETED` and `RELEASED` rows excluded."

        Design: Difficulty/resource_temporal_overlap/evaluator_slot_buffer_blocks_exact_24_hour_gap_admits_one_second_more
        """
        env = reviewer_booked_to_the_twelfth
        validate_success(
            api.create_review_assignment(
                review_assignment_payload(
                    env["evr_id"],
                    env["app_ids"][2],
                    "2026-08-13T00:00:01Z",
                    "2026-08-15T00:00:00Z",
                    env["evr_version"],
                ),
                ANALYST_HEADERS,
            ),
            201,
        )

        assert_evaluator_fields(setup.read_evaluator(env["evr_id"]), open_assignment_count=2)
        rows, _meta = validate_paginated(
            api.list_review_assignments(ANALYST_HEADERS, {"evaluator_id": env["evr_id"]})
        )
        assert len(rows) == 2
        assert {row["status"] for row in rows} == {ASSIGNMENT_ASSIGNED}
