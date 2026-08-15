"""Sheller contracts, delivery calls, allocation selector, delivery cascades,
reconciliation tolerance, hull lots, and the warehouse partition invariant."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_warehouse,
    allocate_call,
    api_client,
    assert_allocation_line,
    create_active_contract,
    create_delivery_call_payload,
    deliver_call,
    get_buying_point,
    get_load,
    get_storage_receipt,
    get_warehouse,
    issue_call,
    list_hull_lots_for_call,
    list_lines_for_call,
    make_sheller_rep_headers,
    pledge_full_receipt,
    reconcile_call,
    sell_hull_lot,
    set_clock,
    setup_buying_point,
    setup_settlement_foundation,
    setup_stored_load,
    setup_reconciled_call,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
SHELLER = TEST_USERS["sheller_rep_headers"]


class TestContractGuards:

    def test_contract_remaining_boundary(self):
        """PRD section 3.8: "A contract's open commitment,
        `remaining_units_tons`, is the total minus fulfilled tonnage minus the
        requested tonnage of its `ISSUED` and `ALLOCATED` calls."
        PRD section 3.8: "The requested tonnage must not exceed the contract's
        `remaining_units_tons` (`ERR_CONTRACT_REMAINING_EXCEEDED`)."

        Design: Corner/errors/contract_remaining_boundary
        """
        bp = _bp_with_warehouse()
        contract = create_active_contract(bp["id"], total_units_tons=20.0)
        call1 = issue_call(contract["id"], 20.0)
        assert call1["status"] == "ISSUED"

        contract_after = api_client.get_sheller_contract(
            contract["id"], ADMIN).json()["data"]
        assert contract_after["remaining_units_tons"] == 0

        resp = api_client.create_delivery_call(
            create_delivery_call_payload(
                contract_id=contract["id"], requested_tons=0.001,
                dock_window_start="2026-09-12T08:00:00Z",
                dock_window_end="2026-09-12T12:00:00Z"), SHELLER)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_REMAINING_EXCEEDED)

    def test_contract_cancel_with_open_call_rejected(self):
        """PRD section 3.8: "Cancellation from `DRAFT` or `ACTIVE` is blocked
        while any call is `ISSUED` or `ALLOCATED`
        (`ERR_CONTRACT_HAS_OPEN_CALLS`)."

        Design: Corner/errors/contract_cancel_with_open_call_rejected
        """
        bp = _bp_with_warehouse()
        contract = create_active_contract(bp["id"], total_units_tons=20.0)
        call = issue_call(contract["id"], 10.0)

        resp = api_client.cancel_sheller_contract(contract["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_HAS_OPEN_CALLS)
        contract_mid = api_client.get_sheller_contract(
            contract["id"], ADMIN).json()["data"]
        assert contract_mid["status"] == "ACTIVE"

        api_client.cancel_delivery_call(call["id"], SHELLER)
        cancelled = validate_success(
            api_client.cancel_sheller_contract(contract["id"], ADMIN))
        assert cancelled["status"] == "CANCELLED"


class TestDockWindows:

    def test_dock_window_containment_boundary(self):
        """PRD section 3.8: "an inclusive contract window from `window_start`
        to `window_end`".
        PRD section 3.8: "The dock window must fit fully inside the contract
        window (`ERR_DOCK_WINDOW_OUTSIDE_CONTRACT`)."

        Design: Corner/validations/dock_window_containment_boundary
        """
        bp = _bp_with_warehouse()
        contract = create_active_contract(bp["id"], total_units_tons=100.0)

        ok = validate_success(api_client.create_delivery_call(
            create_delivery_call_payload(
                contract_id=contract["id"], requested_tons=10.0,
                dock_window_start="2026-10-31T20:00:00Z",
                dock_window_end="2026-11-01T00:00:00Z"), SHELLER),
            expected_status=201)
        assert ok["status"] == "ISSUED", \
            "dock_window_end == window_end is inside the inclusive window"

        resp = api_client.create_delivery_call(
            create_delivery_call_payload(
                contract_id=contract["id"], requested_tons=10.0,
                dock_window_start="2026-11-01T05:00:00Z",
                dock_window_end="2026-11-01T08:00:00Z"), SHELLER)
        validate_error(resp, ApiErrorId.ERR_DOCK_WINDOW_OUTSIDE_CONTRACT)

    def test_dock_window_buffer_rejects_start_inside_turnaround(self):
        """PRD section 3.8: "dock windows on the same contract may not crowd
        each other: each call's closed window, expanded by a 120-minute
        turnaround buffer on both sides, must not intersect any other
        non-terminal call's buffered window on that contract
        (`ERR_DOCK_WINDOW_OVERLAP`)."

        Design: Difficulty/resource_temporal_overlap/dock_window_closed_interval_buffer
        """
        bp = _bp_with_warehouse()
        contract = create_active_contract(bp["id"], total_units_tons=100.0)
        call_a = issue_call(contract["id"], 10.0,
                            dock_window_start="2026-09-10T08:00:00Z",
                            dock_window_end="2026-09-10T14:00:00Z")
        assert call_a["status"] == "ISSUED"

        # 60 minutes after the first window's inclusive end: inside the buffer.
        resp = api_client.create_delivery_call(
            create_delivery_call_payload(
                contract_id=contract["id"], requested_tons=10.0,
                dock_window_start="2026-09-10T15:00:00Z",
                dock_window_end="2026-09-10T18:00:00Z"), SHELLER)
        validate_error(resp, ApiErrorId.ERR_DOCK_WINDOW_OVERLAP)

    def test_dock_window_buffer_boundary_start_allowed(self):
        """PRD section 3.8: "each call's closed window, expanded by a
        120-minute turnaround buffer on both sides, must not intersect any
        other non-terminal call's buffered window on that contract
        (`ERR_DOCK_WINDOW_OVERLAP`)."

        Design: Difficulty/resource_temporal_overlap/dock_window_closed_interval_buffer
        """
        bp = _bp_with_warehouse()
        contract = create_active_contract(bp["id"], total_units_tons=100.0)
        issue_call(contract["id"], 10.0,
                   dock_window_start="2026-09-10T08:00:00Z",
                   dock_window_end="2026-09-10T14:00:00Z")

        # First call's buffered window is [06:00, 16:00]. A start at 16:00
        # buffers to [14:00, 20:00], overlapping by two hours: rejected.
        resp = api_client.create_delivery_call(
            create_delivery_call_payload(
                contract_id=contract["id"], requested_tons=10.0,
                dock_window_start="2026-09-10T16:00:00Z",
                dock_window_end="2026-09-10T18:00:00Z"), SHELLER)
        validate_error(resp, ApiErrorId.ERR_DOCK_WINDOW_OVERLAP)

        # Start at 18:01 (241 minutes after the first window's end): buffered
        # window [16:01, ...] clears [06:00, 16:00] entirely — accepted.
        # (Exactly end+240min would make the buffered windows touch at one
        # instant; the PRD does not pin that touch case, so it is not probed.)
        ok = validate_success(api_client.create_delivery_call(
            create_delivery_call_payload(
                contract_id=contract["id"], requested_tons=10.0,
                dock_window_start="2026-09-10T18:01:00Z",
                dock_window_end="2026-09-10T20:00:00Z"), SHELLER),
            expected_status=201)
        assert ok["status"] == "ISSUED"


class TestAllocation:

    def test_allocate_state_error_beats_fiscal_error(self):
        """PRD section 2.9: "When several checks could fire on the same
        request, the server evaluates them in a fixed order and reports the
        first failure" — with "State preconditions" at priority 6 and "Fiscal
        limits" at priority 11.
        PRD section 3.8: "If the eligible receipts in total cannot cover the
        requested tonnage, the whole allocation is rejected with
        `ERR_INSUFFICIENT_ALLOCABLE_TONS` and no partial set of lines is
        persisted."

        Design: Difficulty/priority_pair_validation_conflict/allocate_state_error_beats_fiscal_error
        """
        bp = _bp_with_warehouse()  # warehouse exists but holds no stock
        contract = create_active_contract(bp["id"], total_units_tons=40.0)
        call1 = issue_call(contract["id"], 20.0)
        cancelled = validate_success(
            api_client.cancel_delivery_call(call1["id"], ADMIN))

        # Dual failure: CANCELLED call AND zero eligible stock -> state wins.
        resp = api_client.allocate_delivery_call(
            call1["id"], {"expected_delivery_call_version": cancelled["version"]},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_allocate_insufficient_allocable_when_state_clean(self):
        """PRD section 3.8: "If the eligible receipts in total cannot cover the
        requested tonnage, the whole allocation is rejected with
        `ERR_INSUFFICIENT_ALLOCABLE_TONS` and no partial set of lines is
        persisted."

        Design: Difficulty/priority_pair_validation_conflict/allocate_state_error_beats_fiscal_error
        """
        bp = _bp_with_warehouse()
        contract = create_active_contract(bp["id"], total_units_tons=40.0)
        call2 = issue_call(contract["id"], 20.0,
                           dock_window_start="2026-09-11T08:00:00Z",
                           dock_window_end="2026-09-11T12:00:00Z")

        resp = api_client.allocate_delivery_call(
            call2["id"], {"expected_delivery_call_version": call2["version"]},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_ALLOCABLE_TONS)

        call_after = api_client.get_delivery_call(call2["id"], ADMIN).json()["data"]
        assert call_after["status"] == "ISSUED"
        assert list_lines_for_call(call2["id"]) == []

    def test_allocation_selector_skips_pledged_receipt(self):
        """PRD section 3.8: "The selector walks the buying point's eligible
        receipts — `OPEN` receipts with positive `tons_remaining` in warehouses
        of the call's contract's buying point, excluding `segregated` receipts
        unless the contract's `accepts_segregated` allows them — in
        first-in-first-out order: ascending `stored_at`, ties broken by
        ascending `created_at`, never by identifier."
        PRD section 3.7: "the receipt moves `OPEN` → `PLEDGED`".

        Design: Difficulty/cross_entity_state_dependency/allocation_selector_skips_pledged_receipt
        """
        f, rcpt_a, rcpt_b, call = _setup_two_receipts_one_pledged()
        allocated = allocate_call(call["id"], call["version"])
        assert allocated["status"] == "ALLOCATED"

        lines = list_lines_for_call(call["id"])
        assert len(lines) == 1
        assert lines[0]["storage_receipt_id"] == rcpt_b["id"], \
            "FIFO-earlier receipt was PLEDGED and must be skipped"
        assert lines[0]["allocated_tons"] == 20.0

        rcpt_a_after = get_storage_receipt(rcpt_a["id"])
        assert rcpt_a_after["status"] == "PLEDGED"
        assert rcpt_a_after["tons_remaining"] == 25.0
        assert get_warehouse(f["warehouse"]["id"])["reserved_tons"] == 20

    def test_allocation_deliver_ships_only_from_open_receipt(self):
        """PRD section 3.8: "each line's `shipped_tons` becomes its
        `allocated_tons`, each contributing receipt's `tons_remaining` falls by
        the shipped tonnage (a receipt reaching zero closes and flips its load
        to `DEPLETED`)".

        Design: Difficulty/cross_entity_state_dependency/allocation_selector_skips_pledged_receipt
        """
        f, rcpt_a, rcpt_b, call = _setup_two_receipts_one_pledged()
        allocate_call(call["id"], call["version"])
        delivered = deliver_call(call["id"])
        assert delivered["status"] == "DELIVERED"
        assert delivered["delivered_tons"] == 20.0

        rcpt_b_after = get_storage_receipt(rcpt_b["id"])
        assert rcpt_b_after["tons_remaining"] == 5.0
        assert rcpt_b_after["status"] == "OPEN"
        rcpt_a_after = get_storage_receipt(rcpt_a["id"])
        assert rcpt_a_after["status"] == "PLEDGED"
        assert rcpt_a_after["tons_remaining"] == 25.0

    def test_occ_allocate_stale_call_version(self):
        """PRD section 2.8: "Allocating (or re-allocating) a delivery call
        requires `expected_delivery_call_version`, carrying the client's
        last-observed `version` of the call."
        PRD section 2.8: "if the supplied value does not match the parent
        entity's current `version` — because another writer has advanced that
        version since the client last read the parent — the request is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."
        PRD section 3.8: "Re-allocating an `ALLOCATED` call is permitted under
        the same OCC rule".

        Design: Corner/cross_cutting/occ_allocate_stale_call_version
        """
        f = setup_settlement_foundation()
        setup_stored_load(f["grower"]["id"], f["warehouse"]["id"])
        contract = create_active_contract(f["bp"]["id"], total_units_tons=20.0)
        call = issue_call(contract["id"], 20.0)
        observed_v = call["version"]

        allocated = allocate_call(call["id"], observed_v)
        assert allocated["status"] == "ALLOCATED"
        assert allocated["allocated_tons"] == 20.0
        assert allocated["version"] == observed_v + 1

        # Re-allocation is a valid transition, but the stale version loses.
        resp = api_client.allocate_delivery_call(
            call["id"], {"expected_delivery_call_version": observed_v}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        lines = list_lines_for_call(call["id"])
        assert len(lines) == 1
        assert lines[0]["allocated_tons"] == 20.0

    def test_allocation_line_has_no_version_field(self):
        """PRD section 2.4: "One entity breaks this convention: an
        `AllocationLine` is a system-created junction record and carries only
        `id` and `created_at`. Both `updated_at` and `version` are absent from
        allocation lines."

        Design: Corner/entities/allocation_line_has_no_version_field
        """
        f = setup_settlement_foundation()
        setup_stored_load(f["grower"]["id"], f["warehouse"]["id"])
        contract = create_active_contract(f["bp"]["id"], total_units_tons=20.0)
        call = issue_call(contract["id"], 20.0)
        allocate_call(call["id"], call["version"])

        lines = list_lines_for_call(call["id"])
        assert len(lines) == 1
        line = lines[0]
        assert_allocation_line(line)
        assert line["allocated_tons"] == 20.0
        assert line["shipped_tons"] == 0
        assert line["shelled_tons"] == 0


class TestDeliverCascade:

    def _setup_suspended_by_reservation(self):
        """One 600t load in a 620t warehouse; a 20t call allocated so that
        free tonnage is exactly 0 (posture SUSPENDED)."""
        f = setup_settlement_foundation(quota_tons=1000,
                                        warehouse_capacity=620)
        load, sheet, cert, receipt = setup_stored_load(
            f["grower"]["id"], f["warehouse"]["id"], gross_tons=600.0,
            moisture_pct=9.2, foreign_material_pct=0.0, damage_pct=0.0,
            lsk_pct=0.0, result_ppb=3.0)
        contract = create_active_contract(f["bp"]["id"], total_units_tons=20.0)
        call = issue_call(contract["id"], 20.0)
        allocate_call(call["id"], call["version"])
        return f, load, receipt, contract, call

    def test_deliver_cascade_depth4_line_to_posture(self):
        """PRD section 3.8: "Delivery executes the allocation as a full
        truckout: each line's `shipped_tons` becomes its `allocated_tons`, each
        contributing receipt's `tons_remaining` falls by the shipped tonnage
        (a receipt reaching zero closes and flips its load to `DEPLETED`), each
        warehouse's `stored_tons` and `reserved_tons` fall by the shipped
        amount, and the posture recomputes."
        PRD section 2.7: "When aggregate free tonnage is above zero but no more
        than 500 tons, the posture is `RESTRICTED`".

        Design: Difficulty/transitive_cascade/deliver_cascade_depth4_line_to_posture
        """
        f, load, receipt, contract, call = self._setup_suspended_by_reservation()
        assert get_buying_point(f["bp"]["id"])["intake_posture"] == "SUSPENDED", \
            "620 capacity - 600 stored - 20 reserved = 0 free => SUSPENDED"

        deliver_call(call["id"])

        lines = list_lines_for_call(call["id"])
        assert len(lines) == 1
        assert lines[0]["shipped_tons"] == 20.0

        receipt_after = get_storage_receipt(receipt["id"])
        assert receipt_after["tons_remaining"] == 580.0
        assert receipt_after["status"] == "OPEN", "partial shipment does not close"

        wh = get_warehouse(f["warehouse"]["id"])
        assert wh["stored_tons"] == 580
        assert wh["reserved_tons"] == 0
        assert wh["free_tons"] == 40

        bp_after = get_buying_point(f["bp"]["id"])
        assert bp_after["intake_posture"] == "RESTRICTED", \
            "0 < 40 <= 500 => RESTRICTED — reached only through the full chain"
        assert get_load(load["id"])["status"] == "STORED"

    def test_deliver_fulfills_contract_at_equality(self):
        """PRD section 3.8: "the contract's `fulfilled_units_tons` rises by the
        delivered tonnage — and when fulfillment reaches or exceeds the
        contracted total, equality included, the contract moves `ACTIVE` →
        `FULFILLED` and no further delivery calls may be created against it".

        Design: Difficulty/transitive_cascade/deliver_cascade_depth4_line_to_posture
        """
        f, load, receipt, contract, call = self._setup_suspended_by_reservation()
        deliver_call(call["id"])

        contract_after = api_client.get_sheller_contract(
            contract["id"], ADMIN).json()["data"]
        assert contract_after["fulfilled_units_tons"] == 20.0
        assert contract_after["status"] == "FULFILLED", \
            "fulfilled 20 >= total 20: equality counts"

        resp = api_client.create_delivery_call(
            create_delivery_call_payload(contract_id=contract["id"],
                                         requested_tons=1.0), SHELLER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestOpsDefaultCascade:

    def test_contract_defaults_after_two_call_defaults(self):
        """PRD section 3.8: "Every `ISSUED` or `ALLOCATED` call of this buying
        point whose `dock_window_end` falls strictly before the current logical
        clock, processed in ascending `dock_window_end` order with ties broken
        by ascending `created_at`, becomes `DEFAULTED`: an allocated call's
        lines are deleted and reservations released, the contract's
        `default_count` increments by one, and when the count reaches the limit
        of 2 the contract moves `ACTIVE` → `DEFAULTED`".

        Design: Corner/state_machines/contract_defaults_after_two_call_defaults
        """
        bp = _bp_with_warehouse()
        contract = create_active_contract(
            bp["id"], total_units_tons=100.0,
            window_start="2026-09-01T00:00:00Z",
            window_end="2026-09-20T00:00:00Z")
        call_a = issue_call(contract["id"], 10.0,
                            dock_window_start="2026-09-14T08:00:00Z",
                            dock_window_end="2026-09-14T12:00:00Z")
        call_b = issue_call(contract["id"], 10.0,
                            dock_window_start="2026-09-15T08:00:00Z",
                            dock_window_end="2026-09-15T12:00:00Z")
        set_clock("2026-09-21T00:00:00Z")

        api_client.run_ops(bp["id"], ADMIN)

        a_after = api_client.get_delivery_call(call_a["id"], ADMIN).json()["data"]
        b_after = api_client.get_delivery_call(call_b["id"], ADMIN).json()["data"]
        assert a_after["status"] == "DEFAULTED"
        assert b_after["status"] == "DEFAULTED"

        contract_after = api_client.get_sheller_contract(
            contract["id"], ADMIN).json()["data"]
        assert contract_after["default_count"] == 2
        assert contract_after["status"] == "DEFAULTED"

        resp = api_client.create_delivery_call(
            create_delivery_call_payload(
                contract_id=contract["id"], requested_tons=5.0,
                dock_window_start="2026-09-10T08:00:00Z",
                dock_window_end="2026-09-10T12:00:00Z"), SHELLER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_allocated_call_default_releases_reservation(self):
        """PRD section 3.8: "becomes `DEFAULTED`: an allocated call's lines are
        deleted and reservations released, the contract's `default_count`
        increments by one".

        Design: Corner/state_machines/allocated_call_default_releases_reservation
        """
        f = setup_settlement_foundation()
        setup_stored_load(f["grower"]["id"], f["warehouse"]["id"])
        contract = create_active_contract(
            f["bp"]["id"], total_units_tons=100.0,
            window_start="2026-09-01T00:00:00Z",
            window_end="2026-09-20T00:00:00Z")
        call = issue_call(contract["id"], 10.0,
                          dock_window_start="2026-09-14T08:00:00Z",
                          dock_window_end="2026-09-14T12:00:00Z")
        allocate_call(call["id"], call["version"])
        assert get_warehouse(f["warehouse"]["id"])["reserved_tons"] == 10

        set_clock("2026-09-21T00:00:00Z")
        api_client.run_ops(f["bp"]["id"], ADMIN)

        call_after = api_client.get_delivery_call(call["id"], ADMIN).json()["data"]
        assert call_after["status"] == "DEFAULTED"
        wh = get_warehouse(f["warehouse"]["id"])
        assert wh["reserved_tons"] == 0
        assert wh["free_tons"] == 1975
        contract_after = api_client.get_sheller_contract(
            contract["id"], ADMIN).json()["data"]
        assert contract_after["default_count"] == 1
        assert contract_after["status"] == "ACTIVE"
        assert list_lines_for_call(call["id"]) == []


class TestReconcileAndHull:

    def test_reconcile_shrink_boundary(self):
        """PRD section 3.8: "the two together may not exceed the delivered
        tonnage, and the unaccounted remainder — delivered minus shelled kernel
        minus hull — may not exceed one percent of the delivered tonnage, or
        the reconcile is rejected with `ERR_HULL_RECONCILE_MISMATCH`."

        Design: Corner/validations/reconcile_shrink_boundary
        """
        f = setup_settlement_foundation()
        setup_stored_load(f["grower"]["id"], f["warehouse"]["id"],
                          gross_tons=50.0, moisture_pct=8.0,
                          foreign_material_pct=0.0, damage_pct=0.0, lsk_pct=0.0,
                          result_ppb=4.0)
        contract = create_active_contract(f["bp"]["id"], total_units_tons=100.0)
        call1 = issue_call(contract["id"], 20.0)
        allocate_call(call1["id"], call1["version"])
        deliver_call(call1["id"])
        call2 = issue_call(contract["id"], 20.0,
                           dock_window_start="2026-09-11T08:00:00Z",
                           dock_window_end="2026-09-11T12:00:00Z")
        allocate_call(call2["id"], call2["version"])
        deliver_call(call2["id"])

        # shrink exactly 0.2 == 1% of 20 delivered: allowed
        ok = reconcile_call(call1["id"], 16.0, 3.8)
        assert ok["status"] == "RECONCILED"

        # shrink 0.21 > 1%: rejected
        resp = api_client.reconcile_delivery_call(
            call2["id"], {"shelled_kernel_tons": 16.0, "hull_tons": 3.79}, SHELLER)
        validate_error(resp, ApiErrorId.ERR_HULL_RECONCILE_MISMATCH)

        # over-report: 16.5 + 3.6 = 20.1 > 20 delivered: rejected
        resp = api_client.reconcile_delivery_call(
            call2["id"], {"shelled_kernel_tons": 16.5, "hull_tons": 3.6}, SHELLER)
        validate_error(resp, ApiErrorId.ERR_HULL_RECONCILE_MISMATCH)

        mid = api_client.get_delivery_call(call2["id"], ADMIN).json()["data"]
        assert mid["status"] == "DELIVERED"

        ok2 = reconcile_call(call2["id"], 16.0, 3.8)
        assert ok2["status"] == "RECONCILED"

    def test_hull_lot_lifecycle_and_terminal_lockdown(self):
        """PRD section 3.9: "A hull lot in `GENERATED` may be listed for sale
        by an administrator, which records `sale_price_cents_per_ton` and moves
        it to `LISTED`. Selling a listed lot stamps `sold_at` from the logical
        clock, computes `revenue_cents` as the lot's tonnage times its sale
        price per ton rounded half up to whole cents, moves it to `SOLD`, and
        enters its revenue into the hull pool for future settlements. A lot in
        `GENERATED` or `LISTED` may instead be disposed of, which records a
        `disposition_ref` manifest reference and moves it to `DISPOSED`;
        disposed lots never enter the revenue pool."

        Design: Corner/state_machines/hull_lot_lifecycle_and_terminal_lockdown
        """
        f = setup_settlement_foundation()
        env = setup_reconciled_call(f["grower"], f["warehouse"], f["bp"]["id"])
        lot = list_hull_lots_for_call(env["call"]["id"])[0]
        assert lot["tons"] == 3.8
        assert lot["status"] == "GENERATED"

        resp = api_client.sell_hull_lot(lot["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        sold = sell_hull_lot(lot["id"], sale_price_cents_per_ton=4000)
        assert sold["status"] == "SOLD"
        assert sold["revenue_cents"] == 15200  # round_half_up(3.8 x 4000)
        assert sold["sold_at"].startswith("2026-09-01T09:00:00")

        resp = api_client.dispose_hull_lot(lot["id"],
                                           {"disposition_ref": "MANIFEST-9"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_fk_reverse_lookup_lists(self):
        """PRD section 3.4: "Grade sheets may be listed with `load_id`,
        `schedule_id`, and `status` filters."
        PRD section 3.5: "Certificates may be listed with `load_id` and
        `status` filters."
        PRD section 3.7: "Receipts may be listed with `warehouse_id`,
        `load_id`, and `status` filters."
        PRD section 3.8: "discoverable through the allocation-line list with
        `delivery_call_id` and `storage_receipt_id` filters."
        PRD section 3.9: "Hull lots may be listed with `delivery_call_id` and
        `status` filters."

        Design: Corner/endpoints/fk_reverse_lookup_lists
        """
        f = setup_settlement_foundation()
        env = setup_reconciled_call(f["grower"], f["warehouse"], f["bp"]["id"])
        load_id = env["load"]["id"]
        call_id = env["call"]["id"]
        receipt_id = env["receipt"]["id"]

        _d, meta = validate_paginated(api_client.list_grade_sheets(
            ADMIN, params={"load_id": load_id}))
        assert meta["total_count"] == 1

        _d, meta = validate_paginated(api_client.list_aflatoxin_certificates(
            ADMIN, params={"load_id": load_id}))
        assert meta["total_count"] == 1

        _d, meta = validate_paginated(api_client.list_storage_receipts(
            ADMIN, params={"warehouse_id": f["warehouse"]["id"]}))
        assert meta["total_count"] == 1

        lines_by_call, meta = validate_paginated(api_client.list_allocation_lines(
            ADMIN, params={"delivery_call_id": call_id}))
        assert meta["total_count"] == 1
        lines_by_rcpt, meta = validate_paginated(api_client.list_allocation_lines(
            ADMIN, params={"storage_receipt_id": receipt_id}))
        assert meta["total_count"] == 1
        assert lines_by_call[0]["id"] == lines_by_rcpt[0]["id"]

        lots, meta = validate_paginated(api_client.list_hull_lots(
            ADMIN, params={"delivery_call_id": call_id}))
        assert meta["total_count"] == 1
        assert lots[0]["tons"] == 3.8


class TestWarehousePartitionInvariant:

    def test_partition_forward_and_compensating_legs(self):
        """PRD section 2.7: "for each warehouse, `free_tons` is its
        `capacity_tons` minus `stored_tons` minus `reserved_tons`".
        PRD section 3.8: "from `ALLOCATED` it additionally deletes the
        allocation lines, releases their warehouse reservations, and recomputes
        the posture."

        Design: Difficulty/compensating_invariant/warehouse_tons_partition_invariant
        """
        f = setup_settlement_foundation()
        setup_stored_load(f["grower"]["id"], f["warehouse"]["id"])
        wh_id = f["warehouse"]["id"]

        wh = get_warehouse(wh_id)
        assert (wh["stored_tons"], wh["reserved_tons"], wh["free_tons"]) == (25, 0, 1975)
        assert wh["stored_tons"] + wh["reserved_tons"] + wh["free_tons"] == 2000

        contract = create_active_contract(f["bp"]["id"], total_units_tons=100.0)
        call1 = issue_call(contract["id"], 10.0)
        allocate_call(call1["id"], call1["version"])
        wh = get_warehouse(wh_id)
        assert (wh["stored_tons"], wh["reserved_tons"], wh["free_tons"]) == (25, 10, 1965)
        assert wh["stored_tons"] + wh["reserved_tons"] + wh["free_tons"] == 2000

        api_client.cancel_delivery_call(call1["id"], ADMIN)
        wh = get_warehouse(wh_id)
        assert (wh["stored_tons"], wh["reserved_tons"], wh["free_tons"]) == (25, 0, 1975), \
            "cancel returns the reservation with zero drift"
        assert wh["stored_tons"] + wh["reserved_tons"] + wh["free_tons"] == 2000

    def test_partition_after_deliver(self):
        """PRD section 3.8: "each warehouse's `stored_tons` and `reserved_tons`
        fall by the shipped amount, and the posture recomputes."
        PRD section 2.7: "for each warehouse, `free_tons` is its
        `capacity_tons` minus `stored_tons` minus `reserved_tons`".

        Design: Difficulty/compensating_invariant/warehouse_tons_partition_invariant
        """
        f = setup_settlement_foundation()
        _load, _s, _c, receipt = setup_stored_load(
            f["grower"]["id"], f["warehouse"]["id"])
        wh_id = f["warehouse"]["id"]
        contract = create_active_contract(f["bp"]["id"], total_units_tons=100.0)
        call2 = issue_call(contract["id"], 10.0,
                           dock_window_start="2026-09-12T08:00:00Z",
                           dock_window_end="2026-09-12T12:00:00Z")
        allocate_call(call2["id"], call2["version"])
        deliver_call(call2["id"])

        wh = get_warehouse(wh_id)
        assert (wh["stored_tons"], wh["reserved_tons"], wh["free_tons"]) == (15, 0, 1985)
        assert wh["stored_tons"] + wh["reserved_tons"] + wh["free_tons"] == 2000
        assert get_storage_receipt(receipt["id"])["tons_remaining"] == 15.0


class TestShellerRepRBAC:

    def test_sheller_rep_cannot_allocate_returns_forbidden(self):
        """PRD section 4: the allocate row lists only `BuyingPointAdmin`.
        PRD section 2.1: "A request whose role is recognized but not permitted
        for the target operation is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/sheller_rep_cannot_allocate_returns_forbidden
        """
        bp = _bp_with_warehouse()
        contract = create_active_contract(bp["id"], total_units_tons=20.0)
        call = issue_call(contract["id"], 20.0)
        resp = api_client.allocate_delivery_call(
            call["id"], {"expected_delivery_call_version": call["version"]},
            SHELLER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        call_after = api_client.get_delivery_call(call["id"], ADMIN).json()["data"]
        assert call_after["status"] == "ISSUED"

    def test_sheller_rep_foreign_contract_call_forbidden(self):
        """PRD section 2.1: "a sheller representative may act only on contracts
        whose `sheller_ref` equals `X-User-ID`, and on the delivery calls of
        those contracts; acting outside that scope is rejected with
        `ERR_OWNERSHIP_FORBIDDEN`."

        Design: Corner/rbac/sheller_rep_foreign_contract_call_forbidden
        """
        bp = _bp_with_warehouse()
        contract = create_active_contract(bp["id"], total_units_tons=20.0)
        resp = api_client.create_delivery_call(
            create_delivery_call_payload(contract_id=contract["id"],
                                         requested_tons=5.0),
            make_sheller_rep_headers("sheller-other"))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_FORBIDDEN)


# ---------------------------------------------------------------------------
# Local composites
# ---------------------------------------------------------------------------

def _bp_with_warehouse():
    bp = setup_buying_point()
    add_warehouse(bp["id"])
    return bp


def _setup_two_receipts_one_pledged():
    """Two 25.0t stored receipts (rcptA FIFO-first at 09:00, rcptB at 10:00);
    rcptA fully pledged. Returns (foundation, rcptA, rcptB, issued_call)."""
    f = setup_settlement_foundation()
    gid = f["grower"]["id"]
    _la, _sa, _ca, rcpt_a = setup_stored_load(gid, f["warehouse"]["id"])
    set_clock("2026-09-01T10:00:00Z")
    _lb, _sb, _cb, rcpt_b = setup_stored_load(gid, f["warehouse"]["id"])
    pledge_full_receipt(gid, rcpt_a["id"], pledged_tons=25.0)
    contract = create_active_contract(f["bp"]["id"], total_units_tons=20.0)
    call = issue_call(contract["id"], 20.0)
    return f, rcpt_a, rcpt_b, call
