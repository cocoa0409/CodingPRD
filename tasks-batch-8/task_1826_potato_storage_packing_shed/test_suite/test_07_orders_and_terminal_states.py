"""Order terminal-state lockdowns, compensating cancel, and validation-priority
conflicts (PRD §3.5, §3.6, §2.9)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    setup_grower_shed_bin_lot, setup_allocated_contract_order,
    setup_packing_order_with_run,
    create_binned_lot, assess_lot, create_contract, create_order, allocate_order,
    refresh_lot, refresh_order, refresh_contract, complete_run, make_draw,
    TEST_USERS,
)

SALES = TEST_USERS["sales_headers"]
STORAGE = TEST_USERS["storage_headers"]


class TestOrderTerminalLockdown:
    def test_cancel_shipped_order_rejected(self, api):
        """PRD §3.6: "An order can be cancelled by a `SalesManager` from either `REQUESTED` or `ALLOCATED`; cancelling from any other state is `ERR_ORDER_INVALID_STATE`."

        Design: Corner/state_machines/c_order_cancel_shipped_returns_order_invalid_state
        """
        ctx = setup_packing_order_with_run(lot_weight_cwt=500.00, committed_cwt=300.00,
                                           requested_packed_cwt=75.00)
        # Fully ship the 75.00 request.
        complete_run(ctx["run"]["id"], [make_draw(
            ctx["lot"]["id"], 100.00, 75.00, 60.00, 15.00, 25.00, "WASTE"
        )])
        order = refresh_order(ctx["order"]["id"])
        assert order["status"] == "SHIPPED"

        resp = api.cancel_order(ctx["order"]["id"], SALES)
        validate_error(resp, ApiErrorId.ERR_ORDER_INVALID_STATE)
        order = refresh_order(ctx["order"]["id"])
        assert order["status"] == "SHIPPED"  # no compensation ran
        contract = refresh_contract(ctx["contract"]["id"])
        assert abs(contract["packed_to_date_cwt"] - 75.00) <= 0.005


class TestContractCommitmentConservation:
    def test_allocate_then_cancel_restores_commitment_exactly(self, api):
        """PRD §3.3: "`allocated_active_cwt` is the sum over the contract's orders in `ALLOCATED` or `PACKING` of each order's requested volume less what it has already packed; `packed_to_date_cwt` is the sum of packed actuals over all of the contract's orders; and `remaining_committed_cwt` is the committed volume less both of those quantities."
        PRD §3.6: "Cancelling from `ALLOCATED` releases every reservation the order holds — each referenced lot's `reserved_cwt` is decremented by the reservation's raw amount — and, for a `CONTRACT` order, restores the commitment ledger: the contract's `allocated_active_cwt` decreases by the requested volume less what has been packed to date, and its `remaining_committed_cwt` increases by the same amount."

        Design: Difficulty/compensating_invariant/contract_commitment_conservation
        """
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower Eighteen", grower_code="G-18", shed_name="Shed R",
            lot_weight_cwt=1000.00, set_clock_to="2026-08-02T00:00:00Z",
        )
        l = ctx["lot"]
        assess_lot(l["id"], l["version"], us1_pct=70.0, us2_pct=20.0, cull_pct=10.0,
                   cumulative_shrink_cwt=0.00)
        contract = create_contract(committed_volume_cwt=500.00, price_cents_per_cwt=2000,
                                   grade_min_us1_pct=80.0, buyer_name="Buyer N")
        order = create_order(ctx["shed"]["id"], contract_id=contract["id"],
                             requested_packed_cwt=300.00, grade_min_us1_pct=80.0)
        allocate_order(order["id"])

        c = refresh_contract(contract["id"])
        # after allocate: 500 == 200 + 300 + 0
        assert abs(c["remaining_committed_cwt"] - 200.00) <= 0.005
        assert abs(c["allocated_active_cwt"] - 300.00) <= 0.005
        assert abs(c["packed_to_date_cwt"] - 0.00) <= 0.005

        order = validate_success(api.cancel_order(order["id"], SALES), expected_status=200)
        assert order["status"] == "CANCELLED"

        c = refresh_contract(contract["id"])
        # after cancel: 500 == 500 + 0 + 0 — restored exactly
        assert abs(c["remaining_committed_cwt"] - 500.00) <= 0.005
        assert abs(c["allocated_active_cwt"] - 0.00) <= 0.005
        assert abs(c["packed_to_date_cwt"] - 0.00) <= 0.005

    def test_reservation_release_matches_allocation(self, api):
        """PRD §3.6: "Cancelling from `ALLOCATED` releases every reservation the order holds — each referenced lot's `reserved_cwt` is decremented by the reservation's raw amount".

        Design: Difficulty/compensating_invariant/contract_commitment_conservation
        """
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower Eighteen", grower_code="G-18", shed_name="Shed R",
            lot_weight_cwt=1000.00, set_clock_to="2026-08-02T00:00:00Z",
        )
        l = ctx["lot"]
        assess_lot(l["id"], l["version"], us1_pct=70.0, us2_pct=20.0, cull_pct=10.0,
                   cumulative_shrink_cwt=0.00)
        contract = create_contract(committed_volume_cwt=500.00, price_cents_per_cwt=2000,
                                   grade_min_us1_pct=80.0, buyer_name="Buyer N")
        order = create_order(ctx["shed"]["id"], contract_id=contract["id"],
                             requested_packed_cwt=300.00, grade_min_us1_pct=80.0)
        allocate_order(order["id"])

        lot = refresh_lot(l["id"])
        assert abs(lot["reserved_cwt"] - 333.33) <= 0.005  # 300 / 0.9

        api.cancel_order(order["id"], SALES)
        lot = refresh_lot(l["id"])
        assert abs(lot["reserved_cwt"] - 0.00) <= 0.005  # release matched to the cent


class TestDerivedReservationReconciliation:
    def test_reserved_moves_but_available_does_not(self, api):
        """PRD §3.4: "Each reservation records the `field_lot_id`, the reserved `raw_cwt`, and the `packed_equiv_cwt` covered, and the lot's `reserved_cwt` is increased by the raw amount."
        PRD §3.6: "Cancelling from `ALLOCATED` releases every reservation the order holds — each referenced lot's `reserved_cwt` is decremented by the reservation's raw amount".

        Design: Corner/cross_cutting_complexity_layers/c_derived_reserved_reconciles_on_cancel
        """
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower AV", grower_code="G-AV", shed_name="Shed ED",
            lot_weight_cwt=500.00,
        )
        contract = create_contract(committed_volume_cwt=300.00, price_cents_per_cwt=2000,
                                   buyer_name="Buyer AC")
        order = create_order(ctx["shed"]["id"], contract_id=contract["id"],
                             requested_packed_cwt=75.00)
        allocate_order(order["id"])

        lot = refresh_lot(ctx["lot"]["id"])
        assert abs(lot["reserved_cwt"] - 100.00) <= 0.005  # 75 / 0.75
        assert abs(lot["available_cwt"] - 500.00) <= 0.005  # reservation does not debit

        api.cancel_order(order["id"], SALES)
        lot = refresh_lot(ctx["lot"]["id"])
        assert abs(lot["reserved_cwt"] - 0.00) <= 0.005
        assert abs(lot["available_cwt"] - 500.00) <= 0.005


class TestLotWeightConservation:
    def test_abort_leaves_weight_ledger_untouched(self, api):
        """PRD §3.5: "When the outcome is `ABORTED`, no draws are recorded, the run transitions to `ABORTED`, and the order drops back from `PACKING` to `ALLOCATED` as a compensating action — reservations and lot weights are unchanged."

        Design: Difficulty/compensating_invariant/lot_weight_conservation
        """
        ctx = setup_packing_order_with_run(
            lot_weight_cwt=1000.00, committed_cwt=500.00, requested_packed_cwt=200.00,
            grade_min_us1_pct=80.0,
            assess={"us1_pct": 70.0, "us2_pct": 20.0, "cull_pct": 10.0,
                    "cumulative_shrink_cwt": 20.00},
        )
        run = get_success_data(
            api.close_pack_run(ctx["run"]["id"], {"outcome": "ABORTED"},
                               TEST_USERS["supervisor_headers"])
        )
        assert run["status"] == "ABORTED"
        order = refresh_order(ctx["order"]["id"])
        assert order["status"] == "ALLOCATED"  # compensation returns the order

        lot = refresh_lot(ctx["lot"]["id"])
        # create+abort leaves the weight ledger untouched: 1000 == 980 + 0 + 0 + 0 + 20
        assert abs(lot["available_cwt"] - 980.00) <= 0.005
        assert abs(lot["reserved_cwt"] - 222.22) <= 0.005
        assert abs(lot["packed_total_cwt"] - 0.00) <= 0.005
        assert abs(lot["shrink_cwt"] - 20.00) <= 0.005

    def test_completed_close_moves_weight_and_processing_credit(self, api):
        """PRD §3.5: "For each draw, the lot's `packed_total_cwt` increases by the draw's `packed_cwt`, its `cull_total_cwt` increases by the draw's `cull_cwt`, its `available_cwt` decreases by the `raw_drawn_cwt`, and its `reserved_cwt` decreases by the same raw amount; the reservation on that lot is consumed. When the draw's `cull_channel` is `PROCESSING`, the lot's `processing_credit_cwt` also increases by the `cull_cwt`."

        Design: Difficulty/compensating_invariant/lot_weight_conservation
        """
        ctx = setup_packing_order_with_run(
            lot_weight_cwt=1000.00, committed_cwt=500.00, requested_packed_cwt=200.00,
            grade_min_us1_pct=80.0,
            assess={"us1_pct": 70.0, "us2_pct": 20.0, "cull_pct": 10.0,
                    "cumulative_shrink_cwt": 20.00},
        )
        abort_run_id = ctx["run"]["id"]
        get_success_data(api.close_pack_run(abort_run_id, {"outcome": "ABORTED"},
                                            TEST_USERS["supervisor_headers"]))

        # Re-run and complete with a PROCESSING cull channel draw.
        from test_helpers import create_scheduled_run
        run2 = create_scheduled_run(ctx["order"]["id"], "2026-08-02T10:00:00Z",
                                    "2026-08-02T12:00:00Z")
        complete_run(run2["id"], [make_draw(
            ctx["lot"]["id"], 222.22, 200.00, 170.00, 30.00, 22.22, "PROCESSING"
        )])

        lot = refresh_lot(ctx["lot"]["id"])
        # 1000 == 757.78 + 200 + 22.22 + 0 + 20
        assert abs(lot["available_cwt"] - 757.78) <= 0.005
        assert abs(lot["reserved_cwt"] - 0.00) <= 0.005
        assert abs(lot["packed_total_cwt"] - 200.00) <= 0.005
        assert abs(lot["cull_total_cwt"] - 22.22) <= 0.005
        # PROCESSING channel cull accrues grower credit weight
        assert abs(lot["processing_credit_cwt"] - 22.22) <= 0.005


class TestPriorityConflictStateOverFiscal:
    def test_allocate_cancelled_order_reports_state_not_fiscal(self, api):
        """PRD §2.9: "When a single request would trip more than one rule, the server evaluates checks in a fixed priority order so that the surfaced error is deterministic."
        PRD §2.9 tier 5 lists "order requested/allocated gates" among state failures surfacing as "`ERR_ORDER_INVALID_STATE`", and tier 10 lists "the contract commitment ceiling" among fiscal failures surfacing as "`ERR_COMMITMENT_EXCEEDED`".

        Design: Difficulty/priority_pair_validation_conflict/state_outranks_fiscal_on_allocate
        """
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower Ten", grower_code="G-TEN", shed_name="Shed J",
            lot_weight_cwt=120.00, set_clock_to="2026-08-02T00:00:00Z",
        )
        l = ctx["lot"]
        assess_lot(l["id"], l["version"], us1_pct=70.0, us2_pct=20.0, cull_pct=10.0,
                   cumulative_shrink_cwt=0.00)
        contract = create_contract(committed_volume_cwt=100.00, price_cents_per_cwt=2000,
                                   buyer_name="Buyer H")
        o1 = create_order(ctx["shed"]["id"], contract_id=contract["id"],
                          requested_packed_cwt=100.00)
        allocate_order(o1["id"])  # == commitment, allowed; remaining now 0
        # pool coverage floor2(120.00 x 0.9) = 108.00 >= 100.00 satisfies §3.4 atomicity

        o2 = create_order(ctx["shed"]["id"], contract_id=contract["id"],
                          requested_packed_cwt=50.00)
        api.cancel_order(o2["id"], SALES)  # cancel while REQUESTED

        # Both the state gate (CANCELLED) and the fiscal ceiling (0.00 remaining) fail;
        # the state check (tier 5) must surface first.
        resp = api.allocate_order(o2["id"], SALES)
        validate_error(resp, ApiErrorId.ERR_ORDER_INVALID_STATE)

    def test_priority_conflict_leaves_no_side_effects(self, api):
        """PRD §2.9: "When a single request would trip more than one rule, the server evaluates checks in a fixed priority order so that the surfaced error is deterministic."
        PRD §3.6: "Cancelling from `REQUESTED` simply marks the order `CANCELLED` — there are no reservations to release."

        Design: Difficulty/priority_pair_validation_conflict/state_outranks_fiscal_on_allocate
        """
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower Ten", grower_code="G-TEN", shed_name="Shed J",
            lot_weight_cwt=120.00, set_clock_to="2026-08-02T00:00:00Z",
        )
        l = ctx["lot"]
        assess_lot(l["id"], l["version"], us1_pct=70.0, us2_pct=20.0, cull_pct=10.0,
                   cumulative_shrink_cwt=0.00)
        contract = create_contract(committed_volume_cwt=100.00, price_cents_per_cwt=2000,
                                   buyer_name="Buyer H")
        o1 = create_order(ctx["shed"]["id"], contract_id=contract["id"],
                          requested_packed_cwt=100.00)
        allocate_order(o1["id"])  # pool coverage 108.00 >= 100.00; remaining now 0

        o2 = create_order(ctx["shed"]["id"], contract_id=contract["id"],
                          requested_packed_cwt=50.00)
        api.cancel_order(o2["id"], SALES)
        api.allocate_order(o2["id"], SALES)  # rejected; must not leak side effects

        order = refresh_order(o2["id"])
        assert order["status"] == "CANCELLED"
        contract = refresh_contract(contract["id"])
        assert abs(contract["remaining_committed_cwt"] - 0.00) <= 0.005
