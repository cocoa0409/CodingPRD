"""Lock, reopen, lock again — bounded at one reopen and fenced by the calendar."""

import pytest

from test_helpers import (
    ApiErrorId,
    ReviewStatus,
    fixtures,
    get_success_data,
    make_retailer_buyer_headers,
    validate_error,
)

DEADLINE = "2026-08-20T00:00:00Z"
NEW_DEADLINE = "2026-08-25T00:00:00Z"
WINDOW_START = "2026-09-01"
MAX_REVIEW_REOPENS = 1


@pytest.fixture
def open_review_before_its_deadline(api):
    """An OPEN review whose deadline is 2026-08-20 while the clock still reads 2026-08-01."""
    retailer = fixtures.create_retailer(api, total_store_count=1200)
    review = fixtures.opened_review(
        api,
        retailer["id"],
        review_window_start=WINDOW_START,
        review_window_end="2026-09-15",
        submission_deadline=DEADLINE,
    )
    return {"retailer": retailer, "review": review}


def lock(api, scope):
    return api.lock_review(scope["review"]["id"], make_retailer_buyer_headers(scope["retailer"]["id"]))


def reopen(api, scope, new_submission_deadline):
    return api.reopen_review(
        scope["review"]["id"],
        {"new_submission_deadline": new_submission_deadline},
        make_retailer_buyer_headers(scope["retailer"]["id"]),
    )


def read_review(api, scope):
    return fixtures.get_review(api, scope["review"]["id"], scope["retailer"]["id"])


def lock_reopen_and_relock(api, scope):
    fixtures.set_clock(api, DEADLINE)
    get_success_data(lock(api, scope), 200)
    get_success_data(reopen(api, scope, NEW_DEADLINE), 200)
    fixtures.set_clock(api, NEW_DEADLINE)
    return get_success_data(lock(api, scope), 200)


