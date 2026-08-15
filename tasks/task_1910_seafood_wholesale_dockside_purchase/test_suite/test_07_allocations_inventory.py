"""Allocations against inventory lots: the five business gates, optimistic
concurrency on the order, weight-bucket conservation, and fulfillment."""
import pytest

from test_helpers import (
    api_client,
    ApiErrorId,
    TEST_USERS,
    OFFICER_1_HEADERS,
    OFFICER_2_HEADERS,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    assert_kg,
    assert_lot_buckets,
    assert_lot_weight_conservation,
    create_allocation_payload,
    create_sales_order_payload,
    make_customer_headers,
    create_vessel,
    create_catch_area,
    create_species,
    create_and_publish_quote,
    create_customer,
    create_order_with_lines,
    submit_order,
    confirm_order,
    get_order,
    get_order_version,
    get_order_line,
    get_lot,
    create_allocation,
    commit_allocation,
    list_allocations_for_line,
    create_inspection_hold,
    create_shipment,
    setup_graded_lot,
    setup_confirmed_order,
    setup_lot_and_confirmed_order,
    setup_reserved_allocation,
    setup_committed_allocation,
    set_clock,
)

OM = TEST_USERS["operations_manager_headers"]
IP = TEST_USERS["inventory_planner_headers"]
LC = TEST_USERS["logistics_coordinator_headers"]
CO = TEST_USERS["compliance_officer_headers"]


class TestAllocationCrossEntityGuards:
    """The hold gate on allocation creation against a confirmed order."""

    def test_allocation_on_held_lot_rejected_buckets_unchanged(self, api):
        """PRD §3.7: "The lot must not be `ON_HOLD`, else `ERR_LOT_ON_HOLD` (409)."
        PRD §3.8: "A lot on hold is quarantined: allocation, commitment, freezing, and write-off against it are all blocked with `ERR_LOT_ON_HOLD`, and settlement of any ticket with a derived lot on hold is likewise blocked."

        Design: Difficulty/cross_entity_state_dependency/allocation_requires_confirmed_order_and_clear_active_lot
        """
        ctx = setup_lot_and_confirmed_order(line_qty_kg=10.00)
        create_inspection_hold(ctx["lot"]["id"], reason="audit",
                               headers=OFFICER_1_HEADERS)

        resp = api_client.create_allocation(
            create_allocation_payload(
                order_line_id=ctx["line_o"]["id"],
                inventory_lot_id=ctx["lot"]["id"], qty_kg=10.00, transit_hours=8,
                expected_sales_order_version=get_order_version(ctx["order"]["id"])),
            IP)
        validate_error(resp, ApiErrorId.ERR_LOT_ON_HOLD)

        assert list_allocations_for_line(ctx["line_o"]["id"]) == []
        lot = get_lot(ctx["lot"]["id"])
        assert_lot_buckets(lot, available=50.00, reserved=0.00)

    def test_allocation_succeeds_once_hold_released(self, api):
        """PRD §3.8: "Release returns the lot's `hold_status` to `CLEAR` and stamps the releasing officer as `resolved_by_user_id` with `resolved_at` set, but the releasing officer must differ from the officer who placed the hold; a same-user release is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (403)."
        PRD §3.7: "A successful allocation starts in `RESERVED`, moves its quantity from the lot's available bucket to its reserved bucket, recomputes the line's `allocated_qty_kg` as the sum of quantities over its `RESERVED` and `COMMITTED` allocations, and increments the order's `version` by one."

        Design: Difficulty/cross_entity_state_dependency/allocation_requires_confirmed_order_and_clear_active_lot
        """
        ctx = setup_lot_and_confirmed_order(line_qty_kg=10.00)
        hold = create_inspection_hold(ctx["lot"]["id"], reason="audit",
                                      headers=OFFICER_1_HEADERS)
        get_success_data(api_client.release_inspection_hold(hold["id"],
                                                            OFFICER_2_HEADERS))
        assert get_lot(ctx["lot"]["id"])["hold_status"] == "CLEAR"

        allocation = create_allocation(ctx["order"]["id"], ctx["line_o"]["id"],
                                       ctx["lot"]["id"], qty_kg=10.00)
        assert allocation["status"] == "RESERVED"
        lot = get_lot(ctx["lot"]["id"])
        assert_lot_buckets(lot, available=40.00, reserved=10.00)
        assert_kg(get_order_line(ctx["line_o"]["id"])["allocated_qty_kg"], 10.00)


