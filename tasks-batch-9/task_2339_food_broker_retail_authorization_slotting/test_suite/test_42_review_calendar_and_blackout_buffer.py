"""The review calendar rejects malformed windows and buffers each category's window by 14 days."""

import pytest

from test_helpers import (
    BROKER_ADMIN_HEADERS,
    ApiErrorId,
    PRIMARY_CATEGORY,
    ReviewStatus,
    fixtures,
    get_success_data,
    make_retailer_buyer_headers,
    validate_error,
    validate_paginated,
)
from test_helpers import factories as F
from test_helpers.assertions import assert_ordered_by_created_at

DAIRY = "DAIRY"
BEVERAGE = "BEVERAGE"
EXISTING_WINDOW_START = "2026-09-01"
EXISTING_WINDOW_END = "2026-09-15"
# 2026-09-15 plus the 14-day blackout buffer.
FIRST_LEGAL_START = "2026-09-29"


@pytest.fixture
def chain_with_one_frozen_snacks_review(api):
    """BIGMART carries the default 14-day blackout and one review over [2026-09-01, 2026-09-15)."""
    retailer = fixtures.create_retailer(api, total_store_count=1200)
    review = fixtures.create_review(
        api,
        retailer["id"],
        category_code=PRIMARY_CATEGORY,
        review_window_start=EXISTING_WINDOW_START,
        review_window_end=EXISTING_WINDOW_END,
        submission_deadline="2026-08-20T00:00:00Z",
    )
    return {"retailer": retailer, "review": review}


def schedule(api, scope, **overrides):
    return api.create_review(
        F.review_payload(scope["retailer"]["id"], **overrides),
        make_retailer_buyer_headers(scope["retailer"]["id"]),
    )


def frozen_snacks_reviews(api, scope):
    rows, meta = validate_paginated(
        api.list_reviews(
            BROKER_ADMIN_HEADERS,
            {"retailer_id": scope["retailer"]["id"], "category_code": PRIMARY_CATEGORY},
        )
    )
    return rows, meta


