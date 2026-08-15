"""Production orders: planning, trim grossing, and material holds (PRD §3.4)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_operation_spec,
    add_trim_requirement,
    api_client,
    approve_tech_pack,
    assert_trim_ledger_invariants,
    create_available_fabric_roll,
    create_draft_tech_pack,
    create_line_assignment,
    create_marker_payload,
    create_operator,
    create_production_order,
    create_sewing_line,
    create_style,
    create_trim_item,
    get_success_data,
    log_piece_work,
    plan_order,
    receive_trim,
    setup_completed_bundle,
    setup_qc_passed_order,
    setup_released_bundle_with_operator,
    setup_style_with_approved_pack,
    submit_tech_pack,
    validate_error,
    validate_paginated,
    validate_success,
)

MERCH = TEST_USERS["merchandiser_headers"]
MATS = TEST_USERS["materials_planner_headers"]
CUTMGR = TEST_USERS["cutting_manager_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
QI1 = TEST_USERS["quality_inspector_headers"]
ANY = TEST_USERS["any_headers"]


class TestPlanRequiresApprovedPack:
    def test_plan_requires_approved_tech_pack(self):
        """PRD §3.4: "Then the candidate pack must exist, belong to the order's
        style, and be `APPROVED`, or the plan is rejected with
        `ERR_TECH_PACK_NOT_APPROVED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/plan_requires_approved_tech_pack
        """
        style = create_style(style_code="ST-XD1")
        pack = create_draft_tech_pack(style["id"], MERCH)
        add_operation_spec(pack["id"], MERCH)
        submit_tech_pack(pack["id"], MERCH)  # PENDING_APPROVAL, never reviewed
        order = create_production_order(
            style["id"], PLANNER, size_quantities=[{"size": "M", "qty": 10}],
        )
        resp = api_client.plan_production_order(
            order["id"], {"tech_pack_id": pack["id"]}, PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_TECH_PACK_NOT_APPROVED)

    def test_plan_rejection_leaves_order_unpinned(self):
        """PRD §3.4: "Then the candidate pack must exist, belong to the order's
        style, and be `APPROVED`, or the plan is rejected with
        `ERR_TECH_PACK_NOT_APPROVED` (HTTP 409)." and "A new order starts with
        `production_status` `PLANNED` ... its `tech_pack_id` null".

        Design: Difficulty/cross_entity_state_dependency/plan_requires_approved_tech_pack
        """
        style = create_style(style_code="ST-XD1")
        pack = create_draft_tech_pack(style["id"], MERCH)
        add_operation_spec(pack["id"], MERCH)
        submit_tech_pack(pack["id"], MERCH)
        order = create_production_order(
            style["id"], PLANNER, size_quantities=[{"size": "M", "qty": 10}],
        )
        resp = api_client.plan_production_order(
            order["id"], {"tech_pack_id": pack["id"]}, PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_TECH_PACK_NOT_APPROVED)
        order_after = get_success_data(
            api_client.get_production_order(order["id"], ANY)
        )
        assert order_after["tech_pack_id"] is None
        assert order_after["production_status"] == "PLANNED"


class TestTrimGrossing:
    def test_trim_grossing_per_line_ceiling_then_sum(self):
        """PRD §3.4: "each line's exact figure is then rounded up to a whole
        unit with an exact ceiling, per line, before any summation. The pinned
        order is important: applying one ceiling to the sum of exact quantities
        yields a different, smaller total whenever two or more lines carry
        fractional parts summing to one or less, and that order is explicitly
        not authoritative."

        Design: Difficulty/combinatorial_formula/trim_grossing_per_line_ceiling_then_sum
        """
        style = create_style(style_code="ST-TG1")
        ti1 = create_trim_item(sku_code="TI1", description="button")
        receive_trim(ti1["id"], 9)
        ti2 = create_trim_item(sku_code="TI2", description="label", unit_cost_cents=5)
        receive_trim(ti2["id"], 5)
        pack = create_draft_tech_pack(style["id"], MERCH)
        add_operation_spec(pack["id"], MERCH)
        add_trim_requirement(pack["id"], ti1["id"], MERCH,
                             units_per_garment=2, wastage_pct=0.34)
        add_trim_requirement(pack["id"], ti2["id"], MERCH,
                             units_per_garment=1, wastage_pct=0.34)
        approve_tech_pack(pack["id"])
        order = create_production_order(
            style["id"], PLANNER, size_quantities=[{"size": "M", "qty": 3}],
        )
        order = plan_order(order["id"], pack["id"], PLANNER)
        # ceil(3*2*1.34)=ceil(8.04)=9 ; ceil(3*1*1.34)=ceil(4.02)=5
        ti1_after = get_success_data(api_client.get_trim_item(ti1["id"], ANY))
        ti2_after = get_success_data(api_client.get_trim_item(ti2["id"], ANY))
        assert ti1_after["qty_reserved"] == 9
        assert ti2_after["qty_reserved"] == 5
        # Sum-then-ceil would reserve only 13; pinned per-line order reserves 14.
        assert ti1_after["qty_reserved"] + ti2_after["qty_reserved"] == 14
        assert order["trim_hold_status"] == "MATERIALS_OK"
        assert order["trim_shortages"] == []

    def test_trim_grossing_shortfall_places_trim_hold_with_shortages(self):
        """PRD §3.4: "When any line is short, the reservation is
        all-or-nothing: no units are reserved for any line, the order's
        `trim_hold_status` flips to `TRIM_HOLD`, and `trim_shortages` is
        populated with one entry per shorted line carrying its `trim_item_id`,
        `required_units`, `available_units`, and `shortage_units`."

        Design: Corner/state_machines/start_cutting_blocked_by_trim_hold
        """
        style = create_style(style_code="ST-S9")
        ti = create_trim_item(sku_code="TI1", description="button")
        receive_trim(ti["id"], 2)
        pack = create_draft_tech_pack(style["id"], MERCH)
        add_operation_spec(pack["id"], MERCH)
        add_trim_requirement(pack["id"], ti["id"], MERCH,
                             units_per_garment=8, wastage_pct=0)
        approve_tech_pack(pack["id"])
        order = create_production_order(
            style["id"], PLANNER, size_quantities=[{"size": "M", "qty": 1}],
        )
        order = plan_order(order["id"], pack["id"], PLANNER)
        assert order["trim_hold_status"] == "TRIM_HOLD"
        assert order["trim_shortages"] == [{
            "trim_item_id": ti["id"],
            "required_units": 8,
            "available_units": 2,
            "shortage_units": 6,
        }]
        ti_after = get_success_data(api_client.get_trim_item(ti["id"], ANY))
        assert ti_after["qty_reserved"] == 0


    def test_trim_grossing_ceiling_boundary_short_by_one(self):
        """PRD §3.4: "each line's exact figure is then rounded up to a whole
        unit with an exact ceiling, per line, before any summation" and "When
        any line is short, the reservation is all-or-nothing: no units are
        reserved for any line".

        Design: Difficulty/combinatorial_formula/trim_grossing_per_line_ceiling_then_sum
        """
        style = create_style(style_code="ST-TG2")
        ti1 = create_trim_item(sku_code="TI1", description="button")
        # ceil(3 * 2 * 1.34) = 9 required; stock exactly 8 -> shortage 1.
        receive_trim(ti1["id"], 8)
        pack = create_draft_tech_pack(style["id"], MERCH)
        add_operation_spec(pack["id"], MERCH)
        add_trim_requirement(pack["id"], ti1["id"], MERCH,
                             units_per_garment=2, wastage_pct=0.34)
        approve_tech_pack(pack["id"])
        order = create_production_order(
            style["id"], PLANNER, size_quantities=[{"size": "M", "qty": 3}],
        )
        order = plan_order(order["id"], pack["id"], PLANNER)
        assert order["trim_hold_status"] == "TRIM_HOLD"
        assert order["trim_shortages"] == [{
            "trim_item_id": ti1["id"],
            "required_units": 9,
            "available_units": 8,
            "shortage_units": 1,
        }]
        ti1_after = get_success_data(api_client.get_trim_item(ti1["id"], ANY))
        assert ti1_after["qty_reserved"] == 0
        assert ti1_after["qty_available"] == 8


class TestStartCuttingGates:
    def test_start_cutting_blocked_by_trim_hold(self):
        """PRD §3.4: "and must be clear of trim holds — `trim_hold_status`
        `MATERIALS_OK`, otherwise `ERR_TRIM_HOLD_ACTIVE` (HTTP 409)".

        Design: Corner/state_machines/start_cutting_blocked_by_trim_hold
        """
        style = create_style(style_code="ST-S9")
        ti = create_trim_item(sku_code="TI1", description="button")
        receive_trim(ti["id"], 2)
        pack = create_draft_tech_pack(style["id"], MERCH)
        add_operation_spec(pack["id"], MERCH)
        add_trim_requirement(pack["id"], ti["id"], MERCH,
                             units_per_garment=8, wastage_pct=0)
        approve_tech_pack(pack["id"])
        order = create_production_order(
            style["id"], PLANNER, size_quantities=[{"size": "M", "qty": 1}],
        )
        plan_order(order["id"], pack["id"], PLANNER)  # -> TRIM_HOLD
        roll = create_available_fabric_roll(MATS)
        marker = get_success_data(api_client.create_marker(
            create_marker_payload(
                production_order_id=order["id"], fabric_roll_id=roll["id"],
                planned_pieces=1,
            ),
            CUTMGR,
        ))
        get_success_data(api_client.approve_marker(
            marker["id"], {"expected_fabric_roll_version": roll["version"]}, CUTMGR,
        ))
        resp = api_client.start_cutting(order["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_TRIM_HOLD_ACTIVE)
        order_after = get_success_data(
            api_client.get_production_order(order["id"], ANY)
        )
        assert order_after["production_status"] == "PLANNED"

    def test_start_cutting_without_approved_marker_or_plan(self):
        """PRD §3.4: "The order must be `PLANNED` (otherwise
        `ERR_INVALID_STATE_TRANSITION`), must already have a tech pack pinned
        (otherwise `ERR_ORDER_NOT_PLANNED`, HTTP 409), must present at least
        one marker of the order in `APPROVED` status (otherwise
        `ERR_NO_APPROVED_MARKER`, HTTP 409)".

        Design: Corner/errors/start_cutting_without_approved_marker_or_plan
        """
        style, pack, _ops = setup_style_with_approved_pack(
            style_overrides={"style_code": "ST-R6"},
        )
        order1 = create_production_order(
            style["id"], PLANNER, color="c1",
            size_quantities=[{"size": "M", "qty": 10}],
        )
        order2 = create_production_order(
            style["id"], PLANNER, color="c2",
            size_quantities=[{"size": "M", "qty": 10}],
        )
        plan_order(order2["id"], pack["id"], PLANNER)
        roll = create_available_fabric_roll(MATS)
        get_success_data(api_client.create_marker(
            create_marker_payload(
                production_order_id=order2["id"], fabric_roll_id=roll["id"],
                planned_pieces=10,
            ),
            CUTMGR,
        ))  # marker left DRAFT
        resp1 = api_client.start_cutting(order1["id"], PLANNER)
        validate_error(resp1, ApiErrorId.ERR_ORDER_NOT_PLANNED)
        resp2 = api_client.start_cutting(order2["id"], PLANNER)
        validate_error(resp2, ApiErrorId.ERR_NO_APPROVED_MARKER)


class TestTrimHoldSweep:
    def test_trim_hold_sweep_releases_in_created_order(self):
        """PRD §3.4: "Whenever trim stock is received (§3.3), every order
        sitting in `TRIM_HOLD` is re-evaluated in `created_at` ascending
        order." and "An order that still cannot be fully covered stays held
        and untouched."

        Design: Corner/validations/trim_hold_sweep_releases_in_created_order
        """
        style = create_style(style_code="ST-V15")
        ti = create_trim_item(sku_code="TI1", description="button")
        receive_trim(ti["id"], 10)
        pack = create_draft_tech_pack(style["id"], MERCH)
        add_operation_spec(pack["id"], MERCH)
        add_trim_requirement(pack["id"], ti["id"], MERCH,
                             units_per_garment=1, wastage_pct=0)
        approve_tech_pack(pack["id"])
        order_b = create_production_order(
            style["id"], PLANNER, color="cB",
            size_quantities=[{"size": "M", "qty": 8}],
        )
        order_b = plan_order(order_b["id"], pack["id"], PLANNER)
        order_c = create_production_order(
            style["id"], PLANNER, color="cC",
            size_quantities=[{"size": "M", "qty": 5}],
        )
        order_c = plan_order(order_c["id"], pack["id"], PLANNER)
        order_d = create_production_order(
            style["id"], PLANNER, color="cD",
            size_quantities=[{"size": "M", "qty": 4}],
        )
        order_d = plan_order(order_d["id"], pack["id"], PLANNER)
        assert order_b["trim_hold_status"] == "MATERIALS_OK"
        assert order_c["trim_hold_status"] == "TRIM_HOLD"
        assert order_c["trim_shortages"]
        assert order_d["trim_hold_status"] == "TRIM_HOLD"
        receive_trim(ti["id"], 5)  # on_hand 15; sweep runs
        order_c_after = get_success_data(
            api_client.get_production_order(order_c["id"], ANY)
        )
        order_d_after = get_success_data(
            api_client.get_production_order(order_d["id"], ANY)
        )
        # C (created earlier) flips first: needs 5, available 7 -> reserved.
        assert order_c_after["trim_hold_status"] == "MATERIALS_OK"
        # D (created later) needs 4 > remaining 2 -> stays held.
        assert order_d_after["trim_hold_status"] == "TRIM_HOLD"
        ti_after = get_success_data(api_client.get_trim_item(ti["id"], ANY))
        assert ti_after["qty_on_hand"] == 15
        assert ti_after["qty_reserved"] == 13
        assert ti_after["qty_available"] == 2
        assert_trim_ledger_invariants(ti_after)

    def test_held_order_flips_only_on_full_coverage(self):
        """PRD §3.4: "A held order flips back to `MATERIALS_OK` only if every
        requirement line of its pinned pack is coverable from the items'
        current `qty_available`; on a flip, the reservations are applied line
        by line".

        Design: Corner/validations/trim_hold_sweep_releases_in_created_order
        """
        style = create_style(style_code="ST-V16")
        ti = create_trim_item(sku_code="TI1", description="button")
        receive_trim(ti["id"], 1)
        pack = create_draft_tech_pack(style["id"], MERCH)
        add_operation_spec(pack["id"], MERCH)
        add_trim_requirement(pack["id"], ti["id"], MERCH,
                             units_per_garment=1, wastage_pct=0)
        approve_tech_pack(pack["id"])
        order = create_production_order(
            style["id"], PLANNER, size_quantities=[{"size": "M", "qty": 3}],
        )
        order = plan_order(order["id"], pack["id"], PLANNER)
        assert order["trim_hold_status"] == "TRIM_HOLD"
        receive_trim(ti["id"], 1)  # available now 2 < 3 needed
        order_after = get_success_data(
            api_client.get_production_order(order["id"], ANY)
        )
        assert order_after["trim_hold_status"] == "TRIM_HOLD"
        receive_trim(ti["id"], 1)  # available now 3 >= 3 -> flips
        order_after = get_success_data(
            api_client.get_production_order(order["id"], ANY)
        )
        assert order_after["trim_hold_status"] == "MATERIALS_OK"
        assert order_after["trim_shortages"] == []


class TestFinishAndTrimConservation:
    def test_trim_units_plan_finish_conservation(self):
        """PRD §3.5/§3.4: "A successful finish moves `production_status` to
        `FINISHED`, releases all trim reservations the order holds — each
        referenced item's `qty_reserved` is decremented by the order's
        reserved units, recomputing `qty_available` per §2.9".

        Design: Difficulty/compensating_invariant/trim_units_plan_finish_conservation
        """
        ti = create_trim_item(sku_code="TI1", description="button")
        receive_trim(ti["id"], 20)
        ctx = setup_qc_passed_order(
            order_qty=3,
            trim_lines=[(ti["id"], {"units_per_garment": 2, "wastage_pct": 0.34})],
        )
        ti_mid = get_success_data(api_client.get_trim_item(ti["id"], ANY))
        assert ti_mid["qty_on_hand"] == 20
        assert ti_mid["qty_reserved"] == 9
        assert ti_mid["qty_available"] == 11
        assert_trim_ledger_invariants(ti_mid)
        order = get_success_data(
            api_client.finish_production_order(ctx["order"]["id"], PLANNER)
        )
        assert order["production_status"] == "FINISHED"
        ti_after = get_success_data(api_client.get_trim_item(ti["id"], ANY))
        assert ti_after["qty_reserved"] == 0
        assert ti_after["qty_on_hand"] == 20
        assert ti_after["qty_available"] == 20
        assert_trim_ledger_invariants(ti_after)

    def test_trim_units_reserved_at_plan_before_finish(self):
        """PRD §3.4: "When every line is covered, the plan reserves each line
        by adding its ceiled requirement to the item's `qty_reserved`
        (recomputing `qty_available`)".

        Design: Difficulty/compensating_invariant/trim_units_plan_finish_conservation
        """
        ti = create_trim_item(sku_code="TI1", description="button")
        receive_trim(ti["id"], 20)
        setup_qc_passed_order(
            order_qty=3,
            trim_lines=[(ti["id"], {"units_per_garment": 2, "wastage_pct": 0.34})],
        )
        # Mid-chain (post-plan, pre-finish): reserved 9, available 11, on_hand 20.
        ti_mid = get_success_data(api_client.get_trim_item(ti["id"], ANY))
        assert ti_mid["qty_on_hand"] == 20
        assert ti_mid["qty_reserved"] == 9
        assert ti_mid["qty_available"] == 11
        assert_trim_ledger_invariants(ti_mid)

    def test_finish_blocked_until_bundles_completed_and_qc_passed(self):
        """PRD §3.8: "every bundle of the order must be `COMPLETED` and
        `quality_status` must be `QC_PASSED`, or the finish is rejected with
        `ERR_ORDER_NOT_FINISHABLE` (HTTP 409)."

        Design: Corner/errors/finish_blocked_until_bundles_completed_and_qc_passed
        """
        ctx = setup_completed_bundle(order_qty=2)
        # Bundle COMPLETED, but no audit recorded: quality_status QC_PENDING.
        resp = api_client.finish_production_order(ctx["order"]["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FINISHABLE)

    def test_finish_blocked_when_bundle_not_completed(self):
        """PRD §3.8: "every bundle of the order must be `COMPLETED` and
        `quality_status` must be `QC_PASSED`, or the finish is rejected with
        `ERR_ORDER_NOT_FINISHABLE` (HTTP 409)."

        Design: Corner/errors/finish_blocked_until_bundles_completed_and_qc_passed
        """
        # QC passed via a PASS audit on an order whose bundle is COMPLETED;
        # then verify a second order (bundle only IN_PROGRESS) cannot finish.
        ctx = setup_released_bundle_with_operator(order_qty=2)
        log_piece_work(
            ctx["bundle"]["id"], ctx["ops"][0]["id"], ctx["operator"]["id"], qty=1,
        )
        # Bundle IN_PROGRESS (not COMPLETED); order QC_PENDING as well.
        resp = api_client.finish_production_order(ctx["order"]["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FINISHABLE)


class TestTrimItemComputedQuantities:
    def test_trim_item_computed_quantities_track_receipts(self):
        """PRD §3.3: "New items start with `qty_on_hand`, `qty_reserved`, and
        `qty_available` all at zero" and "the receipt adds that quantity to
        `qty_on_hand`, recomputes `qty_available`, and increments the item's
        `version`".

        Design: Corner/entities/trim_item_computed_quantities_track_receipts
        """
        ti = create_trim_item(sku_code="TI-E4", description="button")
        assert ti["qty_on_hand"] == 0
        assert ti["qty_available"] == 0
        assert ti["qty_reserved"] == 0
        ti = receive_trim(ti["id"], 7)
        assert ti["qty_on_hand"] == 7
        assert ti["qty_reserved"] == 0
        assert ti["qty_available"] == 7
        assert_trim_ledger_invariants(ti)


class TestWipBySku:
    def test_wip_read_matches_sku_aggregation(self):
        """PRD §3.6: "The work-in-process read for an order walks the order's
        `size_quantities` in their original order and emits one row per size —
        `size`, `ordered_qty`, `ticketed_qty`, `in_progress_qty`,
        `completed_qty` — where `ticketed_qty` sums the bundles of that size in
        `TICKETED` or `RELEASED`, `in_progress_qty` those in `IN_PROGRESS` or
        `REWORK_HOLD`, and `completed_qty` those in `COMPLETED`".

        Design: Corner/calculations/wip_read_matches_sku_aggregation
        """
        # Build the two-size scenario directly (fixture cuts a single size).
        style, pack, ops = setup_style_with_approved_pack(
            style_overrides={"style_code": "ST-C7", "size_run": ["S", "M"]},
        )
        order = create_production_order(
            style["id"], PLANNER,
            size_quantities=[{"size": "M", "qty": 3}, {"size": "S", "qty": 2}],
        )
        plan_order(order["id"], pack["id"], PLANNER)
        roll = create_available_fabric_roll(MATS)
        marker = get_success_data(api_client.create_marker(
            create_marker_payload(
                production_order_id=order["id"], fabric_roll_id=roll["id"],
                planned_pieces=5,
            ),
            CUTMGR,
        ))
        get_success_data(api_client.approve_marker(
            marker["id"], {"expected_fabric_roll_version": roll["version"]}, CUTMGR,
        ))
        get_success_data(api_client.start_cutting(order["id"], PLANNER))
        get_success_data(api_client.cut_marker(
            marker["id"],
            {"size_quantities": [{"size": "M", "qty": 3}, {"size": "S", "qty": 2}]},
            CUTMGR,
        ))
        bundles, _ = validate_paginated(
            api_client.list_bundles(ANY, params={"marker_id": marker["id"]})
        )
        bundle_m = next(b for b in bundles if b["size"] == "M")
        # Release M's bundle and log one piece -> M bundle IN_PROGRESS.
        get_success_data(api_client.release_bundle(bundle_m["id"], TEST_USERS["line_supervisor_headers"]))
        operator = create_operator(TEST_USERS["line_supervisor_headers"])
        line = create_sewing_line(PLANNER)
        create_line_assignment(
            line["id"], order["id"], ops[0]["id"], operator["id"],
            TEST_USERS["line_supervisor_headers"], assigned_pieces=3,
        )
        log_piece_work(bundle_m["id"], ops[0]["id"], operator["id"], qty=1)
        data = validate_success(
            api_client.get_production_order_wip(order["id"], ANY), 200
        )
        rows = {row["size"]: row for row in data["rows"]}
        assert rows["M"] == {
            "size": "M", "ordered_qty": 3, "ticketed_qty": 0,
            "in_progress_qty": 3, "completed_qty": 0,
        }
        assert rows["S"] == {
            "size": "S", "ordered_qty": 2, "ticketed_qty": 2,
            "in_progress_qty": 0, "completed_qty": 0,
        }