class TestHoldSafetyBeatsShelfLifeTemporal:
    """When the hold gate and the shelf-life gate both fail, the safety error
    surfaces first."""

    def test_held_and_shelf_short_lot_reports_hold(self, api):
        """PRD §2.8: "Every request is validated in a fixed order, and the first failing check determines the error response. The ordering is part of the contract: a missing header surfaces before a permission failure, a stale version surfaces before an invalid-state failure, and a hold violation surfaces before a fiscal failure."
        PRD §2.8: "7. **Safety and compliance gates.** Hold blocks, segregation-of-duties pairs, labeling compliance, and import clearance are enforced, surfacing `ERR_LOT_ON_HOLD` (409), `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (403), `ERR_LABELING_NONCOMPLIANT` (422), or `ERR_IMPORT_DOCS_NOT_CLEARED` (409)."
        PRD §2.8: "8. **Temporal rules.** Landing-window validity surfaces `ERR_INVALID_LANDING_WINDOW` (400), vessel landing-window overlap surfaces `ERR_VESSEL_LANDING_OVERLAP` (409), and the allocation shelf-life gate surfaces `ERR_SHELF_LIFE_INSUFFICIENT` (422)."

        Design: Difficulty/priority_pair_validation_conflict/allocate_held_and_stale_lot_safety_beats_temporal
        """
        # 78 h of shelf life remain at the default clock; the line demands
        # 70 + 12 = 82 h, so the temporal gate fails too — hold must win.
        ctx = setup_lot_and_confirmed_order(line_qty_kg=10.00,
                                            min_remaining_shelf_life_hours=70)
        create_inspection_hold(ctx["lot"]["id"], reason="suspect temperature abuse",
                               headers=OFFICER_1_HEADERS)

        resp = api_client.create_allocation(
            create_allocation_payload(
                order_line_id=ctx["line_o"]["id"],
                inventory_lot_id=ctx["lot"]["id"], qty_kg=10.00, transit_hours=12,
                expected_sales_order_version=get_order_version(ctx["order"]["id"])),
            IP)
        validate_error(resp, ApiErrorId.ERR_LOT_ON_HOLD)

        assert list_allocations_for_line(ctx["line_o"]["id"]) == []
        lot = get_lot(ctx["lot"]["id"])
        assert_lot_buckets(lot, available=50.00, reserved=0.00)

    def test_shelf_shortfall_alone_reports_shelf_life(self, api):
        """PRD §3.7: "And the shelf-life gate: the hours between now and the lot's `expires_at` must be at least the sum of the line's `min_remaining_shelf_life_hours` and the allocation's `transit_hours`, with exact equality sufficient — otherwise `ERR_SHELF_LIFE_INSUFFICIENT` (422)."

        Design: Difficulty/priority_pair_validation_conflict/allocate_held_and_stale_lot_safety_beats_temporal
        """
        ctx = setup_lot_and_confirmed_order(line_qty_kg=10.00,
                                            min_remaining_shelf_life_hours=70)
        # 78 h remaining: 70 + 8 = 78 passes exactly (control), 70 + 12 = 82 fails.
        create_allocation(ctx["order"]["id"], ctx["line_o"]["id"],
                          ctx["lot"]["id"], qty_kg=10.00, transit_hours=8)

        resp = api_client.create_allocation(
            create_allocation_payload(
                order_line_id=ctx["line_o"]["id"],
                inventory_lot_id=ctx["lot"]["id"], qty_kg=10.00, transit_hours=12,
                expected_sales_order_version=get_order_version(ctx["order"]["id"])),
            IP)
        validate_error(resp, ApiErrorId.ERR_SHELF_LIFE_INSUFFICIENT)

        lot = get_lot(ctx["lot"]["id"])
        assert_lot_buckets(lot, available=40.00, reserved=10.00)


