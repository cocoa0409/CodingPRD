"""Seasonal window structure rules, publish/close lifecycle, ship-interval
overlap semantics, and the confirmed-vs-projected build projection."""
import pytest

from test_helpers import (
    MANAGER,
    PLANNER,
    ApiErrorId,
    assert_seasonal_window,
    cancel_run,
    create_run,
    create_seasonal_window_payload,
    create_window,
    get_window,
    produce_lot,
    publish_window,
    set_clock,
    setup_runnable_plant,
    validate_error,
    validate_paginated,
    validate_success,
)

HOLIDAY_TIERS = [
    {"day_offset_min": 0, "discount_pct": 0.30},
    {"day_offset_min": 7, "discount_pct": 0.50},
    {"day_offset_min": 14, "discount_pct": 0.70},
]


class TestWindowDateOrder:
    def test_ship_start_before_build_end_rejected(self, api):
        """PRD §3.4: "Its dates must be internally ordered — `build_start` no later
        than `build_end`, `build_end` no later than `ship_start`, and `ship_start`
        no later than `ship_end` — with any violation rejected as
        `ERR_WINDOW_DATE_ORDER`."

        Design: Corner/validations/window_date_order_invalid_rejected
        """
        payload = create_seasonal_window_payload(
            season_code="HOLIDAY", build_start="2026-09-01T00:00:00Z",
            build_end="2026-10-15T00:00:00Z", ship_start="2026-10-10T00:00:00Z",
            ship_end="2026-12-26T00:00:00Z", target_units=1000)
        resp = api.create_seasonal_window(payload, PLANNER)
        validate_error(resp, ApiErrorId.ERR_WINDOW_DATE_ORDER)


class TestWindowCloseTiming:
    def test_close_on_ship_end_rejected_then_closes_next_day(self, api):
        """PRD §3.4: "a `PUBLISHED` window closes to `CLOSED`, but only once the
        logical clock's date is strictly after the `ship_end` date — attempting to
        close on `ship_end` itself or earlier is rejected with
        `ERR_PREMATURE_CLOSE`."

        Design: Corner/state_machines/window_close_before_ship_end_rejected_then_closes
        """
        set_clock("2026-09-01T00:00:00Z")
        window = publish_window(create_window(season_code="HOLIDAY",
                                              target_units=1000)["id"])

        set_clock("2026-12-26T00:00:00Z")
        validate_error(api.close_window(window["id"], MANAGER),
                       ApiErrorId.ERR_PREMATURE_CLOSE)
        assert get_window(window["id"])["status"] == "PUBLISHED"

        set_clock("2026-12-27T00:00:00Z")
        closed = validate_success(api.close_window(window["id"], MANAGER))
        assert closed["status"] == "CLOSED"


class TestShipIntervalOverlap:
    def test_touching_ship_boundaries_count_as_overlap(self, api):
        """PRD §3.4: "its ship interval must not intersect the ship interval of
        any existing window carrying the same `season_code`; the ship interval is
        closed, both endpoint dates inclusive, so two windows of the same season
        whose ship periods merely touch on a boundary date already count as
        overlapping and the new window is rejected with `ERR_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/window_ship_intervals_closed_overlap
        """
        set_clock("2026-09-01T00:00:00Z")
        create_window(season_code="HOLIDAY", target_units=10000)

        touching = create_seasonal_window_payload(
            season_code="HOLIDAY", build_start="2026-10-01T00:00:00Z",
            build_end="2026-10-31T00:00:00Z", ship_start="2026-12-26T00:00:00Z",
            ship_end="2027-01-10T00:00:00Z", target_units=2000)
        validate_error(api.create_seasonal_window(touching, PLANNER),
                       ApiErrorId.ERR_WINDOW_OVERLAP)

        clear = create_seasonal_window_payload(
            season_code="HOLIDAY", build_start="2026-10-01T00:00:00Z",
            build_end="2026-10-31T00:00:00Z", ship_start="2026-12-27T00:00:00Z",
            ship_end="2027-01-10T00:00:00Z", target_units=2000)
        created = validate_success(api.create_seasonal_window(clear, PLANNER), 201)
        assert created["status"] == "DRAFT"

        windows, meta = validate_paginated(
            api.list_seasonal_windows(PLANNER, params={"season_code": "HOLIDAY"}))
        assert len(windows) == 2

    def test_overlap_not_checked_across_season_codes(self, api):
        """PRD §3.4: "Overlap is never checked across different season codes."

        Design: Difficulty/resource_temporal_overlap/window_ship_intervals_closed_overlap
        """
        set_clock("2026-09-01T00:00:00Z")
        create_window(season_code="HOLIDAY", target_units=10000)

        same_interval_other_season = create_seasonal_window_payload(
            season_code="EASTER", build_start="2026-09-01T00:00:00Z",
            build_end="2026-10-15T00:00:00Z", ship_start="2026-11-01T00:00:00Z",
            ship_end="2026-12-26T00:00:00Z", target_units=2000)
        created = validate_success(
            api.create_seasonal_window(same_interval_other_season, PLANNER), 201)
        assert created["status"] == "DRAFT"
        assert created["season_code"] == "EASTER"


