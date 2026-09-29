"""A twelve-digit UPC-A code: shape, check digit and global uniqueness."""

import pytest

from test_helpers import (
    ACCOUNT_MANAGER_HEADERS,
    UPC_1,
    UPC_BAD_CHECK_DIGIT,
    ApiErrorId,
    CatalogState,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers import factories as F
from test_helpers.assertions import assert_item

SHORT_UPC = UPC_1[:11]


@pytest.fixture
def two_principals(api):
    """Two prospects, so uniqueness can be probed across owners as well as within one."""
    return {
        "northwind": fixtures.create_principal(api, name="Northwind Foods", code="NWF"),
        "sunglow": fixtures.create_principal(api, name="Sunglow Frozen", code="SGF"),
    }


def create_item_with_upc(api, principal_id, upc, description="Mini Tacos 12ct"):
    return api.create_item(
        F.item_payload(principal_id, upc=upc, description=description),
        ACCOUNT_MANAGER_HEADERS,
    )


class TestItemUpcIntegrity:
    def test_an_eleven_digit_code_is_a_shape_violation(self, api, two_principals):
        """Eleven characters never reaches the check-digit arithmetic.

        PRD: "**Request shape.** Required body fields present; types, enum membership and
        numeric ranges valid — for example `amortization_periods` between 1 and 12, `item_ids`
        holding 1 to 5 elements, every basis-point field within 0 through 10,000, `upc` exactly
        twelve digits, dates well-formed."

        Design: Corner/entities/item_upc_type_constraints_and_global_uniqueness_rejected
        """
        response = create_item_with_upc(
            api, two_principals["northwind"]["id"], SHORT_UPC, "Short UPC"
        )

        validate_error(response, ApiErrorId.INVALID_REQUEST, 400)

    def test_twelve_digits_with_the_wrong_mod_ten_digit_has_its_own_code(
        self, api, two_principals
    ):
        """Correct length, wrong GS1 check digit — a distinct 400 in the same band.

        PRD: "Those eleven products are summed, and the expected check digit is the amount that
        must be added to that sum to reach the next multiple of ten — zero when the sum is
        already a multiple of ten. If the twelfth digit differs from that expected value, the
        request is rejected with `ERR_UPC_CHECK_DIGIT_INVALID`."

        Design: Corner/entities/item_upc_type_constraints_and_global_uniqueness_rejected
        """
        assert len(UPC_BAD_CHECK_DIGIT) == 12
        assert UPC_BAD_CHECK_DIGIT[:11] == SHORT_UPC

        response = create_item_with_upc(
            api, two_principals["northwind"]["id"], UPC_BAD_CHECK_DIGIT, "Bad check digit"
        )

        validate_error(response, ApiErrorId.UPC_CHECK_DIGIT_INVALID, 400)

    def test_the_correct_code_creates_an_item_with_an_empty_catalog(self, api, two_principals):
        """A brand new item carries no catalog attributes at all.

        PRD: "A new item begins with `catalog_state` at `INCOMPLETE` and
        `catalog_submission_round` at 0, and its five catalog attributes — `gtin14`,
        `dimensions_cm`, `gross_weight_g`, `nutrition_panel_url` and `shelf_life_days` — are all
        null until the first catalog submission."

        Design: Corner/entities/item_upc_type_constraints_and_global_uniqueness_rejected
        """
        item = get_success_data(
            create_item_with_upc(api, two_principals["northwind"]["id"], UPC_1), 201
        )

        assert_item(item)
        assert item["upc"] == UPC_1
        assert item["catalog_state"] == CatalogState.INCOMPLETE
        assert item["catalog_submission_round"] == 0
        assert item["catalog_reject_reason"] is None
        assert item["gtin14"] is None
        assert item["dimensions_cm"] is None
        assert item["gross_weight_g"] is None
        assert item["nutrition_panel_url"] is None
        assert item["shelf_life_days"] is None

    def test_uniqueness_reaches_across_principals(self, api, two_principals):
        """A second owner does not buy a second copy of the same code.

        PRD: "An item's `upc` is globally unique across all principals
        (`ERR_UPC_DUPLICATE`)."

        Design: Corner/entities/item_upc_type_constraints_and_global_uniqueness_rejected
        """
        get_success_data(create_item_with_upc(api, two_principals["northwind"]["id"], UPC_1), 201)

        response = create_item_with_upc(
            api, two_principals["sunglow"]["id"], UPC_1, "Copycat Tacos"
        )

        validate_error(response, ApiErrorId.UPC_DUPLICATE, 409)

    def test_exactly_one_item_answers_to_that_code_afterwards(self, api, two_principals):
        """The three refused writes left the catalogue holding a single row.

        PRD: "Items may be filtered by `principal_id`, `catalog_state` and `upc`."

        Design: Corner/entities/item_upc_type_constraints_and_global_uniqueness_rejected
        """
        create_item_with_upc(api, two_principals["northwind"]["id"], SHORT_UPC, "Short UPC")
        create_item_with_upc(
            api, two_principals["northwind"]["id"], UPC_BAD_CHECK_DIGIT, "Bad check digit"
        )
        kept = get_success_data(
            create_item_with_upc(api, two_principals["northwind"]["id"], UPC_1), 201
        )
        create_item_with_upc(api, two_principals["sunglow"]["id"], UPC_1, "Copycat Tacos")

        rows, meta = validate_paginated(api.list_items(ACCOUNT_MANAGER_HEADERS, {"upc": UPC_1}))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == kept["id"]
        assert rows[0]["principal_id"] == two_principals["northwind"]["id"]