class TestShelfLifeBoundary:
    """Boundary precision on the shelf-life gate: >= passes, one hour over fails."""

    def test_exact_remaining_hours_allocatable_one_more_hour_fails(self, api):
        """PRD §3.7: "And the shelf-life gate: the hours between now and the lot's `expires_at` must be at least the sum of the line's `min_remaining_shelf_life_hours` and the allocation's `transit_hours`, with exact equality sufficient — otherwise `ERR_SHELF_LIFE_INSUFFICIENT` (422)."
        PRD §3.4: "Being fresh, its shelf-life clock starts immediately: `expires_at` is the `landed_at` instant plus the species' `fresh_shelf_life_hours`, at hour granularity."

        Design: Difficulty/boundary_precision_check/shelf_life_exact_remaining_hours_allocatable
        """
        ctx = setup_lot_and_confirmed_order(
            line_qty_kg=50.00, lot_landed_weight_kg=100.00,
            min_remaining_shelf_life_hours=40,
            lot_kwargs={"assessed_grade": "GRADE_B", "yield_pct": 0.90,
                        "quote_prices": {"GRADE_A": 1200, "GRADE_B": 950}})
        # Landed 2026-08-01T06:00:00Z with a 72 h fresh life -> expires
        # 2026-08-04T06:00:00Z. Advancing to 2026-08-02T06:00:00Z leaves 48 h.
        set_clock("2026-08-02T06:00:00Z")

        first = create_allocation(ctx["order"]["id"], ctx["line_o"]["id"],
                                  ctx["lot"]["id"], qty_kg=10.00, transit_hours=8)
        assert first["status"] == "RESERVED", "48 >= 40 + 8 exactly"

        resp = api_client.create_allocation(
            create_allocation_payload(
                order_line_id=ctx["line_o"]["id"],
                inventory_lot_id=ctx["lot"]["id"], qty_kg=10.00, transit_hours=9,
                expected_sales_order_version=get_order_version(ctx["order"]["id"])),
            IP)
        validate_error(resp, ApiErrorId.ERR_SHELF_LIFE_INSUFFICIENT)

        lot = get_lot(ctx["lot"]["id"])
        assert_lot_buckets(lot, available=77.30, reserved=10.00)

    def test_exact_equality_with_zero_transit(self, api):
        """PRD §3.7: "And the shelf-life gate: the hours between now and the lot's `expires_at` must be at least the sum of the line's `min_remaining_shelf_life_hours` and the allocation's `transit_hours`, with exact equality sufficient — otherwise `ERR_SHELF_LIFE_INSUFFICIENT` (422)."

        Design: Difficulty/boundary_precision_check/shelf_life_exact_remaining_hours_allocatable
        """
        landing = setup_graded_lot(landed_weight_kg=50.00)
        customer = create_customer()
        # 78 h remain at the default clock: min 78 passes exactly, min 79 fails.
        order_ctx = setup_confirmed_order(
            customer,
            [{"species_id": landing["species"]["id"], "requested_qty_kg": 10.00,
              "min_remaining_shelf_life_hours": 78},
             {"species_id": landing["species"]["id"], "requested_qty_kg": 10.00,
              "min_remaining_shelf_life_hours": 79}])

        ok = create_allocation(order_ctx["order"]["id"], order_ctx["lines"][0]["id"],
                               landing["lot"]["id"], qty_kg=10.00, transit_hours=0)
        assert ok["status"] == "RESERVED"

        resp = api_client.create_allocation(
            create_allocation_payload(
                order_line_id=order_ctx["lines"][1]["id"],
                inventory_lot_id=landing["lot"]["id"], qty_kg=10.00, transit_hours=0,
                expected_sales_order_version=get_order_version(
                    order_ctx["order"]["id"])),
            IP)
        validate_error(resp, ApiErrorId.ERR_SHELF_LIFE_INSUFFICIENT)


