"""Deciding a review with an empty award list is legal and declines the whole deck."""

import pytest

from test_helpers import (
    ACCOUNT_MANAGER_HEADERS,
    UPC_1,
    AmortizationMethod,
    DealState,
    PresentationStatus,
    RejectReason,
    ReviewStatus,
    CatalogState,
    fixtures,
    get_success_data,
)
from test_helpers.assertions import (
    assert_review,
    assert_review_slots_conserved,
    assert_version_bumped_by,
)

NEW_ITEM_SLOTS = 2
FEE_PER_STORE_CENTS = 50000
STORE_COUNT = 400


@pytest.fixture
def locked_review_with_one_live_deck(api):
    """A locked two-slot review holding one submitted deck and one proposed deal."""
    retailer = fixtures.create_retailer(api, total_store_count=1200)
    principal = fixtures.active_principal(api, retailer["id"])["principal"]
    item = fixtures.validated_item(api, principal["id"], retailer["id"], upc=UPC_1)
    review = fixtures.opened_review(api, retailer["id"], new_item_slots=NEW_ITEM_SLOTS)
    presentation = fixtures.submitted_presentation(
        api, review["id"], principal["id"], [item["id"]]
    )
    deal = fixtures.proposed_deal(
        api,
        presentation["id"],
        fee_per_store_cents=FEE_PER_STORE_CENTS,
        store_count_in_scope=STORE_COUNT,
        item_count_in_scope=1,
        forecast_annual_units=0,
        amortization_periods=4,
        amortization_method=AmortizationMethod.FORECAST_STRAIGHT,
    )
    locked = fixtures.lock_review(api, review["id"], retailer["id"])
    return {
        "retailer": retailer,
        "principal": principal,
        "item": item,
        "review": locked,
        "presentation": presentation,
        "deal": deal,
    }


def decide_awarding_nothing(api, scope):
    return fixtures.decide_review(api, scope["review"]["id"], scope["retailer"]["id"], [])


