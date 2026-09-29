"""Codes are unique on the code alone, and an exclusive rate card locks out every other principal."""

import pytest

from test_helpers import (
    ACCOUNT_MANAGER_HEADERS,
    BROKER_ADMIN_HEADERS,
    ApiErrorId,
    PresentationStatus,
    UPC_1,
    UPC_2,
    fixtures,
    get_success_data,
    validate_error,
)
from test_helpers import factories as F

DAIRY = "DAIRY"
EXCLUSIVE_CODE = "SGF"
OPEN_CODE = "NWF"


@pytest.fixture
def one_exclusive_and_one_open_principal(api):
    """SGF holds an exclusive FROZEN_SNACKS card; NWF holds ordinary FROZEN_SNACKS and DAIRY cards."""
    retailer = fixtures.create_retailer(api, total_store_count=1200)
    open_bundle = fixtures.active_principal(
        api,
        retailer["id"],
        principal_overrides={"name": "Northwind Foods", "code": OPEN_CODE},
    )
    open_principal = open_bundle["principal"]
    fixtures.create_agreement(
        api,
        open_principal["id"],
        retailer["id"],
        activate=True,
        category_code=DAIRY,
        base_commission_bps=450,
        tier_threshold_cents=2000000,
        tier_commission_bps=250,
    )
    exclusive_bundle = fixtures.active_principal(
        api,
        retailer["id"],
        principal_overrides={"name": "Sunglow Frozen", "code": EXCLUSIVE_CODE},
        agreement_overrides={
            "base_commission_bps": 600,
            "tier_commission_bps": 400,
            "exclusive_in_category": True,
        },
    )
    exclusive_principal = exclusive_bundle["principal"]

    open_item = fixtures.validated_item(
        api, open_principal["id"], retailer["id"], upc=UPC_1
    )
    exclusive_item = fixtures.validated_item(
        api,
        exclusive_principal["id"],
        retailer["id"],
        upc=UPC_2,
        description="Frozen Empanadas 10ct",
    )

    frozen_review = fixtures.opened_review(api, retailer["id"])
    dairy_review = fixtures.opened_review(
        api,
        retailer["id"],
        category_code=DAIRY,
        review_window_start="2026-10-01",
        review_window_end="2026-10-15",
        submission_deadline="2026-09-20T00:00:00Z",
    )
    return {
        "retailer": retailer,
        "open_principal": open_principal,
        "exclusive_principal": exclusive_principal,
        "open_frozen_deck": fixtures.create_presentation(
            api, frozen_review["id"], open_principal["id"], [open_item["id"]]
        ),
        "open_dairy_deck": fixtures.create_presentation(
            api, dairy_review["id"], open_principal["id"], [open_item["id"]]
        ),
        "exclusive_frozen_deck": fixtures.create_presentation(
            api, frozen_review["id"], exclusive_principal["id"], [exclusive_item["id"]]
        ),
    }


def submit(api, deck):
    return api.submit_presentation(deck["id"], ACCOUNT_MANAGER_HEADERS)


def read_deck(api, deck):
    return get_success_data(api.get_presentation(deck["id"], ACCOUNT_MANAGER_HEADERS), 200)


