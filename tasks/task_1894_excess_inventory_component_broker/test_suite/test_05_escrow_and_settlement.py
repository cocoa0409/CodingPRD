"""Escrow funding, cancellation invariants, settlement split and cascades."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_seller, create_customer, create_bin, create_lot, create_active_listing,
    place_order, fund_order_fully, advance_order_to_delivered,
    set_clock, post_snapshot,
    setup_listed_broker_owned_scenario, setup_listed_consignment_scenario,
    make_customer_headers, make_seller_headers,
    assert_lot_quantity_invariant,
    api_client,
    TEST_USERS,
    ApiErrorId,
)

BROKER = TEST_USERS["broker_ops_headers"]
FINANCE = TEST_USERS["finance_admin_headers"]


class TestEscrowFundingBoundary:
    def _scenario(self, api):
        sc = setup_listed_broker_owned_scenario(
            mpn="IRF540", quantity=10, agreed_unit_price_cents=8000,
            asking_price_per_unit_cents=10000,
            credit_limit_cents=100000, urgency_tier="CRITICAL", bin_capacity=50,
        )
        order = place_order(sc["customer"], sc["listing"], quantity=4)
        return sc, order

    def test_partial_deposit_leaves_order_pending(self, api):
        """PRD section 3.6: "Partial deposits are welcome, but the running
        `escrow_funded_cents` may never exceed `required_escrow_cents`: a
        deposit that would overshoot the requirement is rejected with
        `ERR_ESCROW_OVERPAYMENT`. The deposit that brings the funded total to
        exactly the required amount moves the order from `PENDING_ESCROW` to
        `ESCROW_FUNDED`."

        Design: Difficulty/boundary_precision_check/escrow_exact_full_funding_boundary
        """
        sc, order = self._scenario(api)
        # CRITICAL on asking 10000 -> unit 12500; qty 4 -> required 50000.
        assert order["required_escrow_cents"] == 50000

        mid = validate_success(
            api.deposit_escrow(
                order["id"], {"amount_cents": 49999},
                make_customer_headers(sc["customer"]["id"]),
            ),
            200,
        )
        assert mid["status"] == "PENDING_ESCROW", (
            "49999 of 50000 must not flip the order to ESCROW_FUNDED"
        )
        assert mid["escrow_funded_cents"] == 49999

    def test_exact_final_cent_funds_escrow(self, api):
        """PRD section 3.6: "The deposit that brings the funded total to
        exactly the required amount moves the order from `PENDING_ESCROW` to
        `ESCROW_FUNDED`."

        Design: Difficulty/boundary_precision_check/escrow_exact_full_funding_boundary
        """
        sc, order = self._scenario(api)
        validate_success(
            api.deposit_escrow(
                order["id"], {"amount_cents": 49999},
                make_customer_headers(sc["customer"]["id"]),
            ),
            200,
        )
        final = validate_success(
            api.deposit_escrow(
                order["id"], {"amount_cents": 1},
                make_customer_headers(sc["customer"]["id"]),
            ),
            200,
        )
        assert final["status"] == "ESCROW_FUNDED"
        assert final["escrow_funded_cents"] == 50000


class TestEscrowGuards:
    def test_overpayment_rejected_and_funded_unchanged(self, api):
        """PRD section 3.6: "Partial deposits are welcome, but the running
        `escrow_funded_cents` may never exceed `required_escrow_cents`: a
        deposit that would overshoot the requirement is rejected with
        `ERR_ESCROW_OVERPAYMENT`."

        Design: Corner/validations/escrow_overpayment_rejected
        """
        sc = setup_listed_broker_owned_scenario(
            mpn="NE555", quantity=3, agreed_unit_price_cents=4000,
            asking_price_per_unit_cents=5000,
            credit_limit_cents=50000, urgency_tier="STANDARD", bin_capacity=20,
        )
        order = place_order(sc["customer"], sc["listing"], quantity=1)
        assert order["required_escrow_cents"] == 5000

        res = api.deposit_escrow(
            order["id"], {"amount_cents": 5001},
            make_customer_headers(sc["customer"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_ESCROW_OVERPAYMENT, expected_status=422)

        reread = validate_success(api.get_sales_order(order["id"], BROKER), 200)
        assert reread["escrow_funded_cents"] == 0
        assert reread["status"] == "PENDING_ESCROW"

    def test_zero_amount_deposit_rejected(self, api):
        """PRD section 3.6: "Each deposit must be strictly positive — a
        violation yields `ERR_INVALID_AMOUNT`"

        Design: Corner/validations/nonpositive_amount_rejected
        """
        sc = setup_listed_broker_owned_scenario(
            mpn="NE555", quantity=3, agreed_unit_price_cents=4000,
            asking_price_per_unit_cents=5000,
            credit_limit_cents=50000, urgency_tier="STANDARD", bin_capacity=20,
        )
        order = place_order(sc["customer"], sc["listing"], quantity=1)
        res = api.deposit_escrow(
            order["id"], {"amount_cents": 0},
            make_customer_headers(sc["customer"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_AMOUNT, expected_status=422)

    def test_deposit_on_cancelled_order_returns_invalid_state(self, api):
        """PRD section 3.6: "each is booked as a positive `DEPOSIT` entry in
        the order's ledger while the order remains in `PENDING_ESCROW`; a
        deposit against an order that has left that state, such as a cancelled
        one, is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/deposit_on_cancelled_order_returns_invalid_state
        """
        sc = setup_listed_broker_owned_scenario(
            mpn="BC547", quantity=5, agreed_unit_price_cents=4000,
            asking_price_per_unit_cents=5000,
            credit_limit_cents=100000, urgency_tier="STANDARD", bin_capacity=20,
        )
        order = place_order(sc["customer"], sc["listing"], quantity=1)
        validate_success(
            api.cancel_sales_order(
                order["id"], make_customer_headers(sc["customer"]["id"])
            ),
            200,
        )
        res = api.deposit_escrow(
            order["id"], {"amount_cents": 100},
            make_customer_headers(sc["customer"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        entries, _ = validate_paginated(
            api.list_escrow_entries(order["id"], FINANCE)
        )
        assert entries == [], "a rejected deposit must not write an escrow entry"


class TestFundedCancelInvariant:
    def _scenario(self, api):
        sc = setup_listed_broker_owned_scenario(
            mpn="IRF540", quantity=10, agreed_unit_price_cents=8000,
            asking_price_per_unit_cents=10000,
            credit_limit_cents=100000, urgency_tier="CRITICAL", bin_capacity=50,
        )
        order = place_order(sc["customer"], sc["listing"], quantity=4)
        funded = fund_order_fully(sc["customer"], order)
        assert funded["status"] == "ESCROW_FUNDED"
        return sc, funded

    def test_cancel_funded_order_books_full_customer_refund(self, api):
        """PRD section 3.6: "Cancelling an `ESCROW_FUNDED` order does all of
        that and additionally books a `CUSTOMER_REFUND` entry returning every
        funded cent, the entry's amount being the negative of
        `escrow_funded_cents`."

        Design: Difficulty/compensating_invariant/escrow_balance_conserved_on_funded_cancel
        """
        sc, funded = self._scenario(api)
        cancelled = validate_success(
            api.cancel_sales_order(
                funded["id"], make_customer_headers(sc["customer"]["id"])
            ),
            200,
        )
        assert cancelled["status"] == "CANCELLED"

        entries, _ = validate_paginated(
            api.list_escrow_entries(funded["id"], FINANCE)
        )
        assert len(entries) == 2, (
            f"cancelled funded order must hold exactly DEPOSIT + CUSTOMER_REFUND, "
            f"got {[e['entry_type'] for e in entries]}"
        )
        assert entries[0]["entry_type"] == "DEPOSIT"
        assert entries[0]["amount_cents"] == 50000
        assert entries[1]["entry_type"] == "CUSTOMER_REFUND"
        assert entries[1]["amount_cents"] == -50000
        assert entries[0]["amount_cents"] + entries[1]["amount_cents"] == 0

    def test_cancel_funded_order_never_touches_seller_balance(self, api):
        """PRD section 3.6: "Cancelling an `ESCROW_FUNDED` order does all of
        that and additionally books a `CUSTOMER_REFUND` entry returning every
        funded cent, the entry's amount being the negative of
        `escrow_funded_cents`."
        PRD section 3.1: "Both open at zero, and §3.7 describes the single
        event that grows them."

        Design: Difficulty/compensating_invariant/escrow_balance_conserved_on_funded_cancel
        """
        sc, funded = self._scenario(api)
        validate_success(
            api.cancel_sales_order(
                funded["id"], make_customer_headers(sc["customer"]["id"])
            ),
            200,
        )
        seller = validate_success(api.get_seller(sc["seller"]["id"], BROKER), 200)
        assert seller["account_balance_cents"] == 0
        assert seller["total_payouts_cents"] == 0


class TestLotQuantityConservation:
    def test_reserve_and_release_restore_available_units(self, api):
        """PRD section 3.6: "Creation moves physical units immediately: the
        lot's `qty_available` decreases and its `qty_reserved` increases by the
        ordered quantity, and the posture recomputes — an order that drains the
        last available unit pushes the lot to `FULLY_RESERVED`."
        PRD section 3.6: "Cancelling a `PENDING_ESCROW` order simply releases
        the reservation — the lot's `qty_reserved` decreases and its
        `qty_available` increases by the order quantity, the posture
        recomputes, and the customer's exposure is recalculated."

        Design: Difficulty/compensating_invariant/lot_quantity_conserved_through_reserve_and_release
        """
        sc = setup_listed_broker_owned_scenario(
            mpn="TIP120", quantity=10, agreed_unit_price_cents=7000,
            asking_price_per_unit_cents=10000,
            credit_limit_cents=100000, urgency_tier="STANDARD", bin_capacity=50,
        )
        lot_id = sc["lot"]["id"]
        initial = validate_success(api.get_lot(lot_id, BROKER), 200)
        assert initial["qty_available"] == 10
        assert_lot_quantity_invariant(initial)

        order = place_order(sc["customer"], sc["listing"], quantity=4)
        mid = validate_success(api.get_lot(lot_id, BROKER), 200)
        assert mid["qty_available"] == 6
        assert mid["qty_reserved"] == 4
        assert_lot_quantity_invariant(mid)

        validate_success(
            api.cancel_sales_order(
                order["id"], make_customer_headers(sc["customer"]["id"])
            ),
            200,
        )
        end = validate_success(api.get_lot(lot_id, BROKER), 200)
        assert end["qty_available"] == 10
        assert end["qty_reserved"] == 0
        assert end["qty_sold"] == 0
        assert end["qty_returned"] == 0
        assert_lot_quantity_invariant(end)

    def test_reserved_units_remain_conserved_at_probe_points(self, api):
        """PRD section 3.6: "Creation moves physical units immediately: the
        lot's `qty_available` decreases and its `qty_reserved` increases by the
        ordered quantity, and the posture recomputes — an order that drains the
        last available unit pushes the lot to `FULLY_RESERVED`."

        Design: Difficulty/compensating_invariant/lot_quantity_conserved_through_reserve_and_release
        """
        sc = setup_listed_broker_owned_scenario(
            mpn="TIP120", quantity=10, agreed_unit_price_cents=7000,
            asking_price_per_unit_cents=10000,
            credit_limit_cents=100000, urgency_tier="STANDARD", bin_capacity=50,
        )
        lot_id = sc["lot"]["id"]
        order = place_order(sc["customer"], sc["listing"], quantity=4)

        mid = validate_success(api.get_lot(lot_id, BROKER), 200)
        assert mid["quantity_received"] == 10
        assert (
            mid["qty_available"] + mid["qty_reserved"]
            + mid["qty_sold"] + mid["qty_returned"]
        ) == mid["quantity_received"], (
            "unit buckets must always sum back to quantity_received"
        )

        validate_success(
            api.cancel_sales_order(
                order["id"], make_customer_headers(sc["customer"]["id"])
            ),
            200,
        )
        end = validate_success(api.get_lot(lot_id, BROKER), 200)
        assert (
            end["qty_available"] + end["qty_reserved"]
            + end["qty_sold"] + end["qty_returned"]
        ) == end["quantity_received"]
        assert end["status"] == "LISTED", (
            "reservation released while an ACTIVE listing covers the lot "
            "restores LISTED"
        )

    def test_cancel_restores_listed_posture_and_clears_exposure(self, api):
        """PRD section 3.6: "Either way the order lands in `CANCELLED`, and a
        reservation released while an `ACTIVE` listing still covers the lot
        restores the lot to `LISTED`, while a release with no active listing
        restores `IN_STOCK`."
        PRD section 3.6: "orders that have settled, cancelled, or refunded no
        longer count."

        Design: Corner/cross_cutting_layers/derived_field_reconciliation_on_cancel
        """
        sc = setup_listed_broker_owned_scenario(
            mpn="MCP6002", quantity=5, agreed_unit_price_cents=4000,
            asking_price_per_unit_cents=5000,
            credit_limit_cents=50000, urgency_tier="STANDARD", bin_capacity=20,
        )
        order = place_order(sc["customer"], sc["listing"], quantity=2)
        assert order["required_escrow_cents"] == 10000

        validate_success(
            api.cancel_sales_order(
                order["id"], make_customer_headers(sc["customer"]["id"])
            ),
            200,
        )
        customer = validate_success(
            api.get_customer(sc["customer"]["id"], BROKER), 200
        )
        assert customer["open_order_exposure_cents"] == 0

        lot = validate_success(api.get_lot(sc["lot"]["id"], BROKER), 200)
        assert lot["status"] == "LISTED"
        assert lot["qty_available"] == 5
        assert lot["qty_reserved"] == 0


class TestConsignmentSettlementSplit:
    def _scenario(self, api):
        sc = setup_listed_consignment_scenario(
            mpn="STM32F103", quantity=10, agreed_unit_price_cents=8000,
            asking_price_per_unit_cents=10000, broker_fee_bps=1500,
            credit_limit_cents=200000, urgency_tier="CRITICAL",
        )
        order = place_order(sc["customer"], sc["listing"], quantity=10)
        delivered = advance_order_to_delivered(sc["customer"], order)
        set_clock("2026-10-10T00:00:00Z")
        post_snapshot("STM32F103", 8000, source="TRADE_DESK")
        set_clock("2026-10-20T00:00:00Z")
        post_snapshot("STM32F103", 11000, source="TRADE_DESK")
        set_clock("2026-11-04T00:00:00Z")
        return sc, delivered

    def test_broker_fee_rounded_first_and_payout_is_exact_remainder(self, api):
        """PRD section 3.7: "For a `CONSIGNMENT` lot the proceeds split under a
        pinned rounding order that implementations must follow exactly: first
        the broker fee is computed as `final_total_cents` multiplied by the
        order's `consignment_fee_bps_snapshot` and divided by ten thousand,
        rounded half-up to a whole cent; then the seller payout is the exact
        remainder of `final_total_cents` after subtracting that fee. The payout
        is never computed by independently rounding the seller's percentage
        share, because the two orders of operation diverge on half-cent
        boundaries, and the fee basis is always the pinned snapshot captured at
        order creation, never whatever the agreement might say at settlement
        time."

        Design: Difficulty/combinatorial_formula/escrow_split_pinned_rounding_order
        """
        sc, delivered = self._scenario(api)
        settled = validate_success(
            api.settle_sales_order(delivered["id"], FINANCE), 200
        )
        assert settled["final_total_cents"] == 115190

        entries, _ = validate_paginated(
            api.list_escrow_entries(delivered["id"], FINANCE)
        )
        by_type = {e["entry_type"]: e["amount_cents"] for e in entries}
        # broker_fee = round_half_up(115190 * 1500 / 10000) = 17279
        assert by_type["BROKER_FEE"] == -17279
        # seller_payout = 115190 - 17279 == 97911 (exact remainder, NOT the
        # independently rounded round_half_up(115190*0.85) == 97912).
        assert by_type["SELLER_PAYOUT"] == -97911
        assert by_type["CUSTOMER_REFUND"] == -9810
        # Ledger conservation: 125000 + (-9810) + (-17279) + (-97911) == 0.
        assert sum(e["amount_cents"] for e in entries) == 0

    def test_seller_payout_increments_seller_balances(self, api):
        """PRD section 3.7: "A `BROKER_FEE` entry books the negative of the fee
        and a `SELLER_PAYOUT` entry books the negative of the payout; recording
        that payout also increases the seller's `account_balance_cents` and
        `total_payouts_cents` by the payout amount."

        Design: Difficulty/combinatorial_formula/escrow_split_pinned_rounding_order
        """
        sc, delivered = self._scenario(api)
        validate_success(api.settle_sales_order(delivered["id"], FINANCE), 200)
        seller = validate_success(api.get_seller(sc["seller"]["id"], FINANCE), 200)
        assert seller["account_balance_cents"] == 97911
        assert seller["total_payouts_cents"] == 97911


class TestSettleCascade:
    def _scenario(self, api):
        sc = setup_listed_consignment_scenario(
            mpn="STM32F103", quantity=10, agreed_unit_price_cents=8000,
            asking_price_per_unit_cents=10000, broker_fee_bps=1500,
            credit_limit_cents=200000, urgency_tier="CRITICAL",
        )
        order = place_order(sc["customer"], sc["listing"], quantity=10)
        delivered = advance_order_to_delivered(sc["customer"], order)
        set_clock("2026-10-10T00:00:00Z")
        post_snapshot("STM32F103", 8000, source="TRADE_DESK")
        set_clock("2026-10-20T00:00:00Z")
        post_snapshot("STM32F103", 11000, source="TRADE_DESK")
        set_clock("2026-11-04T00:00:00Z")
        return sc, delivered

    def test_settle_moves_order_lot_and_listing_terminal(self, api):
        """PRD section 3.7: "Settlement moves units as well: the lot's
        `qty_reserved` decreases and its `qty_sold` increases by the order
        quantity, and the posture recomputes. When that recompute leaves no
        available and no reserved units with sold or returned units present,
        the lot becomes `DEPLETED`, and any `ACTIVE` listing still attached to
        it cascades to `SOLD_OUT`."

        Design: Difficulty/transitive_cascade/settle_cascade_order_lot_listing_and_seller
        """
        sc, delivered = self._scenario(api)
        settled = validate_success(
            api.settle_sales_order(delivered["id"], FINANCE), 200
        )
        assert settled["status"] == "SETTLED"

        lot = validate_success(api.get_lot(sc["lot"]["id"], BROKER), 200)
        assert lot["qty_sold"] == 10
        assert lot["qty_reserved"] == 0
        assert lot["status"] == "DEPLETED"

        listing = validate_success(api.get_listing(sc["listing"]["id"], BROKER), 200)
        assert listing["status"] == "SOLD_OUT", (
            "lot DEPLETED must cascade its ACTIVE listing to SOLD_OUT"
        )

    def test_settle_releases_exposure_and_pays_seller(self, api):
        """PRD section 3.7: "A `BROKER_FEE` entry books the negative of the fee
        and a `SELLER_PAYOUT` entry books the negative of the payout; recording
        that payout also increases the seller's `account_balance_cents` and
        `total_payouts_cents` by the payout amount."
        PRD section 3.6: "orders that have settled, cancelled, or refunded no
        longer count."

        Design: Difficulty/transitive_cascade/settle_cascade_order_lot_listing_and_seller
        """
        sc, delivered = self._scenario(api)
        validate_success(api.settle_sales_order(delivered["id"], FINANCE), 200)

        seller = validate_success(api.get_seller(sc["seller"]["id"], FINANCE), 200)
        assert seller["account_balance_cents"] == 97911

        customer = validate_success(
            api.get_customer(sc["customer"]["id"], BROKER), 200
        )
        assert customer["open_order_exposure_cents"] == 0, (
            "a settled order must no longer count toward open-order exposure"
        )


class TestSnapshotPropagation:
    def test_snapshot_recomputes_market_value_and_recommended_price(self, api):
        """PRD section 3.4: "Recording a snapshot is a propagating event: the
        mark-to-market carrying value of every lot with a matching `mpn` is
        recomputed, and so is the recommended price of every `ACTIVE` listing
        sitting on those lots."

        Design: Difficulty/transitive_cascade/snapshot_cascade_to_lot_and_listing
        """
        seller = create_seller(name="Hotel Holdings")
        storage_bin = create_bin(capacity_units=50, bin_code="BIN-H1")
        lot, _ = create_lot(
            seller, storage_bin, mpn="OPA2134", quantity=5,
            ask_price_per_unit_cents=5000, agreed_unit_price_cents=5000,
            provenance_doc_url="https://docs.x.com/p8.pdf",
        )
        listing, _ = create_active_listing(lot, asking_price_per_unit_cents=9000)

        before_lot = validate_success(api.get_lot(lot["id"], BROKER), 200)
        assert before_lot["carrying_value_market_cents"] is None
        before_listing = validate_success(api.get_listing(listing["id"], BROKER), 200)
        assert before_listing["recommended_price_per_unit_cents"] is None

        post_snapshot("OPA2134", 12000, source="DISTRIBUTOR_FEED")

        after_listing = validate_success(api.get_listing(listing["id"], BROKER), 200)
        # round_half_up(12000 * 1.10) == 13200
        assert after_listing["recommended_price_per_unit_cents"] == 13200

        after_lot = validate_success(api.get_lot(lot["id"], BROKER), 200)
        # round_half_up(12000 * 0.85 * 5) == 51000
        assert after_lot["carrying_value_market_cents"] == 51000

    def test_snapshot_does_not_move_straight_line_basis(self, api):
        """PRD section 3.3: "The straight-line basis,
        `carrying_value_straight_line_cents`, decays the cost of on-hand units
        over a 365-day horizon"
        PRD section 3.3: "The market basis, `carrying_value_market_cents`,
        ignores age entirely"

        Design: Difficulty/transitive_cascade/snapshot_cascade_to_lot_and_listing
        """
        seller = create_seller(name="Hotel Holdings")
        storage_bin = create_bin(capacity_units=50, bin_code="BIN-H1")
        lot, _ = create_lot(
            seller, storage_bin, mpn="OPA2134", quantity=5,
            ask_price_per_unit_cents=5000, agreed_unit_price_cents=5000,
            provenance_doc_url="https://docs.x.com/p8.pdf",
        )
        create_active_listing(lot, asking_price_per_unit_cents=9000)

        before = validate_success(api.get_lot(lot["id"], BROKER), 200)
        # Age 0: 5000 * 5 * (1 - 0/365) == 25000.
        assert before["carrying_value_straight_line_cents"] == 25000

        post_snapshot("OPA2134", 12000, source="DISTRIBUTOR_FEED")

        after = validate_success(api.get_lot(lot["id"], BROKER), 200)
        assert after["carrying_value_straight_line_cents"] == 25000, (
            "the straight-line basis ignores market observations"
        )
        assert after["carrying_value_market_cents"] == 51000


class TestImmediateConsistency:
    def test_settle_response_carries_final_figures(self, api):
        """PRD section 2.2: "Unless otherwise noted, operations that create or
        modify a resource will return the created or updated resource object in
        the data field."
        PRD section 3.7: "All three final figures remain null until the order
        actually settles."

        Design: Corner/consistency_model/settle_effects_visible_in_same_response
        """
        sc = setup_listed_broker_owned_scenario(
            mpn="BC547", quantity=3, agreed_unit_price_cents=4000,
            asking_price_per_unit_cents=5000,
            credit_limit_cents=50000, urgency_tier="STANDARD", bin_capacity=20,
        )
        order = place_order(sc["customer"], sc["listing"], quantity=1)
        assert order["final_unit_price_cents"] is None
        delivered = advance_order_to_delivered(sc["customer"], order)

        settled = validate_success(
            api.settle_sales_order(delivered["id"], FINANCE), 200
        )
        # Same-day settle: age 0 FRESH, no snapshots -> final == provisional.
        assert settled["status"] == "SETTLED"
        assert settled["final_unit_price_cents"] == 5000
        assert settled["final_total_cents"] == 5000
        assert settled["customer_refund_cents"] == 0

        entries, _ = validate_paginated(
            api.list_escrow_entries(delivered["id"], FINANCE)
        )
        by_type = {e["entry_type"]: e["amount_cents"] for e in entries}
        assert by_type["DEPOSIT"] == 5000
        assert by_type["BROKER_REVENUE"] == -5000
        assert "CUSTOMER_REFUND" not in by_type, (
            "no refund entry is booked when the customer is owed nothing"
        )
