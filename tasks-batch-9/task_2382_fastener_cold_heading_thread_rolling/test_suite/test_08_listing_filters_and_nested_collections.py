"""Collection reads and the partial specification revision.

This module exercises the plant's read surface and its one partial write: the
production-lot listing where filters narrow the set before the page window is
applied, the nested secondary-operation collection that belongs to exactly one
parent lot, the lot that only leaves the dock once its last carton has shipped,
the strip-and-replate run that retires the earlier attempt while the relief-bake
soak is held against the logical clock, and the specification revision that
touches only the keys it was handed while re-deriving the embrittlement bake
duty. Every expectation below is taken from PRD.md.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_lot_piece_ledger,
    assert_versions_incremented,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_START = "2026-09-01T06:00:00Z"


# ---------------------------------------------------------------------------
# Local setup builders (three-lot press schedule and the two-op routing)
# ---------------------------------------------------------------------------
def _three_lots_on_one_die():
    """One die set carrying L-A (headed), L-B (setup) and L-C (setup, then held)."""
    env = fixtures.setup_master_data(clock=CLOCK_START, unplated=True)
    lot_a = fixtures.open_production_lot(
        env["spec"]["id"],
        env["wire"]["id"],
        env["tool"]["id"],
        press_code=env["press_code"],
        lot_code="L-A",
        press_window_start_at="2026-09-01T06:00:00Z",
        press_window_end_at="2026-09-01T08:00:00Z",
        planned_pieces=1000,
    )
    fixtures.report_heading(lot_a["id"], 980, 20)
    lot_b = fixtures.open_production_lot(
        env["spec"]["id"],
        env["wire"]["id"],
        env["tool"]["id"],
        press_code=env["press_code"],
        lot_code="L-B",
        press_window_start_at="2026-09-01T08:00:00Z",
        press_window_end_at="2026-09-01T10:00:00Z",
        planned_pieces=1000,
    )
    lot_c = fixtures.open_production_lot(
        env["spec"]["id"],
        env["wire"]["id"],
        env["tool"]["id"],
        press_code=env["press_code"],
        lot_code="L-C",
        press_window_start_at="2026-09-01T10:00:00Z",
        press_window_end_at="2026-09-01T12:00:00Z",
        planned_pieces=1000,
    )
    fixtures.place_hold(lot_c["id"], reason="PRESS_SETUP_AUDIT")
    env["lot_a"] = lot_a
    env["lot_b"] = lot_b
    env["lot_c"] = lot_c
    return env


def _two_lots_with_drill_and_thread_roll():
    """L-D with a closed DRILL and a pending THREAD_ROLL; L-E with a pending DRILL."""
    env = fixtures.setup_master_data(
        clock=CLOCK_START,
        unplated=True,
        spec_overrides={
            "part_number": "NP-M8-DT",
            "required_secondary_ops": ["DRILL", "THREAD_ROLL"],
        },
    )
    lot_d = fixtures.open_production_lot(
        env["spec"]["id"],
        env["wire"]["id"],
        env["tool"]["id"],
        press_code=env["press_code"],
        lot_code="L-D",
        press_window_start_at="2026-09-01T06:00:00Z",
        press_window_end_at="2026-09-01T08:00:00Z",
        planned_pieces=1000,
    )
    fixtures.report_heading(lot_d["id"], 980, 20)
    lot_e = fixtures.open_production_lot(
        env["spec"]["id"],
        env["wire"]["id"],
        env["tool"]["id"],
        press_code=env["press_code"],
        lot_code="L-E",
        press_window_start_at="2026-09-01T08:00:00Z",
        press_window_end_at="2026-09-01T10:00:00Z",
        planned_pieces=1000,
    )
    fixtures.report_heading(lot_e["id"], 980, 20)

    op_d1 = fixtures.queue_op(lot_d["id"], "DRILL", 1, "DR-1")
    fixtures.complete_op(op_d1["id"], 975)
    op_d2 = fixtures.queue_op(lot_d["id"], "THREAD_ROLL", 2, "TR-1")
    op_e1 = fixtures.queue_op(lot_e["id"], "DRILL", 1, "DR-2")

    env["lot_d"] = lot_d
    env["lot_e"] = lot_e
    env["op_d1"] = op_d1
    env["op_d2"] = op_d2
    env["op_e1"] = op_e1
    return env


def _certified_lot_with_two_sealed_packs():
    """CHAIN-B carried to CERTIFIED, then two 100-piece packs opened and sealed."""
    env = fixtures.setup_certified_lot(
        unplated=True,
        spec_overrides={"max_decarb_depth_mm": 0.100},
        min_measured_core_hardness_hv=322.0,
    )
    pack1 = fixtures.open_pack(
        env["lot"]["id"],
        env["certificate"]["id"],
        label_serial="PK-0001",
        actual_count=100,
        label_fields_complete=True,
    )
    pack2 = fixtures.open_pack(
        env["lot"]["id"],
        env["certificate"]["id"],
        label_serial="PK-0002",
        actual_count=100,
        label_fields_complete=True,
    )
    env["pack1"] = fixtures.seal_pack(pack1["id"])
    env["pack2"] = fixtures.seal_pack(pack2["id"])
    env["lot"] = fixtures.read_lot(env["lot"]["id"])
    return env


def _plating_run_by_id(api, headers, production_lot_id, plating_run_id):
    """The lot's plating run with the given id, read through the nested listing."""
    items, _ = validate_paginated(
        api.list_lot_plating_runs(production_lot_id, headers, params={"limit": 100})
    )
    matches = [row for row in items if row["id"] == plating_run_id]
    assert matches, f"Plating run {plating_run_id} missing from the lot's run list"
    return matches[0]


