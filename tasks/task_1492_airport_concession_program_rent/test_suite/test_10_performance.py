"""Sales-per-enplanement performance review: the TTM and YTD window variants,
window qualification rules, and the insufficient-data outcome."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_enplanement_snapshot,
    file_and_accept_report,
    setup_active_lease,
    setup_spe_scenario,
    validate_error,
    validate_success,
)


class TestTtmVsYtdVariants:
    def test_spe_ttm_window_includes_weak_anchor_month(self, api, analyst_headers):
        """PRD §3.8: "The trailing-twelve-month window covers the twelve calendar
        months ending at the latest month having an `ACCEPTED` or `ADJUSTED` report."
        PRD §3.8: "Sales per enplanement is the window's total sales multiplied by
        one hundred, divided by the window's total enplanements, and rounded half up
        to integer cents per enplanement."
        PRD §3.8: "The `review_outcome` is read off the trailing figure:
        `INSUFFICIENT_DATA` when `spe_ttm_cents` is null, `UNDERPERFORMING` when it
        is below the lease's `min_spe_cents` floor, and `SATISFACTORY` when it is at
        or above the floor — the boundary is satisfactory."

        Design: Difficulty/dual_variant_calc/spe_ttm_vs_ytd_divergence
        """
        sc = setup_spe_scenario()
        perf = validate_success(
            api.get_lease_performance(sc["lease"]["id"], analyst_headers), 200
        )
        # TTM window 2025-08..2026-07 qualifies 2025-12, 2026-06, 2026-07:
        # sales 1,300,000 over 450,000 enplanements.
        assert perf["sales_ttm_cents"] == 1_300_000
        assert perf["enplanements_ttm"] == 450_000
        assert perf["spe_ttm_cents"] == 289  # round_half_up(130,000,000 / 450,000)
        assert perf["review_outcome"] == "UNDERPERFORMING"  # 289 < min_spe 1000

    def test_spe_ytd_window_diverges_from_ttm(self, api, analyst_headers):
        """PRD §3.8: "The year-to-date window covers the months of the logical
        clock's calendar year up to and including the current month."
        PRD §3.8: "Two windows are always computed, and they can disagree because
        they anchor differently."

        Design: Difficulty/dual_variant_calc/spe_ttm_vs_ytd_divergence
        """
        sc = setup_spe_scenario()  # clock stays at the 2026-08-01 startup default
        perf = validate_success(
            api.get_lease_performance(sc["lease"]["id"], analyst_headers), 200
        )
        # YTD window 2026-01..2026-08 qualifies only 2026-06 and 2026-07:
        # 1,200,000 * 100 / 250,000 = 480 — diverging from the TTM figure of 289.
        assert perf["spe_ytd_cents"] == 480
        assert perf["spe_ttm_cents"] == 289
        assert perf["spe_ytd_cents"] != perf["spe_ttm_cents"]


class TestInsufficientData:
    def test_spe_insufficient_data_when_no_snapshots(self, api, analyst_headers):
        """PRD §3.8: "Within each window, a month qualifies only when both sides of
        the ratio exist — an effective sales figure from an `ACCEPTED` or `ADJUSTED`
        report, and an enplanement snapshot — and months missing either side are
        excluded from both the numerator and the denominator."
        PRD §3.8: "A window with zero qualifying months yields a null figure."
        PRD §3.8: "The `review_outcome` is read off the trailing figure:
        `INSUFFICIENT_DATA` when `spe_ttm_cents` is null, `UNDERPERFORMING` when it
        is below the lease's `min_spe_cents` floor, and `SATISFACTORY` when it is at
        or above the floor — the boundary is satisfactory."

        Design: Corner/calculations/spe_insufficient_data_when_no_snapshots
        """
        sc = setup_active_lease()
        file_and_accept_report(sc["lease"], sc["tenant"], "2026-07", 300_000)
        # No enplanement snapshots exist, so no month qualifies for either window.
        perf = validate_success(
            api.get_lease_performance(sc["lease"]["id"], analyst_headers), 200
        )
        assert perf["spe_ttm_cents"] is None
        assert perf["review_outcome"] == "INSUFFICIENT_DATA"

    def test_duplicate_enplanement_month_returns_enplanement_month_duplicate(
        self, api, admin_headers
    ):
        """PRD §3.8: "One snapshot exists per month across the whole program; a
        duplicate month is rejected with `ERR_ENPLANEMENT_MONTH_DUPLICATE`."

        Design: Corner/validations/duplicate_enplanement_month_returns_enplanement_month_duplicate
        """
        create_enplanement_snapshot("2026-06", 100_000)
        res = api.create_enplanement_snapshot(
            {"month": "2026-06", "enplanements": 110_000}, admin_headers
        )
        validate_error(res, ApiErrorId.ERR_ENPLANEMENT_MONTH_DUPLICATE)
