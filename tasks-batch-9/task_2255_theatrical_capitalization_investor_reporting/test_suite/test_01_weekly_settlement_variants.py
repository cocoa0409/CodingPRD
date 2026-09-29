"""
The two royalty settlement variants, and the two recoupment bases.

Both pairs are deliberately built from byte-identical box-office inputs, so the
only thing that can explain a different answer is the variant the server picked.
"""

from test_helpers import (
    COMPTROLLER_HEADERS,
    GM_HEADERS,
    ApiClient,
    World,
    fixtures,
)
from prd_bench_local_runner.testing import get_success_data


def _certified_standard_week(world: World) -> str:
    """Record, submit and certify the profitable week ending 2026-09-06."""
    fixtures.with_submitted_standard_week(world)
    wrap_id = world.wrap_id or ""
    fixtures.certify_wrap(world, wrap_id)
    return wrap_id


def _certified_week(world: World, **overrides) -> str:
    """Record, submit and certify one further week at the current clock."""
    wrap_id = fixtures.new_wrap(world, **overrides)
    fixtures.submit_wrap(world, wrap_id)
    fixtures.certify_wrap(world, wrap_id)
    return wrap_id


class TestFixedGrossVersusPoolSettlement:
    """Two weeks with the same gross settle differently on the two bases."""

    def test_identical_weeks_settle_to_different_royalty_burdens(self, api: ApiClient):
        """A fixed-gross week and a pool week with the same figures differ by 5,256,250.

        "Under the **fixed-gross variant** — the structure every production
        starts in — `royalty_pool_cents` is the sum, over each participant in
        the ordered set, of that participant's `fixed_gross_pct` applied to the
        wrap's `adjusted_gross_cents` and rounded half up to whole cents *per
        participant* before summing."

        Design: Difficulty/dual_variant_calc/wrap_settlement_fixed_gross_vs_pool_basis_delta
        """
        world = fixtures.ledger_world(api)

        first_wrap_id = _certified_standard_week(world)
        first = get_success_data(api.get_weekly_wrap(first_wrap_id, GM_HEADERS), 200)

        # 0.04 + 0.02 + 0.015 of the 61,750,000 adjusted gross, rounded per
        # participant: 2,470,000 + 1,235,000 + 926,250.
        assert first["royalty_basis_applied"] == "FIXED_GROSS"
        assert first["royalty_pool_cents"] == 4_631_250
        assert first["weekly_operating_profit_cents"] == 23_618_750

        fixtures.convert_to_pool(world)
        world.set_clock("2026-09-14")
        second_wrap_id = _certified_week(world, week_ending_date="2026-09-13")
        second = get_success_data(api.get_weekly_wrap(second_wrap_id, GM_HEADERS), 200)

        # 35% of the 28,250,000 royalty base, above the 800,000 floor and below
        # the base itself, so neither clamp binds.
        assert second["royalty_basis_applied"] == "POOL"
        assert second["royalty_pool_cents"] == 9_887_500
        assert second["weekly_operating_profit_cents"] == 18_362_500

        assert (
            first["weekly_operating_profit_cents"]
            - second["weekly_operating_profit_cents"]
            == 5_256_250
        )
        for wrap in (first, second):
            assert wrap["variable_cost_cents"] == 3_250_000
            assert wrap["adjusted_gross_cents"] == 61_750_000
            assert wrap["royalty_base_cents"] == 28_250_000
            assert wrap["capacity_gross_cents"] == 191_040_000
            assert wrap["paid_capacity_pct"] == 0.8542

    def test_conversion_does_not_rewrite_an_already_certified_week(self, api: ApiClient):
        """The frozen basis survives the conversion, and both weeks roll up together.

        "On certification the wrap's `royalty_basis_applied` is frozen to
        whatever the production's `royalty_basis` reads at that instant, and
        that frozen value selects between two settlement variants that produce
        genuinely different numbers from identical inputs."

        Design: Difficulty/dual_variant_calc/wrap_settlement_fixed_gross_vs_pool_basis_delta
        """
        world = fixtures.ledger_world(api)

        first_wrap_id = _certified_standard_week(world)
        fixtures.convert_to_pool(world)
        world.set_clock("2026-09-14")
        _certified_week(world, week_ending_date="2026-09-13")

        reread = get_success_data(api.get_weekly_wrap(first_wrap_id, GM_HEADERS), 200)
        assert reread["royalty_basis_applied"] == "FIXED_GROSS"
        assert reread["royalty_pool_cents"] == 4_631_250

        production = world.production()
        assert production["royalty_basis"] == "POOL"
        # 18,362,500 from the pool week plus 23,618,750 from the fixed-gross week.
        assert production["recouped_amount_cents"] == 41_981_250
        assert production["deferred_royalty_cents"] == 0