def _lot_baking_after_replate(api, heat_treat_headers):
    """A ZINC_CLEAR lot whose surviving replate run is BAKING with a 240-minute soak."""
    env = fixtures.setup_heat_treated_lot(spec_overrides={"max_decarb_depth_mm": 0.100})
    lot_id = env["lot"]["id"]
    plate1 = fixtures.schedule_plating(lot_id)
    plate2 = validate_success(
        api.create_plating_run(
            factories.create_plating_run_payload(lot_id), heat_treat_headers
        ),
        201,
    )
    validate_success(api.complete_plating(plate2["id"], heat_treat_headers))
    validate_success(
        api.start_bake(
            plate2["id"],
            {"bake_temp_c": 200, "bake_duration_min": 240},
            heat_treat_headers,
        )
    )
    env["plate1"] = plate1
    env["plate2"] = plate2
    return env


# ---------------------------------------------------------------------------
# GET /production-lots — filters, then the page window
# ---------------------------------------------------------------------------
class TestProductionLotListing:
    def test_process_state_filter_counts_only_the_matching_lots(self, api, clerk_headers):
        """Filtering the lot list by process_state SETUP reports two lots, not three.

        PRD: "Both `total_count` and `has_more` are computed against the *filtered* result set, not against the whole collection: when a caller filters wire lots by `steel_heat_id` and `status`, `total_count` reports how many wire lots match those filters, and `has_more` reports whether records matching those filters remain beyond the current page."

        PRD: "Production lots may be filtered by `part_spec_id`, `wire_lot_id`, `heading_tool_id`, `traceability_heat_id`, and by either state dimension independently — `process_state` or `disposition`."

        Design: Corner/endpoints/production_lot_list_combines_filters_with_pagination
        """
        env = _three_lots_on_one_die()

        items, meta = validate_paginated(
            api.list_production_lots(
                clerk_headers, params={"process_state": "SETUP", "limit": 10, "offset": 0}
            )
        )

        assert meta["total_count"] == 2, (
            f"Expected total_count 2 for the SETUP filter, got {meta['total_count']}"
        )
        assert meta["has_more"] is False, (
            "Both SETUP lots fit on the page, so has_more must be False"
        )
        codes = [row["lot_code"] for row in items]
        assert codes == ["L-B", "L-C"], (
            f"Expected the two SETUP lots L-B and L-C in created_at order, got {codes}"
        )
        for row in items:
            assert row["process_state"] == "SETUP", (
                f"Lot {row['lot_code']} leaked into the SETUP filter with "
                f"process_state {row['process_state']}"
            )
        assert env["lot_a"]["id"] not in [row["id"] for row in items], (
            "The headed lot L-A must not appear under the SETUP filter"
        )

    def test_pagination_windows_the_already_filtered_lot_set(self, api, clerk_headers):
        """limit 1 / offset 1 over the SETUP filter returns the second SETUP lot only.

        PRD: "`offset` is the number of records skipped before the page begins; when omitted it defaults to 0, and it may not be negative."

        PRD: "Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order."

        PRD: "Both `total_count` and `has_more` are computed against the *filtered* result set, not against the whole collection: when a caller filters wire lots by `steel_heat_id` and `status`, `total_count` reports how many wire lots match those filters, and `has_more` reports whether records matching those filters remain beyond the current page."

        Design: Corner/endpoints/production_lot_list_combines_filters_with_pagination
        """
        env = _three_lots_on_one_die()

        first_page, first_meta = validate_paginated(
            api.list_production_lots(
                clerk_headers, params={"process_state": "SETUP", "limit": 1, "offset": 0}
            )
        )
        assert first_meta["total_count"] == 2, (
            f"total_count is the filtered size regardless of the window, got "
            f"{first_meta['total_count']}"
        )
        assert [row["id"] for row in first_page] == [env["lot_b"]["id"]], (
            "The first page of the SETUP filter is the earliest SETUP lot, L-B"
        )
        assert first_meta["has_more"] is True, (
            "One SETUP lot remains beyond the first page, so has_more must be True"
        )

        second_page, second_meta = validate_paginated(
            api.list_production_lots(
                clerk_headers, params={"process_state": "SETUP", "limit": 1, "offset": 1}
            )
        )
        assert len(second_page) == 1, (
            f"Expected exactly one item at limit 1, got {len(second_page)}"
        )
        assert second_page[0]["lot_code"] == "L-C", (
            f"Expected L-C at offset 1 of the SETUP filter, got "
            f"{second_page[0]['lot_code']}"
        )
        assert second_meta["total_count"] == 2, (
            f"Expected the filtered total_count 2, got {second_meta['total_count']}"
        )
        assert second_meta["has_more"] is False, (
            "Nothing matching the SETUP filter remains after offset 1, so has_more "
            "must be False"
        )
        assert second_meta["limit"] == 1 and second_meta["offset"] == 1, (
            f"meta must echo the requested window, got limit {second_meta['limit']} "
            f"offset {second_meta['offset']}"
        )

    def test_disposition_filter_is_independent_of_process_state(self, api, clerk_headers):
        """The HOLD filter finds the one held lot, which is still SETUP on its route.

        PRD: "Production lots may be filtered by `part_spec_id`, `wire_lot_id`, `heading_tool_id`, `traceability_heat_id`, and by either state dimension independently — `process_state` or `disposition`."

        PRD: "A `QualityInspector` or `QualityManager` may place a hold with a `reason` on any lot whose `disposition` is `IN_PROCESS`, taking it `IN_PROCESS → HOLD` with `hold_source` of `QUALITY` and incrementing its `version` by 1."

        Design: Corner/endpoints/production_lot_list_combines_filters_with_pagination
        """
        env = _three_lots_on_one_die()

        items, meta = validate_paginated(
            api.list_production_lots(
                clerk_headers, params={"disposition": "HOLD", "limit": 10, "offset": 0}
            )
        )

        assert meta["total_count"] == 1, (
            f"Only L-C is on hold, so total_count must be 1, got {meta['total_count']}"
        )
        assert len(items) == 1, f"Expected one held lot, got {len(items)}"
        held = items[0]
        assert held["id"] == env["lot_c"]["id"], "The held lot must be L-C"
        assert held["lot_code"] == "L-C", f"Expected lot_code L-C, got {held['lot_code']}"
        assert held["disposition"] == "HOLD", (
            f"Expected disposition HOLD, got {held['disposition']}"
        )
        assert held["hold_source"] == "QUALITY", (
            f"An inspector-placed hold tags hold_source QUALITY, got "
            f"{held['hold_source']}"
        )
        assert held["process_state"] == "SETUP", (
            "A hold does not move the lot along its process dimension, so L-C stays "
            f"SETUP, got {held['process_state']}"
        )
        assert_versions_incremented(env["lot_c"], held)

    def test_part_spec_filter_reports_the_full_filtered_total_beyond_the_page(
        self, api, clerk_headers
    ):
        """A two-row page over all three lots of one part spec still reports total 3.

        PRD: "`limit` is the maximum number of records returned; when omitted it defaults to 10, and the accepted range is a minimum of 1 and a maximum of 100."

        PRD: "Both `total_count` and `has_more` are computed against the *filtered* result set, not against the whole collection: when a caller filters wire lots by `steel_heat_id` and `status`, `total_count` reports how many wire lots match those filters, and `has_more` reports whether records matching those filters remain beyond the current page."

        Design: Corner/endpoints/production_lot_list_combines_filters_with_pagination
        """
        env = _three_lots_on_one_die()

        items, meta = validate_paginated(
            api.list_production_lots(
                clerk_headers,
                params={"part_spec_id": env["spec"]["id"], "limit": 2, "offset": 0},
            )
        )

        assert meta["total_count"] == 3, (
            f"All three lots share the part spec, so total_count must be 3, got "
            f"{meta['total_count']}"
        )
        assert len(items) == 2, f"Expected two items at limit 2, got {len(items)}"
        assert meta["has_more"] is True, (
            "A third matching lot remains beyond the page, so has_more must be True"
        )
        headed = items[0]
        assert headed["lot_code"] == "L-A", (
            f"Expected the earliest lot L-A first, got {headed['lot_code']}"
        )
        assert headed["process_state"] == "HEADED", (
            f"L-A reported heading, so process_state must be HEADED, got "
            f"{headed['process_state']}"
        )
        assert headed["disposition"] == "IN_PROCESS", (
            f"L-A was never frozen, so disposition must be IN_PROCESS, got "
            f"{headed['disposition']}"
        )
        for row in items:
            assert "process_state" in row and "disposition" in row, (
                f"Lot {row['lot_code']} must carry both state dimensions as separate "
                "fields"
            )


