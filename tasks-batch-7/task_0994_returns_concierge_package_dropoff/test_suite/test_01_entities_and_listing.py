"""Entity creation defaults, required-field and uniqueness guards, 404s,
append-only ledger shape, FK reverse listings, and pagination envelope."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_ID,
    add_order_to_tote,
    assert_refund_ledger_entry,
    assert_shopper,
    create_counter_order_dropped_off,
    create_location,
    create_merchant,
    create_order,
    create_published_plan,
    create_return_item_line,
    get_ledger,
    setup_commercial_spine,
    setup_tote_with_route,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestShopperCreation:

    def test_shopper_create_returns_defaults_and_201(self, api):
        """PRD §3.3: "The account starts `ACTIVE` with `fraud_strikes` at zero."
        PRD §2.4: "`version` (integer): starts at its initial value on creation".

        Design: Corner/entities/shopper_create_returns_defaults_and_201
        """
        from test_helpers import TEST_USERS, api_client, create_shopper_payload

        resp = api_client.create_shopper(
            create_shopper_payload(
                email="c1@x.com", full_name="Corner One", postal_code="30001"
            ),
            TEST_USERS["shopper_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert_shopper(data)
        assert data["status"] == "ACTIVE"
        assert data["fraud_strikes"] == 0
        assert data["version"] == 1

    def test_shopper_create_missing_required_email_returns_invalid_request(self, api):
        """PRD §3.3: "A **Shopper** registers — self-service, or via a
        `PlatformAdmin` — with an `email` that must be unique across shoppers,
        a `full_name`, and a `postal_code`."
        PRD §5: "`ERR_INVALID_REQUEST` | 400".

        Design: Corner/entities/shopper_create_missing_required_email_returns_invalid_request
        """
        from test_helpers import TEST_USERS, api_client
        resp = api_client.create_shopper(
            {"full_name": "No Email", "postal_code": "30002"},
            TEST_USERS["shopper_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_shopper_create_duplicate_email_rejected(self, api):
        """PRD §3.3: "A **Shopper** registers — self-service, or via a
        `PlatformAdmin` — with an `email` that must be unique across shoppers".

        Design: Corner/entities/shopper_create_duplicate_email_rejected
        """
        from test_helpers import TEST_USERS, api_client, create_shopper_payload
        first = api_client.create_shopper(
            create_shopper_payload(email="dup@x.com", full_name="First",
                                   postal_code="30003"),
            TEST_USERS["shopper_headers"],
        )
        validate_success(first, expected_status=201)
        resp = api_client.create_shopper(
            create_shopper_payload(email="dup@x.com", full_name="Second",
                                   postal_code="30004"),
            TEST_USERS["shopper_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestReturnOrderDefaults:

    def test_return_order_boxless_default_false_applied(self, api):
        """PRD §3.3: "A `Shopper` creates one for their own account by supplying
        `shopper_id` and `merchant_id`, choosing a fulfilment `method` of
        `LOCKER_QR`, `COUNTER_DROP`, or `HOME_PICKUP`, optionally setting
        `boxless`" — boxless is optional; a COUNTER_DROP create that omits it
        leaves it false.
        PRD §3.3: "A created order lands in `INITIATED` status."

        Design: Corner/entities/return_order_boxless_default_false_applied
        """
        spine = setup_commercial_spine(shopper_email="sdx@x.com")
        order = create_order(spine, method="COUNTER_DROP",
                             items=[create_return_item_line(sku="DF")])
        assert order["boxless"] is False
        assert order["status"] == "INITIATED"


class TestMerchantComputedFields:

    def test_merchant_create_computed_ledger_input_ignored(self, api):
        """PRD §3.1: "The account starts `ACTIVE` with a `ledger_balance_cents`
        of zero; that balance is a running total of the `total_cents` of the
        merchant's `SETTLED` billing cycles".

        Design: Corner/entities/merchant_create_computed_ledger_input_ignored
        """
        from test_helpers import TEST_USERS, api_client
        plan = create_published_plan()
        resp = api_client.create_merchant_account(
            {"legal_name": "M-Sneaky", "plan_id": plan["id"],
             "ledger_balance_cents": 999999},
            TEST_USERS["platform_admin_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert data["ledger_balance_cents"] == 0


class TestNotFound:

    def test_get_return_order_not_found_returns_404(self, api):
        """PRD §2.8: "path- and body-referenced identifiers exist, validated
        left to right, and enum fields carry a declared member, else
        `ERR_NOT_FOUND`, `ERR_ENUM_INVALID`, or `ERR_INVALID_REQUEST`."

        Design: Corner/entities/get_return_order_not_found_returns_404
        """
        from test_helpers import TEST_USERS, api_client
        resp = api_client.get_return_order(
            NON_EXISTENT_ID, TEST_USERS["platform_admin_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_nested_path_existence_left_to_right_not_found(self, api):
        """PRD §2.9: "The request is rejected immediately with `ERR_NOT_FOUND`
        (HTTP 404) for the first identifier in the path that does not
        correspond to an existing resource".

        Design: Corner/validations/nested_path_existence_left_to_right_not_found
        """
        from test_helpers import TEST_USERS, api_client
        resp = api_client.list_locker_slots(
            NON_EXISTENT_ID, TEST_USERS["platform_admin_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestLedgerShape:

    def test_refund_ledger_entry_immutable_no_version_field(self, api):
        """PRD §2.4: "The `RefundLedgerEntry` resource is the deliberate
        exception: it is an immutable, append-only event log and carries only
        `id` and `created_at`. Both `updated_at` and `version` are absent on
        ledger entries — an entry, once written, never changes."
        PRD §3.3: "the system computes the shopper-facing provisional refund
        and stores it in `refund_estimate_cents`, appending a matching
        `ESTIMATE` entry to the order's refund ledger with `actor_user_id`
        set to `system`."

        Design: Corner/entities/refund_ledger_entry_immutable_no_version_field
        """
        spine = setup_commercial_spine(shopper_email="sim@x.com")
        order = create_order(spine, method="COUNTER_DROP",
                             items=[create_return_item_line(sku="IM")])
        ledger = get_ledger(order["id"])
        assert len(ledger) == 1
        entry = ledger[0]
        assert_refund_ledger_entry(entry)
        assert entry["kind"] == "ESTIMATE"
        assert entry["amount_cents"] == order["refund_estimate_cents"]


class TestFkReverseListings:

    def test_fk_reverse_membership_list_shows_tote_members(self, api):
        """PRD §3.7: "Totes are listable with optional `route_id`,
        `location_id`, and `status` filters, and a tote's member orders are
        listable as a sub-collection."

        Design: Corner/entities/fk_reverse_membership_list_shows_tote_members
        """
        from test_helpers import api_client, make_location_operator_headers
        spine = setup_commercial_spine(shopper_email="sfk@x.com",
                                       plan_overrides={"pickup_enabled": True})
        location = create_location(name="L-FK", kind="COUNTER")
        route, tote = setup_tote_with_route(location)
        order = create_counter_order_dropped_off(spine, location)
        add_order_to_tote(tote, order, location["id"])
        resp = api_client.list_tote_return_orders(
            tote["id"], make_location_operator_headers(location["id"])
        )
        members = validate_success(resp)
        assert len(members) == 1
        assert members[0]["id"] == order["id"]

    def test_location_return_orders_subresource_lists_dropped_off(self, api):
        """PRD §3.5: "the orders dropped off there are listable with an
        optional `status` filter."
        PRD §3.4: "Confirmation moves the order `LABEL_ISSUED` → `DROPPED_OFF`,
        stamps `dropoff_location_id` with the location".

        Design: Corner/endpoints/location_return_orders_subresource_lists_dropped_off
        """
        from test_helpers import api_client, make_location_operator_headers
        spine = setup_commercial_spine(shopper_email="slr@x.com")
        location = create_location(name="L-LR", kind="COUNTER")
        order = create_counter_order_dropped_off(spine, location)
        resp = api_client.list_location_return_orders(
            location["id"], make_location_operator_headers(location["id"])
        )
        orders = validate_success(resp)
        assert len(orders) == 1
        assert orders[0]["id"] == order["id"]


class TestPagination:

    def test_merchant_list_pagination_envelope_defaults(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        when omitted it defaults to 10". "The `offset` parameter controls how
        many items are skipped and defaults to 0." "Paginated list responses
        carry the fields `limit`, `offset`, `total_count`, and `has_more`
        inside the `meta` object of the response envelope."

        Design: Corner/endpoints/merchant_list_pagination_envelope_defaults
        """
        plan = create_published_plan()
        for i in range(1, 13):
            create_merchant(plan["id"], legal_name=f"M-P{i:02d}")
        from test_helpers import TEST_USERS, api_client
        resp = api_client.list_merchant_accounts(TEST_USERS["platform_admin_headers"])
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 12
        assert meta["has_more"] is True
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert len(data) == 10