class TestLotWeightConservation:
    """Kilograms are conserved: buckets always sum back to the received weight."""

    def test_allocate_commit_release_conserve_weight(self, api):
        """PRD §2.9: "Every workflow that moves weight names its source and destination buckets; reservations move weight from available to reserved, commits from reserved to committed, deliveries from committed to shipped, write-offs from available to spoiled, condemnations from available, reserved, and committed into condemned, and recalls from available, reserved, and committed into recalled."
        PRD §3.4: "Its `received_weight_kg` is the line's `processed_weight_kg`, its `available_weight_kg` equals the received weight, and every other weight bucket starts at zero; its `unit_cost_cents` is derived per §2.9."

        Design: Difficulty/compensating_invariant/lot_weight_conservation_through_allocate_release
        """
        ctx = setup_lot_and_confirmed_order(
            line_qty_kg=50.00, lot_landed_weight_kg=100.00,
            lot_kwargs={"assessed_grade": "GRADE_B", "yield_pct": 0.90,
                        "quote_prices": {"GRADE_A": 1200, "GRADE_B": 950}})
        order_id, line_id, lot_id = (ctx["order"]["id"], ctx["line_o"]["id"],
                                     ctx["lot"]["id"])
        assert_kg(ctx["lot"]["received_weight_kg"], 87.30, "received")

        a1 = create_allocation(order_id, line_id, lot_id, qty_kg=20.00)
        commit_allocation(a1["id"])
        a2 = create_allocation(order_id, line_id, lot_id, qty_kg=30.00)
        get_success_data(api_client.release_allocation(a2["id"], IP))

        lot = get_lot(lot_id)
        assert_lot_buckets(lot, available=67.30, reserved=0.00, committed=20.00)
        assert_lot_weight_conservation(lot)

    def test_writeoff_and_deliver_conserve_weight(self, api):
        """PRD §3.7: "Writing off spoilage moves a supplied `qty_kg` from the available bucket into `spoiled_weight_kg`, with an optional `reason`"
        PRD §3.7: "Delivery moves an `IN_TRANSIT` shipment to the terminal `DELIVERED` state and settles the physical flow: for every `COMMITTED` allocation on the shipment's order lines, the quantity moves from the lot's committed bucket into `shipped_weight_kg`, and lots whose available, reserved, and committed buckets all reach zero transition to `DEPLETED`."

        Design: Difficulty/compensating_invariant/lot_weight_conservation_through_allocate_release
        """
        ctx = setup_committed_allocation(
            line_qty_kg=50.00, alloc_qty_kg=20.00, lot_landed_weight_kg=100.00,
            lot_kwargs={"assessed_grade": "GRADE_B", "yield_pct": 0.90,
                        "quote_prices": {"GRADE_A": 1200, "GRADE_B": 950}})
        lot_id = ctx["lot"]["id"]

        get_success_data(api_client.write_off_inventory_lot(
            lot_id, {"qty_kg": 7.30, "reason": "spoilage"}, IP))
        lot = get_lot(lot_id)
        assert_lot_buckets(lot, available=60.00, committed=20.00, spoiled=7.30)
        assert_lot_weight_conservation(lot)

        shipment = create_shipment(ctx["order"]["id"], mode="TRUCK",
                                   booked_weight_kg=20.00)
        get_success_data(api_client.book_shipment(shipment["id"], LC))
        get_success_data(api_client.tender_shipment(
            shipment["id"], {"actual_weight_kg": 20.00, "volume_m3": 0.10}, LC))
        get_success_data(api_client.depart_shipment(shipment["id"], LC))
        get_success_data(api_client.deliver_shipment(shipment["id"], LC))

        lot = get_lot(lot_id)
        assert_lot_buckets(lot, available=60.00, reserved=0.00, committed=0.00,
                           shipped=20.00, spoiled=7.30)
        assert lot["lifecycle_status"] == "ACTIVE", (
            "available 60.00 > 0, so the lot is not depleted")
        assert_lot_weight_conservation(lot)


def test_line_over_allocation_rejected(api):
    """PRD §3.7: "The line's remaining quantity — its `requested_qty_kg` less its current `allocated_qty_kg` — must be at least the requested quantity, else `ERR_LINE_OVER_ALLOCATION` (409)."

    Design: Corner/validations/val_line_over_allocation_rejected
    """
    ctx = setup_lot_and_confirmed_order(line_qty_kg=10.00)
    create_allocation(ctx["order"]["id"], ctx["line_o"]["id"], ctx["lot"]["id"],
                      qty_kg=7.00)

    resp = api_client.create_allocation(
        create_allocation_payload(
            order_line_id=ctx["line_o"]["id"],
            inventory_lot_id=ctx["lot"]["id"], qty_kg=5.00, transit_hours=8,
            expected_sales_order_version=get_order_version(ctx["order"]["id"])),
        IP)
    validate_error(resp, ApiErrorId.ERR_LINE_OVER_ALLOCATION)

    assert_kg(get_order_line(ctx["line_o"]["id"])["allocated_qty_kg"], 7.00)
    assert_lot_buckets(get_lot(ctx["lot"]["id"]), reserved=7.00, available=43.00)