# ---------------------------------------------------------------------------
# GET /production-lots/{id}/secondary-operations — scoped to its parent lot
# ---------------------------------------------------------------------------
class TestNestedSecondaryOperationListing:
    def test_nested_list_returns_only_the_path_lots_operations(self, api, manager_headers):
        """L-D shows its own two operations and L-E only its one, never each other's.

        PRD: "The new operation is created in `status` `PENDING` with `pieces_in` taken from the lot's current `available_count` — the client never supplies it — and with `performed_after_heat_treat` capturing whether the lot's `heat_treat_completed` flag was already true at the moment of creation."

        PRD: "On success the operation moves `PENDING → DONE` (a terminal status), `pieces_out` is recorded, and `scrap_pieces` is set to `pieces_in` minus `pieces_out`."

        PRD: "The lot absorbs the yield: its `available_count` is replaced by `pieces_out` and its `scrap_count` grows by `scrap_pieces`, keeping the piece ledger of §2.8 balanced."

        Design: Corner/endpoints/nested_secondary_operation_list_is_scoped_to_its_parent_lot
        """
        env = _two_lots_with_drill_and_thread_roll()

        d_items, d_meta = validate_paginated(
            api.list_secondary_operations(
                env["lot_d"]["id"], manager_headers, params={"limit": 10, "offset": 0}
            )
        )
        assert d_meta["total_count"] == 2, (
            f"L-D has two queued operations, got total_count {d_meta['total_count']}"
        )
        by_sequence = {row["sequence_no"]: row for row in d_items}
        assert sorted(by_sequence) == [1, 2], (
            f"Expected sequence numbers 1 and 2 on L-D, got {sorted(by_sequence)}"
        )

        drill = by_sequence[1]
        assert drill["op_type"] == "DRILL", (
            f"Sequence 1 on L-D is the DRILL, got {drill['op_type']}"
        )
        assert drill["status"] == "DONE", (
            f"The DRILL was closed, so status must be DONE, got {drill['status']}"
        )
        assert drill["pieces_in"] == 980, (
            f"The DRILL took the lot's 980 available pieces, got {drill['pieces_in']}"
        )
        assert drill["pieces_out"] == 975, (
            f"Expected pieces_out 975, got {drill['pieces_out']}"
        )
        assert drill["scrap_pieces"] == 5, (
            f"scrap_pieces is 980 - 975 = 5, got {drill['scrap_pieces']}"
        )

        thread_roll = by_sequence[2]
        assert thread_roll["op_type"] == "THREAD_ROLL", (
            f"Sequence 2 on L-D is the THREAD_ROLL, got {thread_roll['op_type']}"
        )
        assert thread_roll["status"] == "PENDING", (
            f"The THREAD_ROLL is still open, got status {thread_roll['status']}"
        )
        assert thread_roll["pieces_in"] == 975, (
            f"The THREAD_ROLL took the drilled yield of 975 pieces, got "
            f"{thread_roll['pieces_in']}"
        )

        e_items, e_meta = validate_paginated(
            api.list_secondary_operations(
                env["lot_e"]["id"], manager_headers, params={"limit": 10, "offset": 0}
            )
        )
        assert e_meta["total_count"] == 1, (
            f"L-E has one queued operation, got total_count {e_meta['total_count']}"
        )
        only = e_items[0]
        assert only["id"] == env["op_e1"]["id"], "L-E's list must hold only its own DRILL"
        assert only["op_type"] == "DRILL" and only["status"] == "PENDING", (
            f"Expected a PENDING DRILL on L-E, got {only['op_type']} / {only['status']}"
        )
        assert only["pieces_in"] == 980, (
            f"L-E's DRILL took its 980 available pieces, got {only['pieces_in']}"
        )
        e_ids = {row["id"] for row in e_items}
        assert env["op_d1"]["id"] not in e_ids and env["op_d2"]["id"] not in e_ids, (
            "L-D's operations must never surface under L-E's nested collection"
        )

        lot_d = fixtures.read_lot(env["lot_d"]["id"])
        lot_e = fixtures.read_lot(env["lot_e"]["id"])
        assert lot_d["available_count"] == 975, (
            f"L-D absorbed the drilled yield, expected available_count 975, got "
            f"{lot_d['available_count']}"
        )
        assert lot_e["available_count"] == 980, (
            f"L-E's operation is still open, so available_count stays 980, got "
            f"{lot_e['available_count']}"
        )
        assert_lot_piece_ledger(lot_d)
        assert_lot_piece_ledger(lot_e)

    def test_nested_status_filter_narrows_within_the_parent_lot(self, api, manager_headers):
        """status=DONE on L-D returns the closed DRILL alone, not the pending roll.

        PRD: "A lot's secondary operations may be filtered by `status`."

        PRD: "Both `total_count` and `has_more` are computed against the *filtered* result set, not against the whole collection: when a caller filters wire lots by `steel_heat_id` and `status`, `total_count` reports how many wire lots match those filters, and `has_more` reports whether records matching those filters remain beyond the current page."

        Design: Corner/endpoints/nested_secondary_operation_list_is_scoped_to_its_parent_lot
        """
        env = _two_lots_with_drill_and_thread_roll()

        items, meta = validate_paginated(
            api.list_secondary_operations(
                env["lot_d"]["id"],
                manager_headers,
                params={"status": "DONE", "limit": 10, "offset": 0},
            )
        )

        assert meta["total_count"] == 1, (
            f"Only the DRILL is DONE on L-D, so total_count must be 1, got "
            f"{meta['total_count']}"
        )
        assert meta["has_more"] is False, (
            "The single DONE operation fits on the page, so has_more must be False"
        )
        assert len(items) == 1, f"Expected one DONE operation, got {len(items)}"
        assert items[0]["id"] == env["op_d1"]["id"], (
            "The DONE filter must return L-D's closed DRILL"
        )
        assert items[0]["op_type"] == "DRILL", (
            f"Expected the DRILL, got {items[0]['op_type']}"
        )
        assert env["op_d2"]["id"] not in {row["id"] for row in items}, (
            "The PENDING THREAD_ROLL must not survive the DONE filter"
        )


