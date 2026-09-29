"""A buyer who read the review before the reopen holds a pin that is two writes behind."""

import pytest

from test_helpers import (
    ACCOUNT_MANAGER_HEADERS,
    ApiErrorId,
    ReviewStatus,
    UPC_1,
    fixtures,
    get_success_data,
    make_retailer_buyer_headers,
    validate_error,
    validate_paginated,
)
from test_helpers import factories as F

FIRST_DEADLINE = "2026-08-20T00:00:00Z"
EXTENDED_DEADLINE = "2026-08-25T00:00:00Z"
DECIDE_INSTANT = "2026-09-02T00:00:00Z"
SLOT_COUNT = 2
AWARD_STORE_COUNT = 400


@pytest.fixture
def locked_review_read_by_the_buyer(api):
    """One submitted deck, the review locked at its first deadline, and that version remembered."""
    retailer = fixtures.create_retailer(api, total_store_count=1200)
    bundle = fixtures.active_principal(api, retailer["id"])
    principal = bundle["principal"]
    item = fixtures.validated_item(api, principal["id"], retailer["id"], upc=UPC_1)
    review = fixtures.opened_review(
        api, retailer["id"], submission_deadline=FIRST_DEADLINE, new_item_slots=SLOT_COUNT
    )
    presentation = fixtures.submitted_presentation(
        api, review["id"], principal["id"], [item["id"]]
    )
    locked = fixtures.lock_review(api, review["id"], retailer["id"], at_instant=FIRST_DEADLINE)
    return {
        "retailer": retailer,
        "principal": principal,
        "item": item,
        "review": review,
        "presentation": presentation,
        "stale_version": locked["version"],
        "reopen_count_before": locked["reopen_count"],
        "buyer_headers": make_retailer_buyer_headers(retailer["id"]),
    }


def reopen(api, scope):
    return get_success_data(
        api.reopen_review(
            scope["review"]["id"],
            F.reopen_payload(EXTENDED_DEADLINE),
            scope["buyer_headers"],
        ),
        200,
    )


def lock_again(api, scope):
    fixtures.set_clock(api, EXTENDED_DEADLINE)
    return get_success_data(
        api.lock_review(scope["review"]["id"], scope["buyer_headers"]), 200
    )


def reopen_then_lock(api, scope):
    reopened = reopen(api, scope)
    relocked = lock_again(api, scope)
    return reopened, relocked


def attempt_award(api, scope, expected_review_version):
    return api.decide_review(
        scope["review"]["id"],
        F.decide_payload(
            expected_review_version, [scope["item"]["id"]], default_store_count=AWARD_STORE_COUNT
        ),
        scope["buyer_headers"],
    )


def read_review(api, scope):
    return fixtures.get_review(api, scope["review"]["id"], scope["retailer"]["id"])


