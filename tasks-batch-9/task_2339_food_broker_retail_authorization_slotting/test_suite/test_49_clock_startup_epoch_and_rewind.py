"""The logical clock starts on the declared epoch, is open to every role, and runs both ways."""

import pytest

from test_helpers import (
    BROKER_ADMIN_HEADERS,
    CLOCK_DEFAULT_UTC,
    PRIMARY_CATEGORY,
    ApiErrorId,
    ReviewStatus,
    fixtures,
    get_success_data,
    make_principal_portal_headers,
    make_retailer_buyer_headers,
    validate_error,
)
from test_helpers import factories as F

DAIRY = "DAIRY"
BEVERAGE = "BEVERAGE"
ONE_SECOND_AFTER_EPOCH = "2026-08-01T00:00:01Z"
TWO_SECONDS_AFTER_EPOCH = "2026-08-01T00:00:02Z"
REWOUND_INSTANT = "2026-07-01T00:00:00Z"
PORTAL_USER_ID = "u_portal_1"


@pytest.fixture
def three_reviews_deadlined_around_the_epoch(api):
    """Deadlines at the epoch, one second later and two seconds later — and no clock call yet."""
    retailer = fixtures.create_retailer(api, total_store_count=1200)
    return {
        "retailer": retailer,
        "at_the_epoch": fixtures.create_review(
            api,
            retailer["id"],
            category_code=PRIMARY_CATEGORY,
            submission_deadline=CLOCK_DEFAULT_UTC,
        ),
        "one_second_later": fixtures.create_review(
            api,
            retailer["id"],
            category_code=DAIRY,
            submission_deadline=ONE_SECOND_AFTER_EPOCH,
        ),
        "two_seconds_later": fixtures.create_review(
            api,
            retailer["id"],
            category_code=BEVERAGE,
            submission_deadline=TWO_SECONDS_AFTER_EPOCH,
        ),
    }


def attempt_open(api, scope, key):
    return api.open_review(
        scope[key]["id"], make_retailer_buyer_headers(scope["retailer"]["id"])
    )


def read_review(api, scope, key):
    return fixtures.get_review(api, scope[key]["id"], scope["retailer"]["id"])