# ---------------------------------------------------------------------------
# POST /pack-units/{id}/ship — the lot follows its last carton
# ---------------------------------------------------------------------------
class TestLotShipsWithItsLastPack:
    def test_lot_stays_packed_while_a_sibling_pack_is_still_sealed(self, api, clerk_headers):
        """Shipping the first of two packs leaves the lot PACKED, not SHIPPED.

        PRD: "On success the pack moves `SEALED → SHIPPED` and `shipped_at` is stamped from the logical clock; the lot moves `PACKED → SHIPPED` only once every pack unit of the lot is in `status` `SHIPPED` and at least one such pack exists."

        PRD: "On success the pack moves `OPEN → SEALED`, `sealed_at` is stamped from the logical clock, the lot's `packed_count` grows by `declared_count` while its `available_count` shrinks by the same amount, the lot moves `CERTIFIED → PACKED`, and the pack's `version` and the lot's `version` each increment by 1."

        Design: Corner/endpoints/lot_ships_only_when_its_last_pack_unit_ships
        """
        env = _certified_lot_with_two_sealed_packs()
        lot_id = env["lot"]["id"]

        assert env["lot"]["packed_count"] == 200, (
            f"Two sealed 100-piece packs make packed_count 200, got "
            f"{env['lot']['packed_count']}"
        )
        assert env["lot"]["available_count"] == 4580, (
            f"Sealing moved 200 pieces out of 4780 available, expected 4580, got "
            f"{env['lot']['available_count']}"
        )
        assert env["lot"]["process_state"] == "PACKED", (
            f"After the seals the lot is PACKED, got {env['lot']['process_state']}"
        )

        shipped = validate_success(api.ship_pack_unit(env["pack1"]["id"], clerk_headers))
        assert shipped["status"] == "SHIPPED", (
            f"The first pack must be SHIPPED, got {shipped['status']}"
        )
        assert shipped["shipped_at"], "shipped_at must be stamped from the logical clock"
        assert_versions_incremented(env["pack1"], shipped)

        sibling = fixtures.read_pack_unit(env["pack2"]["id"])
        assert sibling["status"] == "SEALED", (
            f"The untouched sibling pack stays SEALED, got {sibling['status']}"
        )

        lot = fixtures.read_lot(lot_id)
        assert lot["process_state"] == "PACKED", (
            "With one pack still SEALED the lot may not bubble up to SHIPPED, got "
            f"{lot['process_state']}"
        )

    def test_lot_ships_when_its_last_pack_unit_ships_and_moves_no_pieces(
        self, api, clerk_headers
    ):
        """The second ship takes the lot to SHIPPED while its piece counters stand still.

        PRD: "On success the pack moves `SEALED → SHIPPED` and `shipped_at` is stamped from the logical clock; the lot moves `PACKED → SHIPPED` only once every pack unit of the lot is in `status` `SHIPPED` and at least one such pack exists."

        PRD: "For every production lot, everything that came off the header is accounted for somewhere: `headed_count` plus `heading_scrap_count` equals `available_count` plus `scrap_count` plus `destructive_test_count` plus `packed_count`."

        Design: Corner/endpoints/lot_ships_only_when_its_last_pack_unit_ships
        """
        env = _certified_lot_with_two_sealed_packs()
        lot_id = env["lot"]["id"]

        fixtures.ship_pack(env["pack1"]["id"])
        second = validate_success(api.ship_pack_unit(env["pack2"]["id"], clerk_headers))
        assert second["status"] == "SHIPPED", (
            f"The last pack must be SHIPPED, got {second['status']}"
        )

        first = fixtures.read_pack_unit(env["pack1"]["id"])
        assert first["status"] == "SHIPPED", (
            f"The first pack stays SHIPPED, got {first['status']}"
        )

        lot = fixtures.read_lot(lot_id)
        assert lot["process_state"] == "SHIPPED", (
            "Every pack of the lot is SHIPPED, so the lot must be SHIPPED, got "
            f"{lot['process_state']}"
        )
        assert lot["packed_count"] == 200, (
            f"Shipping moves no pieces, so packed_count stays 200, got "
            f"{lot['packed_count']}"
        )
        assert lot["available_count"] == 4580, (
            f"Shipping moves no pieces, so available_count stays 4580, got "
            f"{lot['available_count']}"
        )
        assert lot["headed_count"] == 4900 and lot["heading_scrap_count"] == 60, (
            f"The heading report is untouched, got headed {lot['headed_count']} / "
            f"heading scrap {lot['heading_scrap_count']}"
        )
        assert lot["scrap_count"] == 110, (
            f"Heading scrap 60 plus thread-rolling scrap 50 is 110, got "
            f"{lot['scrap_count']}"
        )
        assert lot["destructive_test_count"] == 70, (
            f"The destructive sample consumed 70 pieces, got "
            f"{lot['destructive_test_count']}"
        )
        assert_lot_piece_ledger(lot)


