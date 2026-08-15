"""Transfer market: dual available-water variants, window overlap, monthly cap,
reservation compensation, and settlement re-checks (PRD §3.4, §3.8)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_transfer,
    create_active_production_well,
    cancel_transfer,
    create_account,
    create_transfer_order_payload,
    get_account,
    make_well_owner_headers,
    propose_and_accept_transfer,
    propose_transfer,
    set_clock,
    settle_transfer,
    setup_account_with_active_production_well,
    setup_account_with_verified_extraction,
    submit_and_verify_report,
    submit_extraction_report,
    validate_error,
    validate_success,
    verify_report,
)


class TestDualVariantAvailability:
    def test_forward_available_counts_pending_settled_does_not(self, api, water_master_headers):
        """PRD §3.8: "The forward-looking variant, used only for the seller-sufficiency gate at transfer proposal, equals the effective allocation plus `credit_balance_af`, minus `extracted_af_ytd`, minus `pending_extraction_af` (which counts only `SUBMITTED` reports of the account's current water year — `VERIFIED` and `DISPUTED` reports are excluded from this counter), minus `transfer_out_af_ytd`, minus `transfer_reserved_af`. The settled variant, used at settlement re-check, as the overdraft basis, and at year-end carryover, is identical except that `pending_extraction_af` is not subtracted — only verified extraction counts against it."
        PRD §3.4: "Second, seller sufficiency: the seller's forward-looking available water must be at least `quantity_af`, with equality passing; a shortfall yields `ERR_INSUFFICIENT_AVAILABLE_WATER`."

        Design: Difficulty/dual_variant_calc/forward_available_counts_pending_settled_does_not
        """
        # Seller A: allocation 100, extracted 40 (VERIFIED), pending 25 (SUBMITTED).
        seller = create_account(holder_name="Seller A", base_allocation_af=100.000)
        buyer = create_account(holder_name="Buyer B", base_allocation_af=50.000)
        well = create_active_production_well(seller["id"])
        submit_and_verify_report(well["id"], seller["id"], month=6, reported_af=40.000)
        submit_extraction_report(well["id"], seller["id"], month=7, reported_af=25.000)

        # T1 for 30.000: forward check 100-40-25 = 35 >= 30 passes.
        order = propose_transfer(seller["id"], buyer["id"], 30.000)
        accept_transfer(order["id"], buyer["id"])

        # Settle re-check uses the settled variant: 100-40-0-(30-30) = 60 >= 30.
        settled = validate_success(api.settle_transfer(order["id"], water_master_headers))
        assert settled["status"] == "SETTLED", (
            "the settled variant ignores the 25.000 pending report, so 60.000 >= 30.000"
        )

        # T2 for 6.000: forward = 100-40-25-30-0 = 5.000 < 6.000 -> rejected.
        rejected = api.create_transfer_order(
            create_transfer_order_payload(seller["id"], buyer["id"], quantity_af=6.000,
                                          effective_start_date="2026-11-01",
                                          effective_end_date="2027-01-01"),
            make_well_owner_headers(seller["id"]),
        )
        validate_error(rejected, ApiErrorId.ERR_INSUFFICIENT_AVAILABLE_WATER)

        seller_after = get_account(seller["id"])
        assert seller_after["transfer_out_af_ytd"] == pytest.approx(30.000, abs=1e-9)
        assert seller_after["transfer_reserved_af"] == pytest.approx(0.0, abs=1e-9)
        buyer_after = get_account(buyer["id"])
        assert buyer_after["credit_balance_af"] == pytest.approx(30.000, abs=1e-9)

    def test_forward_variant_subtracts_pending_at_equality(self, api):
        """PRD §3.8: "The forward-looking variant, used only for the seller-sufficiency gate at transfer proposal, equals the effective allocation plus `credit_balance_af`, minus `extracted_af_ytd`, minus `pending_extraction_af` (which counts only `SUBMITTED` reports of the account's current water year — `VERIFIED` and `DISPUTED` reports are excluded from this counter), minus `transfer_out_af_ytd`, minus `transfer_reserved_af`."
        PRD §3.4: "Second, seller sufficiency: the seller's forward-looking available water must be at least `quantity_af`, with equality passing; a shortfall yields `ERR_INSUFFICIENT_AVAILABLE_WATER`."

        Design: Difficulty/dual_variant_calc/forward_available_counts_pending_settled_does_not
        """
        # Allocation 100, extracted 40, pending 25 -> forward available exactly 35.000.
        seller = create_account(holder_name="Seller A2", base_allocation_af=100.000)
        buyer_1 = create_account(holder_name="Buyer B1", base_allocation_af=50.000)
        buyer_2 = create_account(holder_name="Buyer B2", base_allocation_af=50.000)
        well = create_active_production_well(seller["id"])
        submit_and_verify_report(well["id"], seller["id"], month=6, reported_af=40.000)
        submit_extraction_report(well["id"], seller["id"], month=7, reported_af=25.000)

        exact = propose_transfer(seller["id"], buyer_1["id"], 35.000)
        assert exact["status"] == "PROPOSED", (
            "35.000 == forward available 35.000 must pass the >= gate"
        )

        over = api.create_transfer_order(
            create_transfer_order_payload(seller["id"], buyer_2["id"], quantity_af=0.001),
            make_well_owner_headers(seller["id"]),
        )
        validate_error(over, ApiErrorId.ERR_INSUFFICIENT_AVAILABLE_WATER)


class TestSellerSufficiencyBoundary:
    def test_transfer_quantity_exactly_equals_available_succeeds(self, api):
        """PRD §3.4: "Second, seller sufficiency: the seller's forward-looking available water must be at least `quantity_af`, with equality passing; a shortfall yields `ERR_INSUFFICIENT_AVAILABLE_WATER`."

        Design: Difficulty/boundary_precision_check/transfer_quantity_exactly_equals_available_succeeds
        """
        seller = create_account(holder_name="Seller JS", base_allocation_af=40.000)
        buyer_1 = create_account(holder_name="Buyer JB-1", base_allocation_af=50.000)
        buyer_2 = create_account(holder_name="Buyer JB-2", base_allocation_af=50.000)

        exact = propose_transfer(seller["id"], buyer_1["id"], 40.000)
        assert exact["status"] == "PROPOSED", (
            "quantity 40.000 == available 40.000 must pass the >= check"
        )

        over = api.create_transfer_order(
            create_transfer_order_payload(seller["id"], buyer_2["id"], quantity_af=0.001),
            make_well_owner_headers(seller["id"]),
        )
        validate_error(over, ApiErrorId.ERR_INSUFFICIENT_AVAILABLE_WATER)

    def test_settle_at_exact_equality_succeeds(self, api, water_master_headers):
        """PRD §3.4: "Settlement performs two preconditions before committing: the official basin condition must not be `CRITICAL` (settlement during `CRITICAL` is rejected with `ERR_BASIN_CRITICAL_TRANSFERS_SUSPENDED`), and the seller's settled-variant available water — computed with the order being settled first removed from `transfer_reserved_af`, so its own reservation does not count against it — must be at least `quantity_af`, failing which the settle is rejected with `ERR_SETTLE_INSUFFICIENT_WATER`."

        Design: Difficulty/boundary_precision_check/transfer_quantity_exactly_equals_available_succeeds
        """
        # Allocation 100, verified extraction 70 -> settled-variant deliverable exactly
        # 30.000 for a 30.000-af order (its own reservation is removed first).
        seller = create_account(holder_name="Seller JE", base_allocation_af=100.000)
        buyer = create_account(holder_name="Buyer JE", base_allocation_af=50.000)
        well = create_active_production_well(seller["id"])
        submit_and_verify_report(well["id"], seller["id"], month=6, reported_af=70.000)

        order = propose_transfer(seller["id"], buyer["id"], 30.000)
        accept_transfer(order["id"], buyer["id"])
        settled = validate_success(api.settle_transfer(order["id"], water_master_headers))
        assert settled["status"] == "SETTLED", (
            "settled-variant available 100-70 = 30.000 >= 30.000: equality passes"
        )
        assert settled["settled_at"] is not None
        assert get_account(buyer["id"])["credit_balance_af"] == pytest.approx(30.000, abs=1e-9)


class TestBuyerWindowOverlap:
    def test_buyer_inbound_window_half_open_adjacency(self, api):
        """PRD §3.4: "First, the buyer inbound-window rule: no two transfer orders with the same `buyer_account_id` and a status of `PROPOSED`, `ACCEPTED`, or `SETTLED` may have overlapping half-open windows; adjacency — where an existing order's `effective_end_date` equals the new order's `effective_start_date` — is permitted, and a true overlap is rejected with `ERR_TRANSFER_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/buyer_inbound_window_half_open_adjacency
        """
        seller_1 = create_account(holder_name="Seller MS-1", base_allocation_af=100.000)
        seller_2 = create_account(holder_name="Seller MS-2", base_allocation_af=100.000)
        buyer = create_account(holder_name="Buyer MB", base_allocation_af=50.000)

        propose_transfer(seller_1["id"], buyer["id"], 5.000, "2026-08-01", "2026-10-01")

        adjacent = propose_transfer(seller_2["id"], buyer["id"], 5.000,
                                    "2026-10-01", "2026-12-01")
        assert adjacent["status"] == "PROPOSED", (
            "existing end 2026-10-01 == new start 2026-10-01 is adjacency, not overlap"
        )

        overlapping = api.create_transfer_order(
            create_transfer_order_payload(seller_2["id"], buyer["id"], quantity_af=5.000,
                                          effective_start_date="2026-11-15",
                                          effective_end_date="2027-01-01"),
            make_well_owner_headers(seller_2["id"]),
        )
        validate_error(overlapping, ApiErrorId.ERR_TRANSFER_WINDOW_OVERLAP)

    def test_buyer_window_containment_overlap_rejected(self, api):
        """PRD §3.4: "First, the buyer inbound-window rule: no two transfer orders with the same `buyer_account_id` and a status of `PROPOSED`, `ACCEPTED`, or `SETTLED` may have overlapping half-open windows; adjacency — where an existing order's `effective_end_date` equals the new order's `effective_start_date` — is permitted, and a true overlap is rejected with `ERR_TRANSFER_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/buyer_inbound_window_half_open_adjacency
        """
        seller_1 = create_account(holder_name="Seller MS-3", base_allocation_af=100.000)
        seller_2 = create_account(holder_name="Seller MS-4", base_allocation_af=100.000)
        buyer = create_account(holder_name="Buyer MB-2", base_allocation_af=50.000)

        propose_transfer(seller_1["id"], buyer["id"], 5.000, "2026-08-01", "2026-10-01")

        inside = api.create_transfer_order(
            create_transfer_order_payload(seller_2["id"], buyer["id"], quantity_af=5.000,
                                          effective_start_date="2026-08-15",
                                          effective_end_date="2026-09-15"),
            make_well_owner_headers(seller_2["id"]),
        )
        validate_error(inside, ApiErrorId.ERR_TRANSFER_WINDOW_OVERLAP)

        straddling = api.create_transfer_order(
            create_transfer_order_payload(seller_2["id"], buyer["id"], quantity_af=5.000,
                                          effective_start_date="2026-07-01",
                                          effective_end_date="2026-09-01"),
            make_well_owner_headers(seller_2["id"]),
        )
        validate_error(straddling, ApiErrorId.ERR_TRANSFER_WINDOW_OVERLAP)


class TestMonthlyMarketCap:
    def test_monthly_market_cap_aggregate_intersection(self, api):
        """PRD §3.4: "Third, basin-wide monthly capacity: for every calendar month the new order's window intersects, the aggregate `quantity_af` across all orders in `PROPOSED`, `ACCEPTED`, or `SETTLED` whose windows intersect that same month, plus the new order's `quantity_af`, must not exceed 5000 acre-feet; a month whose running total reaches exactly 5000 is allowed, but any excess is rejected with `ERR_MONTHLY_TRANSFER_CAP_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/monthly_market_cap_aggregate_intersection
        """
        seller = create_account(holder_name="Seller KS-1", base_allocation_af=10000.000)
        buyers = [
            create_account(holder_name=f"Buyer KB-{i}", base_allocation_af=50.000)
            for i in (1, 2, 3, 4)
        ]

        propose_transfer(seller["id"], buyers[0]["id"], 3000.000, "2026-08-15", "2026-10-15")
        propose_transfer(seller["id"], buyers[1]["id"], 1999.999, "2026-09-01", "2026-10-01")

        exact = propose_transfer(seller["id"], buyers[2]["id"], 0.001,
                                 "2026-09-10", "2026-10-10")
        assert exact["status"] == "PROPOSED", (
            "September aggregate 3000.000 + 1999.999 + 0.001 = 5000.000 <= 5000 is allowed"
        )

        over = api.create_transfer_order(
            create_transfer_order_payload(seller["id"], buyers[3]["id"], quantity_af=0.001,
                                          effective_start_date="2026-09-05",
                                          effective_end_date="2026-09-25"),
            make_well_owner_headers(seller["id"]),
        )
        validate_error(over, ApiErrorId.ERR_MONTHLY_TRANSFER_CAP_EXCEEDED)

    def test_monthly_cap_does_not_leak_across_months(self, api):
        """PRD §3.4: "Third, basin-wide monthly capacity: for every calendar month the new order's window intersects, the aggregate `quantity_af` across all orders in `PROPOSED`, `ACCEPTED`, or `SETTLED` whose windows intersect that same month, plus the new order's `quantity_af`, must not exceed 5000 acre-feet; a month whose running total reaches exactly 5000 is allowed, but any excess is rejected with `ERR_MONTHLY_TRANSFER_CAP_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/monthly_market_cap_aggregate_intersection
        """
        seller = create_account(holder_name="Seller KS-2", base_allocation_af=10000.000)
        buyer_1 = create_account(holder_name="Buyer KC-1", base_allocation_af=50.000)
        buyer_2 = create_account(holder_name="Buyer KC-2", base_allocation_af=50.000)

        # Pin September at exactly the cap.
        propose_transfer(seller["id"], buyer_1["id"], 5000.000, "2026-09-01", "2026-10-01")

        # A window that never touches September is evaluated against November only.
        other_month = propose_transfer(seller["id"], buyer_2["id"], 4000.000,
                                       "2026-11-01", "2026-12-01")
        assert other_month["status"] == "PROPOSED", (
            "November's aggregate is 4000.000 <= 5000; September's saturated bucket "
            "must not leak into other months"
        )


class TestProposalCompensation:
    def test_propose_cancel_restores_available_water(self, api):
        """PRD §3.4: "A created order lands in `PROPOSED`, its `expires_at` is stamped at creation time plus 72 hours, and the seller's `transfer_reserved_af` increases by `quantity_af` — a reservation against double-selling that blocks the same water from being committed twice."
        PRD §3.4: "The owner of the buyer account accepts a `PROPOSED` order, moving it to `ACCEPTED`; the owner of the seller account cancels a `PROPOSED` order, moving it to `CANCELLED` and releasing the reservation."

        Design: Difficulty/compensating_invariant/propose_cancel_restores_available_water
        """
        seller = create_account(holder_name="Seller NS", base_allocation_af=80.000)
        buyer = create_account(holder_name="Buyer NB", base_allocation_af=50.000)
        well = create_active_production_well(seller["id"])
        submit_and_verify_report(well["id"], seller["id"], month=6, reported_af=10.000)

        order = propose_transfer(seller["id"], buyer["id"], 25.000)
        cancel_transfer(order["id"], seller["id"])

        seller_after = get_account(seller["id"])
        assert seller_after["transfer_reserved_af"] == pytest.approx(0.0, abs=1e-9), (
            "propose (+25) paired with cancel (-25) must leave no reservation residue"
        )
        assert seller_after["transfer_out_af_ytd"] == pytest.approx(0.0, abs=1e-9)
        assert seller_after["extracted_af_ytd"] == pytest.approx(10.000, abs=1e-9)

        follow_on = propose_transfer(seller["id"], buyer["id"], 70.000,
                                     "2026-11-01", "2027-01-01")
        assert follow_on["status"] == "PROPOSED", (
            "the full remaining 70.000 af must be available again after cancellation"
        )

    def test_propose_expire_restores_available_water(self, api):
        """PRD §2.5: "Setting the clock also triggers an expiry sweep: every `TransferOrder` still in `PROPOSED` status whose `expires_at` is strictly before the new time transitions to `EXPIRED`, and each such expiry releases the seller's reservation."

        Design: Difficulty/compensating_invariant/propose_cancel_restores_available_water
        """
        seller = create_account(holder_name="Seller NE", base_allocation_af=80.000)
        buyer = create_account(holder_name="Buyer NE", base_allocation_af=50.000)
        well = create_active_production_well(seller["id"])
        submit_and_verify_report(well["id"], seller["id"], month=6, reported_af=10.000)

        order = propose_transfer(seller["id"], buyer["id"], 25.000)
        assert get_account(seller["id"])["transfer_reserved_af"] == pytest.approx(25.000, abs=1e-9)

        # Created at the default 2026-08-01T00:00:00Z clock; expires 72 hours later.
        set_clock("2026-08-04T00:00:01Z")
        expired = validate_success(
            api.get_transfer_order(order["id"], TEST_USERS["water_master_headers"])
        )
        assert expired["status"] == "EXPIRED"
        assert get_account(seller["id"])["transfer_reserved_af"] == pytest.approx(0.0, abs=1e-9), (
            "the expiry sweep must release the seller's reservation"
        )

        follow_on = propose_transfer(seller["id"], buyer["id"], 70.000,
                                     "2026-11-01", "2027-01-01")
        assert follow_on["status"] == "PROPOSED"


class TestProposalGateOrdering:
    def test_proposal_overlap_plus_insufficient_constraint_beats_fiscal(self, api):
        """PRD §3.4: "The seller and buyer must differ (`ERR_SELF_TRANSFER`), both parties' accounts must be `ACTIVE` (`ERR_ACCOUNT_NOT_ACTIVE`), and the proposal passes through three independent gates evaluated in the order stated here. First, the buyer inbound-window rule: no two transfer orders with the same `buyer_account_id` and a status of `PROPOSED`, `ACCEPTED`, or `SETTLED` may have overlapping half-open windows; adjacency — where an existing order's `effective_end_date` equals the new order's `effective_start_date` — is permitted, and a true overlap is rejected with `ERR_TRANSFER_WINDOW_OVERLAP`. Second, seller sufficiency: the seller's forward-looking available water must be at least `quantity_af`, with equality passing; a shortfall yields `ERR_INSUFFICIENT_AVAILABLE_WATER`."

        Design: Difficulty/priority_pair_validation_conflict/proposal_overlap_plus_insufficient_constraint_beats_fiscal
        """
        seller_1 = create_account(holder_name="Seller IS-1", base_allocation_af=100.000)
        buyer = create_account(holder_name="Buyer IB", base_allocation_af=50.000)
        seller_2 = create_account(holder_name="Seller IS-2", base_allocation_af=10.000)

        propose_transfer(seller_1["id"], buyer["id"], 5.000, "2026-08-01", "2026-10-01")

        # Window overlaps the buyer's existing inbound order AND quantity 20.000
        # exceeds seller_2's forward-looking 10.000: the window rule fires first.
        resp = api.create_transfer_order(
            create_transfer_order_payload(seller_2["id"], buyer["id"], quantity_af=20.000,
                                          effective_start_date="2026-09-01",
                                          effective_end_date="2026-11-01"),
            make_well_owner_headers(seller_2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TRANSFER_WINDOW_OVERLAP)

    def test_proposal_overlap_with_settled_plus_insufficient_beats_fiscal(
        self, api, water_master_headers
    ):
        """PRD §3.4: "The seller and buyer must differ (`ERR_SELF_TRANSFER`), both parties' accounts must be `ACTIVE` (`ERR_ACCOUNT_NOT_ACTIVE`), and the proposal passes through three independent gates evaluated in the order stated here. First, the buyer inbound-window rule: no two transfer orders with the same `buyer_account_id` and a status of `PROPOSED`, `ACCEPTED`, or `SETTLED` may have overlapping half-open windows; adjacency — where an existing order's `effective_end_date` equals the new order's `effective_start_date` — is permitted, and a true overlap is rejected with `ERR_TRANSFER_WINDOW_OVERLAP`. Second, seller sufficiency: the seller's forward-looking available water must be at least `quantity_af`, with equality passing; a shortfall yields `ERR_INSUFFICIENT_AVAILABLE_WATER`."

        Design: Difficulty/priority_pair_validation_conflict/proposal_overlap_plus_insufficient_constraint_beats_fiscal
        """
        seller_1 = create_account(holder_name="Seller IS-3", base_allocation_af=100.000)
        buyer = create_account(holder_name="Buyer IB-2", base_allocation_af=50.000)
        seller_2 = create_account(holder_name="Seller IS-4", base_allocation_af=10.000)

        # The buyer's existing inbound order is SETTLED — still in the overlap set.
        order = propose_transfer(seller_1["id"], buyer["id"], 5.000,
                                 "2026-08-01", "2026-10-01")
        accept_transfer(order["id"], buyer["id"])
        settled = validate_success(api.settle_transfer(order["id"], water_master_headers))
        assert settled["status"] == "SETTLED"

        resp = api.create_transfer_order(
            create_transfer_order_payload(seller_2["id"], buyer["id"], quantity_af=20.000,
                                          effective_start_date="2026-09-01",
                                          effective_end_date="2026-11-01"),
            make_well_owner_headers(seller_2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TRANSFER_WINDOW_OVERLAP)


class TestTransferStateGates:
    def test_self_transfer_rejected(self, api):
        """PRD §3.4: "The seller and buyer must differ (`ERR_SELF_TRANSFER`), both parties' accounts must be `ACTIVE` (`ERR_ACCOUNT_NOT_ACTIVE`), and the proposal passes through three independent gates evaluated in the order stated here."

        Design: Corner/validations/self_transfer_rejected
        """
        account = create_account(holder_name="Pumper ST-1")
        resp = api.create_transfer_order(
            create_transfer_order_payload(account["id"], account["id"], quantity_af=5.000),
            make_well_owner_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SELF_TRANSFER)

    def test_cancel_settled_transfer_rejected(self, api, water_master_headers):
        """PRD §3.4: "The owner of the buyer account accepts a `PROPOSED` order, moving it to `ACCEPTED`; the owner of the seller account cancels a `PROPOSED` order, moving it to `CANCELLED` and releasing the reservation. Any other from-state for accept or cancel is `ERR_INVALID_TRANSFER_STATE`."

        Design: Corner/state_machines/cancel_settled_transfer_rejected
        """
        seller = create_account(holder_name="Seller TS-1", base_allocation_af=100.000)
        buyer = create_account(holder_name="Buyer TB-1", base_allocation_af=50.000)
        order = propose_transfer(seller["id"], buyer["id"], 5.000)
        accept_transfer(order["id"], buyer["id"])
        settled = validate_success(api.settle_transfer(order["id"], water_master_headers))
        assert settled["status"] == "SETTLED"

        resp = api.cancel_transfer(order["id"], make_well_owner_headers(seller["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_TRANSFER_STATE)

        assert get_account(buyer["id"])["credit_balance_af"] == pytest.approx(5.000, abs=1e-9), (
            "the rejected cancel must not undo the settlement's credit"
        )

    def test_settle_insufficient_water_after_interleaved_verify(self, api, water_master_headers):
        """PRD §3.4: "Settlement performs two preconditions before committing: the official basin condition must not be `CRITICAL` (settlement during `CRITICAL` is rejected with `ERR_BASIN_CRITICAL_TRANSFERS_SUSPENDED`), and the seller's settled-variant available water — computed with the order being settled first removed from `transfer_reserved_af`, so its own reservation does not count against it — must be at least `quantity_af`, failing which the settle is rejected with `ERR_SETTLE_INSUFFICIENT_WATER`."

        Design: Corner/endpoints/settle_insufficient_water_after_interleaved_verify
        """
        # Proposal-time availability 100-40 = 60 >= 30; a 45.000-af report verified
        # between accept and settle drops the settled-variant deliverable to 15.000.
        seller = create_account(holder_name="Seller SS", base_allocation_af=100.000)
        buyer = create_account(holder_name="Buyer SB", base_allocation_af=50.000)
        well = create_active_production_well(seller["id"])
        submit_and_verify_report(well["id"], seller["id"], month=6, reported_af=40.000)

        order = propose_transfer(seller["id"], buyer["id"], 30.000)
        accept_transfer(order["id"], buyer["id"])

        report_2 = submit_extraction_report(well["id"], seller["id"], month=7,
                                            reported_af=45.000)
        verify_report(report_2["id"])

        resp = api.settle_transfer(order["id"], water_master_headers)
        validate_error(resp, ApiErrorId.ERR_SETTLE_INSUFFICIENT_WATER)

        after = validate_success(api.get_transfer_order(order["id"], water_master_headers))
        assert after["status"] == "ACCEPTED", (
            "the failed settlement must leave the order in ACCEPTED"
        )

