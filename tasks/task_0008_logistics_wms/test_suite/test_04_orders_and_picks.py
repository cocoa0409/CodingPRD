"""Order creation, allocation, lot selector (FEFO/FIFO), pick task lifecycle,
short-pick handling, and replan."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_order_payload, create_wave_payload,
    create_pick_complete_payload, create_pack_payload,
    create_warehouse, create_bin, create_lot, putaway_lot_units,
    setup_warehouse_with_inventory, create_allocated_order,
    setup_released_wave_for_order, get_pick_tasks_for_order,
    setup_picking_pick_task, setup_two_lots_same_sku,
    TEST_USERS, NON_EXISTENT_UUID,
)


class TestOrderCreation:
    def test_create_order_initial_status(self, api, staff_headers, manager_headers):
        """PRD §3.4: "New orders begin life with status CREATED. The order's
        wave_id, provisional_carton_count, final_carton_count,
        shipping_label_id, and tracking_number are all empty at creation
        and are populated by later transitions."

        Claim: POST /orders → status CREATED with empty downstream fields.
        """
        wh = create_warehouse()
        order = validate_success(api.create_order(
            wh["id"],
            create_order_payload(
                requested_lines=[{"sku": "PEN", "qty_units": 5}],
                order_number="ORD-INIT", carrier="UPS"),
            staff_headers), 201)
        assert order["status"] == "CREATED"
        assert order.get("wave_id") is None
        assert order.get("provisional_carton_count") in (None, 0) or order.get("provisional_carton_count") is None
        assert order.get("final_carton_count") is None
        assert order.get("shipping_label_id") is None
        assert order.get("tracking_number") is None

    def test_create_order_default_pick_strategy_fefo(self, api, staff_headers):
        """PRD §3.4: "an optional pick_strategy that defaults to FEFO when
        the request omits it (the alternative is FIFO)"

        Claim: omitting pick_strategy yields default FEFO.
        """
        wh = create_warehouse()
        payload = create_order_payload(
            requested_lines=[{"sku": "PEN", "qty_units": 5}],
            order_number="ORD-DEFAULT", carrier="UPS")
        # No pick_strategy in payload
        assert "pick_strategy" not in payload
        order = validate_success(api.create_order(wh["id"], payload, staff_headers), 201)
        assert order["pick_strategy"] == "FEFO"

    @pytest.mark.parametrize("carrier", ["UPS", "FEDEX", "USPS"])
    def test_create_order_each_valid_carrier(self, api, staff_headers, carrier):
        """PRD §3.4: "a carrier chosen from UPS, FEDEX, or USPS"

        Claim: each valid carrier value is accepted.
        """
        wh = create_warehouse()
        order = validate_success(api.create_order(
            wh["id"],
            create_order_payload(
                requested_lines=[{"sku": "PEN", "qty_units": 1}],
                order_number=f"ORD-{carrier}", carrier=carrier),
            staff_headers), 201)
        assert order["carrier"] == carrier

    def test_create_order_invalid_carrier_rejected(self, api, staff_headers):
        """PRD §3.4: "a carrier chosen from UPS, FEDEX, or USPS (any other
        value is rejected with ERR_INVALID_INPUT and HTTP status 422)"

        Claim: an invalid carrier value yields ERR_INVALID_INPUT (422).
        """
        wh = create_warehouse()
        validate_error(api.create_order(
            wh["id"],
            create_order_payload(
                requested_lines=[{"sku": "PEN", "qty_units": 1}],
                order_number="ORD-INV", carrier="DHL"),
            staff_headers), "ERR_INVALID_INPUT")


class TestAllocationFEFO:
    def test_fefo_picks_earlier_expiring_lot(self, api, staff_headers, manager_headers):
        """PRD §3.4: "under the FEFO strategy the primary sort key is the
        lot's expiry_date in ascending order — the earliest-expiring lot
        is consumed first"

        # difficulty: dual_variant_calc/pick_lot_selection_fefo_vs_fifo
        Claim: with two lots of identical SKU (LOT_A: earlier received_at,
        later expiry; LOT_B: later received_at, earlier expiry), FEFO
        allocates from LOT_B (earlier expiry).
        """
        wh, b, lot_a, lot_b = setup_two_lots_same_sku(
            sku="PEN",
            lot_a_received_at_clock="2025-01-01T00:00:00.000Z",
            lot_a_expiry="2030-06-01T00:00:00.000Z",
            lot_b_received_at_clock="2025-02-01T00:00:00.000Z",
            lot_b_expiry="2025-12-31T00:00:00.000Z",
            lot_a_units=50, lot_b_units=50,
        )
        order = create_allocated_order(
            wh["id"], sku="PEN", qty_units=30, pick_strategy="FEFO",
            order_number="ORD-FEFO",
        )
        pick_tasks = get_pick_tasks_for_order(wh["id"], order["id"])
        assert len(pick_tasks) == 1, f"FEFO should produce 1 pick task with sufficient inventory, got {len(pick_tasks)}"
        assert pick_tasks[0]["lot_id"] == lot_b["id"], \
            "FEFO must pick LOT_B (earlier expiry)"
        assert pick_tasks[0]["planned_units"] == 30


class TestAllocationFIFO:
    def test_fifo_picks_earlier_received_lot(self, api, staff_headers, manager_headers):
        """PRD §3.4: "under the FIFO strategy the primary sort key is the
        lot's received_at in ascending order — the earliest-received lot
        is consumed first, and expiry_date is irrelevant."

        # difficulty: dual_variant_calc/pick_lot_selection_fefo_vs_fifo
        Claim: with two lots of identical SKU (LOT_A: earlier received_at,
        later expiry; LOT_B: later received_at, earlier expiry), FIFO
        allocates from LOT_A (earlier received_at).
        """
        wh, b, lot_a, lot_b = setup_two_lots_same_sku(
            sku="PEN",
            lot_a_received_at_clock="2025-01-01T00:00:00.000Z",
            lot_a_expiry="2030-06-01T00:00:00.000Z",
            lot_b_received_at_clock="2025-02-01T00:00:00.000Z",
            lot_b_expiry="2025-12-31T00:00:00.000Z",
            lot_a_units=50, lot_b_units=50,
        )
        order = create_allocated_order(
            wh["id"], sku="PEN", qty_units=30, pick_strategy="FIFO",
            order_number="ORD-FIFO",
        )
        pick_tasks = get_pick_tasks_for_order(wh["id"], order["id"])
        assert len(pick_tasks) == 1, f"FIFO should produce 1 pick task with sufficient inventory, got {len(pick_tasks)}"
        assert pick_tasks[0]["lot_id"] == lot_a["id"], \
            "FIFO must pick LOT_A (earlier received_at)"
        assert pick_tasks[0]["planned_units"] == 30


class TestAllocationInventoryGuards:
    def test_allocate_insufficient_inventory(self, api, staff_headers, manager_headers):
        """PRD §3.4: "every requested line must be fully satisfiable from
        inventory rows whose lot status is in ACTIVE or NEAR_EXPIRY
        (otherwise ERR_INSUFFICIENT_INVENTORY)"

        Claim: requesting more units than total available → ERR_INSUFFICIENT_INVENTORY.
        """
        wh, b, lot = setup_warehouse_with_inventory(units=10, sku="PEN")
        order = validate_success(api.create_order(
            wh["id"],
            create_order_payload(
                requested_lines=[{"sku": "PEN", "qty_units": 50}],
                order_number="ORD-OVER", carrier="UPS"),
            staff_headers), 201)
        validate_error(api.allocate_order(wh["id"], order["id"], staff_headers),
                      "ERR_INSUFFICIENT_INVENTORY")

    def test_allocate_excludes_recalled_lots(self, api, staff_headers, manager_headers):
        """PRD §3.4: "Any candidate lot whose status is RECALLED or EXPIRED
        is excluded from the candidate set up-front; if the resulting set
        cannot fully satisfy the line, the response is still
        ERR_INSUFFICIENT_INVENTORY."

        Claim: when the only candidate inventory belongs to a RECALLED lot,
        allocate fails ERR_INSUFFICIENT_INVENTORY.
        """
        wh, b, lot = setup_warehouse_with_inventory(units=20, sku="PEN")
        # Recall the only lot
        from test_helpers import create_recall_payload
        validate_success(api.recall_lot(
            wh["id"], lot["id"], create_recall_payload("SAFETY_ISSUE"),
            TEST_USERS["manager_headers"]), 200)
        order = validate_success(api.create_order(
            wh["id"],
            create_order_payload(
                requested_lines=[{"sku": "PEN", "qty_units": 5}],
                order_number="ORD-RECALL", carrier="UPS"),
            staff_headers), 201)
        validate_error(api.allocate_order(wh["id"], order["id"], staff_headers),
                      "ERR_INSUFFICIENT_INVENTORY")


class TestAllocationPostureGate:
    def test_allocate_blocked_by_frozen_posture(self, api, staff_headers, manager_headers):
        """PRD §3.4: "first, the warehouse posture must be OPEN or RESTRICTED
        (otherwise ERR_POSTURE_FROZEN)"
        PRD §3.1: "when risk_score is greater than 200 the posture is FROZEN"

        # difficulty: cross_entity_state_dependency/order_allocate_depends_on_warehouse_posture
        Claim: an order in a FROZEN-posture warehouse cannot be allocated
        even if inventory exists.
        """
        from test_helpers import setup_warehouse_with_recalls
        wh = setup_warehouse_with_recalls(num_recalls=3)
        assert wh["posture"] == "FROZEN"
        # Now create good inventory
        b = create_bin(wh["id"], bin_code="OPEN-BIN",
                      capacity_volume_cm3=100000, capacity_weight_g=100000)
        lot = create_lot(wh["id"], sku="GOOD", category="AMBIENT")
        putaway_lot_units(wh["id"], lot["id"], 30)
        order = validate_success(api.create_order(
            wh["id"],
            create_order_payload(
                requested_lines=[{"sku": "GOOD", "qty_units": 5}],
                order_number="ORD-FROZ", carrier="UPS"),
            staff_headers), 201)
        validate_error(api.allocate_order(wh["id"], order["id"], staff_headers),
                      "ERR_POSTURE_FROZEN")


class TestAllocationSideEffects:
    def test_allocate_increments_reserved_units(self, api, staff_headers):
        """PRD §3.4: "A successful allocation generates pick tasks per the
        lot-selector rule, increases each consumed inventory row's
        reserved_units by the units allocated to the corresponding pick
        task, and sets the order's provisional_carton_count"

        # difficulty: compensating_invariant/reserved_units_invariant_allocate_then_cancel (forward leg)
        Claim: after allocate, the source inventory row's reserved_units
        equals the pick task's planned_units.
        """
        wh, b, lot = setup_warehouse_with_inventory(units=50, sku="PEN")
        from test_helpers import get_inventory_row
        inv_before = get_inventory_row(wh["id"], b["id"], lot["id"])
        assert inv_before["reserved_units"] == 0
        order = create_allocated_order(
            wh["id"], sku="PEN", qty_units=30, order_number="ORD-RESV",
        )
        assert order["status"] == "ALLOCATED"
        inv_after = get_inventory_row(wh["id"], b["id"], lot["id"])
        assert inv_after["reserved_units"] == 30
        assert inv_after["qty_units"] == 50  # qty_units unchanged
        assert inv_after["available_units"] == 20  # 50 - 30


class TestOrderCancelSideEffects:
    def test_allocated_cancel_releases_reservations(self, api, staff_headers):
        """PRD §3.4: "An ALLOCATED order may be cancelled with no preconditions;
        cancellation cascades all of its CREATED pick tasks to CANCELLED and
        reduces each consumed inventory row's reserved_units by the per-task
        planned_units of the cancelled pick task."

        # difficulty: compensating_invariant/reserved_units_invariant_allocate_then_cancel (compensating leg)
        Claim: after allocate→cancel, reserved_units returns to its pre-allocate value;
        pick tasks transition CREATED→CANCELLED.
        """
        wh, b, lot = setup_warehouse_with_inventory(units=50, sku="PEN")
        from test_helpers import get_inventory_row
        pre = get_inventory_row(wh["id"], b["id"], lot["id"])
        order = create_allocated_order(
            wh["id"], sku="PEN", qty_units=30, order_number="ORD-CXL",
        )
        # Cancel
        cancelled = validate_success(api.cancel_order(
            wh["id"], order["id"], staff_headers), 200)
        assert cancelled["status"] == "CANCELLED"
        # PickTasks → CANCELLED
        pick_tasks = get_pick_tasks_for_order(wh["id"], order["id"])
        for pt in pick_tasks:
            assert pt["status"] == "CANCELLED"
        # Reservations released
        post = get_inventory_row(wh["id"], b["id"], lot["id"])
        assert post["reserved_units"] == pre["reserved_units"]
        assert post["qty_units"] == pre["qty_units"]


class TestPickTaskStart:
    def test_start_pick_task_to_picking(self, api, staff_headers):
        """PRD §3.6: "Starting a pick task takes it from CREATED to PICKING"

        Claim: /pick_tasks/{id}/start transitions a CREATED task to PICKING.
        """
        wh, b, lot, order, wave, pt = setup_picking_pick_task()
        assert pt["status"] == "PICKING"

    def test_start_pick_task_advances_order_and_wave(self, api, staff_headers):
        """PRD §3.6: "On the first such start within a wave, the wave
        automatically advances from RELEASED to IN_PROGRESS; on the first
        such start within an order, the order automatically advances from
        ALLOCATED to PICKING."

        Claim: starting the first pick task in an order/wave moves the
        parent order to PICKING and the parent wave to IN_PROGRESS.
        """
        wh, b, lot, order, wave, pt = setup_picking_pick_task()
        order_after = validate_success(api.get_order(wh["id"], order["id"], staff_headers), 200)
        wave_after = validate_success(api.get_wave(wh["id"], wave["id"], staff_headers), 200)
        assert order_after["status"] == "PICKING"
        assert wave_after["status"] == "IN_PROGRESS"

    def test_start_pick_task_when_lot_recalled_invalid_state(self, api, staff_headers, manager_headers):
        """PRD §2.6 priority rules 5 and 6: state-eligibility check (priority 5,
        ERR_INVALID_STATE) is evaluated before lot-pickability check
        (priority 6, ERR_LOT_NOT_PICKABLE).

        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_pick_start
        Claim: when a pick task is in CANCELLED state AND its lot is RECALLED,
        the higher-priority state check wins → ERR_INVALID_STATE (not
        ERR_LOT_NOT_PICKABLE).
        """
        wh, b, lot = setup_warehouse_with_inventory(units=50, sku="PEN")
        order = create_allocated_order(
            wh["id"], sku="PEN", qty_units=10, order_number="ORD-PRI",
        )
        # Cancel the order to push pick tasks to CANCELLED
        validate_success(api.cancel_order(wh["id"], order["id"], staff_headers), 200)
        # Recall the lot to push it to RECALLED
        from test_helpers import create_recall_payload
        validate_success(api.recall_lot(
            wh["id"], lot["id"], create_recall_payload("SAFETY_ISSUE"),
            TEST_USERS["manager_headers"]), 200)
        pick_tasks = get_pick_tasks_for_order(wh["id"], order["id"])
        pt = pick_tasks[0]
        assert pt["status"] == "CANCELLED"
        validate_error(api.start_pick_task(
            wh["id"], pt["id"], staff_headers), "ERR_INVALID_STATE")

    def test_start_pick_task_when_bin_frozen(self, api, staff_headers, manager_headers):
        """PRD §3.6: "the source bin's status must be ACTIVE (otherwise ERR_BIN_FROZEN)"

        # difficulty: cross_entity_state_dependency/pick_task_depends_on_bin_status
        Claim: starting a pick task whose source bin is FROZEN by a cycle
        count → ERR_BIN_FROZEN.
        """
        wh, b, lot = setup_warehouse_with_inventory(units=30, sku="PEN")
        order = create_allocated_order(
            wh["id"], sku="PEN", qty_units=10, order_number="ORD-PT-FROZ",
        )
        wave = setup_released_wave_for_order(wh["id"], order["id"])
        # Schedule cycle count to freeze the bin
        from test_helpers import create_cycle_count_payload
        validate_success(api.create_cycle_count(
            wh["id"],
            create_cycle_count_payload(b["id"], lot["id"]),
            staff_headers), 201)
        # Confirm bin frozen
        bin_after = validate_success(api.get_bin(wh["id"], b["id"], staff_headers), 200)
        assert bin_after["status"] == "FROZEN"
        pick_tasks = get_pick_tasks_for_order(wh["id"], order["id"])
        pt = pick_tasks[0]
        validate_error(api.start_pick_task(
            wh["id"], pt["id"], staff_headers), "ERR_BIN_FROZEN")


class TestPickTaskComplete:
    def test_complete_pick_task_full_match(self, api, staff_headers):
        """PRD §3.6: "When picked_units exactly equals planned_units, the
        pick task moves from PICKING to PICKED and Wave.picked_unit_count
        is increased by picked_units."

        Claim: full picked_units → PickTask.PICKED; wave.picked_unit_count += picked_units.
        """
        wh, b, lot, order, wave, pt = setup_picking_pick_task(order_qty=10)
        wave_before = validate_success(api.get_wave(wh["id"], wave["id"], staff_headers), 200)
        result = validate_success(api.complete_pick_task(
            wh["id"], pt["id"], create_pick_complete_payload(10), staff_headers), 200)
        assert result["status"] == "PICKED"
        assert result["picked_units"] == 10
        wave_after = validate_success(api.get_wave(wh["id"], wave["id"], staff_headers), 200)
        assert wave_after["picked_unit_count"] == wave_before.get("picked_unit_count", 0) + 10

    def test_complete_pick_task_short_pick(self, api, staff_headers):
        """PRD §3.6: "When picked_units is at least 0 and strictly less than
        planned_units, the pick task moves from PICKING to SHORT_PICKED:
        the system writes picked_units from the body onto the pick task,
        releases the unpicked reservation by decreasing the source inventory
        row's reserved_units by the difference between planned_units and
        picked_units, and increases Wave.picked_unit_count by picked_units."

        Claim: short pick → SHORT_PICKED; reserved_units decreased by the
        unpicked amount.
        """
        wh, b, lot, order, wave, pt = setup_picking_pick_task(order_qty=10)
        from test_helpers import get_inventory_row
        inv_before = get_inventory_row(wh["id"], b["id"], lot["id"])
        result = validate_success(api.complete_pick_task(
            wh["id"], pt["id"], create_pick_complete_payload(7), staff_headers), 200)
        assert result["status"] == "SHORT_PICKED"
        assert result["picked_units"] == 7
        inv_after = get_inventory_row(wh["id"], b["id"], lot["id"])
        # planned_units was 10, picked 7 → released 3 from reservations
        assert inv_after["reserved_units"] == inv_before["reserved_units"] - 3

    @pytest.mark.parametrize("picked_units", [-1, 11])
    def test_complete_pick_task_picked_units_out_of_bounds(self, api, staff_headers, picked_units):
        """PRD §3.6: "Completion of a pick task takes a picked_units count in
        the request body that must be at least 0 and at most planned_units
        (any other value yields ERR_INVALID_INPUT with HTTP status 422)."

        Claim: picked_units < 0 or > planned_units → ERR_INVALID_INPUT (422).
        """
        wh, b, lot, order, wave, pt = setup_picking_pick_task(order_qty=10)
        validate_error(api.complete_pick_task(
            wh["id"], pt["id"],
            create_pick_complete_payload(picked_units),
            staff_headers), "ERR_INVALID_INPUT")

    def test_short_pick_rolls_up_order_to_short_picked(self, api, staff_headers):
        """PRD §3.6: "If every pick task is terminal and at least one is
        SHORT_PICKED or FAILED, the order moves from PICKING to SHORT_PICKED
        and abnormal_event_count_24h on the warehouse is incremented by 1."

        Claim: a single short-picked pick task on an order with one task
        rolls the order up to SHORT_PICKED and increments abnormal counter.
        """
        wh, b, lot, order, wave, pt = setup_picking_pick_task(order_qty=10)
        before = validate_success(api.get_warehouse(wh["id"], staff_headers), 200)
        validate_success(api.complete_pick_task(
            wh["id"], pt["id"], create_pick_complete_payload(7), staff_headers), 200)
        order_after = validate_success(api.get_order(wh["id"], order["id"], staff_headers), 200)
        assert order_after["status"] == "SHORT_PICKED"
        after = validate_success(api.get_warehouse(wh["id"], staff_headers), 200)
        assert after["abnormal_event_count_24h"] == before["abnormal_event_count_24h"] + 1


class TestReplan:
    def test_replan_short_picked_to_allocated(self, api, staff_headers):
        """PRD §3.6: "A SHORT_PICKED order may be replanned by floor staff,
        sending it back to ALLOCATED. ... The terminal pick tasks from the
        previous round are retained for audit; new pick tasks are generated
        for the residual units (each line's planned_units minus the sum of
        picked_units over its existing terminal pick tasks for that lot or
        sku); reservations on inventory rows are adjusted by the new pick
        tasks' planned_units"

        # difficulty: non_linear_state_machine/order_short_picked_to_allocated_cycle
        Claim: /replan on SHORT_PICKED order moves it back to ALLOCATED;
        a new pick task is created with planned_units = residual; original
        pick task is retained in SHORT_PICKED for audit.
        """
        wh, b, lot, order, wave, pt = setup_picking_pick_task(order_qty=30)
        # Short pick: 10 of 30
        validate_success(api.complete_pick_task(
            wh["id"], pt["id"], create_pick_complete_payload(10), staff_headers), 200)
        order_short = validate_success(api.get_order(wh["id"], order["id"], staff_headers), 200)
        assert order_short["status"] == "SHORT_PICKED"
        # Replan
        replanned = validate_success(api.replan_order(
            wh["id"], order["id"], staff_headers), 200)
        assert replanned["status"] == "ALLOCATED"
        # Check: original pt still SHORT_PICKED; new pt with planned_units=20 in CREATED
        pick_tasks = get_pick_tasks_for_order(wh["id"], order["id"])
        statuses = [pt["status"] for pt in pick_tasks]
        assert "SHORT_PICKED" in statuses, "Original SHORT_PICKED pick task should be retained"
        new_picks = [pt for pt in pick_tasks if pt["status"] == "CREATED"]
        assert len(new_picks) >= 1, "Replan should create at least one new pick task"
        assert new_picks[0]["planned_units"] == 20  # residual: 30 - 10

    def test_replan_blocked_by_frozen_posture(self, api, staff_headers, manager_headers):
        """PRD §3.6: "The same posture gate as initial allocation applies —
        replan is rejected with ERR_POSTURE_FROZEN while posture is FROZEN."

        Claim: with warehouse posture FROZEN, replan on a SHORT_PICKED
        order → ERR_POSTURE_FROZEN.
        """
        wh, b, lot, order, wave, pt = setup_picking_pick_task(order_qty=30, sku="PEN")
        # Short-pick
        validate_success(api.complete_pick_task(
            wh["id"], pt["id"], create_pick_complete_payload(10), staff_headers), 200)
        # Now drive posture FROZEN by recalling 3 unrelated lots
        for i in range(3):
            unrelated_lot = create_lot(wh["id"], sku=f"OTHER_{i}",
                                       lot_code=f"REC_{i}_{order['id'][:6]}")
            from test_helpers import create_recall_payload
            validate_success(api.recall_lot(
                wh["id"], unrelated_lot["id"],
                create_recall_payload("SUPPLIER_RECALL"),
                TEST_USERS["manager_headers"]), 200)
        wh_now = validate_success(api.get_warehouse(wh["id"], staff_headers), 200)
        # The lot we used (already recalled cascade aside, the abnormal count from short-pick
        # contributes too); only proceed if posture is actually FROZEN
        # If it's not FROZEN due to other dynamics, we add one more recall
        if wh_now["posture"] != "FROZEN":
            extra_lot = create_lot(wh["id"], sku="EXTRA",
                                  lot_code=f"EXTRA_{order['id'][:6]}")
            from test_helpers import create_recall_payload
            validate_success(api.recall_lot(
                wh["id"], extra_lot["id"],
                create_recall_payload("SUPPLIER_RECALL"),
                TEST_USERS["manager_headers"]), 200)
            wh_now = validate_success(api.get_warehouse(wh["id"], staff_headers), 200)
        assert wh_now["posture"] == "FROZEN"
        validate_error(api.replan_order(
            wh["id"], order["id"], staff_headers), "ERR_POSTURE_FROZEN")
