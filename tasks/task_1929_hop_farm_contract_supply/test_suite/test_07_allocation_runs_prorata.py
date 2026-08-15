"""Allocation runs: the pro-rata waterfall, its invariants, and supersede."""
from test_helpers import (
    validate_success, validate_paginated,
    setup_harvesting_plan_with_kiln, create_dried_lot, create_pellet_lot,
    create_active_contract, run_allocation, find_allocation,
    assert_allocation_volume_invariants, TEST_USERS,
)

CM = TEST_USERS["contract_manager_headers"]


def _setup_single_lot_inventory(dried_lbs, wet_lbs):
    """One pellet lot from a single source of the given dried weight."""
    ctx = setup_harvesting_plan_with_kiln()
    lot = create_dried_lot(ctx["plan"]["id"], ctx["kiln"]["id"],
                           wet_lbs=wet_lbs, dried_lbs=dried_lbs)
    pellet = create_pellet_lot([lot["id"]])
    return ctx, pellet


def _two_active_contracts(volume_a, brewery_a, volume_b, brewery_b):
    """Two ACTIVE CASCADE 2026-2028 contracts; the first created is brewery_a."""
    contract_a = create_active_contract(
        brewery_name=brewery_a, annual_volume_lbs=volume_a)
    contract_b = create_active_contract(
        brewery_name=brewery_b, annual_volume_lbs=volume_b)
    return contract_a, contract_b


class TestExactSupplyBoundary:
    def test_run_at_exact_supply_reports_totals(self, api):
        """PRD §3.6: "When the available total meets or exceeds the contracted
        total, every contract is allocated its full `annual_volume_lbs` with a
        `shortfall_lbs` of 0." Available 2300 == contracted 2300.

        Design: Difficulty/boundary_precision_check/allocation_run_exact_supply_no_shortfall
        """
        ctx, pellet = _setup_single_lot_inventory(dried_lbs=2500, wet_lbs=9375)
        assert pellet["qty_lbs"] == 2300
        contract_a, contract_b = _two_active_contracts(1000, "BrewA", 1300, "BrewB")
        run = run_allocation(crop_year=2026, variety="CASCADE")
        assert run["available_lbs"] == 2300
        assert run["contracted_total_lbs"] == 2300
        alloc_a = find_allocation(contract_id=contract_a["id"], crop_year=2026)
        assert alloc_a["allocated_lbs"] == 1000
        assert alloc_a["shortfall_lbs"] == 0

    def test_run_at_exact_supply_fills_every_contract(self, api):
        """PRD §3.6: "When the available total meets or exceeds the contracted
        total, every contract is allocated its full `annual_volume_lbs` with a
        `shortfall_lbs` of 0." and "the total allocated across contracts equals
        the smaller of the available and contracted totals."

        Design: Difficulty/boundary_precision_check/allocation_run_exact_supply_no_shortfall
        """
        ctx, pellet = _setup_single_lot_inventory(dried_lbs=2500, wet_lbs=9375)
        contract_a, contract_b = _two_active_contracts(1000, "BrewA", 1300, "BrewB")
        run_allocation(crop_year=2026, variety="CASCADE")
        alloc_b = find_allocation(contract_id=contract_b["id"], crop_year=2026)
        assert alloc_b["allocated_lbs"] == 1300
        assert alloc_b["shortfall_lbs"] == 0
        alloc_a = find_allocation(contract_id=contract_a["id"], crop_year=2026)
        assert alloc_a["allocated_lbs"] + alloc_b["allocated_lbs"] == 2300


class TestRemainderTiebreak:
    def test_equal_fractions_tiebreak_by_earlier_created(self, api):
        """PRD §3.6: "the leftover pounds — the available total minus the sum of
        the base allocations — are then distributed one pound at a time to
        contracts in descending order of fractional part, ties broken in favor of
        the contract created earlier, until no pounds remain." Available 1001
        across two 1000-lb contracts: exact shares 500.5 each; the single
        leftover pound goes to the first-created contract.

        Design: Corner/calculations/prorata_tiebreak_by_created_at
        """
        ctx, pellet = _setup_single_lot_inventory(dried_lbs=1088, wet_lbs=4080)
        assert pellet["qty_lbs"] == 1001
        contract_a, contract_b = _two_active_contracts(1000, "BrewA", 1000, "BrewB")
        run_allocation(crop_year=2026, variety="CASCADE")
        alloc_a = find_allocation(contract_id=contract_a["id"], crop_year=2026)
        alloc_b = find_allocation(contract_id=contract_b["id"], crop_year=2026)
        assert alloc_a["allocated_lbs"] == 501
        assert alloc_a["shortfall_lbs"] == 499
        assert alloc_b["allocated_lbs"] == 500
        assert alloc_b["shortfall_lbs"] == 500


