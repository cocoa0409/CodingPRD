"""Chain listings page by creation order and filter before they paginate."""

import pytest

from test_helpers import (
    ACCOUNT_MANAGER_HEADERS,
    DEFAULT_LIMIT,
    fixtures,
    validate_paginated,
)
from test_helpers.assertions import assert_ordered_by_created_at


@pytest.fixture
def three_chains_in_creation_order(api):
    """Bigmart, then Midco, then Tinymart — deliberately not alphabetical by id."""
    return [
        fixtures.create_retailer(api, name="Bigmart", chain_code="BIGMART", total_store_count=1200),
        fixtures.create_retailer(
            api, name="Midco Markets", chain_code="MIDCO", total_store_count=400
        ),
        fixtures.create_retailer(api, name="Tinymart", chain_code="TINYMART", total_store_count=40),
    ]


class TestRetailerListing:
    def test_the_first_page_reports_the_full_count_and_more_to_come(
        self, api, three_chains_in_creation_order
    ):
        """Two of three rows, with the unpaginated total alongside them.

        PRD: "Every list response reports `limit`, `offset`, `total_count` and `has_more` inside
        the `meta` object of the envelope, where `total_count` is the size of the filtered result
        set before pagination is applied."

        Design: Corner/entities/retailer_listing_paginates_and_filters_deterministically
        """
        response = api.list_retailers(ACCOUNT_MANAGER_HEADERS, {"limit": 2, "offset": 0})
        rows, meta = validate_paginated(response)

        assert response.json()["response_type"] == "array"
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        assert len(rows) == 2

    def test_the_page_window_walks_the_chains_in_creation_order(
        self, api, three_chains_in_creation_order
    ):
        """Page one holds Bigmart and Midco; page two holds Tinymart and nothing follows.

        PRD: "Unless a specific endpoint states otherwise, list results are ordered by
        `created_at` ascending."

        Design: Corner/entities/retailer_listing_paginates_and_filters_deterministically
        """
        first_page, _ = validate_paginated(
            api.list_retailers(ACCOUNT_MANAGER_HEADERS, {"limit": 2, "offset": 0})
        )
        second_page, second_meta = validate_paginated(
            api.list_retailers(ACCOUNT_MANAGER_HEADERS, {"limit": 2, "offset": 2})
        )

        expected_ids = [chain["id"] for chain in three_chains_in_creation_order]
        assert [row["id"] for row in first_page] == expected_ids[:2]
        assert len(second_page) == 1
        assert second_page[0]["id"] == expected_ids[2]
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False
        assert_ordered_by_created_at(first_page + second_page)

    def test_the_chain_code_filter_narrows_the_total_count_itself(
        self, api, three_chains_in_creation_order
    ):
        """Filtering happens before paging, so the total reflects one row, not three.

        PRD: "Retail chains may be filtered by `chain_code`."

        Design: Corner/entities/retailer_listing_paginates_and_filters_deterministically
        """
        rows, meta = validate_paginated(
            api.list_retailers(ACCOUNT_MANAGER_HEADERS, {"chain_code": "MIDCO"})
        )

        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert rows[0]["id"] == three_chains_in_creation_order[1]["id"]

    def test_omitting_the_pagination_parameters_uses_the_declared_defaults(
        self, api, three_chains_in_creation_order
    ):
        """No query string at all still yields an explicit limit of ten from offset zero.

        PRD: "`limit` caps the number of records returned; it defaults to 10, may not be smaller
        than 1, and may not exceed 100. `offset` skips a number of leading records and defaults
        to 0."

        Design: Corner/entities/retailer_listing_paginates_and_filters_deterministically
        """
        rows, meta = validate_paginated(api.list_retailers(ACCOUNT_MANAGER_HEADERS))

        assert meta["limit"] == DEFAULT_LIMIT
        assert meta["offset"] == 0
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert len(rows) == 3