class TestBuildProjectionVariants:
    def _setup_confirmed_plus_pipeline(self, api):
        """Window (target 10000): run A completed with 4000, run B PLANNED 3000."""
        plant = setup_runnable_plant(
            product_type="SEASONAL", sku_code="TRUFFLE-24", base_price_cents=1000,
            shelf_life_days=180, allergens=["MILK", "SOY"], shape_code="SHELL-HEART",
            cleared_allergens=["MILK", "SOY"], season_code="HOLIDAY",
            target_units=10000, markdown_tiers=HOLIDAY_TIERS)
        produce_lot(plant["window"]["id"], plant["product"]["id"],
                    plant["recipe"]["id"], plant["line"]["id"],
                    planned_units=5000, output_units=4000,
                    scheduled_start="2026-09-05T08:00:00Z",
                    scheduled_end="2026-09-05T16:00:00Z")
        run_b = create_run(plant["window"]["id"], plant["product"]["id"],
                           plant["recipe"]["id"], plant["line"]["id"],
                           planned_units=3000,
                           scheduled_start="2026-09-06T08:00:00Z",
                           scheduled_end="2026-09-06T16:00:00Z")
        return plant, run_b

    def test_confirmed_and_projected_diverge_with_pipeline(self, api):
        """PRD §3.4: "The confirmed variant — the post-production truth — sets
        `confirmed_build_units` to the sum of `qty_on_hand` over exactly those
        lots whose producing run belongs to this window and whose `status` is
        `ACTIVE`; blocked, depleted, and scrapped lots contribute nothing."
        PRD §3.4: "The projected variant — the forward-looking answer to "will we
        hit target if the schedule executes?" — sets `projected_build_units` to
        the confirmed figure plus the sum of `planned_units` over this window's
        runs still in the pipeline, namely those in `PLANNED`, `IN_PROGRESS`, or
        `ON_HOLD`"

        Design: Difficulty/dual_variant_calc/seasonal_build_projection_forward_vs_confirmed
        """
        plant, _run_b = self._setup_confirmed_plus_pipeline(api)
        window = get_window(plant["window"]["id"])
        assert_seasonal_window(window)
        assert window["confirmed_build_units"] == 4000
        assert window["projected_build_units"] == 7000, "confirmed plus pipeline"
        assert window["coverage_pct"] == pytest.approx(40.0)
        assert window["shortfall"] is True

    def test_cancel_drags_projected_down_to_confirmed(self, api):
        """PRD §3.6: "And the window's projection is recomputed with the `version`
        incremented, dropping the cancelled run from the pipeline term."
        PRD §3.4: "For any given window state the projected figure is at least the
        confirmed one, and the two diverge exactly when runs are still in the
        pipeline."

        Design: Difficulty/dual_variant_calc/seasonal_build_projection_forward_vs_confirmed
        """
        plant, run_b = self._setup_confirmed_plus_pipeline(api)
        cancel_run(run_b["id"])
        window = get_window(plant["window"]["id"])
        assert window["confirmed_build_units"] == 4000
        assert window["projected_build_units"] == 4000, (
            "with the pipeline empty the two variants coincide")


class TestProjectedExcludesCancelled:
    def test_cancelled_run_contributes_nothing_to_pipeline(self, api):
        """PRD §3.4: "`COMPLETED` and `CANCELLED` runs contribute nothing to the
        pipeline term."

        Design: Corner/calculations/projected_excludes_cancelled_runs
        """
        plant = setup_runnable_plant()
        run = create_run(plant["window"]["id"], plant["product"]["id"],
                         plant["recipe"]["id"], plant["line"]["id"],
                         planned_units=2000)
        window = get_window(plant["window"]["id"])
        assert window["projected_build_units"] == 2000
        assert window["confirmed_build_units"] == 0

        cancel_run(run["id"])
        window = get_window(plant["window"]["id"])
        assert window["projected_build_units"] == 0
        assert window["confirmed_build_units"] == 0
