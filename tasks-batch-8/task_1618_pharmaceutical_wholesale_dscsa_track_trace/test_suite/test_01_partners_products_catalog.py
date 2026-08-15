"""Partner/product catalog: creation defaults, required fields, uniqueness,
referential integrity, 404s, and the pagination envelope."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_product,
    assert_trading_partner,
    create_license_payload,
    create_product_payload,
    create_trading_partner_payload,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTradingPartnerCreation:
    def test_create_partner_initializes_computed_counters(
        self, api, order_manager_headers, compliance_officer_headers
    ):
        """PRD §3.1: "Two computed counters start at zero on every new partner.
        The first, `open_receivable_cents`, equals at any moment the sum of
        outstanding invoice balances across that partner's orders whose
        financial status is `INVOICED` or `PARTIALLY_PAID`... The second,
        `allocation_watermark_units`, is a rolling historical-usage watermark
        consulted for shortage-allocation fairness."

        Design: Corner/entities/create_trading_partner_required_fields_and_defaults
        """
        set_clock()
        payload = create_trading_partner_payload(
            partner_name="NewRx", partner_kind="CUSTOMER", credit_limit_cents=5000
        )
        resp = api.create_trading_partner(payload, order_manager_headers)
        data = validate_success(resp, expected_status=201)
        assert_trading_partner(data)
        assert data["open_receivable_cents"] == 0, (
            f"open_receivable_cents must start at 0, got {data['open_receivable_cents']}"
        )
        assert data["allocation_watermark_units"] == 0, (
            "allocation_watermark_units must start at 0, "
            f"got {data['allocation_watermark_units']}"
        )

        follow_up = api.get_trading_partner(data["id"], compliance_officer_headers)
        fetched = validate_success(follow_up)
        assert fetched["partner_name"] == "NewRx"
        assert fetched["open_receivable_cents"] == 0

    def test_create_partner_missing_credit_limit_rejected(
        self, api, order_manager_headers
    ):
        """PRD §3.1: "An `OrderManager` onboards a counterparty by registering a
        trading partner with its legal `partner_name`, a `partner_kind` of
        exactly `CUSTOMER` or `SUPPLIER`, and a non-negative `credit_limit_cents`
        capping the open receivable the partner may carry."
        PRD §2.8: "Requests that are malformed, that omit a required field, or
        that carry a value of the wrong type are rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/create_trading_partner_missing_required_returns_invalid_request
        """
        payload = create_trading_partner_payload(partner_name="NoCredit")
        payload.pop("credit_limit_cents")
        resp = api.create_trading_partner(payload, order_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestProductCatalog:
    def test_get_unknown_product_returns_not_found(self, api, order_manager_headers):
        """PRD §2.8: "The request is rejected immediately with `ERR_NOT_FOUND`
        (HTTP 404) at the first path identifier that does not correspond to an
        existing resource, before later identifiers or the request body are
        examined."

        Design: Corner/entities/get_nonexistent_product_returns_not_found
        """
        resp = api.get_product(NON_EXISTENT_UUID, order_manager_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_duplicate_ndc_rejected(self, api, order_manager_headers):
        """PRD §3.2: "Products are registered by an `OrderManager` with an
        11-digit canonical `ndc` that is unique across the catalog — a duplicate
        is rejected with `ERR_DUPLICATE_UNIQUE_FIELD` (HTTP 409)".

        Design: Corner/entities/create_product_duplicate_ndc_rejected
        """
        first = create_product_payload(ndc="00000000900", product_name="First")
        resp1 = api.create_product(first, order_manager_headers)
        validate_success(resp1, expected_status=201)

        dupe = create_product_payload(ndc="00000000900", product_name="Dupe")
        resp2 = api.create_product(dupe, order_manager_headers)
        validate_error(resp2, ApiErrorId.ERR_DUPLICATE_UNIQUE_FIELD)

    def test_product_list_pagination_envelope(self, api, order_manager_headers):
        """PRD §2.3: "`limit` caps the number of items returned; when omitted it
        defaults to 10, and it accepts a minimum of 1 and a maximum of 100.
        `offset` skips that many items from the front of the result set and
        defaults to 0."
        PRD §2.3: "Paginated and non-paginated list-based responses include the
        following fields in the `meta` object of the response envelope: `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/list_products_pagination_envelope
        """
        for i in range(3):
            resp = api.create_product(
                create_product_payload(product_name=f"P{i}"), order_manager_headers
            )
            validate_success(resp, expected_status=201)

        page1 = api.list_products(order_manager_headers, params={"limit": 2, "offset": 0})
        data1, meta1 = validate_paginated(page1)
        assert len(data1) == 2, f"limit=2 must return 2 rows, got {len(data1)}"
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        for row in data1:
            assert_product(row)

        page2 = api.list_products(order_manager_headers, params={"limit": 2, "offset": 2})
        data2, meta2 = validate_paginated(page2)
        assert len(data2) == 1, f"offset=2 of 3 must return 1 row, got {len(data2)}"
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestLicenseReferentialIntegrity:
    def test_license_with_unknown_partner_rejected(self, api, compliance_officer_headers):
        """PRD §2.8: "Identifiers referenced inside a request body are resolved
        after path validation: `customer_id`, `product_id`, `case_id`,
        `order_id`, and the partner identifiers supplied on event capture must
        each name an existing resource, and an unknown body reference is
        rejected with `ERR_REFERENCE_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/create_license_fk_integrity
        """
        payload = create_license_payload(
            NON_EXISTENT_UUID, state_code="CA", license_number="LIC-GHOST"
        )
        resp = api.create_partner_state_license(payload, compliance_officer_headers)
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)
