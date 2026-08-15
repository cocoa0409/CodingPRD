"""Outbound orders: lifecycle cycles, OCC amend, credit gate, tier pricing,
quality gating, allocation release bubble-up, and count conservation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    allocate_order,
    assert_order,
    complete_receipt,
    confirm_excursion,
    create_allocated_order,
    create_customer_with_card,
    create_order,
    create_submitted_order,
    create_zone,
    get_lot,
    get_open_invoice,
    get_order,
    get_pallet,
    get_zone,
    list_lot_pallets,
    list_order_allocations,
    make_customer_admin_headers,
    receive_stock,
    release_allocation,
    release_quarantine,
    report_excursion,
    schedule_receipt,
    arrive_receipt,
    setup_stocked_account,
    ship_order,
    submit_order,
    validate_error,
    validate_success,
)

OPERATOR = TEST_USERS["warehouse_operator_headers"]


class TestCancelledOrderLockdown:
    def test_cancelled_order_rejects_all_actions(self, api):
        """PRD §2.9: "State validity, applied to all action endpoints: the target
        resource must stand in a valid from-state for the requested transition,
        including terminal-state lockdown, and any OCC expectation on the request
        must match; an invalid from-state is rejected `ERR_INVALID_STATE`, while
        a stale OCC expectation is rejected `ERR_STALE_VERSION`."
        PRD §3.5: "Cancellation, by the owning `CustomerAdmin`, is available from
        `DRAFT`, `SUBMITTED`, `SHORTED`, or `ALLOCATED` and moves the order to
        `CANCELLED`."

        Design: Corner/state_machines/cancelled_order_terminal_lockdown
        """
        customer, _card = create_customer_with_card("Term Co")
        order = create_order(customer["id"], requested_pallets=1)
        headers = make_customer_admin_headers(customer["id"])
        validate_success(api.cancel_outbound_order(order["id"], headers))

        submit_resp = api.submit_outbound_order(order["id"], headers)
        validate_error(submit_resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        ship_resp = api.ship_outbound_order(order["id"], OPERATOR)
        validate_error(ship_resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        cancel_resp = api.cancel_outbound_order(order["id"], headers)
        validate_error(cancel_resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestOrderAmendOcc:
    def test_stale_amend_rejected_current_version_succeeds(self, api):
        """PRD §2.7: "Amending an outbound order releases its allocations and
        re-prices its estimate, so an amend request must carry
        `expected_order_version`, holding the client's last observed `version` of
        that OutboundOrder. A mismatch with the order's current `version` is
        rejected with `ERR_STALE_VERSION` (HTTP 412), because a previously
        accepted amend has already changed the requested quantity and the
        allocation set the caller observed."

        Design: Corner/complexity_layers/occ_order_amend_stale_version_rejected
        """
        customer, _card = create_customer_with_card("Occ2 Co")
        order = create_order(customer["id"], requested_pallets=5)
        headers = make_customer_admin_headers(customer["id"])
        created_version = order["version"]

        stale = api.amend_outbound_order(
            order["id"],
            {"requested_pallets": 4, "expected_order_version": created_version - 1},
            headers)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
        assert get_order(order["id"])["requested_pallets"] == 5, (
            "stale amend changes nothing")

        amended = validate_success(
            api.amend_outbound_order(
                order["id"],
                {"requested_pallets": 4,
                 "expected_order_version": created_version},
                headers))
        assert amended["requested_pallets"] == 4
        assert amended["version"] == created_version + 1, (
            "a successful amend increments the order version by one")

        replayed = api.amend_outbound_order(
            order["id"],
            {"requested_pallets": 3, "expected_order_version": created_version},
            headers)
        validate_error(replayed, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


class TestOrderShortedAmendCycle:
    def _setup_shorted_order(self):
        """Order for 3 against exactly 2 pallets -> SHORTED with 2 allocated."""
        sc = setup_stocked_account(customer_name="Cycle Co", zone_code="FZ-7",
                                   pallets=2)
        order = create_submitted_order(sc["customer"]["id"], 3)
        allocate_order(order["id"])
        return sc, order

    def test_partial_fill_shorts_the_order(self, api):
        """PRD §3.5: "When the fill is complete, meaning `allocated_pallets` now
        equals `requested_pallets`, the order advances to `ALLOCATED`; a partial
        or empty fill leaves it at `SHORTED`."

        Design: Difficulty/non_linear_state_machine/order_submit_shorted_draft_allocate_cycle
        """
        _sc, order = self._setup_shorted_order()
        after = get_order(order["id"])
        assert after["status"] == "SHORTED"
        assert after["allocated_pallets"] == 2, (
            "partial fill: 2 of 3 requested pallets allocated")

    def test_amend_releases_then_reallocate_allocates(self, api):
        """PRD §3.5: "Amendment releases every `ACTIVE` allocation on the order —
        each pallet returning `ALLOCATED` → `STORED`, each allocation moving to
        `RELEASED` — replaces `requested_pallets`, recomputes the estimate,
        re-runs the credit check (`ERR_CREDIT_LIMIT_EXCEEDED`), and increments the
        order's `version` by one. A `SHORTED` order returns to `DRAFT`; a `DRAFT`
        order remains `DRAFT`."

        Design: Difficulty/non_linear_state_machine/order_submit_shorted_draft_allocate_cycle
        """
        sc, order = self._setup_shorted_order()
        customer_id = sc["customer"]["id"]
        headers = make_customer_admin_headers(customer_id)
        version = get_order(order["id"])["version"]

        amended = validate_success(
            api.amend_outbound_order(
                order["id"],
                {"requested_pallets": 2, "expected_order_version": version},
                headers))
        assert amended["status"] == "DRAFT", "SHORTED returns to DRAFT on amend"
        assert amended["allocated_pallets"] == 0, "all allocations released"

        submit_order(order["id"], customer_id)
        allocate_order(order["id"])
        final = get_order(order["id"])
        assert final["status"] == "ALLOCATED"
        assert final["allocated_pallets"] == 2


class TestHandlingOutTierDivergence:
    def _setup_tier_crossing(self):
        """order1 (100) submitted first; order2 (400) ships before order1 does."""
        sc = setup_stocked_account(customer_name="Vol Co", zone_code="FZ-3",
                                   capacity_pallets=600, pallets=500)
        customer_id = sc["customer"]["id"]
        order1 = create_submitted_order(customer_id, 100)
        order2 = create_submitted_order(customer_id, 400)
        allocate_order(order2["id"])
        ship_order(order2["id"])
        return sc, order1, order2

    def test_estimate_uses_submit_time_volume_tier(self, api):
        """PRD §3.5: "The volume figure is the count of pallets this customer has
        `SHIPPED` with an `out_at` falling inside the calendar month of now, plus
        this order's own quantity — `requested_pallets` when estimating at submit
        or amend, `allocated_pallets` when fixing the final fee at ship. A volume
        reaching five hundred pallets earns a twenty percent discount; reaching
        one hundred earns ten percent; below that, none."

        Design: Difficulty/dual_variant_calc/handling_out_estimate_vs_final_diverge_on_tier_crossing
        """
        _sc, order1, order2 = self._setup_tier_crossing()
        # At submit, shipped volume was 0: 0 + 100 = 100 -> 10% tier.
        o1 = get_order(order1["id"])
        assert o1["estimated_handling_out_cents"] == 45000, (
            f"round_half_up(100 * 500 * 0.9) == 45000, got "
            f"{o1['estimated_handling_out_cents']}")
        # order2's final fee: ship-month volume 0 + 400 -> 10% tier.
        o2 = get_order(order2["id"])
        assert o2["final_handling_out_cents"] == 180000, (
            f"400 * 500 * 0.9 == 180000, got {o2['final_handling_out_cents']}")

    def test_final_fee_diverges_after_tier_crossing(self, api):
        """PRD §3.5: "The estimate stored at submit or amend uses the current
        month's shipped volume and is provisional; the final fee computed at ship
        uses the ship month's shipped volume, so the two diverge whenever
        cumulative volume crosses a tier boundary between submission and
        shipment."

        Design: Difficulty/dual_variant_calc/handling_out_estimate_vs_final_diverge_on_tier_crossing
        """
        _sc, order1, _order2 = self._setup_tier_crossing()
        allocate_order(order1["id"])
        ship_order(order1["id"])
        o1 = get_order(order1["id"])
        # At ship: 400 already shipped this month + 100 allocated = 500 -> 20%.
        assert o1["final_handling_out_cents"] == 40000, (
            f"round_half_up(100 * 500 * 0.8) == 40000, got "
            f"{o1['final_handling_out_cents']}")
        assert o1["estimated_handling_out_cents"] == 45000
        assert o1["final_handling_out_cents"] != o1["estimated_handling_out_cents"], (
            "the two variants diverge across the tier boundary")


class TestCreditCheckEvaluationOrder:
    def _setup_credit_scenario(self):
        """55-pallet receipt accrues 55000 handling_in; credit limit is 100000."""
        customer, _card = create_customer_with_card("Credit Co",
                                                    credit_limit_cents=100000)
        zone = create_zone("FZ-5", capacity_pallets=100, dock_doors=2)
        receive_stock(customer["id"], zone["id"], 55, lot_code="KL1")
        return customer

    def test_estimate_equal_to_remaining_credit_passes(self, api):
        """PRD §3.5: "the order is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` if
        and only if the customer's `outstanding_balance_cents` plus the estimated
        fee is strictly greater than `credit_limit_cents`; a sum exactly equal to
        the limit passes."

        Design: Difficulty/combinatorial_formula/credit_check_forward_tier_evaluation_order
        """
        customer = self._setup_credit_scenario()
        # outstanding 55000 + estimate 100*500*0.9 = 45000 -> exactly 100000.
        order = create_order(customer["id"], requested_pallets=100)
        submitted = submit_order(order["id"], customer["id"])
        assert submitted["status"] == "SUBMITTED", "equality passes the credit check"
        assert submitted["estimated_handling_out_cents"] == 45000, (
            "the order counts toward its own volume tier: 0 + 100 >= 100 -> 10%")

    def test_one_pallet_over_the_limit_rejected(self, api):
        """PRD §3.5: "the order is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` if
        and only if the customer's `outstanding_balance_cents` plus the estimated
        fee is strictly greater than `credit_limit_cents`; a sum exactly equal to
        the limit passes."

        Design: Difficulty/combinatorial_formula/credit_check_forward_tier_evaluation_order
        """
        customer = self._setup_credit_scenario()
        # outstanding 55000 + estimate 101*500*0.9 = 45450 -> 100450 > 100000.
        order = create_order(customer["id"], requested_pallets=101)
        resp = api.submit_outbound_order(
            order["id"], make_customer_admin_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED,
                       expected_status=409)
        assert get_order(order["id"])["status"] == "DRAFT", (
            "rejected submission leaves the order DRAFT")


class TestAuthorizationBeatsState:
    def test_owner_cannot_call_operator_allocate(self, api):
        """PRD §2.9: "A request that would fail at several tiers is rejected with
        the error belonging to the earliest applicable tier, so that a failure
        deeper in the cascade never masks one nearer the surface."
        PRD §2.9: "Role authorization, applied to all endpoints: the caller's role
        is listed among the endpoint's authorized roles; otherwise
        `ERR_FORBIDDEN`."
        PRD §4: "POST `/api/outbound-orders/{id}/allocate` ... WarehouseOperator".

        Design: Difficulty/priority_pair_validation_conflict/authorization_beats_state_on_allocate
        """
        customer, _card = create_customer_with_card("Authz Co")
        order = create_order(customer["id"], requested_pallets=1)
        # The DRAFT order is not allocatable (state tier 6) AND the caller's role
        # is wrong (tier 3): the earlier tier wins.
        resp = api.allocate_outbound_order(
            order["id"], make_customer_admin_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_forbidden_allocate_leaves_order_untouched(self, api):
        """PRD §2.9: "Role authorization, applied to all endpoints: the caller's
        role is listed among the endpoint's authorized roles; otherwise
        `ERR_FORBIDDEN`."

        Design: Difficulty/priority_pair_validation_conflict/authorization_beats_state_on_allocate
        """
        customer, _card = create_customer_with_card("Authz Co")
        order = create_order(customer["id"], requested_pallets=1)
        resp = api.allocate_outbound_order(
            order["id"], make_customer_admin_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = get_order(order["id"])
        assert after["status"] == "DRAFT"
        assert after["allocated_pallets"] == 0


class TestAllocationGatedByPalletQuality:
    def _setup_quarantined_stock_and_order(self):
        sc = setup_stocked_account(customer_name="Gate Co", zone_code="FZ-17",
                                   pallets=2)
        excursion = report_excursion(sc["zone"]["id"], observed_temp_c=-3.0)
        confirm_excursion(excursion["id"])
        order = create_submitted_order(sc["customer"]["id"], 2)
        return sc, order

    def test_quarantined_stock_shorts_the_order(self, api):
        """PRD §3.3: "Neither dimension implies the other, and guards reference
        both — allocation and blast-freeze selection, for instance, each demand a
        pallet that is simultaneously `STORED` and `OK`."
        PRD §3.5: "When the fill is complete, meaning `allocated_pallets` now
        equals `requested_pallets`, the order advances to `ALLOCATED`; a partial
        or empty fill leaves it at `SHORTED`."

        Design: Difficulty/cross_entity_state_dependency/order_allocation_gated_by_pallet_quality
        """
        _sc, order = self._setup_quarantined_stock_and_order()
        allocate_order(order["id"])
        after = get_order(order["id"])
        assert after["status"] == "SHORTED"
        assert after["allocated_pallets"] == 0, (
            "QUARANTINED pallets fail the quality == OK candidate guard")

    def test_release_quarantine_unblocks_allocation(self, api):
        """PRD §3.3: "Releasing a quarantined pallet returns its `quality` from
        `QUARANTINED` to `OK` and recomputes the parent lot's status."
        PRD §3.5: "From `SHORTED`, a later allocation run after more stock arrives
        tops the order up: a full fill advances it to `ALLOCATED`, while a
        still-short fill leaves it at `SHORTED`."

        Design: Difficulty/cross_entity_state_dependency/order_allocation_gated_by_pallet_quality
        """
        sc, order = self._setup_quarantined_stock_and_order()
        allocate_order(order["id"])
        assert get_order(order["id"])["status"] == "SHORTED"
        for pallet in list_lot_pallets(sc["lot_id"]):
            release_quarantine(pallet["id"])
        allocate_order(order["id"])
        after = get_order(order["id"])
        assert after["status"] == "ALLOCATED"
        assert after["allocated_pallets"] == 2


class TestManualAllocationRelease:
    def _setup_allocated_pair(self):
        sc = setup_stocked_account(customer_name="Rel Co", zone_code="FZ-11",
                                   pallets=2)
        order = create_allocated_order(sc["customer"]["id"], 2)
        allocation = list_order_allocations(order["id"])[0]
        return sc, order, allocation

    def test_release_returns_pallet_and_demotes_order(self, api):
        """PRD §3.5: "A `WarehouseOperator` releasing an `ACTIVE` allocation moves
        it to `RELEASED`, returns the pallet `ALLOCATED` → `STORED`, demotes the
        owning order from `ALLOCATED` back to `SUBMITTED` — an order at `SHORTED`
        stays `SHORTED` — and recomputes `allocated_pallets`, which is always the
        count of `ACTIVE` allocations on the order."

        Design: Difficulty/transitive_cascade/manual_allocation_release_bubble_up
        """
        _sc, order, allocation = self._setup_allocated_pair()
        released = release_allocation(allocation["id"])
        assert released["status"] == "RELEASED"
        pallet = get_pallet(allocation["pallet_id"])
        assert pallet["status"] == "STORED", "released pallet returns to STORED"
        after = get_order(order["id"])
        assert after["status"] == "SUBMITTED", "order demoted ALLOCATED -> SUBMITTED"
        assert after["allocated_pallets"] == 1

    def test_reallocate_recovers_full_fill(self, api):
        """PRD §3.5: "The selector takes from the front of that ordering as many
        pallets as are needed to close the gap between `requested_pallets` and the
        order's current `allocated_pallets`."
        PRD §3.3: "Failing all of those, the lot is `AVAILABLE`."

        Design: Difficulty/transitive_cascade/manual_allocation_release_bubble_up
        """
        sc, order, allocation = self._setup_allocated_pair()
        release_allocation(allocation["id"])
        allocate_order(order["id"])
        after = get_order(order["id"])
        assert after["status"] == "ALLOCATED"
        assert after["allocated_pallets"] == 2, "top-up closes the gap"
        lot = get_lot(sc["lot_id"])
        assert lot["status"] == "AVAILABLE", "quality untouched throughout"


class TestAllocateAmendConservation:
    def _setup_shorted_for_amend(self):
        """Order for 4 against exactly 3 pallets -> SHORTED with 3 allocated,
        so the compensating amend is legal (amend requires DRAFT or SHORTED)."""
        sc = setup_stocked_account(customer_name="Inv Co", zone_code="FZ-23",
                                   pallets=3)
        order = create_submitted_order(sc["customer"]["id"], 4)
        return sc, order

    def test_allocation_does_not_move_physical_counts(self, api):
        """PRD §2.8: "`in_use_pallets` counts the pallets physically present in
        the zone — those whose custody status is `STORED`, `IN_BLAST_FREEZE`, or
        `ALLOCATED`; pallets that have shipped or been dispositioned no longer
        count."

        Design: Difficulty/compensating_invariant/allocate_then_amend_conserves_pallet_counts
        """
        sc, order = self._setup_shorted_for_amend()
        allocate_order(order["id"])
        after = get_order(order["id"])
        assert after["status"] == "SHORTED" and after["allocated_pallets"] == 3
        zone = get_zone(sc["zone"]["id"])
        assert zone["in_use_pallets"] == 3, "ALLOCATED pallets remain physically present"
        assert zone["free_pallets"] == 7
        assert get_lot(sc["lot_id"])["on_hand_pallets"] == 3

    def test_amend_releases_allocations_conserving_counts(self, api):
        """PRD §3.5: "Amendment releases every `ACTIVE` allocation on the order —
        each pallet returning `ALLOCATED` → `STORED`, each allocation moving to
        `RELEASED` — replaces `requested_pallets`, recomputes the estimate,
        re-runs the credit check (`ERR_CREDIT_LIMIT_EXCEEDED`), and increments the
        order's `version` by one. A `SHORTED` order returns to `DRAFT`; a `DRAFT`
        order remains `DRAFT`."

        Design: Difficulty/compensating_invariant/allocate_then_amend_conserves_pallet_counts
        """
        sc, order = self._setup_shorted_for_amend()
        allocate_order(order["id"])
        version = get_order(order["id"])["version"]
        amended = validate_success(
            api.amend_outbound_order(
                order["id"],
                {"requested_pallets": 1, "expected_order_version": version},
                make_customer_admin_headers(sc["customer"]["id"])))
        assert amended["status"] == "DRAFT"
        assert amended["allocated_pallets"] == 0
        zone = get_zone(sc["zone"]["id"])
        assert zone["in_use_pallets"] == 3, "pallet counts conserved across amend"
        assert zone["free_pallets"] == 7
        assert get_lot(sc["lot_id"])["on_hand_pallets"] == 3
