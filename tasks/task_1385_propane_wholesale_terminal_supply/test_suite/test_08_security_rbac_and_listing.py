"""Security envelope (authentication, role authorization, entity-backed
ownership) and list-endpoint behavior (pagination envelope, FK filters)."""
from test_helpers import (
    CREDIT_MANAGER,
    DISPATCHER,
    PRICING_DESK,
    ApiErrorId,
    api_client,
    assert_delivery_order,
    base_order_fixture,
    base_terminal_fixture,
    create_dealer,
    create_terminal,
    create_terminal_payload,
    create_order,
    dealer_with_active_contract,
    make_dealer_user_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAuthentication:

    def test_missing_auth_headers_returns_unauthenticated(self):
        """PRD section 2.1: "A request with missing headers, an undeclared
        role, or an entity-backed identity that does not resolve is rejected
        with `ERR_UNAUTHENTICATED` (HTTP 401)"

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        resp = api_client.create_terminal(create_terminal_payload(name="T-V1"),
                                          None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleAuthorization:

    def test_dealer_role_cannot_create_terminal_forbidden(self):
        """PRD section 2.1: "A caller whose role is not listed among an
        endpoint's authorized roles is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."
        PRD section 4: POST `/terminals` is authorized for `SupplyAdmin` only.

        Design: Corner/validations/dealer_role_cannot_create_terminal_forbidden
        """
        dealer = create_dealer(legal_name="Dealer V2")
        resp = api_client.create_terminal(
            create_terminal_payload(name="T-V2"),
            make_dealer_user_headers(dealer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_pricing_desk_cannot_post_payments(self):
        """PRD section 2.1: "A caller whose role is not listed among an
        endpoint's authorized roles is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."
        PRD section 4: POST `/dealer-payments` is authorized for
        `CreditManager` only.

        Design: Corner/rbac/pricing_desk_cannot_post_payments
        """
        dealer = create_dealer(legal_name="Dealer RB1")
        resp = api_client.create_dealer_payment(
            {"dealer_id": dealer["id"], "amount_cents": 1_000, "method": "ACH"},
            PRICING_DESK,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_dispatcher_cannot_manage_supply_contracts(self):
        """PRD section 2.1: "A caller whose role is not listed among an
        endpoint's authorized roles is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."
        PRD section 4: POST `/supply-contracts` is authorized for
        `SupplyAdmin` only.

        Design: Corner/rbac/dispatcher_cannot_manage_supply_contracts
        """
        term = create_terminal(name="T-RB2")
        resp = api_client.create_supply_contract(
            {"terminal_id": term["id"], "supplier_name": "SUP",
             "contracted_volume_gal": 600_000,
             "receipt_window_start": "2026-07-01",
             "receipt_window_end": "2026-09-30"},
            DISPATCHER,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestDealerOwnership:

    def test_dealer_cannot_read_other_dealers_order(self):
        """PRD section 2.1: "When `X-User-Role` is `DealerUser`, `X-User-ID` is
        the `id` of the acting `Dealer`; ownership checks on any resource that
        references a `Dealer` compare the resource's `dealer_id` foreign key to
        `X-User-ID`, and a mismatch is rejected with `ERR_DEALER_MISMATCH`
        (HTTP 403)."

        Design: Corner/rbac/dealer_cannot_read_other_dealers_order
        """
        ctx = base_order_fixture(name="T-RB3", truck_count=0,
                                 dealer_name="Dealer RB3A")
        order = create_order(ctx["dealer"]["id"], ctx["terminal"]["id"],
                             ctx["zone"]["id"], 5_000,
                             dealer_contract_id=ctx["dealer_contract"]["id"])
        other = create_dealer(legal_name="Dealer RB3B")

        resp = api_client.get_delivery_order(
            order["id"], make_dealer_user_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_DEALER_MISMATCH)

    def test_dealer_reads_own_resources_ok(self):
        """PRD section 2.1: "ownership checks on any resource that references a
        `Dealer` compare the resource's `dealer_id` foreign key to `X-User-ID`"
        — a match passes.
        PRD section 4: GET `/dealers/{id}` ("DealerUser limited to self"),
        GET `/dealer-contracts/{id}` ("DealerUser limited to own"), and
        GET `/delivery-orders/{id}` ("DealerUser limited to own") are all
        authorized for `DealerUser`.

        Design: Corner/rbac/dealer_reads_own_resources_ok
        """
        ctx = base_order_fixture(name="T-RB4", truck_count=0)
        order = create_order(ctx["dealer"]["id"], ctx["terminal"]["id"],
                             ctx["zone"]["id"], 5_000,
                             dealer_contract_id=ctx["dealer_contract"]["id"])
        own = make_dealer_user_headers(ctx["dealer"]["id"])

        own_order = validate_success(
            api_client.get_delivery_order(order["id"], own))
        assert_delivery_order(own_order)
        assert own_order["id"] == order["id"]
        assert own_order["dealer_id"] == ctx["dealer"]["id"]

        own_dealer = validate_success(
            api_client.get_dealer(ctx["dealer"]["id"], own))
        assert own_dealer["id"] == ctx["dealer"]["id"]

        own_contract = validate_success(
            api_client.get_dealer_contract(ctx["dealer_contract"]["id"], own))
        assert own_contract["id"] == ctx["dealer_contract"]["id"]
        assert own_contract["dealer_id"] == ctx["dealer"]["id"]


class TestListEndpoints:

    def test_delivery_order_list_pagination_envelope(self):
        """PRD section 2.3: "The `limit` parameter caps the number of items
        returned: it defaults to 10, with a minimum of 1 and a maximum of 100.
        The `offset` parameter skips a number of items from the front of the
        result set and defaults to 0." and "The `meta` object of list responses
        carries `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/delivery_order_list_pagination_envelope
        """
        ctx = base_order_fixture(name="T-E4", truck_count=0)
        for _ in range(3):
            create_order(ctx["dealer"]["id"], ctx["terminal"]["id"],
                         ctx["zone"]["id"], 5_000,
                         dealer_contract_id=ctx["dealer_contract"]["id"])

        page1, meta1 = validate_paginated(api_client.list_delivery_orders(
            CREDIT_MANAGER,
            params={"terminal_id": ctx["terminal"]["id"], "limit": 2,
                    "offset": 0}))
        assert meta1["total_count"] == 3
        assert len(page1) == 2
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(api_client.list_delivery_orders(
            CREDIT_MANAGER,
            params={"terminal_id": ctx["terminal"]["id"], "limit": 2,
                    "offset": 2}))
        assert len(page2) == 1
        assert meta2["has_more"] is False
        assert meta2["total_count"] == 3

    def test_fk_reverse_list_orders_by_dealer(self):
        """PRD section 4: GET `/delivery-orders` — "List delivery orders
        (filter by dealer, terminal, contract, truck, zone, statuses)".
        PRD section 2.3: "Unless otherwise specified, every list endpoint
        returns resources sorted by `created_at` in ascending order."

        Design: Corner/entities/fk_reverse_list_orders_by_dealer
        """
        ctx = base_terminal_fixture(name="T-E7", truck_count=0)
        dealer_a, contract_a = dealer_with_active_contract(
            ctx["terminal"]["id"], legal_name="Dealer EA")
        dealer_b, contract_b = dealer_with_active_contract(
            ctx["terminal"]["id"], legal_name="Dealer EB")

        for _ in range(2):
            create_order(dealer_a["id"], ctx["terminal"]["id"],
                         ctx["zone"]["id"], 5_000,
                         dealer_contract_id=contract_a["id"])
        create_order(dealer_b["id"], ctx["terminal"]["id"], ctx["zone"]["id"],
                     7_000, dealer_contract_id=contract_b["id"])

        rows, meta = validate_paginated(api_client.list_delivery_orders(
            CREDIT_MANAGER, params={"dealer_id": dealer_a["id"]}))
        assert meta["total_count"] == 2
        assert len(rows) == 2
        for row in rows:
            assert row["dealer_id"] == dealer_a["id"], \
                "the dealer filter must not leak another dealer's orders"