def test_insufficient_lot_quantity_rejected(api):
    """PRD §3.7: "The lot's `available_weight_kg` must be at least the requested quantity, else `ERR_INSUFFICIENT_LOT_QUANTITY` (409)."

    Design: Corner/validations/val_insufficient_lot_quantity_rejected
    """
    ctx = setup_lot_and_confirmed_order(
        line_qty_kg=100.00, lot_landed_weight_kg=100.00,
        lot_kwargs={"assessed_grade": "GRADE_B", "yield_pct": 0.90,
                    "quote_prices": {"GRADE_A": 1200, "GRADE_B": 950}})
    assert_kg(ctx["lot"]["available_weight_kg"], 87.30, "lot available")

    resp = api_client.create_allocation(
        create_allocation_payload(
            order_line_id=ctx["line_o"]["id"],
            inventory_lot_id=ctx["lot"]["id"], qty_kg=90.00, transit_hours=8,
            expected_sales_order_version=get_order_version(ctx["order"]["id"])),
        IP)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_LOT_QUANTITY)

    lot = get_lot(ctx["lot"]["id"])
    assert_lot_buckets(lot, available=87.30, reserved=0.00)


def test_species_mismatch_between_line_and_lot_rejected(api):
    """PRD §3.7: "The lot's species must equal the line's species, else `ERR_SPECIES_MISMATCH` (422)."

    Design: Corner/validations/val_species_mismatch_rejected
    """
    landing = setup_graded_lot(landed_weight_kg=50.00,
                               species_overrides={"species_code": "COD"})
    haddock = create_species(species_code="HADDOCK")
    create_and_publish_quote(haddock["id"], grade="GRADE_A", price_per_kg_cents=999)
    customer = create_customer()
    order_ctx = setup_confirmed_order(
        customer, [{"species_id": haddock["id"], "requested_qty_kg": 10.00}])

    resp = api_client.create_allocation(
        create_allocation_payload(
            order_line_id=order_ctx["lines"][0]["id"],
            inventory_lot_id=landing["lot"]["id"], qty_kg=10.00, transit_hours=8,
            expected_sales_order_version=get_order_version(
                order_ctx["order"]["id"])),
        IP)
    validate_error(resp, ApiErrorId.ERR_SPECIES_MISMATCH)
    assert list_allocations_for_line(order_ctx["lines"][0]["id"]) == []


def test_allocate_with_stale_order_version_rejected(api):
    """PRD §2.7: "Creating an allocation against a sales order requires `expected_sales_order_version` matching the order's current `version`. Because each successful allocation advances the order's `version`, a writer holding an older reading of the order's remaining quantities is rejected with `ERR_STALE_VERSION`."

    Design: Corner/cross_cutting/occ_stale_order_version_on_allocate
    """
    ctx = setup_lot_and_confirmed_order(line_qty_kg=20.00)
    stale_version = ctx["order"]["version"]

    first = api_client.create_allocation(
        create_allocation_payload(
            order_line_id=ctx["line_o"]["id"], inventory_lot_id=ctx["lot"]["id"],
            qty_kg=5.00, transit_hours=8,
            expected_sales_order_version=stale_version), IP)
    validate_success(first, expected_status=201)

    stale = api_client.create_allocation(
        create_allocation_payload(
            order_line_id=ctx["line_o"]["id"], inventory_lot_id=ctx["lot"]["id"],
            qty_kg=5.00, transit_hours=8,
            expected_sales_order_version=stale_version), IP)
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    assert len(list_allocations_for_line(ctx["line_o"]["id"])) == 1
    assert_lot_buckets(get_lot(ctx["lot"]["id"]), reserved=5.00, available=45.00)