# ---------------------------------------------------------------------------
# POST /plating-runs — the replate, and the enforced relief-bake soak
# ---------------------------------------------------------------------------
class TestReplateAndBakeSoak:
    def test_second_plating_run_supersedes_the_scheduled_first_one(
        self, api, heat_treat_headers
    ):
        """A replate retires the merely SCHEDULED earlier run and bumps its version.

        PRD: "Scheduling a second run for the same lot is the plant's strip-and-replate path, and it retires the earlier attempt automatically: any existing run of that lot in `status` `SCHEDULED` or `PLATED` moves to `SUPERSEDED` and has its `version` incremented by 1."

        Design: Corner/endpoints/replate_supersedes_the_earlier_run_and_the_bake_soak_is_enforced
        """
        env = fixtures.setup_heat_treated_lot(
            spec_overrides={"max_decarb_depth_mm": 0.100}
        )
        lot_id = env["lot"]["id"]
        plate1 = fixtures.schedule_plating(lot_id)
        assert plate1["status"] == "SCHEDULED", (
            f"A new plating run starts SCHEDULED, got {plate1['status']}"
        )
        assert plate1["version"] == 1, (
            f"A freshly created run is at version 1, got {plate1['version']}"
        )

        plate2 = validate_success(
            api.create_plating_run(
                factories.create_plating_run_payload(lot_id), heat_treat_headers
            ),
            201,
        )
        assert plate2["status"] == "SCHEDULED", (
            f"The replate run itself starts SCHEDULED, got {plate2['status']}"
        )
        assert plate2["id"] != plate1["id"], "The replate must be a distinct run"

        retired = _plating_run_by_id(api, heat_treat_headers, lot_id, plate1["id"])
        assert retired["status"] == "SUPERSEDED", (
            f"The earlier SCHEDULED run must flip to SUPERSEDED, got "
            f"{retired['status']}"
        )
        assert retired["version"] == 2, (
            f"Being superseded is a mutation, so version must reach 2, got "
            f"{retired['version']}"
        )

    def test_superseded_plating_run_refuses_the_completion_call(
        self, api, heat_treat_headers
    ):
        """Completing plating on the superseded run answers ERR_INVALID_PROCESS_RUN_STATE.

        PRD: "`SUPERSEDED` is terminal and a superseded run refuses every subsequent operation with `ERR_INVALID_PROCESS_RUN_STATE`."

        PRD: "The run moves `SCHEDULED → PLATED` and stamps `plated_at` from the logical clock, which starts the embrittlement relief clock ticking."

        Design: Corner/endpoints/replate_supersedes_the_earlier_run_and_the_bake_soak_is_enforced
        """
        env = fixtures.setup_heat_treated_lot(
            spec_overrides={"max_decarb_depth_mm": 0.100}
        )
        lot_id = env["lot"]["id"]
        plate1 = fixtures.schedule_plating(lot_id)
        plate2 = validate_success(
            api.create_plating_run(
                factories.create_plating_run_payload(lot_id), heat_treat_headers
            ),
            201,
        )

        validate_error(
            api.complete_plating(plate1["id"], heat_treat_headers),
            ApiErrorId.ERR_INVALID_PROCESS_RUN_STATE.value,
        )

        surviving = validate_success(
            api.complete_plating(plate2["id"], heat_treat_headers)
        )
        assert surviving["status"] == "PLATED", (
            f"The surviving run must reach PLATED, got {surviving['status']}"
        )
        assert surviving["plated_at"].startswith("2026-09-01T22:00:00"), (
            f"plated_at is stamped from the logical clock at 22:00, got "
            f"{surviving['plated_at']}"
        )
        lot = fixtures.read_lot(lot_id)
        assert lot["process_state"] == "PLATED", (
            f"The lot follows plating completion to PLATED, got {lot['process_state']}"
        )

    def test_relief_bake_cannot_close_before_the_committed_soak_elapses(
        self, api, heat_treat_headers
    ):
        """A complete-bake thirty minutes into a 240-minute soak is refused with 409.

        PRD: "For a part that needed the bake, the run must be in `status` `BAKING` and the logical clock must have reached or passed `bake_started_at` plus the committed `bake_duration_min` in minutes; closing early is refused with `ERR_BAKE_DURATION_NOT_ELAPSED`."

        PRD: "On success the run moves `PLATED → BAKING`, `bake_started_at` is stamped from the logical clock, `bake_delay_hours` and both bake parameters are recorded, and the run's `version` increments by 1."

        Design: Corner/endpoints/replate_supersedes_the_earlier_run_and_the_bake_soak_is_enforced
        """
        env = _lot_baking_after_replate(api, heat_treat_headers)
        lot_id = env["lot"]["id"]
        run_id = env["plate2"]["id"]

        baking = _plating_run_by_id(api, heat_treat_headers, lot_id, run_id)
        assert baking["status"] == "BAKING", (
            f"Starting the bake takes the run to BAKING, got {baking['status']}"
        )
        assert baking["bake_started_at"].startswith("2026-09-01T22:00:00"), (
            f"bake_started_at is the logical clock at 22:00, got "
            f"{baking['bake_started_at']}"
        )
        assert baking["bake_delay_hours"] == pytest.approx(0.000, abs=0.001), (
            f"The bake began the instant plating closed, so bake_delay_hours is "
            f"0.000, got {baking['bake_delay_hours']}"
        )
        assert baking["bake_duration_min"] == 240, (
            f"The committed soak is 240 minutes, got {baking['bake_duration_min']}"
        )

        fixtures.set_clock("2026-09-01T22:30:00Z", heat_treat_headers)
        validate_error(
            api.complete_bake(run_id, heat_treat_headers),
            ApiErrorId.ERR_BAKE_DURATION_NOT_ELAPSED.value,
        )

        unchanged = _plating_run_by_id(api, heat_treat_headers, lot_id, run_id)
        assert unchanged["status"] == "BAKING", (
            f"The refused close leaves the run BAKING, got {unchanged['status']}"
        )
        assert unchanged["bake_completed_at"] in (None, ""), (
            f"bake_completed_at must stay empty, got {unchanged['bake_completed_at']!r}"
        )
        lot = fixtures.read_lot(lot_id)
        assert lot["process_state"] == "PLATED", (
            f"The lot may not reach BAKED on a refused close, got "
            f"{lot['process_state']}"
        )

    def test_relief_bake_closes_once_the_soak_has_elapsed(self, api, heat_treat_headers):
        """At exactly 240 elapsed minutes the bake closes and the pre-test score lands.

        PRD: "The run moves `BAKING → BAKE_COMPLETE` and `bake_completed_at` is stamped."

        PRD: "In both branches the lot moves `PLATED → BAKED`, the lot's pre-test risk score is computed, and the run's `version` and the lot's `version` each increment by 1."

        PRD: "The **bake term** is 0 for a part whose `he_bake_required` is false; otherwise it depends on `bake_delay_hours`: 0 when that delay is at most 2.0 hours, and otherwise the excess over 2.0 hours multiplied by 40, capped at 100 — so a bake started 3.5 hours after plating contributes 60."

        PRD: "The score is 0.30 multiplied by the heat term, plus 0.20 multiplied by the tool term, plus 0.25 multiplied by the bake term, plus 0.25 multiplied by the decarburization term, with the sum rounded half up to two decimal places exactly once at the end — the individual weighted terms are never rounded on their own."

        Design: Corner/endpoints/replate_supersedes_the_earlier_run_and_the_bake_soak_is_enforced
        """
        env = _lot_baking_after_replate(api, heat_treat_headers)
        lot_id = env["lot"]["id"]
        run_id = env["plate2"]["id"]

        fixtures.set_clock("2026-09-01T22:30:00Z", heat_treat_headers)
        validate_error(
            api.complete_bake(run_id, heat_treat_headers),
            ApiErrorId.ERR_BAKE_DURATION_NOT_ELAPSED.value,
        )

        fixtures.set_clock("2026-09-02T02:00:00Z", heat_treat_headers)
        closed = validate_success(api.complete_bake(run_id, heat_treat_headers))
        assert closed["status"] == "BAKE_COMPLETE", (
            f"With the soak elapsed the run must reach BAKE_COMPLETE, got "
            f"{closed['status']}"
        )
        assert closed["bake_completed_at"].startswith("2026-09-02T02:00:00"), (
            f"bake_completed_at is the logical clock at 02:00, got "
            f"{closed['bake_completed_at']}"
        )

        lot = fixtures.read_lot(lot_id)
        assert lot["process_state"] == "BAKED", (
            f"Closing the bake takes the lot to BAKED, got {lot['process_state']}"
        )
        assert lot["risk_score_pre_test"] == pytest.approx(5.83, abs=0.001), (
            "A verified heat, 4.13 percent die utilisation, a zero bake delay and a "
            "0.020 of 0.100 mm decarburization depth score 5.83, got "
            f"{lot['risk_score_pre_test']}"
        )
        assert lot["tool_utilization_pct"] == pytest.approx(4.13, abs=0.001), (
            f"The snapshotted die utilisation is 4.13 percent, got "
            f"{lot['tool_utilization_pct']}"
        )


