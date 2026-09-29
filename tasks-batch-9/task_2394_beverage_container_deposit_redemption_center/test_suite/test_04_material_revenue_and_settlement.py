"""Material revenue arithmetic and the ten-step funding settlement.

Baling and selling turn accepted containers into money, and the quarter's
reconciliation composes ten pinned steps over the resulting ledger. Both are
rounding-sensitive, so the expected figures are pinned to the cent.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    assert_center_pool,
    assert_period_settlement,
    assert_weight_precision,
    expected_handling_fee_cents,
)
from test_helpers import factories as f
from test_helpers import fixtures as h

INSTANT = "2026-08-05T09:00:00Z"
BALE_WEIGHTS = [14.12, 16.13, 12.62]
CONTAMINATION = 0.0375


def _center_holding_five_hundred_containers(api, period_overrides=None):
    """A world whose centre holds 500 unbatched containers from one anonymous visit."""
    world = h.build_world(
        api,
        center_overrides={"site_name": "Bend Redemption Center"},
        period_overrides=period_overrides or {"operating_cost_cents": 1000},
    )
    h.create_counted_center_visit(
        api, world.center_id, world.machine_id, world.product_id, [500]
    )
    return world


class TestPricingModeDivergence:
    """Two identical batches diverge purely by pricing mode."""

    def test_spot_price_is_taken_as_quoted(self, api):
        """A SPOT sale keeps the quoted price and nets 6162 cents.

        PRD: "under `SPOT` pricing it equals `quoted_price_cents_per_tonne` unchanged"

        Design: Difficulty/dual_variant_calc/commodity_spot_vs_index_pricing_divergence
        """
        world = _center_holding_five_hundred_containers(api)
        batch = h.create_baled_batch(
            api,
            world.center_id,
            200,
            CONTAMINATION,
            BALE_WEIGHTS,
            batch_code="SPOT-A",
        )

        sold = validate_success(
            api.sell_commodity_batch(
                batch["id"],
                f.batch_sale_payload("SPOT", 154000, world.period_id),
                world.center_headers,
            )
        )

        assert sold["effective_price_cents_per_tonne"] == 154000
        assert sold["gross_weight_kg"] == 42.87
        assert_weight_precision(sold["gross_weight_kg"])
        assert sold["gross_revenue_cents"] == 6355
        assert sold["freight_cents"] == 193
        assert sold["net_revenue_cents"] == 6162
        assert sold["status"] == "SOLD"

    def test_index_price_is_cut_by_two_hundred_and_fifty_basis_points(self, api):
        """An INDEX sale at 160000 prices at 156000 and nets 6244 cents.

        PRD: "under `INDEX` pricing the quoted price is reduced by 250 basis points — that
        is, multiplied by 0.9750 — and rounded to the nearest cent, which lowers every
        per-bale figure and therefore the batch's gross revenue."

        Design: Difficulty/dual_variant_calc/commodity_spot_vs_index_pricing_divergence
        """
        world = _center_holding_five_hundred_containers(api)
        spot = h.create_baled_batch(
            api, world.center_id, 200, CONTAMINATION, BALE_WEIGHTS, batch_code="SPOT-A"
        )
        h.sell_batch(api, spot["id"], world.center_id, "SPOT", 154000, world.period_id)
        index = h.create_baled_batch(
            api, world.center_id, 200, CONTAMINATION, BALE_WEIGHTS, batch_code="IDX-B"
        )

        sold = validate_success(
            api.sell_commodity_batch(
                index["id"],
                f.batch_sale_payload("INDEX", 160000, world.period_id),
                world.center_headers,
            )
        )

        assert sold["effective_price_cents_per_tonne"] == 156000
        assert sold["gross_weight_kg"] == 42.87
        assert sold["gross_revenue_cents"] == 6437
        assert sold["freight_cents"] == 193
        assert sold["net_revenue_cents"] == 6244

        period = h.read_period(api, world.period_id)
        assert period["material_revenue_cents"] == 12406
        assert period["outstanding_liability_cents"] == 0

        center = h.read_center(api, world.center_id, world.center_headers)
        assert_center_pool(
            center, batched_container_count=400, unbatched_container_count=100
        )


class TestPerBaleRounding:
    """Gross revenue rounds each bale before summing, not after."""

    def test_gross_revenue_is_the_sum_of_three_rounded_bales(self, api):
        """The three bales contribute 2093, 2391 and 1871 cents, summing to 6355.

        PRD: "that per-bale figure is rounded to the nearest cent before it is added in"

        Design: Difficulty/combinatorial_formula/material_sale_round_per_bale_then_sum
        """
        world = _center_holding_five_hundred_containers(api)
        batch = h.create_baled_batch(
            api,
            world.center_id,
            300,
            CONTAMINATION,
            BALE_WEIGHTS,
            batch_code="ROUND-A",
        )
        assert batch["bale_count"] == 3
        assert batch["gross_weight_kg"] == 42.87

        sold = validate_success(
            api.sell_commodity_batch(
                batch["id"],
                f.batch_sale_payload("SPOT", 154000, world.period_id),
                world.center_headers,
            )
        )

        assert sold["gross_revenue_cents"] == 6355
        assert sold["gross_revenue_cents"] != 6354, (
            "rounding the summed product instead of each bale would yield 6354"
        )

    def test_freight_is_deducted_from_the_summed_gross(self, api):
        """Freight of 193 cents leaves a net of 6162 cents booked to the quarter.

        PRD: "`freight_cents` is `gross_weight_kg` divided by 1000 to convert to tonnes,
        multiplied by a flat freight rate of 4500 cents per tonne, rounded to the nearest
        cent. Fourth, `net_revenue_cents` is `gross_revenue_cents` less `freight_cents`,
        floored at 0".

        Design: Difficulty/combinatorial_formula/material_sale_round_per_bale_then_sum
        """
        world = _center_holding_five_hundred_containers(api)
        batch = h.create_baled_batch(
            api,
            world.center_id,
            300,
            CONTAMINATION,
            BALE_WEIGHTS,
            batch_code="ROUND-A",
        )
        sold = h.sell_batch(
            api, batch["id"], world.center_id, "SPOT", 154000, world.period_id
        )

        assert sold["freight_cents"] == 193
        assert sold["net_revenue_cents"] == 6162

        period = h.read_period(api, world.period_id)
        assert period["material_revenue_cents"] == 6162


class TestFundingSettlement:
    """Reconciliation composes ten steps, each consuming the previous one."""

    @staticmethod
    def _quarter_ready_to_reconcile(api):
        """3000 cents initiated, 2200 paid out over 220 containers, 755 earned on glass."""
        world = h.build_world(
            api,
            center_overrides={"site_name": "Bend Redemption Center"},
            period_overrides={"operating_cost_cents": 1000},
        )
        h.initiate_deposits(
            api, world.distributor_id, world.product_id, 300, world.period_id
        )
        h.create_paid_center_visit(
            api,
            world.center_id,
            world.machine_id,
            world.product_id,
            [220],
            world.account_id,
        )
        glass = h.create_baled_batch(
            api,
            world.center_id,
            100,
            0.02,
            [50.00],
            material="GLASS",
            batch_code="GLASS-A",
        )
        sold = h.sell_batch(
            api, glass["id"], world.center_id, "SPOT", 20000, world.period_id
        )
        assert sold["net_revenue_cents"] == 755
        return world

    def test_reconcile_walks_the_handling_tiers_marginally(self, api):
        """220 redeemed containers earn 3 cents each, so the handling fee is 660.

        PRD: "the fee is 3 cents times the lesser of the redeemed count and 50,000; plus
        2 cents times the lesser of the redeemed count and 150,000 reduced by 50,000,
        floored at 0; plus 1 cent times the redeemed count reduced by 150,000, floored at
        0."

        Design: Difficulty/combinatorial_formula/period_settlement_pinned_evaluation_order
        """
        world = self._quarter_ready_to_reconcile(api)

        reconciled = validate_success(
            api.post_period_action(
                world.period_id, f.period_action_payload("RECONCILE"), ADMIN_HEADERS
            )
        )

        assert reconciled["status"] == "RECONCILING"
        assert reconciled["deposits_initiated_cents"] == 3000
        assert reconciled["containers_initiated_count"] == 300
        assert reconciled["redemptions_paid_cents"] == 2200
        assert reconciled["containers_redeemed_count"] == 220
        assert reconciled["material_revenue_cents"] == 755
        assert reconciled["handling_fee_cents"] == 660
        assert reconciled["handling_fee_cents"] == expected_handling_fee_cents(220)

    def test_sweep_is_bounded_by_the_shortfall_and_leaves_the_quarter_short(
        self, api
    ):
        """The 800-cent unredeemed pool is swept in full against a 905-cent shortfall.

        PRD: "`sweep_to_funding_cents` is the lesser of `gross_unredeemed_cents` and
        `admin_shortfall_cents` — the programme may consume unredeemed deposits only up to
        the size of its shortfall, and only up to the size of the unredeemed pool."

        Design: Difficulty/combinatorial_formula/period_settlement_pinned_evaluation_order
        """
        world = self._quarter_ready_to_reconcile(api)

        h.period_action(api, world.period_id, "RECONCILE")
        period = h.read_period(api, world.period_id)

        assert_period_settlement(
            period,
            handling_fee_cents=660,
            gross_unredeemed_cents=800,
            admin_shortfall_cents=905,
            sweep_to_funding_cents=800,
            unredeemed_deposit_cents=0,
            funding_balance_cents=-105,
            funding_status="SHORTFALL",
        )
        assert period["outstanding_liability_cents"] == 0

        center = h.read_center(api, world.center_id, world.center_headers)
        assert center["cash_drawer_balance_cents"] == 47800


class TestQuarterIntervalsAreClosed:
    """A quarter reserves a closed interval, so a shared endpoint collides."""

    def test_a_single_shared_calendar_date_is_refused(self, api):
        """A quarter starting on the stored quarter's end date overlaps it.

        PRD: "if the requested closed interval from `start_date` to `end_date` shares even
        a single calendar date with any existing quarter — whatever that quarter's
        `status`, `OPEN`, `RECONCILING` or `CLOSED` — the request is refused with
        `ERR_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/program_period_closed_interval_shared_endpoint_overlap
        """
        h.set_clock(api, INSTANT)
        q3 = h.create_period(api, operating_cost_cents=1000)

        response = api.create_program_period(
            f.create_program_period_payload(
                quarter_code="2026Q4",
                start_date="2026-09-30",
                end_date="2026-12-31",
                operating_cost_cents=900,
            ),
            ADMIN_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_PERIOD_OVERLAP.value)

        assert h.read_period(api, q3["id"])["end_date"] == "2026-09-30"

    def test_the_zero_gap_adjacent_quarter_is_accepted(self, api):
        """A quarter starting the day after the stored end date is created.

        PRD: "A new quarter opens in `status` `OPEN` with `funding_status` `UNSETTLED` and
        every money field at 0."

        Design: Difficulty/resource_temporal_overlap/program_period_closed_interval_shared_endpoint_overlap
        """
        h.set_clock(api, INSTANT)
        h.create_period(api, operating_cost_cents=1000)

        response = api.create_program_period(
            f.create_program_period_payload(
                quarter_code="2026Q4",
                start_date="2026-10-01",
                end_date="2026-12-31",
                operating_cost_cents=900,
            ),
            ADMIN_HEADERS,
        )
        q4 = validate_success(response, expected_status=201)

        assert q4["status"] == "OPEN"
        assert q4["start_date"] == "2026-10-01"
        assert q4["end_date"] == "2026-12-31"
        assert q4["funding_status"] == "UNSETTLED"

        _, meta = validate_paginated(api.list_program_periods(ADMIN_HEADERS))
        assert meta["total_count"] == 2
