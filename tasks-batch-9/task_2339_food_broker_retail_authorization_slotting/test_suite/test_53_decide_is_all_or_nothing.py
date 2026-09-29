"""The award decision is the one bulk write, and a bad element leaves nothing behind."""

import pytest

from test_helpers import (
    ACCOUNT_MANAGER_HEADERS,
    ApiErrorId,
    AuthorizationState,
    PresentationStatus,
    ReviewStatus,
    SettlementStateAuthorization,
    UPC_1,
    UPC_2,
    UPC_3,
    fixtures,
    get_success_data,
    make_retailer_buyer_headers,
    validate_error,
    validate_paginated,
)
from test_helpers import factories as F

SLOT_COUNT = 3
AWARD_STORE_COUNT = 400


@pytest.fixture
def locked_review_with_a_two_item_deck_and_a_spare_item(api):
    """Three slots, two items on the submitted deck and one validated item on no deck at all."""
    retailer = fixtures.create_retailer(api, total_store_count=1200)
    bundle = fixtures.active_principal(api, retailer["id"])
    principal = bundle["principal"]
    first_item = fixtures.validated_item(api, principal["id"], retailer["id"], upc=UPC_1)
    second_item = fixtures.validated_item(
        api, principal["id"], retailer["id"], upc=UPC_2, description="Frozen Empanadas 10ct"
    )
    off_deck_item = fixtures.validated_item(
        api, principal["id"], retailer["id"], upc=UPC_3, description="Churro Bites 8ct"
    )
    review = fixtures.opened_review(api, retailer["id"], new_item_slots=SLOT_COUNT)
    presentation = fixtures.submitted_presentation(
        api, review["id"], principal["id"], [first_item["id"], second_item["id"]]
    )
    locked = fixtures.lock_review(api, review["id"], retailer["id"])
    fixtures.set_clock(api, fixtures.DECIDE_INSTANT)
    return {
        "retailer": retailer,
        "principal": principal,
        "first_item": first_item,
        "second_item": second_item,
        "off_deck_item": off_deck_item,
        "review": review,
        "presentation": presentation,
        "pinned_version": locked["version"],
    }


def attempt_decision(api, scope, item_ids):
    return api.decide_review(
        scope["review"]["id"],
        F.decide_payload(
            scope["pinned_version"], item_ids, default_store_count=AWARD_STORE_COUNT
        ),
        make_retailer_buyer_headers(scope["retailer"]["id"]),
    )


def attempt_the_three_item_award(api, scope):
    return attempt_decision(
        api,
        scope,
        [
            scope["first_item"]["id"],
            scope["second_item"]["id"],
            scope["off_deck_item"]["id"],
        ],
    )


def award_the_two_deck_items(api, scope):
    return get_success_data(
        attempt_decision(
            api, scope, [scope["first_item"]["id"], scope["second_item"]["id"]]
        ),
        200,
    )


def read_deck(api, scope):
    return get_success_data(
        api.get_presentation(scope["presentation"]["id"], ACCOUNT_MANAGER_HEADERS), 200
    )


