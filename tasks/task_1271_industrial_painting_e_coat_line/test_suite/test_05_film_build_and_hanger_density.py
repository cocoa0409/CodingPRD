"""Film-build prediction tiers, window boundaries, and hanger density."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    setup_master_data, setup_lot_scheduled,
    create_and_accept_lot_in_ctx, create_run_slot_payload_for_ctx, get_lot,
    TEST_USERS,
)

SCHED = TEST_USERS["scheduler_headers"]


class TestFilmBuildDensityTiers:
    def test_tier_boundary_20_vs_21_parts_per_hanger(self, api):
        """PRD §3.4: "A denser hanger shields parts from deposition, so a density
        factor discounts the transfer: 1.00 when `parts_per_hanger` is 20 or fewer, 0.95
        when it lies between 21 and 40 inclusive, and 0.88 when it is 41 or more. The
        `predicted_film_build_um` is the film transfer constant 220.0 divided by the
        line speed, multiplied by the density factor, and rounded half-up to one decimal
        place — computed against a snapshot of the line's `line_speed_fpm` stored on the
        slot as `planned_line_speed_fpm`, so later speed changes do not rewrite history."

        Design: Difficulty/combinatorial_formula/film_build_tiered_density_speed_interaction
        """
        ctx = setup_master_data()  # line speed 10.0 fpm, film window 18-30
        lot_x = create_and_accept_lot_in_ctx(ctx, part_quantity=50)
        lot_y = create_and_accept_lot_in_ctx(ctx, part_quantity=50)

        slot_x = validate_success(
            api.create_run_slot(
                create_run_slot_payload_for_ctx(
                    ctx, lot_x["id"],
                    start_utc="2026-05-05T08:00:00Z", end_utc="2026-05-05T09:00:00Z",
                    parts_per_hanger=20,
                ),
                SCHED,
            ),
            201,
        )
        slot_y = validate_success(
            api.create_run_slot(
                create_run_slot_payload_for_ctx(
                    ctx, lot_y["id"],
                    start_utc="2026-05-05T09:00:00Z", end_utc="2026-05-05T10:00:00Z",
                    parts_per_hanger=21,
                ),
                SCHED,
            ),
            201,
        )
        assert slot_x["predicted_film_build_um"] == pytest.approx(22.0, abs=1e-9)
        assert slot_y["predicted_film_build_um"] == pytest.approx(20.9, abs=1e-9)

    def test_tier3_density_factor_at_41_parts(self, api):
        """PRD §3.4: "A denser hanger shields parts from deposition, so a density
        factor discounts the transfer: 1.00 when `parts_per_hanger` is 20 or fewer, 0.95
        when it lies between 21 and 40 inclusive, and 0.88 when it is 41 or more."

        Design: Difficulty/combinatorial_formula/film_build_tiered_density_speed_interaction
        """
        ctx = setup_master_data()
        lot = create_and_accept_lot_in_ctx(ctx)
        slot = validate_success(
            api.create_run_slot(
                create_run_slot_payload_for_ctx(
                    ctx, lot["id"],
                    start_utc="2026-05-05T08:00:00Z", end_utc="2026-05-05T09:00:00Z",
                    parts_per_hanger=41,
                ),
                SCHED,
            ),
            201,
        )
        # 220.0 / 10.0 * 0.88 = 19.36 -> 19.4 at one decimal half-up.
        assert slot["predicted_film_build_um"] == pytest.approx(19.4, abs=1e-9)


class TestFilmBuildWindowBoundary:
    def test_prediction_exactly_at_minimum_window_accepted(self, api):
        """PRD §3.4: "The prediction must lie within the specification's film window,
        `film_build_min_um` at the low end and `film_build_max_um` at the high end, both
        bounds inclusive; outside the window the create is rejected with
        `ERR_FILM_BUILD_OUT_OF_WINDOW`."

        Design: Difficulty/boundary_precision_check/film_build_exact_minimum_window_allowed
        """
        ctx = setup_master_data(
            spec_overrides={"film_build_min_um": 20.0, "film_build_max_um": 26.0},
            line_overrides={"line_speed_fpm": 11.0},
        )
        lot = create_and_accept_lot_in_ctx(ctx)
        # 220.0 / 11.0 * 1.00 = 20.0 -> exactly the inclusive lower bound.
        slot = validate_success(
            api.create_run_slot(
                create_run_slot_payload_for_ctx(
                    ctx, lot["id"],
                    start_utc="2026-05-05T08:00:00Z", end_utc="2026-05-05T10:00:00Z",
                    parts_per_hanger=20,
                ),
                SCHED,
            ),
            201,
        )
        assert slot["predicted_film_build_um"] == pytest.approx(20.0, abs=1e-9)

    def test_prediction_below_minimum_window_rejected(self, api):
        """PRD §3.4: "The prediction must lie within the specification's film window,
        `film_build_min_um` at the low end and `film_build_max_um` at the high end, both
        bounds inclusive; outside the window the create is rejected with
        `ERR_FILM_BUILD_OUT_OF_WINDOW`."

        Design: Difficulty/boundary_precision_check/film_build_exact_minimum_window_allowed
        """
        ctx = setup_master_data(
            spec_overrides={"film_build_min_um": 20.0, "film_build_max_um": 26.0},
            line_overrides={"line_speed_fpm": 13.0},
        )
        lot = create_and_accept_lot_in_ctx(ctx)
        # 220.0 / 13.0 * 1.00 = 16.923... -> 16.9 < 20.0 -> rejected.
        res = api.create_run_slot(
            create_run_slot_payload_for_ctx(
                ctx, lot["id"],
                start_utc="2026-05-05T08:00:00Z", end_utc="2026-05-05T10:00:00Z",
                parts_per_hanger=20,
            ),
            SCHED,
        )
        validate_error(res, "ERR_FILM_BUILD_OUT_OF_WINDOW", expected_status=422)
        lot_after = get_lot(lot["id"])
        assert lot_after["status"] == "QUEUED"