class TestClockStartupEpochAndRewind:
    def test_a_deadline_exactly_on_the_epoch_is_already_closed(
        self, api, three_reviews_deadlined_around_the_epoch
    ):
        """No clock call has been made, so the clock still reads the epoch and is not strictly before
        a deadline equal to it.

        PRD: "Before any call is made, the clock reads exactly `2026-08-01T00:00:00Z`; this startup
        default is mandatory and the server must never fall back to real time."

        PRD: "Opening a review moves `status` from `SCHEDULED` to `OPEN` and requires the logical clock
        to be strictly before `submission_deadline`, otherwise `ERR_REVIEW_SUBMISSION_CLOSED`; once
        open, presentations may be submitted."

        Design: Corner/endpoints/clock_endpoint_defaults_to_the_declared_epoch_and_moves_both_ways
        """
        scope = three_reviews_deadlined_around_the_epoch

        response = attempt_open(api, scope, "at_the_epoch")

        validate_error(response, ApiErrorId.REVIEW_SUBMISSION_CLOSED, 422)
        assert read_review(api, scope, "at_the_epoch")["status"] == ReviewStatus.SCHEDULED

    def test_one_second_of_head_room_is_enough_to_open(
        self, api, three_reviews_deadlined_around_the_epoch
    ):
        """A wall-clock server would be years past this deadline; a logical clock is one second short.

        PRD: "Before any call is made, the clock reads exactly `2026-08-01T00:00:00Z`; this startup
        default is mandatory and the server must never fall back to real time."

        PRD: "A scheduled review begins with `status` at `SCHEDULED`, `slots_awarded` at 0,
        `slots_remaining` equal to `new_item_slots`, `reopen_count` at 0 and `decided_at` null."

        Design: Corner/endpoints/clock_endpoint_defaults_to_the_declared_epoch_and_moves_both_ways
        """
        scope = three_reviews_deadlined_around_the_epoch
        validate_error(
            attempt_open(api, scope, "at_the_epoch"),
            ApiErrorId.REVIEW_SUBMISSION_CLOSED,
            422,
        )

        opened = get_success_data(attempt_open(api, scope, "one_second_later"), 200)

        assert opened["status"] == ReviewStatus.OPEN
        assert opened["submission_deadline"] == ONE_SECOND_AFTER_EPOCH

    def test_the_read_only_portal_role_may_also_drive_the_clock(
        self, api, three_reviews_deadlined_around_the_epoch
    ):
        """The one capability a `PrincipalPortalUser` holds beyond reading.

        PRD: "An administrative test-driving capability sets the clock to a supplied `current_utc`
        instant and echoes `current_utc` back; all five roles may use it, and every subsequent temporal
        evaluation uses the new value."

        PRD: "Every request — including the logical-clock capability — must carry two headers:
        `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which
        that user is acting."

        Design: Corner/endpoints/clock_endpoint_defaults_to_the_declared_epoch_and_moves_both_ways
        """
        moved = get_success_data(
            api.set_clock(
                F.clock_payload(TWO_SECONDS_AFTER_EPOCH),
                make_principal_portal_headers(PORTAL_USER_ID),
            ),
            200,
        )

        assert moved["current_utc"] == TWO_SECONDS_AFTER_EPOCH

    def test_advancing_the_clock_closes_the_last_remaining_deadline(
        self, api, three_reviews_deadlined_around_the_epoch
    ):
        """Two seconds on, the clock equals the third deadline and is no longer strictly before it.

        PRD: "An administrative test-driving capability sets the clock to a supplied `current_utc`
        instant and echoes `current_utc` back; all five roles may use it, and every subsequent temporal
        evaluation uses the new value."

        PRD: "`ERR_REVIEW_SUBMISSION_CLOSED` guards opening a review and submitting a presentation"

        Design: Corner/endpoints/clock_endpoint_defaults_to_the_declared_epoch_and_moves_both_ways
        """
        scope = three_reviews_deadlined_around_the_epoch
        fixtures.set_clock(
            api, TWO_SECONDS_AFTER_EPOCH, make_principal_portal_headers(PORTAL_USER_ID)
        )

        response = attempt_open(api, scope, "two_seconds_later")

        validate_error(response, ApiErrorId.REVIEW_SUBMISSION_CLOSED, 422)
        assert read_review(api, scope, "two_seconds_later")["status"] == (
            ReviewStatus.SCHEDULED
        )

    def test_rewinding_the_clock_reopens_a_deadline_that_had_closed(
        self, api, three_reviews_deadlined_around_the_epoch
    ):
        """The identical request that just failed succeeds once the clock moves backwards, so nothing
        temporal is cached at creation time.

        PRD: "All temporal evaluation — submission deadlines, decision windows, review blackout
        buffers, commission-agreement coverage, promotion windows, demo changeover buffers and
        deduction dispute windows — reads a server-side logical UTC clock rather than wall-clock time."

        PRD: "An administrative test-driving capability sets the clock to a supplied `current_utc`
        instant and echoes `current_utc` back; all five roles may use it, and every subsequent temporal
        evaluation uses the new value."

        Design: Corner/endpoints/clock_endpoint_defaults_to_the_declared_epoch_and_moves_both_ways
        """
        scope = three_reviews_deadlined_around_the_epoch
        fixtures.set_clock(api, TWO_SECONDS_AFTER_EPOCH)
        validate_error(
            attempt_open(api, scope, "two_seconds_later"),
            ApiErrorId.REVIEW_SUBMISSION_CLOSED,
            422,
        )

        rewound = get_success_data(
            api.set_clock(F.clock_payload(REWOUND_INSTANT), BROKER_ADMIN_HEADERS), 200
        )
        opened = get_success_data(attempt_open(api, scope, "two_seconds_later"), 200)

        assert rewound["current_utc"] == REWOUND_INSTANT
        assert opened["status"] == ReviewStatus.OPEN
