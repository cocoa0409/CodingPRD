"""Shipment execution: provisional vs final freight variants, the ship
cascade into the account receivable, invoice payment, and terminal lockdown.

Standard rated fixture used by several classes: 100 units of a class-70
product (density 20, 10 lbs/unit) at ship_zone 5 sourced from ATL (zone 2):
zone distance 3 -> factor 1.24; 1000 lbs at 120 cents/lb; provisional freight
ceil(120000 x 1.24 x 1.10) = 163,680; final freight ceil(120000 x 1.24) =
148,800; subtotal 100,000; no pallets, no oversize.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_line,
    assert_account,
    assert_inventory,
    assert_order,
    create_draft_order,
    create_inventory,
    create_stock_product,
    get_success_data,
    make_approver_headers,
    make_buyer_headers,
    setup_shipped_stock_order,
    setup_submitted_stock_order,
    setup_warehouse_and_account,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["warehouse_ops_headers"]


class TestProvisionalVsFinalFreight:
    def test_submit_carries_uplifted_provisional_freight(self, api):
        """PRD section 3.7: "The provisional variant computed at submit differs
        in exactly two ways: it covers all non-cancelled lines rather than only
        shipped ones, and it applies an additional eleven-tenths uplift — which
        makes the provisional figure strictly at least the final figure for
        identical inputs."
        PRD section 3.4: "the order's `grand_total_cents` is the subtotal minus
        the pallet discount plus `oversize_surcharge_cents` plus
        `freight_estimate_cents`."

        Design: Difficulty/dual_variant_calc/freight_estimate_provisional_uplift_vs_final
        """
        ctx = setup_submitted_stock_order(qty=100, on_hand=500)
        submitted = ctx["order"]
        assert_order(submitted)
        assert submitted["status"] == "STOCK_RESERVED"
        assert submitted["subtotal_cents"] == 100000
        assert submitted["freight_estimate_cents"] == 163680   # with the 11/10 uplift
        assert submitted["grand_total_cents"] == 263680        # 100000 + 163680

    def test_ship_settles_final_freight_without_uplift(self, api, warehouse_ops_headers):
        """PRD section 3.7: "Freight settles at ship time in its final variant.
        The billable weight is the sum over the lines that actually shipped of
        shipped quantity times `weight_lbs_per_unit`."
        PRD section 3.7: "The final `freight_estimate_cents` is the ceiling of
        weight times rate times zone factor, computed with exact rational
        arithmetic and a single ceiling applied once."

        Design: Difficulty/dual_variant_calc/freight_estimate_provisional_uplift_vs_final
        """
        ctx = setup_submitted_stock_order(qty=100, on_hand=500)
        shipped = validate_success(api.ship_order(ctx["order"]["id"], warehouse_ops_headers))
        assert_order(shipped)
        assert shipped["status"] == "SHIPPED"
        assert shipped["freight_estimate_cents"] == 148800     # uplift dropped
        assert shipped["grand_total_cents"] == 248800          # 100000 + 148800


class TestShipCascade:
    def test_submit_leaves_receivable_at_provisional_grand(self, api, platform_admin_headers):
        """PRD section 3.1: "The account record continuously exposes
        `open_receivable_cents`, a computed figure maintained in full on every
        triggering event — order submit, ship, cancel, return restock, invoice
        payment, and purchase-order approval — as the sum of
        `grand_total_cents` over the account's orders whose `invoice_status` is
        `OPEN` and whose order status is one of `STOCK_RESERVED`,
        `PARTIALLY_BACKORDERED`, `CUSTOM_PRODUCTION`, or `SHIPPED`."

        Design: Difficulty/transitive_cascade/ship_freight_recompute_receivable_chain
        """
        ctx = setup_submitted_stock_order(qty=100, on_hand=500)
        acct = validate_success(api.get_account(ctx["account"]["id"], platform_admin_headers))
        assert_account(acct)
        assert acct["open_receivable_cents"] == 263680

    def test_ship_recomputes_freight_then_receivable_and_decrements_stock(
            self, api, platform_admin_headers, warehouse_ops_headers):
        """PRD section 3.7: "Shipping also refreshes the account's open
        receivable and increments the order's `version`."
        PRD section 3.7: "For each line that ships, the inventory row at its
        allocated facility loses the shipped quantity from both `on_hand_qty`
        and `reserved_qty` — custom lines decrement by their produced quantity,
        and a made-to-order line with no inventory row at its facility skips
        the decrement — the line becomes `SHIPPED`, and its `shipped_qty` is
        recorded."

        Design: Difficulty/transitive_cascade/ship_freight_recompute_receivable_chain
        """
        ctx = setup_submitted_stock_order(qty=100, on_hand=500)
        shipped = validate_success(api.ship_order(ctx["order"]["id"], warehouse_ops_headers))
        assert shipped["freight_estimate_cents"] == 148800
        assert shipped["grand_total_cents"] == 248800

        acct = validate_success(api.get_account(ctx["account"]["id"], platform_admin_headers))
        # Hop C reflects hop B exactly: the receivable tracks the new grand.
        assert acct["open_receivable_cents"] == 248800

        inv = validate_success(api.get_inventory(ctx["inventory"]["id"], warehouse_ops_headers))
        assert_inventory(inv)
        assert inv["on_hand_qty"] == 400
        assert inv["reserved_qty"] == 0


class TestReceivableConservedAcrossLifecycle:
    def test_receivable_tracks_grand_through_submit_and_ship(self, api, platform_admin_headers,
                                                             warehouse_ops_headers):
        """PRD section 3.1: "the sum of `grand_total_cents` over the account's
        orders whose `invoice_status` is `OPEN` and whose order status is one
        of `STOCK_RESERVED`, `PARTIALLY_BACKORDERED`, `CUSTOM_PRODUCTION`, or
        `SHIPPED`."
        PRD section 3.1: "all are excluded, and the figure is recomputed
        wholesale each time so it cannot drift incrementally."

        Design: Difficulty/compensating_invariant/invoice_pay_receivable_cents_conserved
        """
        ctx = setup_submitted_stock_order(qty=100, on_hand=500)
        after_submit = validate_success(api.get_account(ctx["account"]["id"],
                                                        platform_admin_headers))
        assert after_submit["open_receivable_cents"] == 263680

        validate_success(api.ship_order(ctx["order"]["id"], warehouse_ops_headers))
        after_ship = validate_success(api.get_account(ctx["account"]["id"],
                                                      platform_admin_headers))
        assert after_ship["open_receivable_cents"] == 248800

    def test_invoice_payment_returns_receivable_to_zero(self, api, platform_admin_headers,
                                                        warehouse_ops_headers):
        """PRD section 3.7: "Once an order is `SHIPPED`, an `AccountApprover`
        or `PlatformAdmin` marks its invoice `PAID`, which likewise refreshes
        the receivable and increments `version`; attempting payment on an order
        that has not shipped is rejected with `ERR_INVALID_STATE`."
        PRD section 3.1: "the sum of `grand_total_cents` over the account's
        orders whose `invoice_status` is `OPEN` and whose order status is one
        of `STOCK_RESERVED`, `PARTIALLY_BACKORDERED`, `CUSTOM_PRODUCTION`, or
        `SHIPPED`."

        Design: Difficulty/compensating_invariant/invoice_pay_receivable_cents_conserved
        """
        ctx = setup_shipped_stock_order(qty=100, on_hand=500)
        paid = validate_success(api.pay_invoice(
            ctx["order"]["id"], make_approver_headers(ctx["account"]["id"])))
        assert paid["invoice_status"] == "PAID"

        acct = validate_success(api.get_account(ctx["account"]["id"], platform_admin_headers))
        assert acct["open_receivable_cents"] == 0, (
            "paying the only open invoice must return the receivable to its zero baseline")


class TestOrderLifecycleVersions:
    def test_happy_path_versions_and_invoice_flip(self, api, warehouse_ops_headers):
        """PRD section 2.4: "`version` (integer): a system-managed integer that
        increments by one on every mutation of the resource, and underpins
        optimistic concurrency control where it applies."
        PRD section 2.4: "Separately, note that on an order, a refresh of
        derived totals caused by adding or editing a line while the order is
        still a draft is not a mutation of the order itself — only lifecycle
        transitions increment the order's `version`."
        PRD section 3.7: "Once an order is `SHIPPED`, an `AccountApprover` or
        `PlatformAdmin` marks its invoice `PAID`, which likewise refreshes the
        receivable and increments `version`"

        Design: Corner/endpoints/endpoint_order_lifecycle_happy_path_versions
        """
        ctx = setup_submitted_stock_order(qty=2, on_hand=100)
        order, submitted = ctx["order"], ctx["order"]
        # The submitted response is the post-submit order; the draft was version 1.
        assert submitted["status"] == "STOCK_RESERVED"

        shipped = validate_success(api.ship_order(submitted["id"], warehouse_ops_headers))
        assert shipped["status"] == "SHIPPED"
        assert shipped["version"] == submitted["version"] + 1

        paid = validate_success(api.pay_invoice(
            shipped["id"], make_approver_headers(ctx["account"]["id"])))
        assert paid["status"] == "SHIPPED"
        assert paid["invoice_status"] == "PAID"
        assert paid["version"] == shipped["version"] + 1

    def test_draft_line_add_does_not_increment_order_version(self, api):
        """PRD section 2.4: "Separately, note that on an order, a refresh of
        derived totals caused by adding or editing a line while the order is
        still a draft is not a mutation of the order itself — only lifecycle
        transitions increment the order's `version`."

        Design: Corner/endpoints/endpoint_order_lifecycle_happy_path_versions
        """
        wh, acct = setup_warehouse_and_account()
        prod = create_stock_product(sku="W-1", base_price_cents=100, pallet_qty=10,
                                    weight_lbs_per_unit=1)
        create_inventory(prod["id"], wh["id"], 100)
        order = create_draft_order(acct["id"], ship_zone=5)
        add_line(order["id"], acct["id"], prod["id"], 2)
        reread = get_success_data(api.get_order(order["id"], ADMIN))
        assert reread["version"] == order["version"], (
            "a draft totals refresh must not increment the order version")


class TestImmediateConsistency:
    def test_ship_response_body_carries_final_state(self, api, warehouse_ops_headers):
        """PRD section 2.2: "Unless otherwise noted, operations that create or
        modify a resource will return the created or updated resource object in
        the data field."
        PRD section 3.7: "Freight settles at ship time in its final variant."

        Design: Corner/cross_cutting_layers/consistency_immediate_all_changes_visible_in_response
        """
        ctx = setup_submitted_stock_order(qty=100, on_hand=500)
        resp = api.ship_order(ctx["order"]["id"], warehouse_ops_headers)
        data = validate_success(resp)
        # No re-read: the POST body itself carries the mutation.
        assert data["status"] == "SHIPPED"
        assert data["freight_estimate_cents"] == 148800
        assert data["grand_total_cents"] == 248800


class TestTerminalCancelledLockdown:
    def test_cancelled_order_rejects_ship_and_recancel(self, api, warehouse_ops_headers):
        """PRD section 2.9: "Next, the requested transition must exist from the
        target resource's current state, including terminal-state lockdown
        (`ERR_INVALID_STATE`)."
        PRD section 3.7: "A `Buyer` may cancel an order, with an optional
        `reason`, from `DRAFT`, `PENDING`, `STOCK_RESERVED`, or
        `PARTIALLY_BACKORDERED` — subject to the custom-production guard of
        §3.6."

        Design: Corner/state_machines/order_terminal_cancelled_lockdown
        """
        ctx = setup_submitted_stock_order(qty=1, on_hand=100)
        cancelled = validate_success(api.cancel_order(ctx["order"]["id"], {},
                                                      ctx["buyer_headers"]))
        assert cancelled["status"] == "CANCELLED"

        validate_error(api.ship_order(cancelled["id"], warehouse_ops_headers),
                       ApiErrorId.ERR_INVALID_STATE)
        validate_error(api.cancel_order(cancelled["id"], {}, ctx["buyer_headers"]),
                       ApiErrorId.ERR_INVALID_STATE)


class TestErrorEnvelope:
    def test_business_error_envelope_shape(self, api, warehouse_ops_headers):
        """PRD section 2.2: "All error API responses (4xx status codes) follow
        this standard envelope format"
        PRD section 2.2: "The `error_id` is a unique, machine-readable string
        that identifies the specific error."
        PRD section 2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/errors/error_envelope_shape_on_business_error
        """
        wh, acct = setup_warehouse_and_account()
        prod = create_stock_product(sku="X-1", base_price_cents=100, pallet_qty=10,
                                    weight_lbs_per_unit=1)
        create_inventory(prod["id"], wh["id"], 10)
        order = create_draft_order(acct["id"], ship_zone=5)
        add_line(order["id"], acct["id"], prod["id"], 1)

        resp = api.ship_order(order["id"], warehouse_ops_headers)  # DRAFT: no ship transition
        err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert err.get("error_id") == "ERR_INVALID_STATE"
        assert isinstance(err.get("message"), str) and err["message"]
        body = resp.json()
        assert body["response_type"] == "error"
        assert isinstance(body["meta"].get("api_request_id"), str)
