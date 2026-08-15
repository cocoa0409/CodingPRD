"""Scarcity: cold-snap curtailment cascades, pro-rata allocation runs with
terminal OCC, the lift requeue, and the daily ops epoch sweeps."""
from test_helpers import (
    CREDIT_MANAGER,
    SUPPLY_ADMIN,
    SUPPLY_PLANNER,
    SYSTEM_ADMIN,
    ApiErrorId,
    activate_dealer_contract,
    api_client,
    assert_allocation_run,
    base_order_fixture,
    base_terminal_fixture,
    create_allocation_run,
    create_allocation_run_payload,
    create_dealer,
    create_dealer_contract,
    create_order,
    create_supply_contract,
    create_terminal,
    curtail_terminal,
    dealer_with_active_contract,
    declare_cold_snap,
    get_success_data,
    publish_index,
    set_clock,
    tender_shipment,
    validate_error,
    validate_success,
)


class TestColdSnapActivationCascade:

    def _setup_allocated_index_order(self):
        """Dealer limit 3000000; 20000-gal INDEX order ALLOCATED at 2060000
        (68.7% of the limit: GOOD_STANDING)."""
        ctx = base_order_fixture(name="T-K1", truck_count=0,
                                 credit_limit_cents=3_000_000,
                                 pricing_mode="INDEX")
        publish_index(price_mc_per_gal=95_000, effective_date="2026-08-01")
        order = create_order(ctx["dealer"]["id"], ctx["terminal"]["id"],
                             ctx["zone"]["id"], 20_000,
                             dealer_contract_id=ctx["dealer_contract"]["id"])
        # rhu(20000*95000/1000)=1900000 + max(150000, 160000)=160000.
        assert order["provisional_total_cents"] == 2_060_000, "setup check"
        return ctx, order

    def test_activation_curtails_and_restamps_provisionals(self):
        """PRD section 3.7: "Activation curtails the terminal:
        `allocation_posture` flips from `NORMAL` to `CURTAILED`, bumping
        `Terminal.version`. The cascade is immediate and atomic. Every order of
        this terminal in `ALLOCATED` or `SCHEDULED` has its
        `provisional_total_cents` recomputed, now including the 30-cent winter
        surcharge."

        Design: Difficulty/transitive_cascade/cold_snap_activation_repricing_to_credit_flip
        """
        ctx, order = self._setup_allocated_index_order()
        snap = declare_cold_snap(ctx["terminal"]["id"], severity="EMERGENCY")
        api_client.activate_cold_snap(snap["id"], SUPPLY_PLANNER)

        term = get_success_data(api_client.get_terminal(ctx["terminal"]["id"],
                                                        SUPPLY_PLANNER))
        assert term["allocation_posture"] == "CURTAILED"

        repriced = get_success_data(api_client.get_delivery_order(order["id"],
                                                                  SUPPLY_PLANNER))
        # 2060000 + rhu(20000*30000/1000) = 2060000 + 600000.
        assert repriced["provisional_total_cents"] == 2_660_000, (
            "the winter leg is added to the standing provisional; got "
            f"{repriced['provisional_total_cents']}")

    def test_activation_repricing_flips_credit_to_watch(self):
        """PRD section 3.7: "Each affected dealer's committed exposure is
        recomputed from the new provisionals, and credit postures may flip from
        `GOOD_STANDING` to `WATCH` or `SUSPENDED`."
        PRD section 3.3: "when five times the committed exposure reaches or
        exceeds four times the credit limit — an exposure of exactly eighty
        percent crosses the line — the dealer is `WATCH`."

        Design: Difficulty/transitive_cascade/cold_snap_activation_repricing_to_credit_flip
        """
        ctx, order = self._setup_allocated_index_order()
        before = get_success_data(api_client.get_dealer(ctx["dealer"]["id"],
                                                        CREDIT_MANAGER))
        assert before["credit_status"] == "GOOD_STANDING", "setup check"

        snap = declare_cold_snap(ctx["terminal"]["id"], severity="EMERGENCY")
        api_client.activate_cold_snap(snap["id"], SUPPLY_PLANNER)

        after = get_success_data(api_client.get_dealer(ctx["dealer"]["id"],
                                                       CREDIT_MANAGER))
        # 2660000 * 5 = 13300000 >= 3000000 * 4 = 12000000 -> WATCH.
        assert after["credit_status"] == "WATCH", (
            f"the repriced provisional pushes exposure past 80%; got "
            f"{after['credit_status']}")
        assert after["committed_exposure_cents"] == 2_660_000


