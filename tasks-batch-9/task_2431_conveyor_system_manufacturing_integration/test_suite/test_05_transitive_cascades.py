"""The two named cascades: design reopening and scrap unwind."""

from test_helpers import (
    CUSTOMER_REP,
    SHOP_SUPERVISOR,
    ApiErrorId,
    assert_share_ledger_conserved,
    create_fabrication_lot_payload,
    decide_change_order,
    fail_fat_attempt,
    make_fat_passed_lot,
    make_planned_lot,
    make_scheduled_window,
    make_staging_bay,
    make_submitted_change_order,
    read_lot,
    read_project,
    read_window,
    run_simulation,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestDesignReopeningCascade:
    """A scope-bearing approval reprices, reopens and unwinds in one request."""

    def _staged_world_with_submitted_order(self, api):
        bay = make_staging_bay(api, bay_code="BAY-4", concurrent_capacity=2)
        state = make_scheduled_window(
            api,
            state=make_fat_passed_lot(api, bay=bay, segment_codes=["IB-01"], lot_code="LOT-400"),
        )
        state["change_order"] = make_submitted_change_order(
            api,
            state["project"]["id"],
            title="Add second sorter loop",
            scope_delta_cph=120,
            price_delta_cents=18_000_000,
            schedule_delta_days=21,
        )
        return state

    def test_scope_bearing_approval_reprices_then_reopens_the_design(self, api):
        """The subtotal moves into the 220 basis point tier and the freeze is undone.

        PRD §2.6: "Link 1 increments the project's `design_version` by 1, clears
        `design_frozen_at` and returns `delivery_status` to `DESIGN` from whichever of
        `DESIGN_FROZEN`, `IN_FABRICATION`, `CUTOVER` or `REBASELINE_REQUIRED` it held."

        Design: Difficulty/transitive_cascade/change_order_approval_cascades_design_simulation_window_lot_hold
        """
        state = self._staged_world_with_submitted_order(api)
        before = read_project(api, state["project"]["id"])
        decided = decide_change_order(
            api,
            state["project"]["id"],
            state["change_order"]["id"],
            "APPROVE",
            headers=CUSTOMER_REP,
        )

        assert decided["status"] == "APPROVED"
        after = read_project(api, state["project"]["id"])
        assert after["contract_value_cents"] == 263_676_000
        assert after["design_version"] == before["design_version"] + 1
        assert after["delivery_status"] == "DESIGN"
        assert after["design_frozen_at"] is None

    def test_the_cascade_stales_the_run_blocks_the_window_and_holds_the_lot(self, api):
        """Three further links fire inside the same approval request.

        PRD §2.6: "Link 4 is caused by that blocking: every fabrication lot referenced
        by a window blocked in link 3 whose `status` is `STAGED` or `FAT_PASSED` becomes
        `HOLD`."

        Design: Difficulty/transitive_cascade/change_order_approval_cascades_design_simulation_window_lot_hold
        """
        state = self._staged_world_with_submitted_order(api)
        decide_change_order(
            api,
            state["project"]["id"],
            state["change_order"]["id"],
            "APPROVE",
            headers=CUSTOMER_REP,
        )

        runs, _ = validate_paginated(
            api.list_simulation_runs(state["project"]["id"], SHOP_SUPERVISOR)
        )
        assert {run["id"]: run["status"] for run in runs}[state["simulation"]["id"]] == "STALE"
        assert read_window(api, state["window"]["id"])["status"] == "BLOCKED_STALE_DESIGN"
        assert read_lot(api, state["lot"]["id"])["status"] == "HOLD"

    def test_a_fresh_compliant_degraded_run_releases_the_window_then_the_lot(self, api):
        """The design-block mechanism runs in reverse when the basis is restored.

        PRD §2.6: "When a fresh availability-degraded simulation restores a compliant
        view of the line, every cutover window of the project sitting in
        `BLOCKED_STALE_DESIGN` returns to `SCHEDULED`, and each lot referenced by such a
        window sitting in `HOLD` returns to `STAGED`."

        Design: Difficulty/transitive_cascade/change_order_approval_cascades_design_simulation_window_lot_hold
        """
        state = self._staged_world_with_submitted_order(api)
        decide_change_order(
            api,
            state["project"]["id"],
            state["change_order"]["id"],
            "APPROVE",
            headers=CUSTOMER_REP,
        )
        refreshed = run_simulation(api, state["project"]["id"], "DEGRADED_AVAILABILITY")

        assert refreshed["status"] == "COMPLETE"
        assert refreshed["effective_throughput_cph"] == 1330
        assert read_window(api, state["window"]["id"])["status"] == "SCHEDULED"
        assert read_lot(api, state["lot"]["id"])["status"] == "STAGED"

        runs, _ = validate_paginated(
            api.list_simulation_runs(state["project"]["id"], SHOP_SUPERVISOR)
        )
        assert {run["id"]: run["status"] for run in runs}[state["simulation"]["id"]] == "STALE"


class TestScrapUnwindCascade:
    """The third failure cancels the appointment and rebaselines the project."""

    def _world_with_window_before_fabrication(self, api):
        bay = make_staging_bay(api, bay_code="BAY-5", concurrent_capacity=2)
        planned = make_planned_lot(api, bay=bay, segment_codes=["IB-01"], lot_code="LOT-500")
        return make_scheduled_window(api, state=planned)

    def test_third_failure_cancels_the_window_and_releases_the_zone(self, api):
        """The cancelled window stamps closed_at and gives the zone reservation back.

        PRD §3.5: "every cutover window referencing that lot whose `status` is
        `SCHEDULED` becomes `CANCELLED_LOT_SCRAPPED` with its `closed_at` stamped from
        the logical clock and its own `version` incremented, releasing the zone
        reservation it held"

        Design: Difficulty/transitive_cascade/third_fat_failure_cascades_window_cancellation_to_project_rebaseline
        """
        state = self._world_with_window_before_fabrication(api)
        for measured in (1200, 1280):
            fail_fat_attempt(api, state, measured_cph=measured, defect_count=0)
        third = fail_fat_attempt(api, state, measured_cph=1310, defect_count=0)

        assert third["attempt_no"] == 3
        assert third["result"] == "FAIL"
        assert read_lot(api, state["lot"]["id"])["status"] == "SCRAPPED"

        window = read_window(api, state["window"]["id"])
        assert window["status"] == "CANCELLED_LOT_SCRAPPED"
        assert window["closed_at"] is not None

        zones = validate_success(api.list_site_zones(state["project"]["id"], SHOP_SUPERVISOR))
        assert [zone["ops_status"] for zone in zones] == ["LIVE_LEGACY"]

        project = read_project(api, state["project"]["id"])
        assert project["legacy_share_bps"] == 10000
        assert project["in_transition_share_bps"] == 0
        assert_share_ledger_conserved(project)

    def test_rebaseline_is_opened_by_the_scrap_and_closed_by_a_replacement_lot(self, api):
        """Planning a replacement lot returns the project to IN_FABRICATION.

        PRD §3.4: "Planning a lot also increments the project's `version` by 1, and if
        the project's `delivery_status` was `REBASELINE_REQUIRED` it returns to
        `IN_FABRICATION`, closing the rebaseline cycle opened by an earlier scrap."

        Design: Difficulty/transitive_cascade/third_fat_failure_cascades_window_cancellation_to_project_rebaseline
        """
        state = self._world_with_window_before_fabrication(api)
        for measured in (1200, 1280, 1310):
            fail_fat_attempt(api, state, measured_cph=measured, defect_count=0)

        scrapped_project = read_project(api, state["project"]["id"])
        assert scrapped_project["delivery_status"] == "REBASELINE_REQUIRED"

        replacement = validate_success(
            api.create_fabrication_lot(
                create_fabrication_lot_payload(
                    state["project"]["id"],
                    state["bay"]["id"],
                    ["IB-01"],
                    lot_code="LOT-501",
                    occupancy_start_utc="2026-08-14T00:00:00Z",
                    occupancy_end_utc="2026-08-18T00:00:00Z",
                ),
                SHOP_SUPERVISOR,
            ),
            expected_status=201,
        )
        assert replacement["status"] == "PLANNED"
        assert read_project(api, state["project"]["id"])["delivery_status"] == "IN_FABRICATION"

    def test_the_scrapped_lot_refuses_every_further_shop_operation(self, api):
        """The scrap is terminal for the traveller.

        PRD §3.5: "Three strikes is the whole rule: there is no fourth attempt, because
        a lot in `SCRAPPED` admits no operations at all."

        Design: Difficulty/transitive_cascade/third_fat_failure_cascades_window_cancellation_to_project_rebaseline
        """
        state = self._world_with_window_before_fabrication(api)
        for measured in (1200, 1280, 1310):
            fail_fat_attempt(api, state, measured_cph=measured, defect_count=0)

        response = api.stage_fabrication_lot(state["lot"]["id"], SHOP_SUPERVISOR)
        validate_error(response, ApiErrorId.ERR_LOT_SCRAPPED.value)