class TestDecideAwardingNothing:
    def test_the_empty_award_list_is_accepted_and_the_review_decides(
        self, api, locked_review_with_one_live_deck
    ):
        """Zero is a legal cardinality, not a malformed request.

        PRD: "An empty `authorized_item_ids` array is entirely legal and declines the whole
        deck."

        Design: Difficulty/boundary_precision_check/decide_with_empty_authorized_item_ids_awards_zero_slots
        """
        decided = decide_awarding_nothing(api, locked_review_with_one_live_deck)

        assert_review(decided)
        assert decided["status"] == ReviewStatus.DECIDED
        assert decided["decided_at"] is not None

    def test_no_slot_is_consumed_and_the_version_still_advances(
        self, api, locked_review_with_one_live_deck
    ):
        """slots_awarded stays at zero while the write itself is still a version bump.

        PRD: "On success `decided_at` is stamped from the logical clock, `slots_awarded`
        increases by the number of awarded items, and the review's `version` advances by one."

        Design: Difficulty/boundary_precision_check/decide_with_empty_authorized_item_ids_awards_zero_slots
        """
        before = fixtures.get_review(
            api,
            locked_review_with_one_live_deck["review"]["id"],
            locked_review_with_one_live_deck["retailer"]["id"],
        )
        decided = decide_awarding_nothing(api, locked_review_with_one_live_deck)

        assert decided["slots_awarded"] == 0
        assert decided["new_item_slots"] == NEW_ITEM_SLOTS
        assert_version_bumped_by(before, decided, 1)

    def test_the_whole_slot_allowance_survives_the_decision(
        self, api, locked_review_with_one_live_deck
    ):
        """Nothing was awarded, so the remaining allowance is still the full two slots.

        PRD: "Throughout its life `slots_remaining` is simply `new_item_slots` less
        `slots_awarded`."

        Design: Difficulty/boundary_precision_check/decide_with_empty_authorized_item_ids_awards_zero_slots
        """
        decided = decide_awarding_nothing(api, locked_review_with_one_live_deck)

        assert decided["slots_remaining"] == NEW_ITEM_SLOTS
        assert_review_slots_conserved(decided)

    def test_not_one_authorization_row_is_created(self, api, locked_review_with_one_live_deck):
        """Authorizations are minted per awarded item, so an empty award mints none.

        PRD: "For every awarded item, processed in ascending `upc` order, an `Authorization` is
        created with `authorization_state` at `PENDING_SETUP` and `settlement_state` at
        `UNBILLED`, carrying the `review_id` of the deciding review, the `item_id` of the
        awarded item, and a `retailer_id` denormalized from the review so that chain-scope
        checks never need to walk the graph."

        Design: Difficulty/boundary_precision_check/decide_with_empty_authorized_item_ids_awards_zero_slots
        """
        decide_awarding_nothing(api, locked_review_with_one_live_deck)

        rows = fixtures.authorizations_for_review(
            api, locked_review_with_one_live_deck["review"]["id"]
        )
        assert rows == []

    def test_the_losing_deck_is_declined_and_its_deal_rejected(
        self, api, locked_review_with_one_live_deck
    ):
        """Branch B fires in full: the deck is declined and the live negotiation is closed.

        PRD: "Every presentation of this review with zero awarded items moves `status` from
        `SUBMITTED` to `DECLINED` and keeps `authorized_item_count` at 0, and every slotting
        deal of that presentation whose `state` is `DRAFT`, `PROPOSED` or `COUNTERED` is moved
        to `REJECTED` with `reject_reason` recorded as `PRESENTATION_DECLINED`."

        Design: Difficulty/boundary_precision_check/decide_with_empty_authorized_item_ids_awards_zero_slots
        """
        decide_awarding_nothing(api, locked_review_with_one_live_deck)

        presentation = get_success_data(
            api.get_presentation(
                locked_review_with_one_live_deck["presentation"]["id"], ACCOUNT_MANAGER_HEADERS
            ),
            200,
        )
        assert presentation["status"] == PresentationStatus.DECLINED
        assert presentation["authorized_item_count"] == 0

        deal = fixtures.get_deal(api, locked_review_with_one_live_deck["deal"]["id"])
        assert deal["state"] == DealState.REJECTED
        assert deal["reject_reason"] == RejectReason.PRESENTATION_DECLINED
        # No fee was ever frozen on a deal that never reached acceptance.
        assert not deal["accepted_fee_cents"]

    def test_nothing_is_committed_against_the_principal_budget(
        self, api, locked_review_with_one_live_deck
    ):
        """A rejected negotiation contributes no committed slotting money.

        PRD: "A principal's derived aggregates are re-derived on every write that changes a
        slotting deal's state or balance, an authorization's at-risk flag, or a deduction's
        settlement: `slotting_committed_cents` is the sum of `accepted_fee_cents` over that
        principal's deals in state `ACCEPTED`, `AMORTIZING` or `RECOVERY_HOLD`;
        `open_slotting_liability_cents` is the sum of `unamortized_balance_cents` over deals in
        `AMORTIZING` or `RECOVERY_HOLD`; `open_deduction_cents` is the sum of `open_cents` over
        deductions whose `settlement_state` is `OPEN`; `at_risk_authorization_count` is the
        number of authorizations on that principal's items whose `authorization_state` is
        `AT_RISK`."

        Design: Difficulty/boundary_precision_check/decide_with_empty_authorized_item_ids_awards_zero_slots
        """
        decide_awarding_nothing(api, locked_review_with_one_live_deck)

        principal = fixtures.get_principal(
            api, locked_review_with_one_live_deck["principal"]["id"]
        )
        assert principal["slotting_committed_cents"] == 0
        assert principal["open_slotting_liability_cents"] == 0
        assert principal["at_risk_authorization_count"] == 0

    def test_a_declined_deck_does_not_undo_catalog_validation(
        self, api, locked_review_with_one_live_deck
    ):
        """The item keeps its terminal validated catalog state.

        PRD: "Validation moves `catalog_state` from `SUBMITTED` to `VALIDATED`, which is
        terminal: the item is now eligible to appear in a submitted presentation and to be
        awarded an authorization, and the `prep_completeness_bps` of every `DRAFT`
        presentation listing this item is recomputed."

        Design: Difficulty/boundary_precision_check/decide_with_empty_authorized_item_ids_awards_zero_slots
        """
        decide_awarding_nothing(api, locked_review_with_one_live_deck)

        item = get_success_data(
            api.get_item(locked_review_with_one_live_deck["item"]["id"], ACCOUNT_MANAGER_HEADERS),
            200,
        )
        assert item["catalog_state"] == CatalogState.VALIDATED