class TestColdSnapLifecycle:

    def test_cold_snap_second_active_rejected(self):
        """PRD section 3.7: "Activation — manual, or by the daily epoch once
        `start_date` is reached — requires that no other event on the same
        terminal is already `ACTIVE`, failing with
        `ERR_COLD_SNAP_ALREADY_ACTIVE` otherwise."

        Design: Corner/state_machines/cold_snap_second_active_rejected
        """
        term = create_terminal(name="T-M8")
        first = declare_cold_snap(term["id"], severity="WATCH",
                                  start_date="2026-08-01", end_date="2026-08-10")
        second = declare_cold_snap(term["id"], severity="EMERGENCY",
                                   start_date="2026-08-02",
                                   end_date="2026-08-15")
        api_client.activate_cold_snap(first["id"], SUPPLY_PLANNER)

        resp = api_client.activate_cold_snap(second["id"], SUPPLY_PLANNER)
        validate_error(resp, ApiErrorId.ERR_COLD_SNAP_ALREADY_ACTIVE)

        after = get_success_data(api_client.get_cold_snap_event(second["id"],
                                                                SUPPLY_PLANNER))
        assert after["status"] == "DECLARED"
        term_after = get_success_data(api_client.get_terminal(term["id"],
                                                              SUPPLY_PLANNER))
        assert term_after["allocation_posture"] == "CURTAILED", \
            "the first event still holds the terminal curtailed"

    def test_lift_requeues_shorted_orders(self):
        """PRD section 3.7: "The posture flips back to `NORMAL`, provisionals
        on `ALLOCATED` and `SCHEDULED` orders are re-stamped with the surcharge
        removed, every `SHORTED` order at the terminal returns to `REQUESTED`
        with its original `created_at` preserved, and then a FIFO auto-
        allocation sweep runs" and "an order that does not fit stays
        `REQUESTED` and never blocks later orders."

        Design: Corner/state_machines/lift_requeues_shorted_orders
        """
        ctx = base_terminal_fixture(name="T-M13", truck_count=0)
        publish_index(price_mc_per_gal=95_000, effective_date="2026-08-01")
        dealer_r, contract_r = dealer_with_active_contract(
            ctx["terminal"]["id"], legal_name="Dealer MR",
            volume_committed_gal=400_000)
        # Pre-snap: the full ATP (400000 - 50000) is reserved.
        create_order(dealer_r["id"], ctx["terminal"]["id"], ctx["zone"]["id"],
                     350_000, dealer_contract_id=contract_r["id"])

        snap = curtail_terminal(ctx["terminal"]["id"])

        dealer_s = create_dealer(legal_name="Dealer MS")
        spot = create_order(dealer_s["id"], ctx["terminal"]["id"],
                            ctx["zone"]["id"], 10_000)
        assert spot["fulfillment_status"] == "REQUESTED"

        run = create_allocation_run(ctx["terminal"]["id"])
        api_client.compute_allocation_run(run["id"], SUPPLY_PLANNER)
        api_client.ratify_allocation_run(run["id"], SUPPLY_PLANNER)
        shorted = get_success_data(api_client.get_delivery_order(spot["id"],
                                                                 SUPPLY_PLANNER))
        assert shorted["fulfillment_status"] == "SHORTED", "setup check"
        assert shorted["allocated_gal"] == 0

        resp = api_client.lift_cold_snap(snap["id"], SUPPLY_PLANNER)
        lifted = validate_success(resp, expected_status=200)
        assert lifted["status"] == "LIFTED"

        term = get_success_data(api_client.get_terminal(ctx["terminal"]["id"],
                                                        SUPPLY_PLANNER))
        assert term["allocation_posture"] == "NORMAL"

        requeued = get_success_data(api_client.get_delivery_order(spot["id"],
                                                                  SUPPLY_PLANNER))
        assert requeued["fulfillment_status"] == "REQUESTED", (
            "back in the queue; the FIFO sweep finds ATP still 0 against the "
            "pre-snap reservation and leaves it REQUESTED")