class TestUniquenessAndCategoryExclusivity:
    def test_a_repeated_chain_code_is_refused_while_a_one_character_variant_is_accepted(
        self, api, one_exclusive_and_one_open_principal
    ):
        """The name may repeat freely; only `chain_code` is the unique key.

        PRD: "A retail chain's `chain_code` is globally unique (`ERR_CHAIN_CODE_DUPLICATE`)."

        Design: Corner/validations/global_uniqueness_and_category_exclusivity_rejected
        """
        duplicate = api.create_retailer(
            F.retailer_payload(
                name="Bigmart Wholesale", chain_code="BIGMART", total_store_count=50
            ),
            BROKER_ADMIN_HEADERS,
        )

        validate_error(duplicate, ApiErrorId.CHAIN_CODE_DUPLICATE, 409)
        accepted = get_success_data(
            api.create_retailer(
                F.retailer_payload(
                    name="Bigmart Wholesale", chain_code="BIGMART2", total_store_count=50
                ),
                BROKER_ADMIN_HEADERS,
            ),
            201,
        )
        assert accepted["chain_code"] == "BIGMART2"
        assert accepted["name"] == "Bigmart Wholesale"

    def test_a_repeated_principal_code_is_refused_while_a_variant_is_accepted(
        self, api, one_exclusive_and_one_open_principal
    ):
        """Two legally distinct entities may share a trading name but never a code.

        PRD: "A principal's `code` is globally unique (`ERR_PRINCIPAL_CODE_DUPLICATE`)."

        Design: Corner/validations/global_uniqueness_and_category_exclusivity_rejected
        """
        duplicate = api.create_principal(
            F.principal_payload(
                name="Northwind Foods LLC", code=OPEN_CODE, slotting_budget_cents=100000
            ),
            BROKER_ADMIN_HEADERS,
        )

        validate_error(duplicate, ApiErrorId.PRINCIPAL_CODE_DUPLICATE, 409)
        accepted = get_success_data(
            api.create_principal(
                F.principal_payload(
                    name="Northwind Foods LLC", code="NWF2", slotting_budget_cents=100000
                ),
                BROKER_ADMIN_HEADERS,
            ),
            201,
        )
        assert accepted["code"] == "NWF2"

    def test_an_exclusive_rate_card_blocks_another_principals_deck(
        self, api, one_exclusive_and_one_open_principal
    ):
        """NWF has its own ACTIVE, date-covering FROZEN_SNACKS card and is still refused.

        PRD: "And no *other* principal may hold an `ACTIVE`, date-covering agreement with
        `exclusive_in_category` set to true for this chain and category; if one does, the submission is
        `ERR_CATEGORY_EXCLUSIVITY`."

        Design: Corner/validations/global_uniqueness_and_category_exclusivity_rejected
        """
        scope = one_exclusive_and_one_open_principal

        response = submit(api, scope["open_frozen_deck"])

        validate_error(response, ApiErrorId.CATEGORY_EXCLUSIVITY, 409)
        assert read_deck(api, scope["open_frozen_deck"])["status"] == PresentationStatus.DRAFT

    def test_the_exclusivity_holder_is_not_blocked_by_its_own_card(
        self, api, one_exclusive_and_one_open_principal
    ):
        """The rule names every *other* principal, so the holder presents normally.

        PRD: "And no *other* principal may hold an `ACTIVE`, date-covering agreement with
        `exclusive_in_category` set to true for this chain and category; if one does, the submission is
        `ERR_CATEGORY_EXCLUSIVITY`."

        Design: Corner/validations/global_uniqueness_and_category_exclusivity_rejected
        """
        scope = one_exclusive_and_one_open_principal
        validate_error(
            submit(api, scope["open_frozen_deck"]), ApiErrorId.CATEGORY_EXCLUSIVITY, 409
        )

        submitted = get_success_data(submit(api, scope["exclusive_frozen_deck"]), 200)

        assert submitted["status"] == PresentationStatus.SUBMITTED
        assert submitted["principal_id"] == scope["exclusive_principal"]["id"]

    def test_exclusivity_does_not_reach_into_another_category(
        self, api, one_exclusive_and_one_open_principal
    ):
        """The same blocked principal submits freely in DAIRY, where nobody holds exclusivity.

        PRD: "The optional flag `exclusive_in_category` defaults to false; when true, it locks the
        whole category at that chain to this principal for as long as the agreement is `ACTIVE` and
        date-covering."

        PRD: "And no *other* principal may hold an `ACTIVE`, date-covering agreement with
        `exclusive_in_category` set to true for this chain and category; if one does, the submission is
        `ERR_CATEGORY_EXCLUSIVITY`."

        Design: Corner/validations/global_uniqueness_and_category_exclusivity_rejected
        """
        scope = one_exclusive_and_one_open_principal
        validate_error(
            submit(api, scope["open_frozen_deck"]), ApiErrorId.CATEGORY_EXCLUSIVITY, 409
        )

        submitted = get_success_data(submit(api, scope["open_dairy_deck"]), 200)

        assert submitted["status"] == PresentationStatus.SUBMITTED
        assert submitted["prep_completeness_bps"] == 10000
        assert read_deck(api, scope["open_frozen_deck"])["status"] == PresentationStatus.DRAFT
