"""The two-variant calculations: PROVISIONAL vs FINAL restock allocation, and
TRAILING_30 vs SEASONAL_WEIGHTED velocity forecasting on identical inputs."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_line_item,
    api_client,
    assert_velocity_forecast,
    confirm_plan,
    create_forecast,
    create_plan,
    newest_quota,
    read_fulfillment_center,
    read_listing,
    read_plan,
    read_seller,
    setup_baseline,
    validate_error,
    validate_paginated,
)


def _two_draft_plans() -> dict:
    """Seller scored 1000 (restock_limit_units 3000) holding two DRAFT plans:
    plan A declares 1200 units, plan B declares 2500 units across two lines."""
    ctx = setup_baseline()
    plan_a = create_plan(
        ctx["seller_id"], ctx["fc_id"], "2026-08-10T00:00:00Z", "2026-08-11T00:00:00Z"
    )
    line_a = add_line_item(plan_a["id"], ctx["seller_id"], ctx["listing_id"], 1200)
    plan_b = create_plan(
        ctx["seller_id"], ctx["fc_id"], "2026-08-20T00:00:00Z", "2026-08-21T00:00:00Z"
    )
    line_b1 = add_line_item(plan_b["id"], ctx["seller_id"], ctx["listing_id"], 1000)
    line_b2 = add_line_item(plan_b["id"], ctx["seller_id"], ctx["listing_id"], 1500)
    ctx.update({
        "plan_a": plan_a, "line_a": line_a,
        "plan_b": plan_b, "line_b1": line_b1, "line_b2": line_b2,
    })
    return ctx


def _plan_lines(plan_id: str, headers) -> list:
    rows, _meta = validate_paginated(api_client.list_plan_line_items(plan_id, headers))
    return rows


class TestRestockAllocationProvisionalVersusFinal:
    """The PROVISIONAL pool charges sibling drafts and the FINAL pool does not."""

    def test_provisional_pool_is_reduced_by_the_sibling_draft_charge(self):
        """The second draft plan sees a pool of only 1800 units because its sibling
        draft has already provisionally claimed 1200 of the 3000-unit limit.

        PRD 3.3: "The `PROVISIONAL` variant, which runs on plan creation and on every
        line-item creation, works from a pool equal to the larger of 0 and
        `restock_limit_units` minus the committed charge minus the sibling draft charge."
        PRD 3.3: "Given a pool, the waterfall walks this plan's line items in ascending
        `created_at` order, granting each line the smaller of its `units` and the pool
        remaining at that point, then reducing the remaining pool by the grant."

        Design: Difficulty/dual_variant_calc/restock_allocation_provisional_pool_shrinks_below_final_pool
        """
        ctx = _two_draft_plans()
        quota = newest_quota(ctx["seller_id"])
        assert quota["restock_limit_units"] == 3000

        plan_b = read_plan(ctx["plan_b"]["id"], ctx["seller_id"])
        assert plan_b["declared_units"] == 2500
        assert plan_b["provisional_allocated_units"] == 1800
        assert plan_b["allocation_status"] == "OVER_LIMIT"
        assert plan_b["final_allocated_units"] == 0

        lines = _plan_lines(ctx["plan_b"]["id"], ctx["seller_headers"])
        assert [line["provisional_allocated_units"] for line in lines] == [1000, 800]

    def test_final_pool_ignores_sibling_drafts_so_an_over_limit_draft_confirms(self):
        """Plan B reads OVER_LIMIT in draft yet confirms for its full 2500 units,
        because the FINAL pool drops the sibling draft charge entirely.

        PRD 3.3: "The `FINAL` variant, which runs only at confirmation, works from a pool
        equal to the larger of 0 and `restock_limit_units` minus the committed charge
        alone, ignoring every sibling draft."
        PRD 3.4: "The seller's `restock_reserved_units` increases by the plan's
        `allocated_units`, the active quota period's `utilized_units` increases by the same
        amount, and the destination centre's `committed_receiving_units` increases by the
        plan's `declared_units`."

        Design: Difficulty/dual_variant_calc/restock_allocation_provisional_pool_shrinks_below_final_pool
        """
        ctx = _two_draft_plans()
        confirmed = confirm_plan(
            ctx["plan_b"]["id"], ctx["seller_id"], confirmation_note="final allocation"
        )
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["final_allocated_units"] == 2500
        assert confirmed["allocated_units"] == 2500

        lines = _plan_lines(ctx["plan_b"]["id"], ctx["seller_headers"])
        assert [line["final_allocated_units"] for line in lines] == [1000, 1500]

        assert newest_quota(ctx["seller_id"])["utilized_units"] == 2500
        assert read_seller(ctx["seller_id"])["restock_reserved_units"] == 2500
        assert read_fulfillment_center(ctx["fc_id"])["committed_receiving_units"] == 2500

    def test_sibling_draft_is_refreshed_and_then_fails_the_restock_gate(self):
        """Once plan B's units join the committed charge, plan A's provisional grant
        falls to 500 and its own confirmation is refused outright.

        PRD 3.4: "Finally, the `PROVISIONAL` waterfall is refreshed for every *other* plan
        of this seller whose `status` is `DRAFT`, which may flip those siblings'
        `allocation_status` to `OVER_LIMIT` now that this plan's units have moved into the
        committed charge."
        PRD 3.4: "The `FINAL` waterfall runs, and if the resulting `final_allocated_units`
        is strictly below the plan's `declared_units` the confirmation is rejected with
        `ERR_RESTOCK_LIMIT_EXCEEDED` and nothing is persisted; a grant exactly equal to
        `declared_units` is accepted."

        Design: Difficulty/dual_variant_calc/restock_allocation_provisional_pool_shrinks_below_final_pool
        """
        ctx = _two_draft_plans()
        confirm_plan(
            ctx["plan_b"]["id"], ctx["seller_id"], confirmation_note="final allocation"
        )

        plan_a = read_plan(ctx["plan_a"]["id"], ctx["seller_id"])
        assert plan_a["provisional_allocated_units"] == 500
        assert plan_a["allocation_status"] == "OVER_LIMIT"
        lines = _plan_lines(ctx["plan_a"]["id"], ctx["seller_headers"])
        assert [line["provisional_allocated_units"] for line in lines] == [500]

        response = api_client.confirm_plan(
            ctx["plan_a"]["id"], {}, ctx["seller_headers"]
        )
        validate_error(response, ApiErrorId.ERR_RESTOCK_LIMIT_EXCEEDED.value)

        plan_a = read_plan(ctx["plan_a"]["id"], ctx["seller_id"])
        assert plan_a["status"] == "DRAFT"
        assert plan_a["final_allocated_units"] == 0


class TestVelocityForecastVariantsOnIdenticalInputs:
    """`TRAILING_30` and `SEASONAL_WEIGHTED` are genuinely different answers."""

    FORECAST_INPUTS = {
        "trailing_30_units_sold": 600,
        "prior_year_same_period_units_sold": 900,
        "seasonal_index": 1.40,
        "coverage_target_days": 45,
        "lead_time_days": 15,
    }

    def test_trailing_variant_ignores_the_prior_year_figure_and_seasonal_index(self):
        """With 600 units sold in the trailing window the daily velocity is exactly
        20.0000 and the 60-day coverage target is 1200 units.

        PRD 3.3: "Under `TRAILING_30`, `daily_velocity` is `trailing_30_units_sold` divided
        by the 30-day trailing window, rounded half up to four decimal places; the
        prior-year figure and the `seasonal_index` are ignored even when supplied."
        PRD 3.3: "`target_units` is `daily_velocity` multiplied by the sum of
        `coverage_target_days` and `lead_time_days`, rounded **up** to the next whole unit."

        Design: Difficulty/dual_variant_calc/velocity_forecast_seasonal_blend_diverges_from_trailing_window
        """
        ctx = setup_baseline()
        forecast = create_forecast(
            ctx["listing_id"], ctx["seller_id"],
            forecast_variant="TRAILING_30", **self.FORECAST_INPUTS,
        )
        assert_velocity_forecast(forecast)
        assert float(forecast["daily_velocity"]) == pytest.approx(20.0, abs=1e-4)
        assert forecast["target_units"] == 1200
        assert forecast["in_flight_units"] == 0
        assert forecast["quota_headroom_units"] == 3000
        assert forecast["recommended_replenishment_units"] == 1200
        assert forecast["stranded_risk_flag"] is False

    def test_seasonal_blend_diverges_from_the_trailing_window_by_528_units(self):
        """The blended numerator lifts daily velocity to 28.8000 and the recommendation
        to 1728 units, and the listing keeps the most recent forecast's number.

        PRD 3.3: "Under `SEASONAL_WEIGHTED`, the numerator is 0.60 times
        `trailing_30_units_sold` plus 0.40 times the product of
        `prior_year_same_period_units_sold` and `seasonal_index`; that numerator is divided
        by 30 and rounded half up to four decimal places."
        PRD 3.3: "Each forecast is written as a new immutable row, and its
        `recommended_replenishment_units` is copied onto the listing; the listing therefore
        always reflects the most recent forecast, meaning the forecast row with the latest
        `created_at`."

        Design: Difficulty/dual_variant_calc/velocity_forecast_seasonal_blend_diverges_from_trailing_window
        """
        ctx = setup_baseline()
        trailing = create_forecast(
            ctx["listing_id"], ctx["seller_id"],
            forecast_variant="TRAILING_30", **self.FORECAST_INPUTS,
        )
        seasonal = create_forecast(
            ctx["listing_id"], ctx["seller_id"],
            forecast_variant="SEASONAL_WEIGHTED", **self.FORECAST_INPUTS,
        )
        assert_velocity_forecast(seasonal)
        assert float(seasonal["daily_velocity"]) == pytest.approx(28.8, abs=1e-4)
        assert seasonal["target_units"] == 1728
        assert seasonal["recommended_replenishment_units"] == 1728
        assert (
            seasonal["recommended_replenishment_units"]
            - trailing["recommended_replenishment_units"] == 528
        )

        listing = read_listing(ctx["listing_id"], ctx["seller_id"])
        assert listing["recommended_replenishment_units"] == 1728
