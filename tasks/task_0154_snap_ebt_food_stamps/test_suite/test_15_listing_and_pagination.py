"""Listing endpoints: pagination, filters, sort order.

Covers PRD §2.3 (pagination), §3.10 (filters and sort by created_at asc).
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    NON_EXISTENT_UUID,
    ERR_VALIDATION,
    TEST_USERS, make_merchant_headers,
    create_household, setup_authorized_merchant,
    setup_full_purchase_scene, create_transaction_payload,
)


CASEWORKER = TEST_USERS["caseworker_headers"]
FRAUD_INV = TEST_USERS["fraud_investigator_headers"]


class TestPaginationBasics:
    def test_default_pagination_limit(self, api):
        """PRD §2.3: "List endpoints accept two query parameters: `limit`
        (default 10, minimum 1, maximum 100) and `offset` (default 0)."

        Claim: omitting limit applies the default of 10.
        """
        create_household()
        resp = api.list_households(CASEWORKER)
        _, meta = validate_paginated(resp)
        # Default limit should be 10
        assert meta.get("limit") == 10

    def test_pagination_limit_bound_lower(self, api):
        """PRD §2.3: "limit (default 10, minimum 1, maximum 100)."

        Claim: limit=0 yields ERR_VALIDATION.
        """
        resp = api.list_households(CASEWORKER, params={"limit": 0})
        validate_error(resp, ERR_VALIDATION)

    def test_pagination_limit_bound_upper(self, api):
        """PRD §2.3: "limit (default 10, minimum 1, maximum 100)."

        Claim: limit=101 yields ERR_VALIDATION.
        """
        resp = api.list_households(CASEWORKER, params={"limit": 101})
        validate_error(resp, ERR_VALIDATION)

    def test_pagination_explicit_limit_1(self, api):
        """PRD §2.3: "limit (default 10, minimum 1, maximum 100)."

        Claim: limit=1 is accepted.
        """
        create_household()
        create_household()
        resp = api.list_households(CASEWORKER, params={"limit": 1})
        data, meta = validate_paginated(resp)
        assert len(data) <= 1
        assert meta["limit"] == 1


class TestSortOrder:
    def test_households_sorted_by_created_at_asc(self, api):
        """PRD §3.10: "All list endpoints honor the standard `limit` and
        `offset` pagination from §2.3 and emit results in `created_at`
        ascending order."

        Claim: household list is sorted by created_at ascending.
        """
        h1 = create_household()
        h2 = create_household()
        h3 = create_household()
        resp = api.list_households(CASEWORKER, params={"limit": 100})
        data, _ = validate_paginated(resp)
        ids = [h["id"] for h in data]
        if h1["id"] in ids and h2["id"] in ids and h3["id"] in ids:
            # Filter for our created ones
            ts_order = [
                h["created_at"] for h in data
                if h["id"] in {h1["id"], h2["id"], h3["id"]}
            ]
            assert ts_order == sorted(ts_order), (
                f"Households not in created_at ASC order: {ts_order}"
            )


class TestTransactionFilters:
    def test_list_transactions_filter_by_card(self, api):
        """PRD §3.10: "Listing transactions supports filters on `card_id`,
        `merchant_id`, and `status`."

        Claim: filtering by card_id restricts results.
        """
        ctx = setup_full_purchase_scene(size=1, age=30)
        m_headers = make_merchant_headers(ctx["merchant"]["id"])
        payload = create_transaction_payload(
            card_id=ctx["card"]["id"], merchant_id=ctx["merchant"]["id"],
            line_items=[{"item_category": "STAPLE", "unit_price_cents": 100, "quantity": 1}],
        )
        validate_success(api.create_transaction(payload, m_headers), expected_status=201)
        resp = api.list_transactions(
            CASEWORKER, params={"card_id": ctx["card"]["id"], "limit": 100}
        )
        data, _ = validate_paginated(resp)
        for tx in data:
            assert tx["card_id"] == ctx["card"]["id"]
