"""Catalog/customer creation rules, uniqueness, defaults, and read envelopes."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_customer_account,
    assert_item,
    assert_stock_location,
    create_branch,
    create_customer,
    create_customer_payload,
    create_item,
    create_item_payload,
    create_location_payload,
    get_success_data,
    place_order,
    restock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCustomerCreation:
    def test_customer_creation_applies_defaults(self, api, admin_headers):
        """PRD §3.1: "The account's `price_tier` — one of `STANDARD`, `SILVER`,
        `GOLD`, or `PLATINUM` — selects which row set of the contract price matrix
        applies and defaults to `STANDARD`. The `is_national_account` flag defaults
        to false and gates rebate eligibility later. The `approval_threshold_cents`,
        defaulting to zero, controls the punch-out approval fork described in §3.4.
        New accounts are born in `ACTIVE` status with both fiscal counters at zero"
        PRD §2.5: "`version` (integer): starts at 1 on creation and increments by
        exactly one on every mutation of the resource"

        Design: Corner/entities/customer_creation_applies_defaults
        """
        payload = {
            "account_number": "DF-1",
            "display_name": "Defaults Co",
            "credit_limit_cents": 50000,
            "primary_ship_to_state": "OH",
        }
        data = validate_success(api.create_customer(payload, admin_headers), 201)
        assert_customer_account(data)
        assert data["price_tier"] == "STANDARD"
        assert data["is_national_account"] is False
        assert data["approval_threshold_cents"] == 0
        assert data["status"] == "ACTIVE"
        assert data["net_spend_cents"] == 0
        assert data["open_credit_exposure_cents"] == 0
        assert data["version"] == 1

    def test_customer_create_missing_required_field_returns_err_validation(
        self, api, admin_headers
    ):
        """PRD §2.10: "Fifth, the request shape is validated — required fields
        present, enum members valid, quantities at least one, amounts non-negative,
        windows well-formed — with any violation rejected as `ERR_VALIDATION`."
        PRD §3.1: "A `CustomerAccount` is created with a unique `account_number` ...,
        a `display_name`, a `credit_limit_cents` ceiling that may be zero but never
        negative, and a `primary_ship_to_state`"

        Design: Corner/entities/customer_create_missing_required_field_returns_invalid_request
        """
        payload = {
            "account_number": "DF-2",
            "display_name": "Missing Field Co",
            "primary_ship_to_state": "OH",
        }
        res = api.create_customer(payload, admin_headers)
        validate_error(res, ApiErrorId.ERR_VALIDATION)


class TestItemCatalog:
    def test_item_creation_and_retrieval_roundtrip(self, api, admin_headers):
        """PRD §3.1: "Items intended for the vendor drop-ship channel are flagged
        `drop_ship_eligible` (default false) and carry planning figures
        `vendor_cost_estimate_cents` and `vendor_freight_estimate_cents`"
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/entities/item_creation_and_retrieval_roundtrip
        """
        payload = {
            "sku": "RT-1",
            "description": "Roundtrip filter",
            "item_class": "STOCKED",
            "hazmat_restriction": "GROUND_ONLY",
            "restricted_states": ["CA"],
            "list_price_cents": 1234,
            "drop_ship_eligible": True,
            "vendor_cost_estimate_cents": 700,
            "vendor_freight_estimate_cents": 60,
        }
        created = validate_success(api.create_item(payload, admin_headers), 201)
        assert_item(created)
        assert created["version"] == 1

        fetched = validate_success(api.get_item(created["id"], admin_headers), 200)
        assert_item(fetched)
        assert fetched["sku"] == "RT-1"
        assert fetched["hazmat_restriction"] == "GROUND_ONLY"
        assert fetched["restricted_states"] == ["CA"]
        assert fetched["list_price_cents"] == 1234
        assert fetched["drop_ship_eligible"] is True
        assert fetched["vendor_cost_estimate_cents"] == 700
        assert fetched["vendor_freight_estimate_cents"] == 60

    def test_item_duplicate_sku_rejected(self, api, admin_headers):
        """PRD §3.1: "Each item carries a unique `sku` — reusing an existing SKU is
        rejected with `ERR_SKU_ALREADY_EXISTS`"

        Design: Corner/entities/item_duplicate_sku_rejected
        """
        first = create_item_payload(sku="DUP-1", list_price_cents=100)
        validate_success(api.create_item(first, admin_headers), 201)
        second = create_item_payload(sku="DUP-1", list_price_cents=200)
        res = api.create_item(second, admin_headers)
        validate_error(res, ApiErrorId.ERR_SKU_ALREADY_EXISTS)

    def test_invalid_enum_value_rejected(self, api, admin_headers):
        """PRD §3.1: "The `item_class` of an item is one of `STOCKED`,
        `SPECIAL_ORDER`, or `NON_RETURNABLE`"
        PRD §2.10: "Fifth, the request shape is validated — required fields
        present, enum members valid, quantities at least one, amounts non-negative,
        windows well-formed — with any violation rejected as `ERR_VALIDATION`."

        Design: Corner/errors/invalid_enum_value_rejected
        """
        payload = create_item_payload(
            sku="EN-1", item_class="PLASTIC", list_price_cents=100
        )
        res = api.create_item(payload, admin_headers)
        validate_error(res, ApiErrorId.ERR_VALIDATION)

    def test_immediate_consistency_read_after_write(self, api, admin_headers):
        """PRD §3.1: "Regulatory handling is described by `hazmat_restriction` —
        `NONE` by default, or `GROUND_ONLY` or `WILL_CALL_ONLY` — together with
        `restricted_states`, a list of state codes where delivery of the item is
        prohibited (defaulting to empty). Items intended for the vendor drop-ship
        channel are flagged `drop_ship_eligible` (default false)"
        PRD §2.5: "`version` (integer): starts at 1 on creation and increments by
        exactly one on every mutation of the resource"

        Design: Corner/consistency_model/immediate_consistency_read_after_write
        """
        created = validate_success(
            api.create_item(
                create_item_payload(
                    sku="IC-1", item_class="SPECIAL_ORDER", list_price_cents=4321
                ),
                admin_headers,
            ),
            201,
        )
        assert created["drop_ship_eligible"] is False
        assert created["hazmat_restriction"] == "NONE"

        fetched = validate_success(api.get_item(created["id"], admin_headers), 200)
        assert fetched["list_price_cents"] == 4321
        assert fetched["item_class"] == "SPECIAL_ORDER"
        assert fetched["version"] == 1


class TestLocations:
    def test_location_cutoff_required_iff_branch(self, api, admin_headers):
        """PRD §3.3: "Branches make the customer-facing promise and therefore must
        declare `same_day_cutoff_minute`, a UTC minute-of-day from 0 through 1439;
        central depots must omit it. Supplying the cutoff for a `CENTRAL` site, or
        omitting it for a `BRANCH`, is a shape violation rejected with
        `ERR_VALIDATION`."

        Design: Corner/entities/location_cutoff_required_iff_branch
        """
        branch_no_cutoff = api.create_location(
            {"location_code": "BR-NC", "location_type": "BRANCH", "region_state": "OH"},
            admin_headers,
        )
        validate_error(branch_no_cutoff, ApiErrorId.ERR_VALIDATION)

        central_with_cutoff = api.create_location(
            {
                "location_code": "CN-WC",
                "location_type": "CENTRAL",
                "region_state": "OH",
                "same_day_cutoff_minute": 900,
            },
            admin_headers,
        )
        validate_error(central_with_cutoff, ApiErrorId.ERR_VALIDATION)

        branch_ok = validate_success(
            api.create_location(
                create_location_payload(
                    location_code="BR-OK", same_day_cutoff_minute=900
                ),
                admin_headers,
            ),
            201,
        )
        assert_stock_location(branch_ok)
        central_ok = validate_success(
            api.create_location(
                create_location_payload(location_code="CN-OK", location_type="CENTRAL"),
                admin_headers,
            ),
            201,
        )
        assert_stock_location(central_ok)

    def test_duplicate_account_number_and_location_code_rejected(
        self, api, admin_headers
    ):
        """PRD §3.1: "A `CustomerAccount` is created with a unique `account_number`
        (duplicates rejected with `ERR_ACCOUNT_NUMBER_EXISTS`)"
        PRD §3.3: "The fulfillment network is a flat set of `StockLocation` records,
        each with a unique `location_code` — duplicates are rejected with
        `ERR_LOCATION_CODE_EXISTS`"

        Design: Corner/errors/duplicate_account_number_and_location_code_rejected
        """
        create_customer(
            account_number="ACC-DUP", credit_limit_cents=1000,
            primary_ship_to_state="OH",
        )
        res1 = api.create_customer(
            create_customer_payload(
                account_number="ACC-DUP", credit_limit_cents=2000,
                primary_ship_to_state="MI",
            ),
            admin_headers,
        )
        validate_error(res1, ApiErrorId.ERR_ACCOUNT_NUMBER_EXISTS)

        create_branch(location_code="LOC-DUP", region_state="OH")
        res2 = api.create_location(
            create_location_payload(
                location_code="LOC-DUP", region_state="MI", same_day_cutoff_minute=800
            ),
            admin_headers,
        )
        validate_error(res2, ApiErrorId.ERR_LOCATION_CODE_EXISTS)


class TestReadEnvelopes:
    def test_error_envelope_and_not_found_for_all_resources(self, api, admin_headers):
        """PRD §2.8: "The same discipline applies to every other resource kind —
        `ERR_ITEM_NOT_FOUND`, `ERR_PRICE_RULE_NOT_FOUND`, `ERR_LOCATION_NOT_FOUND`,
        `ERR_CART_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, and `ERR_RETURN_NOT_FOUND` each
        reports the first unresolvable identifier of its kind"
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/endpoints/error_envelope_and_not_found_for_all_resources
        """
        cases = [
            (api.get_customer, ApiErrorId.ERR_CUSTOMER_NOT_FOUND),
            (api.get_item, ApiErrorId.ERR_ITEM_NOT_FOUND),
            (api.get_price_rule, ApiErrorId.ERR_PRICE_RULE_NOT_FOUND),
            (api.get_rebate_agreement, ApiErrorId.ERR_REBATE_AGREEMENT_NOT_FOUND),
            (api.get_location, ApiErrorId.ERR_LOCATION_NOT_FOUND),
            (api.get_cart, ApiErrorId.ERR_CART_NOT_FOUND),
            (api.get_order, ApiErrorId.ERR_ORDER_NOT_FOUND),
            (api.get_return, ApiErrorId.ERR_RETURN_NOT_FOUND),
        ]
        for getter, expected_error in cases:
            res = getter(NON_EXISTENT_UUID, admin_headers)
            validate_error(res, expected_error, expected_status=404)

    def _make_customer_with_orders(self, api, admin_headers, count):
        customer = create_customer(account_number=f"PG-{count}")
        item = create_item(sku=f"PG-IT-{count}", list_price_cents=100)
        branch = create_branch(location_code=f"BR-PG-{count}")
        restock(branch["id"], item["id"], count)
        for _ in range(count):
            place_order(
                customer["id"], branch["id"],
                [{"item_id": item["id"], "qty": 1}],
            )
        return customer, item, branch

    def test_orders_list_pagination_envelope(self, api, admin_headers):
        """PRD §2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
        the request that starts with `req_`. The `api_request_timestamp` is a
        server-generated ISO 8601 UTC timestamp with three fractional digits."

        Design: Corner/endpoints/orders_list_pagination_envelope
        """
        customer, _item, _branch = self._make_customer_with_orders(
            api, admin_headers, 3
        )

        page1 = api.list_orders(
            admin_headers, params={"customer_id": customer["id"], "limit": 2}
        )
        data1, meta1 = validate_paginated(page1)
        assert len(data1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0
        assert meta1["api_request_id"].startswith("req_")
        assert isinstance(meta1["api_request_timestamp"], str)

        page2 = api.list_orders(
            admin_headers,
            params={"customer_id": customer["id"], "limit": 2, "offset": 2},
        )
        data2, meta2 = validate_paginated(page2)
        assert len(data2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        assert meta2["api_request_id"].startswith("req_")
        assert isinstance(meta2["api_request_timestamp"], str)

    def test_orders_filtered_by_customer_id(self, api, admin_headers):
        """PRD §3.5: "The orders collection supports filtering by `customer_id`,
        `fulfillment_branch_id`, `source_cart_id`, and `status`, and an order's
        lines are always listed in creation order."

        Design: Corner/endpoints/orders_filtered_by_customer_id
        """
        customer_a = create_customer(account_number="FA-1")
        customer_b = create_customer(account_number="FB-1")
        item = create_item(sku="FLT-1", list_price_cents=100)
        branch = create_branch(location_code="BR-FL")
        restock(branch["id"], item["id"], 2)
        place_order(
            customer_a["id"], branch["id"], [{"item_id": item["id"], "qty": 1}]
        )
        place_order(
            customer_b["id"], branch["id"], [{"item_id": item["id"], "qty": 1}]
        )

        data, meta = validate_paginated(
            api.list_orders(admin_headers, params={"customer_id": customer_a["id"]})
        )
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert all(order["customer_id"] == customer_a["id"] for order in data)
        assert data[0]["customer_id"] == customer_a["id"]

    def test_order_lines_returned_in_creation_order(self, api, admin_headers):
        """PRD §3.5: "The orders collection supports filtering by `customer_id`,
        `fulfillment_branch_id`, `source_cart_id`, and `status`, and an order's
        lines are always listed in creation order."

        Design: Corner/endpoints/order_lines_returned_in_creation_order
        """
        customer = create_customer(account_number="LO-1")
        item_x = create_item(sku="LO-X", list_price_cents=100)
        item_y = create_item(sku="LO-Y", list_price_cents=200)
        branch = create_branch(location_code="BR-LO")
        restock(branch["id"], item_x["id"], 1)
        restock(branch["id"], item_y["id"], 1)
        order = place_order(
            customer["id"], branch["id"],
            [
                {"item_id": item_x["id"], "qty": 1},
                {"item_id": item_y["id"], "qty": 1},
            ],
        )

        data, _meta = validate_paginated(
            api.list_order_lines(order["id"], admin_headers)
        )
        assert len(data) == 2
        assert data[0]["item_id"] == item_x["id"]
        assert data[1]["item_id"] == item_y["id"]