class TestReviewLockReopenCycle:
    def test_locking_before_the_deadline_is_refused(self, api, open_review_before_its_deadline):
        """The submission window is still open, so the deck may not be frozen.

        PRD: "Locking the deck moves `status` from `OPEN` to `PRESENTATION_LOCKED` and requires
        the opposite condition — the clock must have reached or passed `submission_deadline`,
        otherwise `ERR_SUBMISSION_WINDOW_STILL_OPEN`."

        Design: Corner/state_machines/review_lock_reopen_cycle_is_bounded_and_window_guarded
        """
        response = lock(api, open_review_before_its_deadline)

        validate_error(response, ApiErrorId.SUBMISSION_WINDOW_STILL_OPEN, 422)
        assert read_review(api, open_review_before_its_deadline)["status"] == ReviewStatus.OPEN

    def test_locking_at_exactly_the_deadline_succeeds(self, api, open_review_before_its_deadline):
        """The guard is inclusive, so the deadline instant itself is late enough.

        PRD: "After locking, further submissions fail with `ERR_REVIEW_NOT_OPEN` and the deck is
        frozen for the buyer's decision."

        Design: Corner/state_machines/review_lock_reopen_cycle_is_bounded_and_window_guarded
        """
        fixtures.set_clock(api, DEADLINE)

        locked = get_success_data(lock(api, open_review_before_its_deadline), 200)

        assert locked["status"] == ReviewStatus.PRESENTATION_LOCKED

    def test_a_new_deadline_past_the_window_start_is_a_calendar_violation(
        self, api, open_review_before_its_deadline
    ):
        """A 2026-09-05 deadline sits after the 2026-09-01 window start.

        PRD: "And `new_submission_deadline` must be strictly after the current clock instant and
        strictly before `review_window_start` at midnight UTC, otherwise
        `ERR_REVIEW_CALENDAR_INVALID`."

        Design: Corner/state_machines/review_lock_reopen_cycle_is_bounded_and_window_guarded
        """
        scope = open_review_before_its_deadline
        fixtures.set_clock(api, DEADLINE)
        get_success_data(lock(api, scope), 200)

        validate_error(
            reopen(api, scope, "2026-09-05T00:00:00Z"), ApiErrorId.REVIEW_CALENDAR_INVALID, 409
        )
        assert read_review(api, scope)["status"] == ReviewStatus.PRESENTATION_LOCKED

    def test_a_legal_reopen_replaces_the_deadline_and_counts_the_traversal(
        self, api, open_review_before_its_deadline
    ):
        """Back to OPEN with one reopen consumed and a later deadline in force.

        PRD: "On success `submission_deadline` is replaced by the supplied value and
        `reopen_count` increases by one, so lock, reopen and lock again is a genuine cycle —
        bounded at one reopen."

        Design: Corner/state_machines/review_lock_reopen_cycle_is_bounded_and_window_guarded
        """
        scope = open_review_before_its_deadline
        fixtures.set_clock(api, DEADLINE)
        get_success_data(lock(api, scope), 200)

        reopened = get_success_data(reopen(api, scope, NEW_DEADLINE), 200)

        assert reopened["status"] == ReviewStatus.OPEN
        assert reopened["reopen_count"] == MAX_REVIEW_REOPENS
        assert reopened["submission_deadline"] != scope["review"]["submission_deadline"]

        # The replacement deadline is genuinely in force: the clock that was late
        # enough to lock a moment ago is now too early.
        validate_error(lock(api, scope), ApiErrorId.SUBMISSION_WINDOW_STILL_OPEN, 422)

    def test_the_second_reopen_hits_the_cap(self, api, open_review_before_its_deadline):
        """The cycle closes once, and the re-locked deck cannot be opened again.

        PRD: "`reopen_count` must still be below the single reopen the calendar allows,
        otherwise `ERR_REVIEW_REOPEN_LIMIT` — a review may be reopened at most once."

        Design: Corner/state_machines/review_lock_reopen_cycle_is_bounded_and_window_guarded
        """
        scope = open_review_before_its_deadline
        relocked = lock_reopen_and_relock(api, scope)
        assert relocked["status"] == ReviewStatus.PRESENTATION_LOCKED

        validate_error(
            reopen(api, scope, "2026-08-28T00:00:00Z"), ApiErrorId.REVIEW_REOPEN_LIMIT, 409
        )
        assert read_review(api, scope)["status"] == ReviewStatus.PRESENTATION_LOCKED

    def test_a_review_whose_decision_window_has_begun_cannot_reopen(self, api):
        """Once the clock reaches the window start the deck is settled for good.

        PRD: "The logical clock must be strictly before `review_window_start` at midnight UTC,
        otherwise `ERR_REVIEW_WINDOW_STARTED`: once the decision window has begun the deck cannot
        be reopened."

        Design: Corner/state_machines/review_lock_reopen_cycle_is_bounded_and_window_guarded
        """
        retailer = fixtures.create_retailer(api, total_store_count=1200)
        review = fixtures.opened_review(
            api,
            retailer["id"],
            review_window_start=WINDOW_START,
            review_window_end="2026-09-15",
            submission_deadline=DEADLINE,
        )
        scope = {"retailer": retailer, "review": review}
        fixtures.set_clock(api, DEADLINE)
        get_success_data(lock(api, scope), 200)
        fixtures.set_clock(api, "2026-09-02T00:00:00Z")

        validate_error(
            reopen(api, scope, "2026-09-10T00:00:00Z"), ApiErrorId.REVIEW_WINDOW_STARTED, 422
        )

    def test_opening_a_scheduled_review_after_its_deadline_is_refused(self, api):
        """The other end of the same window guard, on the SCHEDULED to OPEN edge.

        PRD: "Opening a review moves `status` from `SCHEDULED` to `OPEN` and requires the logical
        clock to be strictly before `submission_deadline`, otherwise
        `ERR_REVIEW_SUBMISSION_CLOSED`; once open, presentations may be submitted."

        Design: Corner/state_machines/review_lock_reopen_cycle_is_bounded_and_window_guarded
        """
        retailer = fixtures.create_retailer(api, total_store_count=1200)
        review = fixtures.create_review(
            api,
            retailer["id"],
            review_window_start=WINDOW_START,
            review_window_end="2026-09-15",
            submission_deadline=DEADLINE,
        )
        fixtures.set_clock(api, DEADLINE)

        response = api.open_review(review["id"], make_retailer_buyer_headers(retailer["id"]))

        validate_error(response, ApiErrorId.REVIEW_SUBMISSION_CLOSED, 422)