# ---------------------------------------------------------------------------
# PATCH /part-specs/{id} — partial, and it re-derives the bake duty
# ---------------------------------------------------------------------------
class TestPartSpecRevision:
    def test_part_spec_revision_touches_only_the_supplied_keys(self, api, engineer_headers):
        """Revising nominal_pack_count leaves the tolerance and hardness window alone.

        PRD: "Specifications may be revised later by a `ProcessEngineer` or a `PlantAdmin`, and a revision may touch `min_core_hardness_hv`, `max_core_hardness_hv`, `max_decarb_depth_mm`, `nominal_pack_count`, `count_tolerance_pct`, `plating_spec` and `proof_load_kn`, each optional."

        PRD: "A revision increments the specification's `version` by 1, and when `plating_spec` changes it re-derives both `he_bake_required` and `he_bake_min_minutes` from the new finish and the unchanged strength class."

        PRD: "`he_bake_required` is true exactly when the part is plated with something — that is, `plating_spec` is not `NONE` — *and* its `strength_class` is one of the three embrittlement-prone classes `CLASS_10_9`, `CLASS_12_9` and `GRADE_8`; in every other combination it is false."

        Design: Corner/endpoints/part_spec_patch_is_partial_and_rederives_the_bake_fields
        """
        fixtures.set_clock(CLOCK_START)
        spec = fixtures.register_unplated_part_spec(
            min_core_hardness_hv=304,
            max_core_hardness_hv=361,
            max_decarb_depth_mm=0.100,
            nominal_pack_count=100,
        )
        assert spec["count_tolerance_pct"] == pytest.approx(0.02, abs=0.001), (
            f"count_tolerance_pct defaults to 0.02 when omitted, got "
            f"{spec['count_tolerance_pct']}"
        )

        fixtures.set_clock("2026-09-01T07:00:00Z")
        revised = validate_success(
            api.revise_part_spec(spec["id"], {"nominal_pack_count": 250}, engineer_headers)
        )

        assert revised["version"] == 2, (
            f"One revision takes the spec from version 1 to 2, got {revised['version']}"
        )
        assert revised["nominal_pack_count"] == 250, (
            f"Expected nominal_pack_count 250, got {revised['nominal_pack_count']}"
        )
        assert revised["count_tolerance_pct"] == pytest.approx(0.02, abs=0.001), (
            f"An unsupplied key is untouched, so count_tolerance_pct stays 0.02, got "
            f"{revised['count_tolerance_pct']}"
        )
        assert revised["min_core_hardness_hv"] == 304, (
            f"min_core_hardness_hv must stay 304, got {revised['min_core_hardness_hv']}"
        )
        assert revised["max_core_hardness_hv"] == 361, (
            f"max_core_hardness_hv must stay 361, got {revised['max_core_hardness_hv']}"
        )
        assert revised["max_decarb_depth_mm"] == pytest.approx(0.100, abs=0.001), (
            f"max_decarb_depth_mm must stay 0.100, got {revised['max_decarb_depth_mm']}"
        )
        assert revised["plating_spec"] == "NONE", (
            f"The finish was not revised, so plating_spec stays NONE, got "
            f"{revised['plating_spec']}"
        )
        assert revised["he_bake_required"] is False, (
            "An unplated part needs no relief bake, so he_bake_required stays False"
        )
        assert revised["he_bake_min_minutes"] == 0, (
            f"With no bake required he_bake_min_minutes stays 0, got "
            f"{revised['he_bake_min_minutes']}"
        )

    def test_revising_the_finish_rederives_the_relief_bake_duty(
        self, api, engineer_headers, admin_headers, clerk_headers
    ):
        """Moving a CLASS_10_9 part from NONE to ZINC_CLEAR imposes a 240-minute bake.

        PRD: "A revision increments the specification's `version` by 1, and when `plating_spec` changes it re-derives both `he_bake_required` and `he_bake_min_minutes` from the new finish and the unchanged strength class."

        PRD: "`he_bake_min_minutes` follows from it: zero when no bake is required; a full eight hours, expressed as 480 minutes, for `CLASS_12_9` and `GRADE_8`; and four hours, expressed as 240 minutes, for `CLASS_10_9`."

        PRD: "**`updated_at`** (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed from the logical clock on every mutation of the record."

        Design: Corner/endpoints/part_spec_patch_is_partial_and_rederives_the_bake_fields
        """
        fixtures.set_clock(CLOCK_START)
        spec = fixtures.register_unplated_part_spec(
            strength_class="CLASS_10_9",
            max_decarb_depth_mm=0.100,
            nominal_pack_count=100,
        )
        created_at = spec["created_at"]

        fixtures.set_clock("2026-09-01T07:00:00Z")
        validate_success(
            api.revise_part_spec(spec["id"], {"nominal_pack_count": 250}, engineer_headers)
        )

        fixtures.set_clock("2026-09-01T08:00:00Z")
        replated = validate_success(
            api.revise_part_spec(
                spec["id"], {"plating_spec": "ZINC_CLEAR"}, admin_headers
            )
        )

        assert replated["version"] == 3, (
            f"Two revisions take the spec to version 3, got {replated['version']}"
        )
        assert replated["plating_spec"] == "ZINC_CLEAR", (
            f"Expected plating_spec ZINC_CLEAR, got {replated['plating_spec']}"
        )
        assert replated["he_bake_required"] is True, (
            "A plated CLASS_10_9 part is embrittlement-prone, so he_bake_required "
            "must be True"
        )
        assert replated["he_bake_min_minutes"] == 240, (
            f"CLASS_10_9 takes the four-hour soak of 240 minutes, not 480, got "
            f"{replated['he_bake_min_minutes']}"
        )

        echoed = validate_success(api.get_part_spec(spec["id"], clerk_headers))
        assert echoed["version"] == 3, (
            f"The read must echo version 3, got {echoed['version']}"
        )
        assert echoed["nominal_pack_count"] == 250, (
            f"The earlier revision survives, so nominal_pack_count is 250, got "
            f"{echoed['nominal_pack_count']}"
        )
        assert echoed["thread_timing"] == "BEFORE_HEAT_TREAT", (
            f"thread_timing was never revised, got {echoed['thread_timing']}"
        )
        assert echoed["he_bake_required"] is True, (
            "The read must echo the re-derived bake duty"
        )
        assert echoed["he_bake_min_minutes"] == 240, (
            f"The read must echo he_bake_min_minutes 240, got "
            f"{echoed['he_bake_min_minutes']}"
        )
        assert echoed["created_at"] == created_at, (
            f"created_at is set once at creation, expected {created_at}, got "
            f"{echoed['created_at']}"
        )
        assert echoed["updated_at"] > created_at, (
            f"updated_at is refreshed on every mutation, so it must have advanced past "
            f"{created_at}, got {echoed['updated_at']}"
        )