class TestAllocationRunLifecycle:

    def test_compute_on_normal_terminal_rejected(self):
        """PRD section 3.7: "Computing the run requires the terminal to be
        `CURTAILED` (`ERR_TERMINAL_NOT_CURTAILED`)."

        Design: Corner/errors/compute_on_normal_terminal_rejected
        """
        term = create_terminal(name="T-R1")
        run = create_allocation_run(term["id"])

        resp = api_client.compute_allocation_run(run["id"], SUPPLY_PLANNER)
        validate_error(resp, ApiErrorId.ERR_TERMINAL_NOT_CURTAILED)

        after = get_success_data(api_client.get_allocation_run(run["id"],
                                                               SUPPLY_PLANNER))
        assert after["status"] == "OPEN"

    def test_allocation_run_ratify_before_compute_rejected(self):
        """PRD section 3.7: "Ratifying a `COMPUTED` run — attempting it in any
        other state is `ERR_RUN_NOT_COMPUTED`"

        Design: Corner/state_machines/allocation_run_ratify_before_compute_rejected
        """
        term = create_terminal(name="T-M6")
        run = create_allocation_run(term["id"])

        resp = api_client.ratify_allocation_run(run["id"], SUPPLY_PLANNER)
        validate_error(resp, ApiErrorId.ERR_RUN_NOT_COMPUTED)

        after = get_success_data(api_client.get_allocation_run(run["id"],
                                                               SUPPLY_PLANNER))
        assert after["status"] == "OPEN"

    def test_allocation_run_superseded_on_new_run(self):
        """PRD section 3.7: "creation moves any existing `OPEN` or `COMPUTED`
        run on the same terminal to `SUPERSEDED`, bumps `Terminal.version`, and
        assigns the next per-terminal `run_index`, starting at 1. A
        `SUPERSEDED` run rejects every further action with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/allocation_run_superseded_on_new_run
        """
        term = create_terminal(name="T-M7")
        run1 = create_allocation_run(term["id"])
        assert run1["run_index"] == 1

        run2 = create_allocation_run(term["id"])
        assert_allocation_run(run2)
        assert run2["status"] == "OPEN"
        assert run2["run_index"] == run1["run_index"] + 1

        first = get_success_data(api_client.get_allocation_run(run1["id"],
                                                               SUPPLY_PLANNER))
        assert first["status"] == "SUPERSEDED"

        resp = api_client.compute_allocation_run(run1["id"], SUPPLY_PLANNER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_occ_allocation_run_stale_terminal_version(self):
        """PRD section 2.6: "Creating an allocation run requires
        `expected_terminal_version` as a non-optional input, carrying the
        caller's last observed `version` of the target `Terminal`. Because
        creating a run supersedes the terminal's existing open run and bumps
        `Terminal.version`, a presented value that no longer matches the
        terminal's current `version` is rejected with
        `ERR_STALE_TERMINAL_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_allocation_run_stale_terminal_version
        """
        term = create_terminal(name="T-O1")
        stale_version = term["version"]
        run1 = create_allocation_run(term["id"])
        assert run1["status"] == "OPEN"

        # The first create bumped Terminal.version; the stale view is dead.
        resp = api_client.create_allocation_run(
            create_allocation_run_payload(term["id"], stale_version),
            SUPPLY_PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_TERMINAL_VERSION)

        # The refreshed view succeeds and supersedes the first run.
        run2 = create_allocation_run(term["id"])
        assert run2["status"] == "OPEN"
        first = get_success_data(api_client.get_allocation_run(run1["id"],
                                                               SUPPLY_PLANNER))
        assert first["status"] == "SUPERSEDED"


class TestAllocationWaterfall:

    def _setup_curtailed_with_three_spot_orders(self):
        """400000 on hand; a 250000-gal FIXED order reserves most of the ATP
        pre-curtailment (pool becomes 100000); a cold snap curtails; dealer S
        posts three 40000-gal SPOT orders; a run is computed."""
        ctx = base_terminal_fixture(name="T-C2", truck_count=0)
        publish_index(price_mc_per_gal=95_000, effective_date="2026-08-01")
        dealer_r, contract_r = dealer_with_active_contract(
            ctx["terminal"]["id"], legal_name="Dealer R",
            volume_committed_gal=300_000)
        create_order(dealer_r["id"], ctx["terminal"]["id"], ctx["zone"]["id"],
                     250_000, dealer_contract_id=contract_r["id"])
        curtail_terminal(ctx["terminal"]["id"])

        dealer_s = create_dealer(legal_name="Dealer S")
        spots = [
            create_order(dealer_s["id"], ctx["terminal"]["id"],
                         ctx["zone"]["id"], 40_000)
            for _ in range(3)
        ]
        for spot in spots:
            assert spot["fulfillment_status"] == "REQUESTED", "setup check"
        run = create_allocation_run(ctx["terminal"]["id"])
        return ctx, run, spots

    def test_allocation_floor_then_remainder_compute_snapshot(self):
        """PRD section 3.7: "The pool is a snapshot of
        `available_to_promise_gal` taken at compute time into `pool_gal`."
        and "the order's share is floored and capped at its `requested_gal` —
        floor first, never above the request. The remainder after flooring is
        then distributed one gallon at a time to orders still below their
        request, oldest `created_at` first with larger `requested_gal`
        breaking ties, looping until the remainder is gone or every order is
        satisfied." and "each tier-3 order has weight 1."

        Design: Difficulty/combinatorial_formula/allocation_floor_then_remainder_distribution
        """
        ctx, run, spots = self._setup_curtailed_with_three_spot_orders()
        resp = api_client.compute_allocation_run(run["id"], SUPPLY_PLANNER)
        computed = validate_success(resp, expected_status=200)
        assert_allocation_run(computed)
        assert computed["status"] == "COMPUTED"
        # Pool snapshot: 400000 - 50000 floor - 250000 reserved = 100000.
        assert computed["pool_gal"] == 100_000, (
            f"ATP at compute time is the pool; got {computed['pool_gal']}")

        # Three equal-weight tier-3 shares: floor(100000/3)=33333 each, and
        # the one-gallon remainder goes to the oldest created_at.
        by_id = {row["order_id"]: row for row in computed["results"]}
        assert by_id[spots[0]["id"]]["allocated_gal"] == 33_334
        assert by_id[spots[1]["id"]]["allocated_gal"] == 33_333
        assert by_id[spots[2]["id"]]["allocated_gal"] == 33_333

    def test_allocation_ratify_applies_shares(self):
        """PRD section 3.7: "Ratifying a `COMPUTED` run — attempting it in any
        other state is `ERR_RUN_NOT_COMPUTED` — applies the results: each order
        with a positive share moves from `REQUESTED` to `ALLOCATED` with
        `allocated_gal` set to the share and a provisional stamped, and each
        zero-share order moves to `SHORTED` with `allocated_gal` 0 and
        `provisional_total_cents` null. The run becomes `RATIFIED`, a terminal
        state."

        Design: Difficulty/combinatorial_formula/allocation_floor_then_remainder_distribution
        """
        ctx, run, spots = self._setup_curtailed_with_three_spot_orders()
        api_client.compute_allocation_run(run["id"], SUPPLY_PLANNER)
        resp = api_client.ratify_allocation_run(run["id"], SUPPLY_PLANNER)
        ratified = validate_success(resp, expected_status=200)
        assert ratified["status"] == "RATIFIED"

        expected = [33_334, 33_333, 33_333]
        for spot, share in zip(spots, expected):
            after = get_success_data(api_client.get_delivery_order(
                spot["id"], SUPPLY_PLANNER))
            assert after["fulfillment_status"] == "ALLOCATED"
            assert after["allocated_gal"] == share, (
                f"partial allocation applies the floored share; got "
                f"{after['allocated_gal']} for {spot['id']}")
            assert after["allocated_gal"] < after["requested_gal"]


class TestOpsEpoch:

    def test_ops_epoch_advances_all_sweeps(self):
        """PRD section 3.9: "The epoch activates each `DECLARED` cold-snap
        event whose `start_date` is today or in the past, firing the full
        curtail cascade per section 3.7. It lifts each `ACTIVE` event whose
        `end_date` has passed, firing the full lift cascade including the FIFO
        requeue. It expires each `ACTIVE` dealer contract whose `window_end`
        has passed. It settles each `ACTIVE` supply contract whose
        `receipt_window_end` has passed: to `COMPLETED` if the delivered volume
        reached the contracted volume, otherwise to `DEFAULTED`, with its
        `TENDERED` and `IN_TRANSIT` shipments cancelled (`ARRIVED` shipments
        are unaffected and may still unload). Finally, every terminal's
        `ops_epoch` increments by one, bumping `Terminal.version`."

        Design: Corner/endpoints/ops_epoch_advances_all_sweeps
        """
        set_clock("2026-08-01T00:00:00Z")
        term = create_terminal(name="T-N2")
        # Supply contract whose receipt window already ended, delivered 0.
        contract = create_supply_contract(
            term["id"], receipt_window_start="2026-06-01",
            receipt_window_end="2026-07-31")
        api_client.activate_supply_contract(contract["id"], SUPPLY_ADMIN)
        ship = tender_shipment(contract["id"], volume_gal=100_000,
                               railcar_count=5,
                               scheduled_arrival_date="2026-07-15")
        # Dealer contract already past its window.
        dealer = create_dealer(legal_name="Dealer N2")
        dcontract = create_dealer_contract(
            dealer["id"], term["id"], window_start="2026-06-01",
            window_end="2026-07-31")
        activate_dealer_contract(dcontract["id"], dealer["id"])
        # Cold snap whose start_date is today.
        snap = declare_cold_snap(term["id"], severity="WATCH",
                                 start_date="2026-08-01", end_date="2026-08-20")

        resp = api_client.run_epoch(SYSTEM_ADMIN)
        report = validate_success(resp, expected_status=200)
        assert report["cold_snaps_activated"] == 1
        assert report["cold_snaps_lifted"] == 0
        assert report["dealer_contracts_expired"] == 1
        assert report["supply_contracts_defaulted"] == 1
        assert report["supply_contracts_completed"] == 0
        assert report["shipments_cancelled"] == 1

        snap_after = get_success_data(api_client.get_cold_snap_event(
            snap["id"], SUPPLY_PLANNER))
        assert snap_after["status"] == "ACTIVE"
        term_after = get_success_data(api_client.get_terminal(term["id"],
                                                              SUPPLY_PLANNER))
        assert term_after["allocation_posture"] == "CURTAILED", \
            "the curtail cascade fired inside the epoch"
        assert term_after["ops_epoch"] == 1

        dcontract_after = get_success_data(api_client.get_dealer_contract(
            dcontract["id"], CREDIT_MANAGER))
        assert dcontract_after["status"] == "EXPIRED"

        contract_after = get_success_data(api_client.get_supply_contract(
            contract["id"], SUPPLY_PLANNER))
        assert contract_after["status"] == "DEFAULTED", \
            "the window ended with 0 of 600000 gallons delivered"

        ship_after = get_success_data(api_client.get_rail_shipment(
            ship["id"], SUPPLY_PLANNER))
        assert ship_after["status"] == "CANCELLED", \
            "the still-TENDERED shipment is cancelled with the default"
