"""Lot reservation validation order, lot quantity conservation, depletion, and
the customer-supplied shortfall lifecycle (declare, waterfall, escalate)."""
from test_helpers import (
    ApiErrorId,
    allocate_lots,
    allocation_item,
    assert_allocation,
    assert_lot,
    assert_order,
    assert_shortfall,
    confirm_order,
    create_active_formula,
    create_component,
    create_customer,
    create_customer_supplied_component,
    create_lot,
    create_order,
    declare_shortfall,
    escalate_shortfall,
    mixing_batch_ctx,
    reject_batch,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import QA1, PP


class TestAllocationValidationOrder:
    def test_safety_vs_referential_on_allocate(self, api):
        """PRD §3.5: "Reservation validates in a fixed order: the lot must be
        unexpired, its `expires_at` strictly after the current logical clock,
        failing with `ERR_LOT_EXPIRED` (HTTP 422); a lot of a
        `CUSTOMER_SUPPLIED` component may serve only orders of its owning
        customer, failing with `ERR_COMPONENT_OWNERSHIP_MISMATCH` (HTTP 422)".

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_referential_on_allocate
        """
        owner = create_customer(name="Acme Beauty")
        other = create_customer(name="Other Brand")
        water = create_component(name="Water", standard_cost_per_kg_cents=1000)
        jar = create_customer_supplied_component(other["id"], name="C2 Jar", kind="PRIMARY_PACK")
        formula = create_active_formula(owner["id"], component_id=water["id"])
        order = create_order(owner["id"], formula["id"], 1000)
        confirm_order(order["id"], owner["id"])
        # Expired relative to the logical clock's 2026-05-01 startup default (§2.5).
        foreign_expired_lot = create_lot(jar["id"], lot_code="J1", quantity_received=500,
                                         expires_at="2026-04-01T00:00:00Z")

        resp = api.create_allocations(
            order["id"], {"items": [allocation_item(foreign_expired_lot["id"], 10)]}, PP)
        validate_error(resp, ApiErrorId.ERR_LOT_EXPIRED, 422)

    def test_foreign_customer_lot_allocation_rejected(self, api):
        """PRD §3.5: "a lot of a `CUSTOMER_SUPPLIED` component may serve only
        orders of its owning customer, failing with
        `ERR_COMPONENT_OWNERSHIP_MISMATCH` (HTTP 422)".

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_referential_on_allocate
        """
        owner = create_customer(name="Acme Beauty")
        other = create_customer(name="Other Brand")
        water = create_component(name="Water", standard_cost_per_kg_cents=1000)
        jar = create_customer_supplied_component(other["id"], name="C2 Jar", kind="PRIMARY_PACK")
        formula = create_active_formula(owner["id"], component_id=water["id"])
        order = create_order(owner["id"], formula["id"], 1000)
        confirm_order(order["id"], owner["id"])
        foreign_lot = create_lot(jar["id"], lot_code="J1", quantity_received=500)

        resp = api.create_allocations(
            order["id"], {"items": [allocation_item(foreign_lot["id"], 10)]}, PP)
        validate_error(resp, ApiErrorId.ERR_COMPONENT_OWNERSHIP_MISMATCH, 422)

    def test_referential_vs_constraint_on_allocate(self, api):
        """PRD §3.5: "a `MINOR_VARIANT` lot must already hold a `WAIVED` waiver,
        failing with `ERR_VARIANT_WAIVER_REQUIRED` (HTTP 422) while its waiver
        stands `PENDING` or `REJECTED`; and finally the lot must stand
        `AVAILABLE` with `quantity_available` covering the requested `quantity`,
        failing with `ERR_LOT_INSUFFICIENT_QUANTITY` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/referential_vs_constraint_on_allocate
        """
        customer = create_customer()
        water = create_component(name="Water", standard_cost_per_kg_cents=1000)
        bottle = create_customer_supplied_component(customer["id"], name="Bottle", kind="PRIMARY_PACK")
        formula = create_active_formula(
            customer["id"], component_id=water["id"],
            required_components=[{"component_id": bottle["id"], "units_per_product": 1}])
        order = create_order(customer["id"], formula["id"], 1000)
        confirm_order(order["id"], customer["id"])
        variant_lot = create_lot(bottle["id"], lot_code="B1", quantity_received=100,
                                 sensorial_profile="MINOR_VARIANT")

        resp = api.create_allocations(
            order["id"], {"items": [allocation_item(variant_lot["id"], 500)]}, PP)
        validate_error(resp, ApiErrorId.ERR_VARIANT_WAIVER_REQUIRED, 422)

    def test_insufficient_quantity_allocation_rejected(self, api):
        """PRD §3.5: "and finally the lot must stand `AVAILABLE` with
        `quantity_available` covering the requested `quantity`, failing with
        `ERR_LOT_INSUFFICIENT_QUANTITY` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/referential_vs_constraint_on_allocate
        """
        customer = create_customer()
        water = create_component(name="Water", standard_cost_per_kg_cents=1000)
        bottle = create_customer_supplied_component(customer["id"], name="Bottle", kind="PRIMARY_PACK")
        formula = create_active_formula(
            customer["id"], component_id=water["id"],
            required_components=[{"component_id": bottle["id"], "units_per_product": 1}])
        order = create_order(customer["id"], formula["id"], 1000)
        confirm_order(order["id"], customer["id"])
        small_lot = create_lot(bottle["id"], lot_code="B1", quantity_received=100)

        resp = api.create_allocations(
            order["id"], {"items": [allocation_item(small_lot["id"], 500)]}, PP)
        validate_error(resp, ApiErrorId.ERR_LOT_INSUFFICIENT_QUANTITY, 422)


class TestLotQuantityInvariant:
    def test_lot_quantity_conservation_reserve_release(self, api, production_planner_headers):
        """PRD §3.5: "Each successful reservation moves the quantity from the
        lot's `quantity_available` into its `quantity_reserved`, and a lot driven
        to exactly zero available becomes `DEPLETED`."
        PRD §3.5: "A planner may also manually release a `RESERVED` allocation,
        which returns its `quantity` from `quantity_reserved` to
        `quantity_available`".

        Design: Difficulty/compensating_invariant/lot_quantity_conservation_reserve_release
        """
        customer = create_customer()
        water = create_component(name="Water", standard_cost_per_kg_cents=1000)
        formula = create_active_formula(customer["id"], component_id=water["id"])
        order = create_order(customer["id"], formula["id"], 2000)
        confirm_order(order["id"], customer["id"])
        lot = create_lot(water["id"], lot_code="A1", quantity_received=200)

        allocations = allocate_lots(order["id"], [allocation_item(lot["id"], 100)])
        mid = validate_success(api.get_lot(lot["id"], production_planner_headers), 200)
        assert_lot(mid)
        assert mid["quantity_available"] == 100
        assert mid["quantity_reserved"] == 100
        assert mid["quantity_consumed"] == 0

        released = validate_success(api.release_allocation(allocations[0]["id"], production_planner_headers), 200)
        assert_allocation(released)
        assert released["status"] == "RELEASED"
        end = validate_success(api.get_lot(lot["id"], production_planner_headers), 200)
        assert_lot(end)
        assert end["quantity_available"] == 200
        assert end["quantity_reserved"] == 0
        assert end["quantity_consumed"] == 0

    def test_lot_conservation_on_batch_reject_consume(self, api, production_planner_headers):
        """PRD §3.6: "Rejection moves the batch to `REJECTED` and consumes its
        materials as waste: every `RESERVED` allocation of the batch becomes
        `CONSUMED`, each referenced lot's `quantity_reserved` falls by the
        allocation's `quantity` while its `quantity_consumed` rises."

        Design: Difficulty/compensating_invariant/lot_quantity_conservation_reserve_release
        """
        ctx = mixing_batch_ctx(batch_size_kg=100, lot_quantity=200, alloc_quantity=100)
        reject_batch(ctx["batch"]["id"], reason="contamination", headers=QA1)

        lot = validate_success(api.get_lot(ctx["lot"]["id"], production_planner_headers), 200)
        assert_lot(lot)
        assert lot["quantity_available"] == 100
        assert lot["quantity_reserved"] == 0
        assert lot["quantity_consumed"] == 100
        allocation = validate_success(api.get_allocation(ctx["allocations"][0]["id"], production_planner_headers), 200)
        assert allocation["status"] == "CONSUMED"


class TestLotDepletion:
    def test_lot_depleted_at_exactly_zero(self, api, production_planner_headers):
        """PRD §3.1: "And when reservation or consumption drives a lot's
        `quantity_available` to exactly zero, the lot transitions from
        `AVAILABLE` to `DEPLETED` on its own."
        PRD §3.5: "and finally the lot must stand `AVAILABLE` with
        `quantity_available` covering the requested `quantity`, failing with
        `ERR_LOT_INSUFFICIENT_QUANTITY` (HTTP 422)."

        Design: Corner/state_machines/lot_depleted_at_exactly_zero
        """
        customer = create_customer()
        water = create_component(name="Water", standard_cost_per_kg_cents=1000)
        formula = create_active_formula(customer["id"], component_id=water["id"])
        order = create_order(customer["id"], formula["id"], 2000)
        confirm_order(order["id"], customer["id"])
        lot = create_lot(water["id"], lot_code="A1", quantity_received=200)

        allocate_lots(order["id"], [allocation_item(lot["id"], 200)])
        depleted = validate_success(api.get_lot(lot["id"], production_planner_headers), 200)
        assert_lot(depleted)
        assert depleted["quantity_available"] == 0
        assert depleted["status"] == "DEPLETED"

        resp = api.create_allocations(order["id"], {"items": [allocation_item(lot["id"], 1)]}, PP)
        validate_error(resp, ApiErrorId.ERR_LOT_INSUFFICIENT_QUANTITY, 422)


class TestShortfallDeclaration:
    def test_no_shortfall_when_coverage_sufficient(self, api):
        """PRD §3.5: "The system computes `allocatable_quantity` as the sum of
        `quantity_available` over the customer's `AVAILABLE`, unexpired lots of
        that component at declaration time, and `shortfall_quantity` as the
        difference; a declaration whose computed shortfall is zero or less is
        rejected with `ERR_NO_SHORTFALL` (HTTP 422)."

        Design: Corner/validations/no_shortfall_when_coverage_sufficient
        """
        customer = create_customer()
        water = create_component(name="Water", standard_cost_per_kg_cents=1000)
        cap = create_customer_supplied_component(customer["id"], name="Cap", kind="SECONDARY_PACK")
        formula = create_active_formula(
            customer["id"], component_id=water["id"],
            required_components=[{"component_id": cap["id"], "units_per_product": 1}])
        order = create_order(customer["id"], formula["id"], 1000)
        confirm_order(order["id"], customer["id"])
        create_lot(cap["id"], lot_code="C1", quantity_received=500)

        resp = api.declare_shortfall(
            order["id"], {"component_id": cap["id"], "required_quantity": 300}, PP)
        validate_error(resp, ApiErrorId.ERR_NO_SHORTFALL, 422)


class TestShortfallEscalationCascade:
    def _setup_escalation_scenario(self):
        customer = create_customer()
        water = create_component(name="Water", standard_cost_per_kg_cents=1000)
        bottle = create_customer_supplied_component(customer["id"], name="Bottle", kind="PRIMARY_PACK")
        cap = create_customer_supplied_component(customer["id"], name="Cap", kind="SECONDARY_PACK")
        formula = create_active_formula(
            customer["id"], component_id=water["id"],
            required_components=[
                {"component_id": bottle["id"], "units_per_product": 1},
                {"component_id": cap["id"], "units_per_product": 1},
            ])
        order = create_order(customer["id"], formula["id"], 2000)
        confirm_order(order["id"], customer["id"])
        # Lots are received larger than the reserved quantities so every lot
        # stays AVAILABLE (a fully reserved lot goes DEPLETED per §3.1, which
        # would make the pools below depend on how §3.5's reserved add-back
        # interacts with the lot-status eligibility filter).
        bottle_lots = [create_lot(bottle["id"], lot_code=f"B{i}", quantity_received=1000)
                       for i in range(1, 5)]
        cap_lot = create_lot(cap["id"], lot_code="C1", quantity_received=500)
        bottle_allocs = allocate_lots(order["id"], [
            allocation_item(lot["id"], 500) for lot in bottle_lots])
        allocate_lots(order["id"], [allocation_item(cap_lot["id"], 250)])
        shortfall = declare_shortfall(order["id"], cap["id"], 2000)
        return customer, order, bottle_lots, cap_lot, bottle_allocs, shortfall

    def test_shortfall_escalation_cascade_depth3(self, api, production_planner_headers):
        """PRD §3.5: "Under `REDUCE_ORDER`, the order's `requested_units` shrink
        to its `fulfillable_units_conservative` and its `forfeited_units` grow by
        the surrendered delta; then, for every component in the formula's
        `required_components`, the order's excess `RESERVED` allocations are
        released newest-first — the most recently created allocation first —
        until that component's reserved quantity no longer exceeds the new
        `requested_units` multiplied by its `units_per_product`, and each release
        restores its lot's reserved and available counters."
        PRD §3.5: "From `OPEN` or `COMMITMENT_RECEIVED`, a `ProductionPlanner`
        escalates with a `resolution`, and the case moves to `ESCALATED`."

        Design: Difficulty/transitive_cascade/shortfall_escalation_cascade_depth3
        """
        (_, order, bottle_lots, _, bottle_allocs, shortfall) = self._setup_escalation_scenario()

        escalated = escalate_shortfall(shortfall["id"], "REDUCE_ORDER")
        assert_shortfall(escalated)
        assert escalated["status"] == "ESCALATED"

        # fulfillable_conservative = min(bottle 2000 avail + 2000 reserved,
        # cap 250 avail + 250 reserved) = min(4000, 500) = 500.
        fetched_order = validate_success(api.get_order(order["id"], production_planner_headers), 200)
        assert_order(fetched_order)
        assert fetched_order["requested_units"] == 500
        assert fetched_order["forfeited_units"] == 1500

        oldest = validate_success(api.get_allocation(bottle_allocs[0]["id"], production_planner_headers), 200)
        newest = validate_success(api.get_allocation(bottle_allocs[3]["id"], production_planner_headers), 200)
        assert oldest["status"] == "RESERVED", "oldest allocation survives the newest-first release"
        assert newest["status"] == "RELEASED"

        # The newest lot (received 1000, 500 reserved) gets its full 500 back.
        newest_lot = validate_success(api.get_lot(bottle_lots[3]["id"], production_planner_headers), 200)
        assert_lot(newest_lot)
        assert newest_lot["quantity_available"] == 1000
        assert newest_lot["quantity_reserved"] == 0

    def test_shortfall_escalate_cancel_order(self, api, production_planner_headers):
        """PRD §3.5: "Under `CANCEL_ORDER`, the order is cancelled outright with
        the full cancellation cascade."
        PRD §3.5: "From `OPEN` or `COMMITMENT_RECEIVED`, a `ProductionPlanner`
        escalates with a `resolution`, and the case moves to `ESCALATED`."

        Design: Difficulty/transitive_cascade/shortfall_escalation_cascade_depth3
        """
        customer = create_customer()
        water = create_component(name="Water", standard_cost_per_kg_cents=1000)
        cap = create_customer_supplied_component(customer["id"], name="Cap", kind="SECONDARY_PACK")
        formula = create_active_formula(
            customer["id"], component_id=water["id"],
            required_components=[{"component_id": cap["id"], "units_per_product": 1}])
        order = create_order(customer["id"], formula["id"], 2000)
        confirm_order(order["id"], customer["id"])
        shortfall = declare_shortfall(order["id"], cap["id"], 2000)

        escalated = escalate_shortfall(shortfall["id"], "CANCEL_ORDER")
        assert escalated["status"] == "ESCALATED"

        fetched_order = validate_success(api.get_order(order["id"], production_planner_headers), 200)
        assert fetched_order["status"] == "CANCELLED"


class TestShortfallWaterfall:
    def test_shortfall_proration_waterfall_order(self, api, production_planner_headers):
        """PRD §3.5: "Receipt of a lot of a customer-supplied component
        distributes its `quantity_available` across that customer's shortfall
        cases for the same component standing `OPEN` or `COMMITMENT_RECEIVED`,
        oldest case first, ties broken by the parent order's creation time,
        earliest first."
        PRD §3.5: "Each grant is the lesser of the case's still-uncovered
        `shortfall_quantity` and the lot's remaining quantity, and each grant
        creates a `RESERVED` allocation against the shortfall's parent order with
        no batch linkage. A case whose grants reach its full `shortfall_quantity`
        transitions to `CLOSED_RESOLVED`; any lot quantity left over stays
        `AVAILABLE`, and a zero-quantity remainder creates no allocation."

        Design: Corner/calculations/shortfall_proration_waterfall_order
        """
        customer = create_customer()
        water = create_component(name="Water", standard_cost_per_kg_cents=1000)
        cap = create_customer_supplied_component(customer["id"], name="Cap", kind="SECONDARY_PACK")
        formula = create_active_formula(
            customer["id"], component_id=water["id"],
            required_components=[{"component_id": cap["id"], "units_per_product": 1}])
        order1 = create_order(customer["id"], formula["id"], 1000)
        confirm_order(order1["id"], customer["id"])
        order2 = create_order(customer["id"], formula["id"], 1000)
        confirm_order(order2["id"], customer["id"])
        shortfall1 = declare_shortfall(order1["id"], cap["id"], 800)
        shortfall2 = declare_shortfall(order2["id"], cap["id"], 600)

        lot = create_lot(cap["id"], lot_code="C1", quantity_received=1000)

        sf1 = validate_success(api.get_shortfall(shortfall1["id"], production_planner_headers), 200)
        assert sf1["status"] == "CLOSED_RESOLVED", "older shortfall covered first (800)"
        sf2 = validate_success(api.get_shortfall(shortfall2["id"], production_planner_headers), 200)
        assert sf2["status"] == "OPEN", "newer shortfall only partially covered (200 of 600)"

        o2_allocs, meta = validate_paginated(
            api.list_order_allocations(order2["id"], production_planner_headers))
        assert meta["total_count"] == 1
        assert o2_allocs[0]["quantity"] == 200
        assert o2_allocs[0]["status"] == "RESERVED"

        fetched_lot = validate_success(api.get_lot(lot["id"], production_planner_headers), 200)
        assert_lot(fetched_lot)
        assert fetched_lot["quantity_available"] == 0
        assert fetched_lot["status"] == "DEPLETED"
