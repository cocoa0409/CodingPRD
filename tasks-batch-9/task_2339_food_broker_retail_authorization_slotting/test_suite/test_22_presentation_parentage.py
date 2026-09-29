"""A deck has three parents, and each bad reference lands on its own rung."""

import pytest

from test_helpers import (
    ACCOUNT_MANAGER_HEADERS,
    NON_EXISTENT_UUID,
    UPC_1,
    UPC_2,
    ApiErrorId,
    PresentationStatus,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers import factories as F
from test_helpers.assertions import assert_presentation


@pytest.fixture
def open_review_with_two_owners(api):
    """One open review, two principals, and one validated item belonging to each."""
    retailer = fixtures.create_retailer(api, total_store_count=1200)
    northwind = fixtures.create_principal(api, name="Northwind Foods", code="NWF")
    sunglow = fixtures.create_principal(api, name="Sunglow Frozen", code="SGF")
    return {
        "retailer": retailer,
        "northwind": northwind,
        "sunglow": sunglow,
        "own_item": fixtures.validated_item(api, northwind["id"], retailer["id"], upc=UPC_1),
        "foreign_item": fixtures.validated_item(
            api,
            sunglow["id"],
            retailer["id"],
            upc=UPC_2,
            description="Frozen Empanadas 10ct",
            case_pack_units=10,
        ),
        "review": fixtures.opened_review(api, retailer["id"]),
    }


def attempt_presentation(api, review_id, principal_id, item_ids):
    return api.create_presentation(
        F.presentation_payload(review_id, principal_id, item_ids), ACCOUNT_MANAGER_HEADERS
    )


class TestPresentationParentage:
    def test_an_unknown_review_is_a_not_found(self, api, open_review_with_two_owners):
        """The deck's calendar parent is resolved first and it does not exist.

        PRD: "Body foreign keys are resolved after the path, in the order the payload declares
        them."

        Design: Corner/entities/presentation_parent_lookups_and_item_ownership_rejected
        """
        scope = open_review_with_two_owners
        response = attempt_presentation(
            api, NON_EXISTENT_UUID, scope["northwind"]["id"], [scope["own_item"]["id"]]
        )

        validate_error(response, ApiErrorId.REVIEW_NOT_FOUND, 404)

    def test_an_unknown_principal_is_a_not_found(self, api, open_review_with_two_owners):
        """A real review does not rescue an imaginary presenter.

        PRD: "The catalogue of not-found codes is one per entity type:
        `ERR_RETAILER_NOT_FOUND`, `ERR_PRINCIPAL_NOT_FOUND` (covering `principal_id`,
        `principal_a_id` and `principal_b_id`), `ERR_AGREEMENT_NOT_FOUND`,
        `ERR_CONFLICT_RULE_NOT_FOUND`, `ERR_ITEM_NOT_FOUND` (covering an element of `item_ids`
        or of `authorized_item_ids`), `ERR_REVIEW_NOT_FOUND`, `ERR_PRESENTATION_NOT_FOUND`,
        `ERR_DEAL_NOT_FOUND`, `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_SNAPSHOT_NOT_FOUND`,
        `ERR_PROMOTION_NOT_FOUND` and `ERR_DEDUCTION_NOT_FOUND` (covering
        `original_deduction_id`)."

        Design: Corner/entities/presentation_parent_lookups_and_item_ownership_rejected
        """
        scope = open_review_with_two_owners
        response = attempt_presentation(
            api, scope["review"]["id"], NON_EXISTENT_UUID, [scope["own_item"]["id"]]
        )

        validate_error(response, ApiErrorId.PRINCIPAL_NOT_FOUND, 404)

    def test_an_item_of_another_principal_is_a_referential_error_not_a_not_found(
        self, api, open_review_with_two_owners
    ):
        """The foreign item exists, so existence checks pass and ownership fails instead.

        PRD: "A `BrokerAccountManager` prepares a deck against a `review_id` and a
        `principal_id` with `item_ids`, an ordered array of between one and five item
        identifiers with no duplicates; every listed item must belong to the presenting
        principal, and a foreign item is rejected with `ERR_ITEM_PRINCIPAL_MISMATCH`."

        Design: Corner/entities/presentation_parent_lookups_and_item_ownership_rejected
        """
        scope = open_review_with_two_owners
        response = attempt_presentation(
            api,
            scope["review"]["id"],
            scope["northwind"]["id"],
            [scope["own_item"]["id"], scope["foreign_item"]["id"]],
        )

        validate_error(response, ApiErrorId.ITEM_PRINCIPAL_MISMATCH, 422)

    def test_the_well_formed_deck_starts_in_draft(self, api, open_review_with_two_owners):
        """Only the presenter's own item is listed, so the deck is created.

        PRD: "A new deck begins with `status` at `DRAFT`, `authorized_item_count` at 0 and
        `submitted_at` null, and reports its preparation progress as `prep_completeness_bps`:
        the count of listed items whose `catalog_state` is `VALIDATED`, multiplied by 10,000,
        divided by the total number of listed items, floored to a whole number of basis points."

        Design: Corner/entities/presentation_parent_lookups_and_item_ownership_rejected
        """
        scope = open_review_with_two_owners
        presentation = get_success_data(
            attempt_presentation(
                api, scope["review"]["id"], scope["northwind"]["id"], [scope["own_item"]["id"]]
            ),
            201,
        )

        assert_presentation(presentation)
        assert presentation["status"] == PresentationStatus.DRAFT
        assert presentation["authorized_item_count"] == 0
        assert presentation["submitted_at"] is None

    def test_only_one_deck_per_review_and_principal_survives(
        self, api, open_review_with_two_owners
    ):
        """A second attempt for the same pair is refused and nothing is duplicated.

        PRD: "Only one deck may exist per review and principal, a second attempt being
        `ERR_PRESENTATION_DUPLICATE`."

        Design: Corner/entities/presentation_parent_lookups_and_item_ownership_rejected
        """
        scope = open_review_with_two_owners
        first = get_success_data(
            attempt_presentation(
                api, scope["review"]["id"], scope["northwind"]["id"], [scope["own_item"]["id"]]
            ),
            201,
        )

        validate_error(
            attempt_presentation(
                api, scope["review"]["id"], scope["northwind"]["id"], [scope["own_item"]["id"]]
            ),
            ApiErrorId.PRESENTATION_DUPLICATE,
            409,
        )

        rows, meta = validate_paginated(
            api.list_presentations(ACCOUNT_MANAGER_HEADERS, {"review_id": scope["review"]["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first["id"]