class TestDecideIsAllOrNothing:
    def test_one_off_deck_item_creates_no_authorizations_at_all(
        self, api, locked_review_with_a_two_item_deck_and_a_spare_item
    ):
        """Two of the three identifiers were awardable, and neither of them was awarded.

        PRD: "Every element of `authorized_item_ids` must be an item listed by a presentation of *this*
        review whose `status` is `SUBMITTED`, and that item's principal must not be terminated; a stray
        identifier that resolves to no item at all is `ERR_ITEM_NOT_FOUND`, while an item that exists
        but is not in a submitted deck of this review is `ERR_ITEM_NOT_IN_SUBMITTED_PRESENTATION`."

        PRD: "Several operations in this system mutate more than one entity. Those cascades are not
        best-effort: they complete inside the same request that triggered them, in the order the
        workflow narrative states, and they are what keeps four conserved quantities true at all times."

        Design: Corner/endpoints/decide_is_all_or_nothing_across_the_awarded_item_set
        """
        scope = locked_review_with_a_two_item_deck_and_a_spare_item

        response = attempt_the_three_item_award(api, scope)

        validate_error(response, ApiErrorId.ITEM_NOT_IN_SUBMITTED_PRESENTATION, 422)
        _, meta = validate_paginated(
            api.list_authorizations(
                ACCOUNT_MANAGER_HEADERS, {"review_id": scope["review"]["id"]}
            )
        )
        assert meta["total_count"] == 0

    def test_the_refused_bulk_write_bumps_neither_the_slots_nor_the_version(
        self, api, locked_review_with_a_two_item_deck_and_a_spare_item
    ):
        """The review is exactly as the caller last read it, pin included.

        PRD: "On success `decided_at` is stamped from the logical clock, `slots_awarded` increases by
        the number of awarded items, and the review's `version` advances by one."

        PRD: "Throughout its life `slots_remaining` is simply `new_item_slots` less `slots_awarded`."

        Design: Corner/endpoints/decide_is_all_or_nothing_across_the_awarded_item_set
        """
        scope = locked_review_with_a_two_item_deck_and_a_spare_item
        validate_error(
            attempt_the_three_item_award(api, scope),
            ApiErrorId.ITEM_NOT_IN_SUBMITTED_PRESENTATION,
            422,
        )

        review = fixtures.get_review(api, scope["review"]["id"], scope["retailer"]["id"])

        assert review["status"] == ReviewStatus.PRESENTATION_LOCKED
        assert review["slots_awarded"] == 0
        assert review["slots_remaining"] == SLOT_COUNT
        assert review["decided_at"] is None
        assert review["version"] == scope["pinned_version"]

    def test_no_presentation_is_forked_by_the_refused_decision(
        self, api, locked_review_with_a_two_item_deck_and_a_spare_item
    ):
        """Neither branch of the fork ran, so the deck is still awaiting its answer.

        PRD: "Every presentation of this review with at least one awarded item moves `status` from
        `SUBMITTED` to `ACCEPTED` and has `authorized_item_count` set to the number of its own items
        that were awarded, and its live deal stays in `PROPOSED` or `COUNTERED` and thereby becomes
        acceptable."

        PRD: "**Branch B — decks that won nothing.** Every presentation of this review with zero
        awarded items moves `status` from `SUBMITTED` to `DECLINED` and keeps `authorized_item_count` at
        0, and every slotting deal of that presentation whose `state` is `DRAFT`, `PROPOSED` or
        `COUNTERED` is moved to `REJECTED` with `reject_reason` recorded as `PRESENTATION_DECLINED`."

        Design: Corner/endpoints/decide_is_all_or_nothing_across_the_awarded_item_set
        """
        scope = locked_review_with_a_two_item_deck_and_a_spare_item
        validate_error(
            attempt_the_three_item_award(api, scope),
            ApiErrorId.ITEM_NOT_IN_SUBMITTED_PRESENTATION,
            422,
        )

        deck = read_deck(api, scope)

        assert deck["status"] == PresentationStatus.SUBMITTED
        assert deck["authorized_item_count"] == 0

    def test_the_same_pin_then_awards_the_two_deck_items(
        self, api, locked_review_with_a_two_item_deck_and_a_spare_item
    ):
        """Replaying the identical `expected_review_version` is exactly what atomicity buys.

        PRD: "`POST /category-reviews/{reviewId}/decide` requires `expected_review_version`, carrying
        the client's last observed `version` of the `CategoryReview`."

        PRD: "On success `decided_at` is stamped from the logical clock, `slots_awarded` increases by
        the number of awarded items, and the review's `version` advances by one."

        Design: Corner/endpoints/decide_is_all_or_nothing_across_the_awarded_item_set
        """
        scope = locked_review_with_a_two_item_deck_and_a_spare_item
        validate_error(
            attempt_the_three_item_award(api, scope),
            ApiErrorId.ITEM_NOT_IN_SUBMITTED_PRESENTATION,
            422,
        )

        decided = award_the_two_deck_items(api, scope)

        assert decided["status"] == ReviewStatus.DECIDED
        assert decided["slots_awarded"] == 2
        assert decided["slots_remaining"] == SLOT_COUNT - 2
        assert decided["version"] == scope["pinned_version"] + 1

    def test_the_two_authorizations_are_created_in_ascending_upc_order(
        self, api, locked_review_with_a_two_item_deck_and_a_spare_item
    ):
        """Both go live immediately because no deal was ever opened against the deck.

        PRD: "**Branch A — decks that won something.** For every awarded item, processed in ascending
        `upc` order, an `Authorization` is created with `authorization_state` at `PENDING_SETUP` and
        `settlement_state` at `UNBILLED`, carrying the `review_id` of the deciding review, the `item_id`
        of the awarded item, and a `retailer_id` denormalized from the review so that chain-scope checks
        never need to walk the graph."

        PRD: "An authorization created with no linked deal has nothing to negotiate and therefore
        auto-advances `PENDING_SETUP` → `AUTHORIZED` immediately in the same request, while remaining
        `UNBILLED` on the settlement dimension."

        Design: Corner/endpoints/decide_is_all_or_nothing_across_the_awarded_item_set
        """
        scope = locked_review_with_a_two_item_deck_and_a_spare_item
        validate_error(
            attempt_the_three_item_award(api, scope),
            ApiErrorId.ITEM_NOT_IN_SUBMITTED_PRESENTATION,
            422,
        )
        award_the_two_deck_items(api, scope)

        rows, meta = validate_paginated(
            api.list_authorizations(
                ACCOUNT_MANAGER_HEADERS, {"review_id": scope["review"]["id"]}
            )
        )

        assert meta["total_count"] == 2
        assert [row["item_id"] for row in rows] == [
            scope["first_item"]["id"],
            scope["second_item"]["id"],
        ]
        assert rows[0]["authorization_state"] == AuthorizationState.AUTHORIZED
        assert rows[0]["settlement_state"] == SettlementStateAuthorization.UNBILLED
        assert rows[0]["authorized_store_count"] == AWARD_STORE_COUNT
        assert rows[0]["retailer_id"] == scope["retailer"]["id"]

    def test_the_deck_is_accepted_and_the_off_deck_item_holds_nothing(
        self, api, locked_review_with_a_two_item_deck_and_a_spare_item
    ):
        """Two of the principal's three validated items now have shelf space.

        PRD: "Every presentation of this review with at least one awarded item moves `status` from
        `SUBMITTED` to `ACCEPTED` and has `authorized_item_count` set to the number of its own items
        that were awarded, and its live deal stays in `PROPOSED` or `COUNTERED` and thereby becomes
        acceptable."

        PRD: "Authorizations may be filtered by `review_id`, `item_id`, `retailer_id`,
        `slotting_deal_id`, `authorization_state` and `settlement_state`."

        Design: Corner/endpoints/decide_is_all_or_nothing_across_the_awarded_item_set
        """
        scope = locked_review_with_a_two_item_deck_and_a_spare_item
        award_the_two_deck_items(api, scope)

        deck = read_deck(api, scope)

        assert deck["status"] == PresentationStatus.ACCEPTED
        assert deck["authorized_item_count"] == 2
        _, meta = validate_paginated(
            api.list_authorizations(
                ACCOUNT_MANAGER_HEADERS, {"item_id": scope["off_deck_item"]["id"]}
            )
        )
        assert meta["total_count"] == 0