def test_release_reconciles_line_and_lot(api):
    """PRD §3.7: "Releasing works in the other direction: an `InventoryPlanner` may release a `RESERVED` allocation, moving the weight from reserved back to available and recomputing the line's `allocated_qty_kg`."

    Design: Corner/cross_cutting/derived_reconcile_line_and_lot_after_release
    """
    ctx = setup_reserved_allocation(line_qty_kg=10.00, alloc_qty_kg=7.00)
    released = validate_success(
        api_client.release_allocation(ctx["allocation"]["id"], IP))
    assert released["status"] == "RELEASED"

    assert_kg(get_order_line(ctx["line_o"]["id"])["allocated_qty_kg"], 0.00,
              "allocated after release")
    lot = get_lot(ctx["lot"]["id"])
    assert_lot_buckets(lot, reserved=0.00, available=50.00)


def test_direct_release_of_committed_allocation_rejected(api):
    """PRD §3.7: "A direct release of a `COMMITTED` allocation is rejected with `ERR_ALLOCATION_INVALID_STATE`; committed weight is released only by the system cascades — condemnation, expiry, void, re-grade, and order cancellation — which return the weight to available unless the cascade itself directs it to the condemned or recalled bucket, and which re-evaluate the fulfillment regression after recomputing the line's quantities. `RELEASED` is terminal for an allocation."

    Design: Corner/state_machines/sm_direct_release_of_committed_allocation_rejected
    """
    ctx = setup_committed_allocation(line_qty_kg=10.00)
    resp = api_client.release_allocation(ctx["allocation"]["id"], IP)
    validate_error(resp, ApiErrorId.ERR_ALLOCATION_INVALID_STATE)

    assert get_success_data(
        api_client.get_allocation(ctx["allocation"]["id"], OM))["status"] == "COMMITTED"
    assert_lot_buckets(get_lot(ctx["lot"]["id"]), committed=10.00, available=40.00)


def test_order_auto_fulfills_when_all_lines_committed(api):
    """PRD §3.6: "When every line's `committed_qty_kg` reaches at least its `requested_qty_kg`, the order transitions from `CONFIRMED` to `FULFILLED` on its own."
    PRD §3.7: "The quantity moves from the lot's reserved bucket to its committed bucket, the line's `committed_qty_kg` — the sum over its `COMMITTED` allocations — is recomputed, and when every line of the order is fully committed the order fulfills automatically per §3.6."

    Design: Corner/state_machines/sm_order_auto_fulfills_when_all_lines_committed
    """
    landing = setup_graded_lot(
        landed_weight_kg=100.00,
        assessed_grade="GRADE_B", yield_pct=0.90,
        quote_prices={"GRADE_A": 1200, "GRADE_B": 950})
    customer = create_customer()
    order_ctx = setup_confirmed_order(
        customer,
        [{"species_id": landing["species"]["id"], "requested_qty_kg": 10.00},
         {"species_id": landing["species"]["id"], "requested_qty_kg": 10.00}])
    order_id = order_ctx["order"]["id"]
    a1 = create_allocation(order_id, order_ctx["lines"][0]["id"],
                           landing["lot"]["id"], qty_kg=10.00)
    a2 = create_allocation(order_id, order_ctx["lines"][1]["id"],
                           landing["lot"]["id"], qty_kg=10.00)

    commit_allocation(a1["id"])
    assert get_order(order_id)["status"] == "CONFIRMED", (
        "Line 2 not yet committed: no fulfillment")

    commit_allocation(a2["id"])
    assert get_order(order_id)["status"] == "FULFILLED"

    lot = get_lot(landing["lot"]["id"])
    assert_lot_buckets(lot, available=67.30, reserved=0.00, committed=20.00)


def test_compliance_officer_cannot_create_allocation(api):
    """PRD §2.1: "A request whose role is valid but not permitted for the target operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §2.8: "Every request is validated in a fixed order, and the first failing check determines the error response."
    PRD §4: "POST | `/allocations` | Reserve weight from a lot against an order line (optimistic concurrency on the order version) | InventoryPlanner"

    Design: Corner/rbac/rbac_compliance_officer_cannot_allocate
    """
    customer = create_customer()
    order = get_success_data(api_client.create_sales_order(
        create_sales_order_payload(customer_id=customer["id"]),
        make_customer_headers(customer["id"])))

    resp = api_client.create_allocation(
        create_allocation_payload(
            order_line_id="00000000-0000-0000-0000-000000000000",
            inventory_lot_id="00000000-0000-0000-0000-000000000000",
            qty_kg=1.00, transit_hours=1,
            expected_sales_order_version=order["version"]),
        CO)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