class TestStaleReviewVersionAcrossAReopen:
    def test_the_reopen_is_itself_a_write_that_moves_the_deadline_and_the_version(
        self, api, locked_review_read_by_the_buyer
    ):
        """One reopen is allowed, and it puts the review back in OPEN with a later deadline.

        PRD: "A buyer who wants one more week can reopen the review, moving `status` from
        `PRESENTATION_LOCKED` back to `OPEN` with a `new_submission_deadline`."

        PRD: "On success `submission_deadline` is replaced by the supplied value and `reopen_count`
        increases by one, so lock, reopen and lock again is a genuine cycle — bounded at one reopen."

        Design: Corner/cross_cutting_complexity_layers/stale_review_version_blocks_the_award_across_a_reopen_cycle
        """
        scope = locked_review_read_by_the_buyer

        reopened = reopen(api, scope)

        assert reopened["status"] == ReviewStatus.OPEN
        assert reopened["submission_deadline"] == EXTENDED_DEADLINE
        assert reopened["reopen_count"] == scope["reopen_count_before"] + 1
        assert reopened["version"] == scope["stale_version"] + 1

    def test_locking_again_puts_the_review_two_versions_beyond_the_buyers_pin(
        self, api, locked_review_read_by_the_buyer
    ):
        """Lock, reopen, lock again — each of the three is a mutation of the same review.

        PRD: "Locking the deck moves `status` from `OPEN` to `PRESENTATION_LOCKED` and requires the
        opposite condition — the clock must have reached or passed `submission_deadline`, otherwise
        `ERR_SUBMISSION_WINDOW_STILL_OPEN`."

        PRD: "A change to a *derived* field counts as a mutation: when an accepted slotting fee moves a
        principal's committed total, or a distribution posting moves an authorization's void counters, the
        affected resource's `updated_at` is refreshed and its `version` advances."

        Design: Corner/cross_cutting_complexity_layers/stale_review_version_blocks_the_award_across_a_reopen_cycle
        """
        scope = locked_review_read_by_the_buyer

        reopened, relocked = reopen_then_lock(api, scope)

        assert relocked["status"] == ReviewStatus.PRESENTATION_LOCKED
        assert relocked["version"] == reopened["version"] + 1
        assert relocked["version"] == scope["stale_version"] + 2

    def test_the_award_is_refused_when_the_pin_predates_the_reopen(
        self, api, locked_review_read_by_the_buyer
    ):
        """The pinned version was read before the deadline moved, so the deck may have changed.

        PRD: "`POST /category-reviews/{reviewId}/decide` requires `expected_review_version`, carrying the
        client's last observed `version` of the `CategoryReview`. The award decision consumes
        `slots_remaining` and forks every submitted presentation; if a reopen extended the submission
        deadline or a further presentation arrived after the client read the review, the decision is
        rejected with `ERR_STALE_REVIEW_VERSION` (HTTP 412) rather than awarding slots out of a deck the
        client never saw."

        PRD: "If the pinned value does not equal the parent's current `version`, the write is refused
        rather than applied on top of a parent state the client never read."

        Design: Corner/cross_cutting_complexity_layers/stale_review_version_blocks_the_award_across_a_reopen_cycle
        """
        scope = locked_review_read_by_the_buyer
        reopen_then_lock(api, scope)
        fixtures.set_clock(api, DECIDE_INSTANT)

        response = attempt_award(api, scope, scope["stale_version"])

        validate_error(response, ApiErrorId.STALE_REVIEW_VERSION, 412)

    def test_the_refused_award_left_the_review_and_the_slot_pool_untouched(
        self, api, locked_review_read_by_the_buyer
    ):
        """A concurrency rejection is not a partial write: no slot was consumed.

        PRD: "On success `decided_at` is stamped from the logical clock, `slots_awarded` increases by the
        number of awarded items, and the review's `version` advances by one."

        PRD: "Throughout its life `slots_remaining` is simply `new_item_slots` less `slots_awarded`."

        Design: Corner/cross_cutting_complexity_layers/stale_review_version_blocks_the_award_across_a_reopen_cycle
        """
        scope = locked_review_read_by_the_buyer
        _, relocked = reopen_then_lock(api, scope)
        fixtures.set_clock(api, DECIDE_INSTANT)
        validate_error(
            attempt_award(api, scope, scope["stale_version"]),
            ApiErrorId.STALE_REVIEW_VERSION,
            412,
        )

        after = read_review(api, scope)

        assert after["version"] == relocked["version"]
        assert after["status"] == ReviewStatus.PRESENTATION_LOCKED
        assert after["slots_awarded"] == 0
        assert after["slots_remaining"] == SLOT_COUNT
        assert after["decided_at"] is None

    def test_no_authorization_was_created_by_the_refused_award(
        self, api, locked_review_read_by_the_buyer
    ):
        """The whole cascade is skipped, so the item still holds no shelf space.

        PRD: "Several operations in this system mutate more than one entity. Those cascades are not
        best-effort: they complete inside the same request that triggered them, in the order the workflow
        narrative states, and they are what keeps four conserved quantities true at all times."

        Design: Corner/cross_cutting_complexity_layers/stale_review_version_blocks_the_award_across_a_reopen_cycle
        """
        scope = locked_review_read_by_the_buyer
        reopen_then_lock(api, scope)
        fixtures.set_clock(api, DECIDE_INSTANT)
        validate_error(
            attempt_award(api, scope, scope["stale_version"]),
            ApiErrorId.STALE_REVIEW_VERSION,
            412,
        )

        _, meta = validate_paginated(
            api.list_authorizations(
                ACCOUNT_MANAGER_HEADERS, {"review_id": scope["review"]["id"]}
            )
        )

        assert meta["total_count"] == 0

    def test_the_refreshed_pin_awards_the_very_same_item(
        self, api, locked_review_read_by_the_buyer
    ):
        """The guard is a pure freshness check: nothing about the award itself was wrong.

        PRD: "No other endpoint accepts a version field, and none of the three is optional: an absent pin
        is a malformed request, not an unchecked write."

        PRD: "**Branch A — decks that won something.** For every awarded item, processed in ascending
        `upc` order, an `Authorization` is created with `authorization_state` at `PENDING_SETUP` and
        `settlement_state` at `UNBILLED`, carrying the `review_id` of the deciding review, the `item_id`
        of the awarded item, and a `retailer_id` denormalized from the review so that chain-scope checks
        never need to walk the graph."

        Design: Corner/cross_cutting_complexity_layers/stale_review_version_blocks_the_award_across_a_reopen_cycle
        """
        scope = locked_review_read_by_the_buyer
        reopen_then_lock(api, scope)
        fixtures.set_clock(api, DECIDE_INSTANT)
        validate_error(
            attempt_award(api, scope, scope["stale_version"]),
            ApiErrorId.STALE_REVIEW_VERSION,
            412,
        )
        refreshed = read_review(api, scope)

        decided = get_success_data(attempt_award(api, scope, refreshed["version"]), 200)

        assert decided["status"] == ReviewStatus.DECIDED
        assert decided["slots_awarded"] == 1
        assert decided["slots_remaining"] == SLOT_COUNT - 1
        assert decided["version"] == refreshed["version"] + 1
        rows, meta = validate_paginated(
            api.list_authorizations(
                ACCOUNT_MANAGER_HEADERS, {"review_id": scope["review"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["item_id"] == scope["item"]["id"]
