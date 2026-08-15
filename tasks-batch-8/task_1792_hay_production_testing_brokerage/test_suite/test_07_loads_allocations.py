"""Delivery loads and allocations: parallel status dimensions, the three-hop
delivery cascade, the condemn cascade, tonnage conservation on release, and
the allocation guards.

Covers PRD §3.7 (loads, allocation, delivery cascade) and §3.5 (buyer
suspension cascade).
"""
from test_helpers import (
    TEST_USERS,
    api_client,
    allocate,
    assert_tonnage,
    create_delivery_load,
    drive_load_to_in_transit,
    get_allocation,
    get_buyer,
    get_contract,
    get_load,
    get_lot,
    setup_accepted_contract,
    setup_certified_lot,
    setup_load_with_allocation,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId

ADMIN = TEST_USERS["admin_headers"]
OPS = TEST_USERS["ops_headers"]


def _contract_and_certified_lot(tons=10.0, quality_tier="GOOD",
                                lot_tonnage=10.0, credit_limit_cents=1000000,
                                rfv=152.0, protein_pct=16.0,
                                moisture_pct=14.0):
    """Accepted contract plus a certified matching-tier lot. Returns (deal, inventory)."""
    deal = setup_accepted_contract(
        tons=tons, quality_tier=quality_tier, credit_limit_cents=credit_limit_cents,
    )
    inventory = setup_certified_lot(
        rfv=rfv, protein_pct=protein_pct, moisture_pct=moisture_pct,
        lot_tonnage=lot_tonnage,
    )
    return deal, inventory


# ===========================================================================
# non_linear_state_machine / delivery_load_parallel_settlement_dimensions
# ===========================================================================

class TestDeliveryLoadParallelSettlementDimensions:
    def _in_transit_load(self):
        deal, inventory = _contract_and_certified_lot(
            tons=5.0, lot_tonnage=8.0, rfv=155.0, protein_pct=17.0,
        )
        load, allocation = setup_load_with_allocation(
            deal["contract"]["id"], inventory["lot"]["id"], 5.0,
        )
        drive_load_to_in_transit(load["id"])
        return load, allocation

    def test_settle_rejected_while_in_transit(self, api):
        """PRD §3.7: "it requires the settlement dimension to be `OPEN` and
        the logistics dimension to be `DELIVERED`, with mismatches rejected
        as `ERR_LOAD_WRONG_STATE`."

        Settling while the load is IN_TRANSIT is rejected.

        Design: Difficulty/non_linear_state_machine/delivery_load_parallel_settlement_dimensions
        """
        load, _allocation = self._in_transit_load()
        resp = api_client.settle_load(load["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_LOAD_WRONG_STATE)
        read = get_load(load["id"])
        assert read["logistics_status"] == "IN_TRANSIT"
        assert read["settlement_status"] == "OPEN"

    def test_dimensions_independent_after_deliver(self, api):
        """PRD §3.7: "A load carries two parallel status dimensions that
        evolve independently: `logistics_status` runs `PLANNED` → `LOADING` →
        `IN_TRANSIT` → `DELIVERED`, while `settlement_status` runs `OPEN` →
        `SETTLED`; the only coupling is that settlement requires the load to
        have been delivered."

        After deliver the pair sits at DELIVERED x OPEN; after settle it sits
        at DELIVERED x SETTLED — settling does not touch logistics.

        Design: Difficulty/non_linear_state_machine/delivery_load_parallel_settlement_dimensions
        """
        load, _allocation = self._in_transit_load()
        delivered = validate_success(api_client.deliver_load(load["id"], OPS))
        assert delivered["logistics_status"] == "DELIVERED"
        assert delivered["settlement_status"] == "OPEN"
        settled = validate_success(api_client.settle_load(load["id"], OPS))
        assert settled["settlement_status"] == "SETTLED"
        assert settled["logistics_status"] == "DELIVERED"


# ===========================================================================
# transitive_cascade / deliver_fulfillment_credit_release_cascade
# ===========================================================================

class TestDeliverFulfillmentCreditReleaseCascade:
    def _delivered_setup(self):
        """PREMIUM 12.0t contract (total 439170) + 12.0t PREMIUM lot + load
        IN_TRANSIT with the full 12.0t allocated."""
        deal, inventory = _contract_and_certified_lot(
            tons=12.0, quality_tier="PREMIUM", lot_tonnage=12.0,
            credit_limit_cents=500000, rfv=175.0, protein_pct=18.0,
        )
        assert get_buyer(deal["buyer"]["id"])["credit_used_cents"] == 439170
        load, allocation = setup_load_with_allocation(
            deal["contract"]["id"], inventory["lot"]["id"], 12.0,
        )
        drive_load_to_in_transit(load["id"])
        validate_success(api_client.deliver_load(load["id"], OPS))
        return deal, inventory, load, allocation

    def test_deliver_flips_allocation_lot_and_contract(self, api):
        """PRD §3.7: "Hop one: every open allocation on the load becomes
        `DELIVERED`; for each, the lot's `shipped_tonnage` increases by the
        allocated tons, the contract's `delivered_tons` increases by the
        same". PRD §3.7: "Hop two: any contract whose `delivered_tons` now
        reaches or exceeds `committed_tons` transitions to `FULFILLED`, and
        any lot whose `allocatable_tonnage` has reached exactly 0.0 with
        `shipped_tonnage` greater than zero transitions to `DEPLETED`."

        Design: Difficulty/transitive_cascade/deliver_fulfillment_credit_release_cascade
        """
        deal, inventory, _load, allocation = self._delivered_setup()
        assert get_allocation(allocation["id"])["status"] == "DELIVERED"
        lot = get_lot(inventory["lot"]["id"])
        assert_tonnage(lot["shipped_tonnage"], 12.0, "shipped_tonnage")
        assert lot["status"] == "DEPLETED"
        contract = get_contract(deal["contract"]["id"])
        assert_tonnage(contract["delivered_tons"], 12.0, "delivered_tons")
        assert contract["status"] == "FULFILLED"

    def test_fulfillment_releases_credit_reserve(self, api):
        """PRD §3.7: "Hop three: each contract that fulfilled in hop two
        releases its credit reserve, subtracting `total_reserved_cents` from
        the buyer's `credit_used_cents`."

        The buyer's 439170-cent reserve drops to exactly 0 once the contract
        fulfills.

        Design: Difficulty/transitive_cascade/deliver_fulfillment_credit_release_cascade
        """
        deal, _inventory, _load, _allocation = self._delivered_setup()
        assert get_buyer(deal["buyer"]["id"])["credit_used_cents"] == 0


# ===========================================================================
# transitive_cascade / condemn_release_replan_cascade
# ===========================================================================

class TestCondemnReleaseReplanCascade:
    def _loading_setup(self):
        """GOOD 10.0t contract + 10.0t certified GOOD lot + LOADING load."""
        deal, inventory = _contract_and_certified_lot(tons=10.0, lot_tonnage=10.0)
        load, allocation = setup_load_with_allocation(
            deal["contract"]["id"], inventory["lot"]["id"], 10.0,
        )
        load = validate_success(api_client.start_loading(load["id"], OPS))
        assert load["logistics_status"] == "LOADING"
        return inventory, load, allocation

    def test_condemn_releases_open_allocations(self, api):
        """PRD §3.2: "Condemnation moves the lot to `CONDEMNED` and triggers a
        two-hop cascade: first, every open load allocation referencing the
        lot transitions from `OPEN` to `RELEASED`, so its reserved tonnage
        stops being held".

        Design: Difficulty/transitive_cascade/condemn_release_replan_cascade
        """
        inventory, _load, allocation = self._loading_setup()
        condemned = validate_success(
            api_client.condemn_lot(inventory["lot"]["id"], OPS)
        )
        assert condemned["status"] == "CONDEMNED"
        assert get_allocation(allocation["id"])["status"] == "RELEASED"

    def test_last_release_reverts_loading_load_to_planned(self, api):
        """PRD §3.2: "second, each delivery load affected by those releases
        has its `loaded_tons` recomputed, and if such a load was in `LOADING`
        it reverts to `PLANNED`."

        Design: Difficulty/transitive_cascade/condemn_release_replan_cascade
        """
        inventory, load, _allocation = self._loading_setup()
        validate_success(api_client.condemn_lot(inventory["lot"]["id"], OPS))
        read = get_load(load["id"])
        assert read["logistics_status"] == "PLANNED"
        assert_tonnage(read["loaded_tons"], 0.0, "loaded_tons")


# ===========================================================================
# compensating_invariant / allocation_release_tonnage_invariant
# ===========================================================================

class TestAllocationReleaseTonnageInvariant:
    def _setup_20t_lot(self):
        deal = setup_accepted_contract(tons=10.0, quality_tier="GOOD")
        inventory = setup_certified_lot(
            rfv=152.0, protein_pct=16.0, moisture_pct=14.0, lot_tonnage=20.0,
        )
        load = create_delivery_load()
        return deal, inventory, load

    def test_allocation_conserves_tonnage_sum(self, api):
        """PRD §3.7: "Success creates the allocation in `OPEN` status and
        applies its reservation in three places at once: the lot's
        `open_allocated_tonnage` increases by the allocated tons".

        At zero stored months the 20.0t lot reports allocatable 20.0; after
        allocating 7.0t, allocatable drops to 13.0 while open_allocated rises
        to 7.0 — the sum is conserved at 20.0.

        Design: Difficulty/compensating_invariant/allocation_release_tonnage_invariant
        """
        deal, inventory, load = self._setup_20t_lot()
        before = get_lot(inventory["lot"]["id"])
        assert_tonnage(before["allocatable_tonnage"], 20.0, "pre allocatable")
        allocate(load["id"], deal["contract"]["id"], inventory["lot"]["id"], 7.0)
        mid = get_lot(inventory["lot"]["id"])
        assert_tonnage(mid["allocatable_tonnage"], 13.0, "mid allocatable")
        assert_tonnage(mid["open_allocated_tonnage"], 7.0, "mid open_allocated")
        assert_tonnage(
            mid["allocatable_tonnage"] + mid["open_allocated_tonnage"], 20.0,
            "conserved sum",
        )

    def test_release_returns_lot_to_exact_pre_allocation_values(self, api):
        """PRD §3.7: "Release returns the reserved tonnage everywhere it was
        held: the lot's `open_allocated_tonnage`, the contract's
        `open_allocated_tons`, and the load's `loaded_tons` each decrease by
        the released tons".

        After releasing the 7.0t allocation the lot reads exactly its
        pre-allocation figures: allocatable 20.0, open_allocated 0.0.

        Design: Difficulty/compensating_invariant/allocation_release_tonnage_invariant
        """
        deal, inventory, load = self._setup_20t_lot()
        allocation = allocate(
            load["id"], deal["contract"]["id"], inventory["lot"]["id"], 7.0,
        )
        validate_success(api_client.release_allocation(allocation["id"], OPS))
        post = get_lot(inventory["lot"]["id"])
        assert_tonnage(post["allocatable_tonnage"], 20.0, "post allocatable")
        assert_tonnage(post["open_allocated_tonnage"], 0.0, "post open_allocated")


# ===========================================================================
# cross_entity_state_dependency / allocation_gated_on_contract_state
# ===========================================================================

class TestAllocationGatedOnContractState:
    def _suspended_contract_setup(self):
        """Accepted GOOD 10.0t contract, then the buyer is suspended so the
        contract cascades to SUSPENDED; a certified GOOD lot and a PLANNED
        load stand ready."""
        deal, inventory = _contract_and_certified_lot(tons=10.0, lot_tonnage=10.0)
        validate_success(api_client.suspend_buyer(deal["buyer"]["id"], ADMIN))
        load = create_delivery_load()
        return deal, inventory, load

    def test_allocation_against_suspended_contract_rejected(self, api):
        """PRD §3.7: "the contract must be `ACTIVE`, otherwise
        `ERR_CONTRACT_NOT_ACTIVE`; the lot must be `ACTIVE` — a `DEPLETED`
        lot fails here with `ERR_LOT_NOT_ACTIVE`".

        Allocating against the cascaded-SUSPENDED contract is rejected even
        though the lot and load are valid.

        Design: Difficulty/cross_entity_state_dependency/allocation_gated_on_contract_state
        """
        deal, inventory, load = self._suspended_contract_setup()
        resp = api_client.create_load_allocation(
            {
                "delivery_load_id": load["id"],
                "contract_id": deal["contract"]["id"],
                "bale_lot_id": inventory["lot"]["id"],
                "tons": 5.0,
                "expected_delivery_load_version": load["version"],
            },
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)

    def test_buyer_suspension_cascades_contract_to_suspended(self, api):
        """PRD §3.5: "Suspending a buyer — an administrator-only action that
        requires the buyer to be `ACTIVE`, otherwise `ERR_INVALID_STATE` —
        cascades: every contract of that buyer still `ACTIVE` becomes
        `SUSPENDED`, but the credit reserve is *not* released; the held
        reserve stays held against suspension."

        Design: Difficulty/cross_entity_state_dependency/allocation_gated_on_contract_state
        """
        deal, _inventory, _load = self._suspended_contract_setup()
        contract = get_contract(deal["contract"]["id"])
        assert contract["status"] == "SUSPENDED"
        assert get_buyer(deal["buyer"]["id"])["credit_used_cents"] == (
            deal["quote"]["total_cents"]
        )


# ===========================================================================
# Corner/state_machines / load_reverts_to_planned_on_last_release
# ===========================================================================

def test_load_reverts_to_planned_on_last_release(api):
    """PRD §3.7: "if the load was `LOADING` and no open allocations remain,
    it automatically reverts to `PLANNED`."

    Manually releasing the load's only OPEN allocation triggers the revert
    (distinct trigger from the condemn cascade).

    Design: Corner/state_machines/load_reverts_to_planned_on_last_release
    """
    deal, inventory = _contract_and_certified_lot(tons=10.0, lot_tonnage=10.0)
    load, allocation = setup_load_with_allocation(
        deal["contract"]["id"], inventory["lot"]["id"], 5.0,
    )
    load = validate_success(api_client.start_loading(load["id"], OPS))
    assert load["logistics_status"] == "LOADING"
    released = validate_success(api_client.release_allocation(allocation["id"], OPS))
    assert released["status"] == "RELEASED"
    read = get_load(load["id"])
    assert read["logistics_status"] == "PLANNED"
    assert_tonnage(read["loaded_tons"], 0.0, "loaded_tons")


# ===========================================================================
# Corner/state_machines / deliver_from_planned_rejected
# ===========================================================================

def test_deliver_from_planned_rejected(api):
    """PRD §3.7: "Departing moves a `LOADING` load to `IN_TRANSIT`.
    Delivery — from `IN_TRANSIT` to `DELIVERED` — fires the system's
    three-hop cascade." PRD §3.7: "an empty load cannot start loading, and
    any from-state mismatch draws `ERR_LOAD_WRONG_STATE`."

    A PLANNED load cannot skip LOADING/IN_TRANSIT straight to DELIVERED.

    Design: Corner/state_machines/deliver_from_planned_rejected
    """
    load = create_delivery_load(carrier_name="CARRIER-S")
    resp = api_client.deliver_load(load["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_LOAD_WRONG_STATE)
    assert get_load(load["id"])["logistics_status"] == "PLANNED"


# ===========================================================================
# Corner/validations / load_capacity_exceeded
# ===========================================================================

def test_load_capacity_exceeded(api):
    """PRD §3.7: "the load's `loaded_tons` plus the new tons must not exceed
    the load's `capacity_tons` (`ERR_LOAD_CAPACITY_EXCEEDED`)".

    A 10.0t truck already carrying 6.0t rejects a further 6.0t allocation;
    the first allocation stands.

    Design: Corner/validations/load_capacity_exceeded
    """
    deal, inventory = _contract_and_certified_lot(
        tons=20.0, lot_tonnage=30.0, credit_limit_cents=2000000,
        rfv=155.0, protein_pct=18.0,
    )
    load = create_delivery_load(capacity_tons=10.0)
    allocate(load["id"], deal["contract"]["id"], inventory["lot"]["id"], 6.0)
    current = get_load(load["id"])
    resp = api_client.create_load_allocation(
        {
            "delivery_load_id": load["id"],
            "contract_id": deal["contract"]["id"],
            "bale_lot_id": inventory["lot"]["id"],
            "tons": 6.0,
            "expected_delivery_load_version": current["version"],
        },
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_LOAD_CAPACITY_EXCEEDED)
    assert_tonnage(get_load(load["id"])["loaded_tons"], 6.0, "loaded_tons")


# ===========================================================================
# Corner/validations / allocation_exceeds_contract_remaining
# ===========================================================================

def test_allocation_exceeds_contract_remaining(api):
    """PRD §3.7: "the requested `tons` must not exceed the contract's
    `remaining_tons` at creation time (`ERR_ALLOCATION_EXCEEDS_REMAINING`)";
    PRD §3.6: "`remaining_tons` is the committed tonnage minus delivered
    tonnage minus open allocated tonnage."

    A 10.0t contract already holding a 10.0t open allocation has
    remaining_tons 0.0, so a further 1.0t allocation is rejected even though
    the truck and the lot both have room.

    Design: Corner/validations/allocation_exceeds_contract_remaining
    """
    deal, inventory = _contract_and_certified_lot(
        tons=10.0, lot_tonnage=30.0, credit_limit_cents=2000000,
        rfv=155.0, protein_pct=18.0,
    )
    load, _allocation = setup_load_with_allocation(
        deal["contract"]["id"], inventory["lot"]["id"], 10.0,
    )
    current = get_load(load["id"])
    resp = api_client.create_load_allocation(
        {
            "delivery_load_id": load["id"],
            "contract_id": deal["contract"]["id"],
            "bale_lot_id": inventory["lot"]["id"],
            "tons": 1.0,
            "expected_delivery_load_version": current["version"],
        },
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_ALLOCATION_EXCEEDS_REMAINING)
    assert_tonnage(
        get_contract(deal["contract"]["id"])["open_allocated_tons"], 10.0,
        "open_allocated_tons",
    )


# ===========================================================================
# Corner/validations / condemned_lot_allocation_rejected
# ===========================================================================

def test_condemned_lot_allocation_rejected(api):
    """PRD §3.2: "Condemned hay can never ship: any later attempt to allocate
    a `CONDEMNED` lot to a load is rejected with
    `ERR_LOT_CONDEMNED_UNSHIPPABLE`."

    Design: Corner/validations/condemned_lot_allocation_rejected
    """
    deal, inventory = _contract_and_certified_lot(
        tons=10.0, lot_tonnage=10.0, rfv=155.0, protein_pct=18.0,
    )
    validate_success(api_client.condemn_lot(inventory["lot"]["id"], OPS))
    load = create_delivery_load()
    resp = api_client.create_load_allocation(
        {
            "delivery_load_id": load["id"],
            "contract_id": deal["contract"]["id"],
            "bale_lot_id": inventory["lot"]["id"],
            "tons": 5.0,
            "expected_delivery_load_version": load["version"],
        },
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_LOT_CONDEMNED_UNSHIPPABLE)
