"""Allocation lifecycle: confirm gating, FIFO reservation, cancel/deliver rules."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    setup_harvesting_plan_with_kiln, create_dried_lot, create_pellet_lot,
    create_active_contract, run_allocation, find_allocation, confirm_allocation,
    setup_settled_allocation, TEST_USERS,
)

CM = TEST_USERS["contract_manager_headers"]
FM = TEST_USERS["farm_manager_headers"]


class TestConfirmRequiresActiveContract:
    def test_confirm_rejected_while_contract_suspended(self, api,
                                                       contract_manager_headers):
        """PRD §3.6: "Confirming an allocation moves it from `PROJECTED` to
        `CONFIRMED` and is gated on the contract being `ACTIVE`, otherwise
        `ERR_CONTRACT_NOT_ACTIVE` — this is where a suspension bites."

        Design: Difficulty/cross_entity_state_dependency/allocation_confirm_requires_contract_active
        """
        contract = create_active_contract(annual_volume_lbs=736)
        run_allocation(crop_year=2026, variety="CASCADE")
        allocation = find_allocation(contract_id=contract["id"], crop_year=2026)
        validate_success(api.suspend_contract(contract["id"], contract_manager_headers), 200)
        res = api.confirm_allocation(allocation["id"], contract_manager_headers)
        validate_error(res, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)

    def test_suspension_non_destructive_and_reinstate_restores_confirm(
            self, api, contract_manager_headers):
        """PRD §3.5: "Suspension moves an `ACTIVE` contract to `SUSPENDED`, and
        it is deliberately non-destructive: no allocation changes state, but
        while a contract is suspended, confirming or delivering its allocations
        is rejected with `ERR_CONTRACT_NOT_ACTIVE`. Reinstatement moves
        `SUSPENDED` back to `ACTIVE`, and the suspend–reinstate loop may repeat
        as often as negotiations require."

        Design: Difficulty/cross_entity_state_dependency/allocation_confirm_requires_contract_active
        """
        contract = create_active_contract(annual_volume_lbs=736)
        run_allocation(crop_year=2026, variety="CASCADE")
        allocation = find_allocation(contract_id=contract["id"], crop_year=2026)
        validate_success(api.suspend_contract(contract["id"], contract_manager_headers), 200)
        validate_error(api.confirm_allocation(allocation["id"], contract_manager_headers),
                       ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)
        untouched = validate_success(
            api.get_allocation(allocation["id"], contract_manager_headers), 200)
        assert untouched["status"] == "PROJECTED", (
            "a failed confirm leaves the allocation untouched")
        validate_success(api.reinstate_contract(contract["id"], contract_manager_headers), 200)
        confirmed = validate_success(
            api.confirm_allocation(allocation["id"], contract_manager_headers), 200)
        assert confirmed["status"] == "CONFIRMED"


class TestConfirmCancelRestoresInventory:
    def _setup_two_lot_confirmed_allocation(self, api):
        """Pellet lots of 920 and 736 lbs; contract for 2000 lbs so the run
        allocates the full available 1656 with shortfall 344."""
        ctx = setup_harvesting_plan_with_kiln()
        lot1 = create_dried_lot(ctx["plan"]["id"], ctx["kiln"]["id"],
                                wet_lbs=3750, dried_lbs=1000)
        lot2 = create_dried_lot(ctx["plan"]["id"], ctx["kiln"]["id"],
                                wet_lbs=3000, dried_lbs=800,
                                window_start="2026-08-20T12:30:00Z",
                                window_end="2026-08-20T16:00:00Z")
        pellet1 = create_pellet_lot([lot1["id"]], storage_room="R1")
        pellet2 = create_pellet_lot([lot2["id"]], storage_room="R1")
        contract = create_active_contract(annual_volume_lbs=2000)
        run_allocation(crop_year=2026, variety="CASCADE")
        allocation = find_allocation(contract_id=contract["id"], crop_year=2026)
        assert allocation["allocated_lbs"] == 1656
        assert allocation["shortfall_lbs"] == 344
        return ctx, pellet1, pellet2, contract, allocation

    def test_confirm_fifo_reserves_both_lots(self, api, contract_manager_headers):
        """PRD §3.6: "the system walks the pellet lots of the contract's variety
        that are `AVAILABLE`, oldest first by `entered_storage_at` with ties
        broken by earlier `created_at`, and reserves a lot only when doing so
        does not push the cumulative reserved total above the allocation's
        `allocated_lbs`; it stops when the cumulative total reaches
        `allocated_lbs` or the pool is exhausted." 920 + 736 = 1656 fits exactly.

        Design: Difficulty/compensating_invariant/allocation_confirm_cancel_restores_inventory
        """
        ctx, pellet1, pellet2, contract, allocation = (
            self._setup_two_lot_confirmed_allocation(api))
        confirmed = validate_success(
            api.confirm_allocation(allocation["id"], contract_manager_headers), 200)
        assert set(confirmed["reserved_lot_ids"]) == {pellet1["id"], pellet2["id"]}
        for pellet in (pellet1, pellet2):
            after = validate_success(
                api.get_pellet_lot(pellet["id"], contract_manager_headers), 200)
            assert after["inventory_status"] == "RESERVED"
        _data, meta = validate_paginated(api.list_pellet_lots(
            contract_manager_headers, params={"inventory_status": "AVAILABLE"}))
        assert meta["total_count"] == 0, "both lots reserved, none AVAILABLE"

    def test_cancel_releases_reserved_lots_without_drift(self, api,
                                                         contract_manager_headers):
        """PRD §3.6: "Cancelling a confirmed allocation releases its reserved
        lots back to `AVAILABLE` and clears its `reserved_lot_ids`." The
        reserve/release round-trip conserves available inventory: 920 + 736 =
        1656 lbs before confirm and 1656 lbs after cancel.

        Design: Difficulty/compensating_invariant/allocation_confirm_cancel_restores_inventory
        """
        ctx, pellet1, pellet2, contract, allocation = (
            self._setup_two_lot_confirmed_allocation(api))
        before, meta_before = validate_paginated(api.list_pellet_lots(
            contract_manager_headers, params={"inventory_status": "AVAILABLE"}))
        available_before = sum(p["qty_lbs"] for p in before)
        assert available_before == 1656

        confirm_allocation(allocation["id"])
        cancelled = validate_success(
            api.cancel_allocation(allocation["id"], contract_manager_headers), 200)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["reserved_lot_ids"] == [], "reservation cleared"
        for pellet in (pellet1, pellet2):
            after = validate_success(
                api.get_pellet_lot(pellet["id"], contract_manager_headers), 200)
            assert after["inventory_status"] == "AVAILABLE"
        after_list, _meta = validate_paginated(api.list_pellet_lots(
            contract_manager_headers, params={"inventory_status": "AVAILABLE"}))
        assert sum(p["qty_lbs"] for p in after_list) == available_before


class TestDeliverGates:
    def test_empty_delivery_rejected(self, api, contract_manager_headers):
        """PRD §3.6: "Delivery moves a `CONFIRMED` allocation to `DELIVERED` and
        consumes the reservation. The `reserved_lot_ids` must be non-empty,
        otherwise the delivery is rejected with `ERR_EMPTY_DELIVERY`."

        Design: Corner/validations/empty_delivery_rejected
        """
        contract = create_active_contract(annual_volume_lbs=736)
        run_allocation(crop_year=2026, variety="CASCADE")
        allocation = find_allocation(contract_id=contract["id"], crop_year=2026)
        assert allocation["allocated_lbs"] == 0, "zero inventory allocates zero"
        confirmed = validate_success(
            api.confirm_allocation(allocation["id"], contract_manager_headers), 200)
        assert confirmed["reserved_lot_ids"] == []
        res = api.deliver_allocation(allocation["id"], contract_manager_headers)
        validate_error(res, ApiErrorId.ERR_EMPTY_DELIVERY)


class TestTerminalLockdown:
    def test_cancel_from_settled_rejected_and_settlement_intact(
            self, api, contract_manager_headers):
        """PRD §3.6: "An allocation may also be cancelled outright — by a
        `ContractManager`, or by the system during contract termination, default,
        completion, or an allocation-run supersede — moving it from `PROJECTED`
        or `CONFIRMED` to `CANCELLED`." SETTLED is not a cancellable from-state.
        PRD §2.8: "6. State-machine from-state — the target resource is in a
        state from which the requested transition exists, else
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/allocation_cancel_from_settled_returns_invalid_state
        """
        ctx = setup_settled_allocation(
            sources=[{"wet_lbs": 3000, "dried_lbs": 800, "final_alpha": 12.0}],
            contract_overrides={"annual_volume_lbs": 736})
        allocation = ctx["allocation"]
        assert allocation["status"] == "SETTLED"
        assert allocation["settlement_total_cents"] == 368000
        res = api.cancel_allocation(allocation["id"], contract_manager_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(
            api.get_allocation(allocation["id"], contract_manager_headers), 200)
        assert after["status"] == "SETTLED"
        assert after["settlement_total_cents"] == 368000, (
            "settlement fields survive the rejected cancel")
