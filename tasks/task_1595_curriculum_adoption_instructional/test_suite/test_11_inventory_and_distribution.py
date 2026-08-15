"""Warehouse inventory and classroom distribution: adoption/freeze gates on
creation, the exact-fit approval boundary, freeze-beats-inventory priority,
unit conservation, and the receipt-driven backorder promotion pass."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_inventory_unit_conservation,
    create_cycle,
    create_distribution_order,
    create_framework,
    create_material,
    create_po_fresh,
    file_material_challenge,
    get_cycle,
    get_distribution_order,
    get_lot,
    get_material,
    issue_po,
    receive_po,
    setup_cycle_adopted,
    setup_cycle_distributing,
    setup_cycle_procuring,
    setup_decided_material_challenge,
    transition_distribution_order,
    validate_error,
    vet_material,
)

WAREHOUSE = TEST_USERS["warehouse_manager_headers"]


class TestDistributionCreateGates:
    def test_distribution_create_requires_adopted(self, api):
        """PRD §3.7: "Distribution exists only for adopted, unfrozen
        materials: a material whose `adoption_status` is not `ADOPTED` fails
        with `ERR_MATERIAL_NOT_ADOPTED`, and a material whose
        `availability_status` is anything but `USABLE` fails with
        `ERR_MATERIAL_FROZEN`."

        Design: Corner/validations/distribution_create_requires_adopted
        """
        framework = create_framework()
        cycle = create_cycle(framework["id"])
        material = create_material(cycle["id"])
        vet_material(material["id"])  # VETTED, never adopted
        validate_error(
            api.create_distribution_order(
                {"material_id": material["id"], "school_code": "SCH-A",
                 "classroom_label": "RM-101", "quantity": 1,
                 "need_priority": 1}, WAREHOUSE),
            ApiErrorId.ERR_MATERIAL_NOT_ADOPTED)

    def test_distribution_create_frozen_while_under_challenge(self, api):
        """PRD §3.7: "a material whose `availability_status` is anything but
        `USABLE` fails with `ERR_MATERIAL_FROZEN`."
        PRD §2.9: "the two move independently, so a material can legitimately
        be `ADOPTED` and `UNDER_CHALLENGE` at the same time."

        Design: Difficulty/cross_entity_state_dependency/distribution_create_requires_usable_material
        """
        ctx = setup_cycle_adopted()
        file_material_challenge(ctx["material"]["id"], filer_id="cm1")
        material = get_material(ctx["material"]["id"])
        assert material["adoption_status"] == "ADOPTED"
        assert material["availability_status"] == "UNDER_CHALLENGE"

        # ADOPTED but frozen: the create fails on the availability dimension.
        validate_error(
            api.create_distribution_order(
                {"material_id": ctx["material"]["id"], "school_code": "SCH-A",
                 "classroom_label": "RM-101", "quantity": 1,
                 "need_priority": 1}, WAREHOUSE),
            ApiErrorId.ERR_MATERIAL_FROZEN)

    def test_distribution_create_succeeds_after_upheld_challenge(self, api):
        """PRD §3.9: "For a material target: `UPHELD` returns availability
        from `UNDER_CHALLENGE` to `USABLE`"
        PRD §3.7: "A new order starts `REQUESTED`."

        Design: Difficulty/cross_entity_state_dependency/distribution_create_requires_usable_material
        """
        ctx = setup_decided_material_challenge(
            votes=(("v1", "UPHOLD"), ("v2", "UPHOLD"), ("v3", "UPHOLD")))
        assert get_material(ctx["material"]["id"])["availability_status"] == \
            "USABLE"
        resp = api.create_distribution_order(
            {"material_id": ctx["material"]["id"], "school_code": "SCH-A",
             "classroom_label": "RM-101", "quantity": 1, "need_priority": 1},
            WAREHOUSE)
        assert resp.status_code == 201
        assert resp.json()["data"]["status"] == "REQUESTED"


class TestApproveInventoryBoundary:
    def test_distribution_approve_exact_fit_boundary(self, api):
        """PRD §3.7: "an exactly equal availability passes, leaving
        `available_units` at zero, while a shortfall fails with
        `ERR_INSUFFICIENT_INVENTORY`."

        Design: Corner/validations/distribution_approve_exact_fit_boundary
        """
        ctx = setup_cycle_distributing()  # lot on_hand 10, allocated 0
        material_id = ctx["material"]["id"]
        do_over = create_distribution_order(material_id, school_code="SCH-A",
                                            classroom_label="RM-101",
                                            quantity=11, need_priority=1)
        do_exact = create_distribution_order(material_id, school_code="SCH-B",
                                             classroom_label="RM-201",
                                             quantity=10, need_priority=1)

        validate_error(api.transition_distribution_order(
            do_over["id"], {"to_state": "APPROVED"}, WAREHOUSE),
            ApiErrorId.ERR_INSUFFICIENT_INVENTORY)

        approved = transition_distribution_order(do_exact["id"], "APPROVED")
        assert approved["status"] == "APPROVED"
        assert get_lot(material_id)["available_units"] == 0, (
            "an exact fit leaves zero available")


class TestFreezeOutranksInventory:
    def _frozen_order(self, api, lot_qty, do_qty):
        """Adopted material with `lot_qty` units on hand, a REQUESTED order
        of `do_qty`, then an open challenge freezing the material."""
        ctx = setup_cycle_distributing(po_print_quantity=lot_qty)
        order = create_distribution_order(ctx["material"]["id"], quantity=do_qty,
                                          school_code="SCH-A",
                                          classroom_label="RM-101",
                                          need_priority=3)
        file_material_challenge(ctx["material"]["id"], filer_id="cm1")
        assert get_material(ctx["material"]["id"])["availability_status"] == \
            "UNDER_CHALLENGE"
        return ctx, order

    def test_frozen_beats_insufficient_inventory(self, api):
        """PRD §3.7: "the freeze check runs before the inventory check, so a
        non-`USABLE` material fails with `ERR_MATERIAL_FROZEN` even when stock
        would have sufficed"

        Design: Difficulty/priority_pair_validation_conflict/do_approve_frozen_outranks_inventory
        """
        # Stock is short (2 on hand vs 5 requested) AND the material is
        # frozen: the safety error must win over the inventory error.
        ctx, order = self._frozen_order(api, lot_qty=2, do_qty=5)
        validate_error(api.transition_distribution_order(
            order["id"], {"to_state": "APPROVED"}, WAREHOUSE),
            ApiErrorId.ERR_MATERIAL_FROZEN)
        assert get_distribution_order(order["id"],
                                      ctx["material"]["id"])["status"] == \
            "REQUESTED"
        assert get_lot(ctx["material"]["id"])["allocated_units"] == 0

    def test_frozen_fires_even_with_sufficient_stock(self, api):
        """PRD §3.7: "the freeze check runs before the inventory check, so a
        non-`USABLE` material fails with `ERR_MATERIAL_FROZEN` even when stock
        would have sufficed"

        Design: Difficulty/priority_pair_validation_conflict/do_approve_frozen_outranks_inventory
        """
        # 10 on hand vs 5 requested: stock would have sufficed, but the
        # freeze check runs first.
        ctx, order = self._frozen_order(api, lot_qty=10, do_qty=5)
        validate_error(api.transition_distribution_order(
            order["id"], {"to_state": "APPROVED"}, WAREHOUSE),
            ApiErrorId.ERR_MATERIAL_FROZEN)
        assert get_lot(ctx["material"]["id"])["allocated_units"] == 0


class TestInventoryUnitConservation:
    def test_ship_and_school_receipt_conserve_units(self, api):
        """PRD §2.11: "Units are conserved by invariant: at every instant,
        `total_received_units` equals the sum of `on_hand_units`,
        `in_transit_units`, and `delivered_units`."
        PRD §3.7: "shipments subtract the shipped `quantity` from
        `on_hand_units` and `allocated_units` while adding it to
        `in_transit_units` (leaving `available_units` unchanged, since the
        stock was already spoken for); school receipts subtract the quantity
        from `in_transit_units` and add it to `delivered_units`"

        Design: Difficulty/compensating_invariant/inventory_units_conservation
        """
        ctx = setup_cycle_distributing()  # on_hand 10
        material_id = ctx["material"]["id"]
        order = create_distribution_order(material_id, school_code="SCH-A",
                                          classroom_label="RM-101", quantity=4,
                                          need_priority=3)
        transition_distribution_order(order["id"], "APPROVED")
        transition_distribution_order(order["id"], "SHIPPED")

        lot = get_lot(material_id)
        assert lot["on_hand_units"] == 6
        assert lot["in_transit_units"] == 4
        assert lot["delivered_units"] == 0
        assert_inventory_unit_conservation(lot)

        transition_distribution_order(order["id"], "RECEIVED")
        lot = get_lot(material_id)
        assert lot["on_hand_units"] == 6
        assert lot["in_transit_units"] == 0
        assert lot["delivered_units"] == 4
        assert lot["total_received_units"] == 10
        assert_inventory_unit_conservation(lot)

    def test_approve_cancel_pair_releases_allocation_exactly(self, api):
        """PRD §3.7: "a cancelled approval releases its `allocated_units`."
        PRD §2.11: "Two further figures are derived rather than stored:
        `allocated_units`, the sum of `quantity` over the material's
        distribution orders in `APPROVED` status, and `available_units`, the
        `on_hand_units` minus the `allocated_units`."

        Design: Difficulty/compensating_invariant/inventory_units_conservation
        """
        ctx = setup_cycle_distributing()  # on_hand 10, allocated 0
        material_id = ctx["material"]["id"]
        before = get_lot(material_id)
        assert before["available_units"] == 10

        order = create_distribution_order(material_id, school_code="SCH-B",
                                          classroom_label="RM-201", quantity=3,
                                          need_priority=2)
        transition_distribution_order(order["id"], "APPROVED")
        assert get_lot(material_id)["available_units"] == 7

        transition_distribution_order(order["id"], "CANCELLED")
        after = get_lot(material_id)
        assert after["allocated_units"] == 0, "allocation released"
        assert after["available_units"] == 10, (
            "the approve/cancel pair leaves availability exactly unchanged")
        assert_inventory_unit_conservation(after)


class TestReceiptBackorderPromotion:
    def _setup_backorders(self, api):
        """PROCURING cycle; three BACKORDERED orders (A: prio 4 qty 6 created
        first; B: prio 4 qty 2 created second; C: prio 5 qty 3 created last);
        PO for 8 print units issued."""
        ctx = setup_cycle_procuring(
            quote_specs=(
                {"publisher_name": "PubA", "print_unit_price": 10.00,
                 "print_quantity": 8, "digital_seat_rate": 0,
                 "digital_seat_count": 0, "training_sessions": 0,
                 "license_years": 0},
                {"publisher_name": "PubB", "print_unit_price": 12.00,
                 "print_quantity": 8, "digital_seat_rate": 0,
                 "digital_seat_count": 0, "training_sessions": 0,
                 "license_years": 0},
            ))
        material_id = ctx["material"]["id"]
        do_a = create_distribution_order(material_id, school_code="SCH-A",
                                         classroom_label="RM-A", quantity=6,
                                         need_priority=4)
        transition_distribution_order(do_a["id"], "BACKORDERED")
        do_b = create_distribution_order(material_id, school_code="SCH-B",
                                         classroom_label="RM-B", quantity=2,
                                         need_priority=4)
        transition_distribution_order(do_b["id"], "BACKORDERED")
        do_c = create_distribution_order(material_id, school_code="SCH-C",
                                         classroom_label="RM-C", quantity=3,
                                         need_priority=5)
        transition_distribution_order(do_c["id"], "BACKORDERED")
        po = create_po_fresh(ctx["cycle"]["id"], ctx["selected_quote"]["id"], 8)
        issue_po(po["id"])
        return ctx, do_a, do_b, do_c, po

    def test_promotion_ranking_and_head_of_line_blocking(self, api):
        """PRD §3.7: "Each receipt runs a promotion pass over the received
        material's `BACKORDERED` orders, ranked by `need_priority` descending
        with ties broken by `created_at` ascending. The head of that ranking
        is promoted to `APPROVED` — committing its `quantity` into
        `allocated_units` — for as long as the head fits within
        `available_units`; the pass stops at the first order that does not
        fit, and later orders are not considered, a strict head-of-line
        blocking discipline."

        Design: Difficulty/transitive_cascade/receipt_backorder_promotion_cascade
        """
        ctx, do_a, do_b, do_c, po = self._setup_backorders(api)
        receive_po(po["id"], 8)  # on_hand 8

        material_id = ctx["material"]["id"]
        # Highest priority first: C (prio 5, qty 3) fits and is promoted
        # despite being created last. Remaining availability is 5, so the
        # next head A (prio 4, qty 6, earliest tie) does not fit — the pass
        # stops, and B is never considered even though its 2 would fit.
        assert get_distribution_order(do_c["id"], material_id)["status"] == \
            "APPROVED"
        assert get_distribution_order(do_a["id"], material_id)["status"] == \
            "BACKORDERED"
        assert get_distribution_order(do_b["id"], material_id)["status"] == \
            "BACKORDERED"

    def test_promotion_recomputes_lot_and_backorder_count(self, api):
        """PRD §3.7: "The cycle's `open_backorder_count` is the number of its
        adopted material's distribution orders sitting in `BACKORDERED`,
        recomputed on every allocation event"
        PRD §3.6: "the very first receipt posted for the cycle advances the
        cycle itself from `PROCURING` to `DISTRIBUTING` automatically."

        Design: Difficulty/transitive_cascade/receipt_backorder_promotion_cascade
        """
        ctx, do_a, do_b, do_c, po = self._setup_backorders(api)
        receive_po(po["id"], 8)

        lot = get_lot(ctx["material"]["id"])
        assert lot["on_hand_units"] == 8
        assert lot["allocated_units"] == 3, "only C's 3 units committed"
        assert lot["available_units"] == 5
        assert_inventory_unit_conservation(lot)

        cycle = get_cycle(ctx["cycle"]["id"])
        assert cycle["open_backorder_count"] == 2, "A and B remain backordered"
        assert cycle["status"] == "DISTRIBUTING", "first-receipt auto-advance"