class TestVolumeConservation:
    def test_prorata_base_shares_floored(self, api):
        """PRD §3.6: "each contract's exact share is the available total
        multiplied by its `annual_volume_lbs` and divided by the contracted
        total; its base allocation is that exact share rounded down to a whole
        pound". Available 3000 across volumes 1000 and 3000 (total 4000): exact
        shares 750.0 and 2250.0 with no remainder pounds.

        Design: Difficulty/compensating_invariant/prorata_allocation_conserves_volume
        """
        ctx, pellet = _setup_single_lot_inventory(dried_lbs=3261, wet_lbs=12229)
        assert pellet["qty_lbs"] == 3000
        contract_a, contract_b = _two_active_contracts(1000, "BrewA", 3000, "BrewB")
        run_allocation(crop_year=2026, variety="CASCADE")
        alloc_a = find_allocation(contract_id=contract_a["id"], crop_year=2026)
        alloc_b = find_allocation(contract_id=contract_b["id"], crop_year=2026)
        assert alloc_a["allocated_lbs"] == 750
        assert alloc_a["shortfall_lbs"] == 250
        assert alloc_b["allocated_lbs"] == 2250
        assert alloc_b["shortfall_lbs"] == 750

    def test_prorata_invariants_hold(self, api):
        """PRD §3.6: "Two invariants hold at the end of every run: for each
        contract, allocated plus shortfall equals its annual volume; and the
        total allocated across contracts equals the smaller of the available and
        contracted totals."

        Design: Difficulty/compensating_invariant/prorata_allocation_conserves_volume
        """
        ctx, pellet = _setup_single_lot_inventory(dried_lbs=3261, wet_lbs=12229)
        contract_a, contract_b = _two_active_contracts(1000, "BrewA", 3000, "BrewB")
        run_allocation(crop_year=2026, variety="CASCADE")
        alloc_a = find_allocation(contract_id=contract_a["id"], crop_year=2026)
        alloc_b = find_allocation(contract_id=contract_b["id"], crop_year=2026)
        assert_allocation_volume_invariants(alloc_a, 1000)
        assert_allocation_volume_invariants(alloc_b, 3000)
        total_allocated = alloc_a["allocated_lbs"] + alloc_b["allocated_lbs"]
        assert total_allocated == min(3000, 4000)


class TestRunSupersede:
    def test_second_run_supersedes_projected(self, api, contract_manager_headers):
        """PRD §3.6: "A rerun supersedes its own projections. Before computing
        anything, any existing `PROJECTED` allocations for the same pair move to
        `CANCELLED`; allocations in `CONFIRMED`, `DELIVERED`, or `SETTLED` are
        untouched, and their contracts are excluded from the new run's input set
        precisely because they already hold a live allocation for the year."

        Design: Corner/calculations/allocation_run_supersedes_projected
        """
        contract = create_active_contract(annual_volume_lbs=1000)
        run_allocation(crop_year=2026, variety="CASCADE")
        first = find_allocation(contract_id=contract["id"], crop_year=2026)

        run_allocation(crop_year=2026, variety="CASCADE")
        first_after = validate_success(
            api.get_allocation(first["id"], contract_manager_headers), 200)
        assert first_after["status"] == "CANCELLED", "the rerun supersedes it"

        data, meta = validate_paginated(api.list_allocations(
            contract_manager_headers,
            params={"contract_id": contract["id"], "status": "PROJECTED"}))
        assert len(data) == 1, "exactly one fresh PROJECTED allocation exists"
        assert data[0]["id"] != first["id"], "the fresh row has a new id"