class TestCashVersusAccrualRecoupment:
    """The report publishes both bases, and they diverge for two named reasons."""

    def test_report_publishes_both_bases_with_the_bridge_between_them(
        self, api: ApiClient
    ):
        """Deferred guarantees come off the cash figure and the receivable goes on.

        "It starts from the cash-basis `recouped_amount_cents`, subtracts the
        production's `deferred_royalty_cents` — the accrued but unpaid minimum
        guarantees banked by loss weeks under the pool structure — and adds a
        receivable: the sum, over every licensing-income row of the production
        whose `status` is still `RECORDED`, of that row's `gross_income_cents`
        multiplied by the production's
        `subsidiary_rights_investor_share_pct` and rounded half up to whole
        cents per row."

        Design: Difficulty/dual_variant_calc/recoupment_progress_cash_vs_accrual_basis_divergence
        """
        world = fixtures.ledger_world(api, pool_basis=True)
        _certified_standard_week(world)

        world.set_clock("2026-09-14")
        _certified_week(
            world,
            week_ending_date="2026-09-13",
            gross_receipts_cents=30_000_000,
            paid_attendance=4_000,
        )
        fixtures.with_recorded_income(
            world, gross_income_cents=5_000_000, received_date="2026-09-12"
        )

        report = get_success_data(
            api.get_recoupment_report(world.production_id, COMPTROLLER_HEADERS), 200
        )
        assert report["cash_basis_recouped_cents"] == 18_362_500
        assert report["cash_basis_recoupment_pct"] == 0.1530
        # 18,362,500 - 800,000 deferred + 40% of the 5,000,000 receipt.
        assert report["accrual_basis_recouped_cents"] == 19_562_500
        assert report["accrual_basis_recoupment_pct"] == 0.1630
        assert report["deferred_royalty_cents"] == 800_000
        assert report["subsidiary_rights_receivable_cents"] == 2_000_000
        assert report["recoupment_status"] == "UNRECOUPED"
        assert report["capitalization_target_cents"] == 120_000_000

    def test_losing_pool_week_accrues_the_guarantee_floor_instead_of_paying_it(
        self, api: ApiClient
    ):
        """A week with no operating profit pays nothing and banks the whole floor.

        "If the wrap's `royalty_base_cents` is 0 or less — a week with no
        operating profit at all — then `royalty_pool_cents` is 0 and
        `deferred_royalty_added_cents` is set to the full `pool_floor_cents`:
        the guarantees are not paid, they accrue."

        Design: Difficulty/dual_variant_calc/recoupment_progress_cash_vs_accrual_basis_divergence
        """
        world = fixtures.ledger_world(api, pool_basis=True)
        _certified_standard_week(world)

        world.set_clock("2026-09-14")
        losing_wrap_id = _certified_week(
            world,
            week_ending_date="2026-09-13",
            gross_receipts_cents=30_000_000,
            paid_attendance=4_000,
        )

        losing = get_success_data(
            api.get_weekly_wrap(losing_wrap_id, COMPTROLLER_HEADERS), 200
        )
        assert losing["adjusted_gross_cents"] == 28_500_000
        # 28,500,000 adjusted gross less 33,500,000 of running expenses, floored.
        assert losing["royalty_base_cents"] == 0
        assert losing["royalty_pool_cents"] == 0
        assert losing["weekly_operating_profit_cents"] == 0
        # 400,000 + 250,000 + 150,000 of aggregate minimum guarantees.
        assert losing["deferred_royalty_added_cents"] == 800_000
        assert losing["paid_capacity_pct"] == 0.4167

        production = world.production()
        assert production["deferred_royalty_cents"] == 800_000
        assert production["recouped_amount_cents"] == 18_362_500