class TestReviewCalendarAndBlackoutBuffer:
    def test_a_window_that_ends_before_it_starts_is_refused(
        self, api, chain_with_one_frozen_snacks_review
    ):
        """2026-11-15 to 2026-11-01 is not a window at all, whatever the category.

        PRD: "Two shape rules apply: `review_window_end` must be later than `review_window_start`,
        and `submission_deadline` must fall strictly before `review_window_start` read as midnight
        UTC."

        PRD: "A violation of either is `ERR_REVIEW_CALENDAR_INVALID`."

        Design: Corner/validations/review_calendar_shape_and_blackout_buffer_reject_overlapping_windows
        """
        response = schedule(
            api,
            chain_with_one_frozen_snacks_review,
            category_code=BEVERAGE,
            review_window_start="2026-11-15",
            review_window_end="2026-11-01",
            submission_deadline="2026-10-20T00:00:00Z",
        )

        validate_error(response, ApiErrorId.REVIEW_CALENDAR_INVALID, 409)

    def test_a_deadline_inside_the_decision_window_is_refused(
        self, api, chain_with_one_frozen_snacks_review
    ):
        """A deadline of 2026-11-05 falls after the 2026-11-01 window start, so nothing could be
        submitted in time.

        PRD: "Where a date-only bound has to be compared against an instant, the date is read as
        midnight UTC at the start of that day — a `submission_deadline` must fall strictly before
        `review_window_start` at `00:00:00Z`."

        PRD: "A violation of either is `ERR_REVIEW_CALENDAR_INVALID`."

        Design: Corner/validations/review_calendar_shape_and_blackout_buffer_reject_overlapping_windows
        """
        response = schedule(
            api,
            chain_with_one_frozen_snacks_review,
            category_code=BEVERAGE,
            review_window_start="2026-11-01",
            review_window_end="2026-11-15",
            submission_deadline="2026-11-05T00:00:00Z",
        )

        validate_error(response, ApiErrorId.REVIEW_CALENDAR_INVALID, 409)

    def test_a_same_category_window_inside_the_buffer_is_refused(
        self, api, chain_with_one_frozen_snacks_review
    ):
        """2026-09-20 is before 2026-09-15 plus 14 days, and 2026-08-18 is before 2026-09-25.

        PRD: "A new review is rejected when its window falls inside another same-chain,
        same-category review's blackout-buffered window: the violation condition is that the new
        `review_window_start` is earlier than the other review's `review_window_end` extended forward
        by `review_blackout_days`, *and* the other review's `review_window_start` pulled back by
        `review_blackout_days` is earlier than the new `review_window_end`."

        Design: Corner/validations/review_calendar_shape_and_blackout_buffer_reject_overlapping_windows
        """
        response = schedule(
            api,
            chain_with_one_frozen_snacks_review,
            category_code=PRIMARY_CATEGORY,
            review_window_start="2026-09-20",
            review_window_end="2026-09-25",
            submission_deadline="2026-09-10T00:00:00Z",
        )

        validate_error(response, ApiErrorId.REVIEW_BLACKOUT_CONFLICT, 409)

    def test_the_identical_window_is_legal_for_a_different_category(
        self, api, chain_with_one_frozen_snacks_review
    ):
        """The buffer protects a category's buyers, not the chain's whole calendar.

        PRD: "`review_blackout_days` defaults to 14 days and is applied on both sides of an existing
        category review window when a new review is scheduled for the same chain and category."

        Design: Corner/validations/review_calendar_shape_and_blackout_buffer_reject_overlapping_windows
        """
        scope = chain_with_one_frozen_snacks_review
        validate_error(
            schedule(
                api,
                scope,
                category_code=PRIMARY_CATEGORY,
                review_window_start="2026-09-20",
                review_window_end="2026-09-25",
                submission_deadline="2026-09-10T00:00:00Z",
            ),
            ApiErrorId.REVIEW_BLACKOUT_CONFLICT,
            409,
        )

        dairy = get_success_data(
            schedule(
                api,
                scope,
                category_code=DAIRY,
                review_window_start="2026-09-20",
                review_window_end="2026-09-25",
                submission_deadline="2026-09-10T00:00:00Z",
            ),
            201,
        )

        assert dairy["category_code"] == DAIRY
        assert dairy["review_window_start"] == "2026-09-20"
        assert dairy["status"] == ReviewStatus.SCHEDULED

    def test_starting_exactly_on_the_buffer_edge_is_legal(
        self, api, chain_with_one_frozen_snacks_review
    ):
        """2026-09-29 is exactly 2026-09-15 plus 14 days, and the comparison is strict.

        PRD: "A new review is rejected when its window falls inside another same-chain,
        same-category review's blackout-buffered window: the violation condition is that the new
        `review_window_start` is earlier than the other review's `review_window_end` extended forward
        by `review_blackout_days`, *and* the other review's `review_window_start` pulled back by
        `review_blackout_days` is earlier than the new `review_window_end`."

        Design: Corner/validations/review_calendar_shape_and_blackout_buffer_reject_overlapping_windows
        """
        adjacent = get_success_data(
            schedule(
                api,
                chain_with_one_frozen_snacks_review,
                category_code=PRIMARY_CATEGORY,
                review_window_start=FIRST_LEGAL_START,
                review_window_end="2026-10-10",
                submission_deadline="2026-09-20T00:00:00Z",
            ),
            201,
        )

        assert adjacent["review_window_start"] == FIRST_LEGAL_START
        assert adjacent["slots_remaining"] == adjacent["new_item_slots"]
        assert adjacent["reopen_count"] == 0
        assert adjacent["decided_at"] is None

    def test_only_the_two_accepted_frozen_snacks_reviews_are_listed(
        self, api, chain_with_one_frozen_snacks_review
    ):
        """The refused windows left no rows behind, and the survivors are in creation order.

        PRD: "A scheduled review begins with `status` at `SCHEDULED`, `slots_awarded` at 0,
        `slots_remaining` equal to `new_item_slots`, `reopen_count` at 0 and `decided_at` null."

        Design: Corner/validations/review_calendar_shape_and_blackout_buffer_reject_overlapping_windows
        """
        scope = chain_with_one_frozen_snacks_review
        validate_error(
            schedule(
                api,
                scope,
                category_code=PRIMARY_CATEGORY,
                review_window_start="2026-09-20",
                review_window_end="2026-09-25",
                submission_deadline="2026-09-10T00:00:00Z",
            ),
            ApiErrorId.REVIEW_BLACKOUT_CONFLICT,
            409,
        )
        adjacent = get_success_data(
            schedule(
                api,
                scope,
                category_code=PRIMARY_CATEGORY,
                review_window_start=FIRST_LEGAL_START,
                review_window_end="2026-10-10",
                submission_deadline="2026-09-20T00:00:00Z",
            ),
            201,
        )

        rows, meta = frozen_snacks_reviews(api, scope)

        assert meta["total_count"] == 2
        assert [row["id"] for row in rows] == [scope["review"]["id"], adjacent["id"]]
        assert_ordered_by_created_at(rows)
