"""Submit and decide read other rows: catalog state, deck membership and the half-open window."""

import pytest

from test_helpers import (
    ACCOUNT_MANAGER_HEADERS,
    ApiErrorId,
    CatalogState,
    PresentationStatus,
    ReviewStatus,
    UPC_1,
    UPC_2,
    UPC_3,
    fixtures,
    get_success_data,
    make_retailer_buyer_headers,
    validate_error,
)
from test_helpers import factories as F

AWARD_STORE_COUNT = 400
WINDOW_END_INSTANT = "2026-09-15T00:00:00Z"
LAST_DECIDABLE_INSTANT = "2026-09-14T00:00:00Z"


@pytest.fixture
def deck_listing_one_validated_and_one_submitted_item(api):
    """I1 is VALIDATED, I2 only SUBMITTED, I3 is VALIDATED but on no deck at all."""
    retailer = fixtures.create_retailer(api, total_store_count=1200)
    bundle = fixtures.active_principal(api, retailer["id"])
    principal = bundle["principal"]
    validated_item = fixtures.validated_item(api, principal["id"], retailer["id"], upc=UPC_1)
    pending_item = fixtures.create_item(
        api, principal["id"], upc=UPC_2, description="Frozen Empanadas 10ct"
    )
    pending_item = get_success_data(
        api.submit_catalog(
            pending_item["id"],
            F.catalog_submission_payload(upc=UPC_2, shelf_life_days=300),
            ACCOUNT_MANAGER_HEADERS,
        ),
        200,
    )
    unlisted_item = fixtures.validated_item(
        api, principal["id"], retailer["id"], upc=UPC_3, description="Churro Bites 8ct"
    )
    review = fixtures.opened_review(api, retailer["id"], new_item_slots=3)
    presentation = fixtures.create_presentation(
        api, review["id"], principal["id"], [validated_item["id"], pending_item["id"]]
    )
    return {
        "retailer": retailer,
        "principal": principal,
        "validated_item": validated_item,
        "pending_item": pending_item,
        "unlisted_item": unlisted_item,
        "review": review,
        "presentation": presentation,
    }


def submit_the_deck(api, scope):
    return api.submit_presentation(scope["presentation"]["id"], ACCOUNT_MANAGER_HEADERS)


def read_deck(api, scope):
    return get_success_data(
        api.get_presentation(scope["presentation"]["id"], ACCOUNT_MANAGER_HEADERS), 200
    )


def validate_the_pending_item(api, scope):
    return get_success_data(
        api.decide_catalog(
            scope["pending_item"]["id"],
            F.catalog_decision_payload(),
            make_retailer_buyer_headers(scope["retailer"]["id"]),
        ),
        200,
    )


def submitted_and_locked(api, scope):
    """Get the deck in and the review locked, leaving only the decision to make."""
    validate_the_pending_item(api, scope)
    get_success_data(submit_the_deck(api, scope), 200)
    return fixtures.lock_review(api, scope["review"]["id"], scope["retailer"]["id"])


def attempt_decision(api, scope, item_ids, review_version):
    return api.decide_review(
        scope["review"]["id"],
        F.decide_payload(review_version, item_ids, default_store_count=AWARD_STORE_COUNT),
        make_retailer_buyer_headers(scope["retailer"]["id"]),
    )


