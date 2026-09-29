"""Fabrication lot lifecycle: the FAT rework loop, scrapping, and bay occupancy."""

from test_helpers import (
    SHOP_SUPERVISOR,
    SITE_MANAGER,
    TEST_INSTANTS,
    ApiErrorId,
    assert_fabrication_lot,
    assert_fat_test,
    assert_share_ledger_conserved,
    create_fabrication_lot_payload,
    fail_fat_attempt,
    make_frozen_project,
    make_planned_lot,
    make_scheduled_window,
    make_staged_lot,
    make_staging_bay,
    read_lot,
    read_project,
    read_window,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestFatReworkCycleAndScrapping:
    """Two failures rework the lot; the third scraps it."""

    def _planned_lot(self, api):
        bay = make_staging_bay(api, bay_code="BAY-2", concurrent_capacity=2)
        return make_planned_lot(api, bay=bay, segment_codes=["IB-01"], lot_code="LOT-200")

    def test_failures_below_the_third_attempt_return_the_lot_to_rework(self, api):
        """Attempts one and two land in FAT_FAILED, which the supervisor may rework.

        PRD §3.5: "A `FAIL` on an `attempt_no` below 3 moves it `STAGED → FAT_FAILED`,
        from which the supervisor may rework it."

        Design: Difficulty/non_linear_state_machine/fabrication_lot_fat_rework_cycle_then_third_failure_scraps
        """
        state = self._planned_lot(api)
        assert_fabrication_lot(state["lot"])
        assert state["lot"]["fat_target_cph"] == 1313
        assert state["lot"]["fat_attempt_count"] == 0

        first = fail_fat_attempt(api, state, measured_cph=1200)
        assert_fat_test(first)
        assert first["attempt_no"] == 1
        assert first["result"] == "FAIL"
        assert first["target_cph_at_test"] == 1313
        assert state["lot"]["status"] == "FAT_FAILED"
        assert state["lot"]["fat_attempt_count"] == 1

        second = fail_fat_attempt(api, state, measured_cph=1250)
        assert second["attempt_no"] == 2
        assert second["result"] == "FAIL"
        assert second["target_cph_at_test"] == 1313
        assert state["lot"]["status"] == "FAT_FAILED"
        assert state["lot"]["fat_attempt_count"] == 2

    def test_third_failure_scraps_the_lot(self, api):
        """A FAIL on attempt three is terminal for the lot.

        PRD §3.5: "A `FAIL` on the third attempt — `attempt_no` exactly 3 — moves it
        `STAGED → SCRAPPED` and triggers the scrap-unwind cascade described in §2.6"

        Design: Difficulty/non_linear_state_machine/fabrication_lot_fat_rework_cycle_then_third_failure_scraps
        """
        state = self._planned_lot(api)
        fail_fat_attempt(api, state, measured_cph=1200)
        fail_fat_attempt(api, state, measured_cph=1250)
        third = fail_fat_attempt(api, state, measured_cph=1300)

        assert third["attempt_no"] == 3
        assert third["result"] == "FAIL"
        assert third["target_cph_at_test"] == 1313
        assert state["lot"]["status"] == "SCRAPPED"
        assert state["lot"]["fat_attempt_count"] == 3

    def test_test_history_is_append_only_and_oldest_first(self, api):
        """Three attempts read back in the order they happened, with no version field.

        PRD §3.5: "A lot's test history is append-only and readable by any role,
        oldest attempt first, so that the rework narrative reads in the order it
        happened."

        Design: Difficulty/non_linear_state_machine/fabrication_lot_fat_rework_cycle_then_third_failure_scraps
        """
        state = self._planned_lot(api)
        for measured in (1200, 1250, 1300):
            fail_fat_attempt(api, state, measured_cph=measured)

        tests, meta = validate_paginated(api.list_fat_tests(state["lot"]["id"], SHOP_SUPERVISOR))
        assert meta["total_count"] == 3
        assert [entry["attempt_no"] for entry in tests] == [1, 2, 3]
        for entry in tests:
            assert_fat_test(entry)
            assert "version" not in entry
            assert "updated_at" not in entry

    def test_a_scrapped_lot_admits_no_further_operations(self, api):
        """There is no fourth attempt because the lot has left the floor.

        PRD §3.4: "Any lot operation attempted after the lot has reached `SCRAPPED` is
        rejected with `ERR_LOT_SCRAPPED`."

        Design: Difficulty/non_linear_state_machine/fabrication_lot_fat_rework_cycle_then_third_failure_scraps
        """
        state = self._planned_lot(api)
        for measured in (1200, 1250, 1300):
            fail_fat_attempt(api, state, measured_cph=measured)

        response = api.start_fabrication(state["lot"]["id"], SHOP_SUPERVISOR)
        validate_error(response, ApiErrorId.ERR_LOT_SCRAPPED.value)
        assert read_lot(api, state["lot"]["id"])["status"] == "SCRAPPED"


class TestStagingBayClosedIntervalCapacity:
    """Closed occupancy intervals make a shared endpoint instant count twice."""

    def _bay_with_two_touching_lots(self, api):
        frozen = make_frozen_project(api)
        bay = make_staging_bay(api, bay_code="BAY-11", concurrent_capacity=2)
        first = validate_success(
            api.create_fabrication_lot(
                create_fabrication_lot_payload(
                    frozen["project"]["id"],
                    bay["id"],
                    ["IB-01"],
                    lot_code="LOT-1100",
                    occupancy_start_utc="2026-08-03T00:00:00Z",
                    occupancy_end_utc="2026-08-07T00:00:00Z",
                ),
                SHOP_SUPERVISOR,
            ),
            expected_status=201,
        )
        second = validate_success(
            api.create_fabrication_lot(
                create_fabrication_lot_payload(
                    frozen["project"]["id"],
                    bay["id"],
                    ["TR-02"],
                    lot_code="LOT-1101",
                    occupancy_start_utc="2026-08-07T00:00:00Z",
                    occupancy_end_utc="2026-08-11T00:00:00Z",
                ),
                SHOP_SUPERVISOR,
            ),
            expected_status=201,
        )
        return frozen, bay, first, second

    def test_a_third_occupancy_over_the_shared_instant_is_rejected(self, api):
        """Two lots touching at 2026-08-07T00:00:00Z already fill a capacity of two.

        PRD §2.10: "On a staging bay, by contrast, occupancy intervals are **closed**
        at both ends: a lot occupies the bay from `occupancy_start_utc` through
        `occupancy_end_utc` inclusive, so two lots that merely touch at an endpoint are
        both present at that instant."

        Design: Difficulty/resource_temporal_overlap/staging_bay_closed_interval_aggregate_capacity_exceeded
        """
        frozen, bay, first, second = self._bay_with_two_touching_lots(api)
        assert first["status"] == "PLANNED"
        assert second["status"] == "PLANNED"

        response = api.create_fabrication_lot(
            create_fabrication_lot_payload(
                frozen["project"]["id"],
                bay["id"],
                ["IB-01"],
                lot_code="LOT-1102",
                occupancy_start_utc="2026-08-07T00:00:00Z",
                occupancy_end_utc="2026-08-09T00:00:00Z",
            ),
            SHOP_SUPERVISOR,
        )
        validate_error(response, ApiErrorId.ERR_STAGING_BAY_CAPACITY_EXCEEDED.value)

    def test_the_rejected_plan_leaves_the_bay_holding_two_lots(self, api):
        """Capacity is an aggregate over instants, and the breach persists nothing.

        PRD §2.10: "A bay tolerates up to `concurrent_capacity` simultaneous
        occupancies; if the requested interval would push the number of overlapping
        occupancies above that capacity at any single instant, the request is rejected
        with `ERR_STAGING_BAY_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/staging_bay_closed_interval_aggregate_capacity_exceeded
        """
        frozen, bay, first, second = self._bay_with_two_touching_lots(api)
        api.create_fabrication_lot(
            create_fabrication_lot_payload(
                frozen["project"]["id"],
                bay["id"],
                ["IB-01"],
                lot_code="LOT-1102",
                occupancy_start_utc="2026-08-07T00:00:00Z",
                occupancy_end_utc="2026-08-09T00:00:00Z",
            ),
            SHOP_SUPERVISOR,
        )

        lots, meta = validate_paginated(
            api.list_fabrication_lots(SHOP_SUPERVISOR, params={"staging_bay_id": bay["id"]})
        )
        assert meta["total_count"] == 2
        assert {lot["status"] for lot in lots} == {"PLANNED"}
        assert read_lot(api, first["id"])["status"] == "PLANNED"
        assert read_lot(api, second["id"])["status"] == "PLANNED"


class TestCutoverStartReadsTheLotState:
    """The window's own state is fine; its lot is not."""

    def _staged_lot_with_window(self, api):
        bay = make_staging_bay(api, bay_code="BAY-8", concurrent_capacity=2)
        staged = make_staged_lot(api, bay=bay, segment_codes=["IB-01"], lot_code="LOT-800")
        state = make_scheduled_window(api, state=staged)
        set_clock(api, TEST_INSTANTS["WINDOW_DUE_UTC"])
        return state

    def test_start_is_refused_while_the_referenced_lot_is_only_staged(self, api):
        """A SCHEDULED window inside its appointment still needs a passed lot.

        PRD §3.6: "Only then are its relatives consulted — the referenced lot must be
        in `FAT_PASSED`, otherwise `ERR_LOT_NOT_FAT_PASSED`, and the referenced zone
        must be in `LIVE_LEGACY`, otherwise `ERR_ZONE_NOT_READY`."

        Design: Difficulty/cross_entity_state_dependency/cutover_start_requires_referenced_lot_in_fat_passed
        """
        state = self._staged_lot_with_window(api)
        assert state["window"]["status"] == "SCHEDULED"
        assert state["lot"]["status"] == "STAGED"

        response = api.start_cutover_window(state["window"]["id"], SITE_MANAGER)
        validate_error(response, ApiErrorId.ERR_LOT_NOT_FAT_PASSED.value)

    def test_refused_start_moves_neither_the_window_nor_the_share_ledger(self, api):
        """No share leaves legacy service when the start is refused.

        PRD §2.9: "Starting a cutover window subtracts that zone's share from
        `legacy_share_bps` and adds the identical amount to `in_transition_share_bps`."

        Design: Difficulty/cross_entity_state_dependency/cutover_start_requires_referenced_lot_in_fat_passed
        """
        state = self._staged_lot_with_window(api)
        api.start_cutover_window(state["window"]["id"], SITE_MANAGER)

        window = read_window(api, state["window"]["id"])
        assert window["status"] == "SCHEDULED"
        assert window["started_at"] is None

        zones = validate_success(api.list_site_zones(state["project"]["id"], SITE_MANAGER))
        assert [zone["ops_status"] for zone in zones] == ["LIVE_LEGACY"]

        project = read_project(api, state["project"]["id"])
        assert project["legacy_share_bps"] == 10000
        assert project["in_transition_share_bps"] == 0
        assert project["cutover_share_bps"] == 0
        assert_share_ledger_conserved(project)
        assert project["delivery_status"] == "IN_FABRICATION"