class TestCrossEntityStateAndWindowChecks:
    def test_a_deck_listing_an_unvalidated_item_cannot_be_submitted(
        self, api, deck_listing_one_validated_and_one_submitted_item
    ):
        """One of the two listed items is only SUBMITTED, and the deck reports half completeness.

        PRD: "and every item in `item_ids` must have `catalog_state` equal to `VALIDATED`, otherwise
        `ERR_ITEM_CATALOG_NOT_VALIDATED`"

        PRD: "A new deck begins with `status` at `DRAFT`, `authorized_item_count` at 0 and
        `submitted_at` null, and reports its preparation progress as `prep_completeness_bps`: the
        count of listed items whose `catalog_state` is `VALIDATED`, multiplied by 10,000, divided by
        the total number of listed items, floored to a whole number of basis points."

        Design: Corner/validations/cross_entity_state_and_window_checks_on_submit_and_decide
        """
        scope = deck_listing_one_validated_and_one_submitted_item
        assert scope["pending_item"]["catalog_state"] == CatalogState.SUBMITTED

        response = submit_the_deck(api, scope)

        validate_error(response, ApiErrorId.ITEM_CATALOG_NOT_VALIDATED, 422)
        deck = read_deck(api, scope)
        assert deck["status"] == PresentationStatus.DRAFT
        assert deck["submitted_at"] is None
        assert deck["prep_completeness_bps"] == 5000

    def test_validating_the_last_item_unblocks_the_same_submission(
        self, api, deck_listing_one_validated_and_one_submitted_item
    ):
        """Nothing about the deck changes — only the catalog state of a row it points at.

        PRD: "Validation moves `catalog_state` from `SUBMITTED` to `VALIDATED`, which is terminal:
        the item is now eligible to appear in a submitted presentation and to be awarded an
        authorization, and the `prep_completeness_bps` of every `DRAFT` presentation listing this item
        is recomputed."

        Design: Corner/validations/cross_entity_state_and_window_checks_on_submit_and_decide
        """
        scope = deck_listing_one_validated_and_one_submitted_item
        validate_error(submit_the_deck(api, scope), ApiErrorId.ITEM_CATALOG_NOT_VALIDATED, 422)

        validated = validate_the_pending_item(api, scope)
        submitted = get_success_data(submit_the_deck(api, scope), 200)

        assert validated["catalog_state"] == CatalogState.VALIDATED
        assert submitted["status"] == PresentationStatus.SUBMITTED
        assert submitted["prep_completeness_bps"] == 10000

    def test_a_locked_review_reports_a_state_error_rather_than_the_closed_deadline(
        self, api, deck_listing_one_validated_and_one_submitted_item
    ):
        """The deck is still DRAFT with an unvalidated item and the deadline has passed, yet the
        review's own state is what answers.

        PRD: "First come the state checks: the review must be `OPEN`, otherwise
        `ERR_REVIEW_NOT_OPEN`, and the principal's `status` must be `ACTIVE`, otherwise
        `ERR_PRINCIPAL_NOT_ACTIVE`."

        PRD: "and a state violation outranks a temporal one, so submitting into a locked review
        reports `ERR_REVIEW_NOT_OPEN` rather than a closed-deadline error."

        Design: Corner/validations/cross_entity_state_and_window_checks_on_submit_and_decide
        """
        scope = deck_listing_one_validated_and_one_submitted_item
        locked = fixtures.lock_review(api, scope["review"]["id"], scope["retailer"]["id"])
        assert locked["status"] == ReviewStatus.PRESENTATION_LOCKED

        response = submit_the_deck(api, scope)

        validate_error(response, ApiErrorId.REVIEW_NOT_OPEN, 409)
        assert read_deck(api, scope)["status"] == PresentationStatus.DRAFT

    def test_the_decision_window_excludes_its_own_end_date(
        self, api, deck_listing_one_validated_and_one_submitted_item
    ):
        """2026-09-15 is `review_window_end`, so the last decidable day was 2026-09-14.

        PRD: "The logical-clock date must lie inside the half-open decision window — on or after
        `review_window_start` and strictly before `review_window_end` — otherwise
        `ERR_REVIEW_WINDOW_CLOSED`."

        PRD: "A review may be decided when the logical clock date is on or after
        `review_window_start` and strictly before `review_window_end`."

        Design: Corner/validations/cross_entity_state_and_window_checks_on_submit_and_decide
        """
        scope = deck_listing_one_validated_and_one_submitted_item
        locked = submitted_and_locked(api, scope)
        fixtures.set_clock(api, WINDOW_END_INSTANT)

        response = attempt_decision(
            api, scope, [scope["validated_item"]["id"]], locked["version"]
        )

        validate_error(response, ApiErrorId.REVIEW_WINDOW_CLOSED, 422)

    def test_a_validated_item_of_the_same_principal_cannot_be_awarded_off_deck(
        self, api, deck_listing_one_validated_and_one_submitted_item
    ):
        """I3 is VALIDATED and belongs to the presenting principal, but no deck of this review lists
        it.

        PRD: "Every element of `authorized_item_ids` must be an item listed by a presentation of
        *this* review whose `status` is `SUBMITTED`, and that item's principal must not be terminated;
        a stray identifier that resolves to no item at all is `ERR_ITEM_NOT_FOUND`, while an item that
        exists but is not in a submitted deck of this review is
        `ERR_ITEM_NOT_IN_SUBMITTED_PRESENTATION`."

        Design: Corner/validations/cross_entity_state_and_window_checks_on_submit_and_decide
        """
        scope = deck_listing_one_validated_and_one_submitted_item
        locked = submitted_and_locked(api, scope)
        fixtures.set_clock(api, LAST_DECIDABLE_INSTANT)

        response = attempt_decision(
            api,
            scope,
            [scope["validated_item"]["id"], scope["unlisted_item"]["id"]],
            locked["version"],
        )

        validate_error(response, ApiErrorId.ITEM_NOT_IN_SUBMITTED_PRESENTATION, 422)

    def test_the_refused_decisions_leave_the_version_pin_usable(
        self, api, deck_listing_one_validated_and_one_submitted_item
    ):
        """Two rejected decisions later, the original pin still awards the one legal item.

        PRD: "On success `decided_at` is stamped from the logical clock, `slots_awarded` increases by
        the number of awarded items, and the review's `version` advances by one."

        Design: Corner/validations/cross_entity_state_and_window_checks_on_submit_and_decide
        """
        scope = deck_listing_one_validated_and_one_submitted_item
        locked = submitted_and_locked(api, scope)
        pinned_version = locked["version"]
        fixtures.set_clock(api, WINDOW_END_INSTANT)
        validate_error(
            attempt_decision(api, scope, [scope["validated_item"]["id"]], pinned_version),
            ApiErrorId.REVIEW_WINDOW_CLOSED,
            422,
        )
        fixtures.set_clock(api, LAST_DECIDABLE_INSTANT)
        validate_error(
            attempt_decision(
                api,
                scope,
                [scope["validated_item"]["id"], scope["unlisted_item"]["id"]],
                pinned_version,
            ),
            ApiErrorId.ITEM_NOT_IN_SUBMITTED_PRESENTATION,
            422,
        )

        decided = get_success_data(
            attempt_decision(api, scope, [scope["validated_item"]["id"]], pinned_version), 200
        )

        assert decided["status"] == ReviewStatus.DECIDED
        assert decided["slots_awarded"] == 1
        assert decided["version"] == pinned_version + 1
        authorizations = fixtures.authorizations_for_review(api, scope["review"]["id"])
        assert [row["item_id"] for row in authorizations] == [scope["validated_item"]["id"]]
