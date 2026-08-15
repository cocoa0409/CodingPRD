"""Order pricing: early-order tiers, cutoff boundaries, volume rebates, and
immediate read-back consistency of the locked price."""
from test_helpers import (
    TEST_USERS,
    add_line,
    assert_seed_order,
    create_draft_order,
    set_clock,
    setup_market,
    validate_success,
)

SALESREP = TEST_USERS["salesrep_headers"]

# Standard three-tier early-order schedule used by the tier tests below.
THREE_TIERS = [
    {"cutoff_at": "2026-09-30T23:59:59Z", "discount_bps": 1200},
    {"cutoff_at": "2026-11-15T23:59:59Z", "discount_bps": 1000},
    {"cutoff_at": "2027-01-15T23:59:59Z", "discount_bps": 600},
]


def _early_tier_market(api):
    return setup_market(
        program_overrides={
            "early_order_tiers": THREE_TIERS,
            "prepay_tiers": [
                {"pay_by": "2026-12-20T23:59:59Z", "discount_bps": 800},
                {"pay_by": "2027-02-15T23:59:59Z", "discount_bps": 500},
            ],
            "volume_rebate_tiers": [{"min_units": 500, "rebate_bps": 500}],
        },
        lot_overrides={"received_units": 10000},
    )


def _order_with_units(ctx, units):
    order = create_draft_order(ctx["grower"], ctx["program"])
    add_line(order, ctx["variety"]["id"], units)
    return order


class TestEarlyOrderTierBranches:
    def test_small_order_gate_beats_date_tier(self, api):
        """PRD §3.5: "otherwise, orders smaller than 20 total units earn
        nothing; otherwise the tiers are walked in ascending `cutoff_at` order
        and the first tier whose cutoff is at or after the confirmation instant
        wins — the boundary is inclusive — and if the clock has passed every
        cutoff the discount is zero."

        Design: Difficulty/combinatorial_formula/early_order_tier_branches_replacement_small_order_date
        """
        ctx = _early_tier_market(api)
        set_clock("2026-09-15T00:00:00Z")
        small = _order_with_units(ctx, 10)
        qualifying = _order_with_units(ctx, 30)

        small = validate_success(api.confirm_order(small["id"], SALESREP))
        assert_seed_order(small)
        assert small["locked_discount_bps"] == 0, (
            "10 total units is below the 20-unit gate despite the tier-1 window"
        )
        assert small["net_amount_cents"] == 10 * 18000

        qualifying = validate_success(api.confirm_order(qualifying["id"], SALESREP))
        assert qualifying["locked_discount_bps"] == 1200
        # per unit: round_half_up(18000 x 0.88) = 15840
        assert qualifying["net_amount_cents"] == 30 * 15840

    def test_order_after_last_cutoff_earns_nothing(self, api):
        """PRD §3.5: "otherwise, orders smaller than 20 total units earn
        nothing; otherwise the tiers are walked in ascending `cutoff_at` order
        and the first tier whose cutoff is at or after the confirmation instant
        wins — the boundary is inclusive — and if the clock has passed every
        cutoff the discount is zero."

        Design: Difficulty/combinatorial_formula/early_order_tier_branches_replacement_small_order_date
        """
        ctx = _early_tier_market(api)
        order = _order_with_units(ctx, 30)
        set_clock("2027-02-01T00:00:00Z")
        order = validate_success(api.confirm_order(order["id"], SALESREP))
        assert order["locked_discount_bps"] == 0, (
            "confirmation after the last cutoff 2027-01-15 earns no tier"
        )
        assert order["net_amount_cents"] == 30 * 18000


class TestEarlyOrderCutoffBoundary:
    def test_confirm_exactly_at_cutoff_earns_tier(self, api):
        """PRD §3.5: "otherwise the tiers are walked in ascending `cutoff_at`
        order and the first tier whose cutoff is at or after the confirmation
        instant wins — the boundary is inclusive".

        Design: Difficulty/boundary_precision_check/early_order_cutoff_inclusive_exact_instant
        """
        ctx = setup_market(
            program_overrides={
                "early_order_tiers": [
                    {"cutoff_at": "2026-09-30T23:59:59Z", "discount_bps": 1000}
                ]
            },
            lot_overrides={"received_units": 10000},
        )
        order = _order_with_units(ctx, 30)
        set_clock("2026-09-30T23:59:59Z")
        order = validate_success(api.confirm_order(order["id"], SALESREP))
        assert order["locked_discount_bps"] == 1000, (
            "confirmation exactly at the cutoff instant is inclusive"
        )
        # per unit: round_half_up(18000 x 0.90) = 16200
        assert order["net_amount_cents"] == 30 * 16200

    def test_confirm_one_second_past_cutoff_earns_nothing(self, api):
        """PRD §3.5: "and if the clock has passed every cutoff the discount is
        zero."

        Design: Difficulty/boundary_precision_check/early_order_cutoff_inclusive_exact_instant
        """
        ctx = setup_market(
            program_overrides={
                "early_order_tiers": [
                    {"cutoff_at": "2026-09-30T23:59:59Z", "discount_bps": 1000}
                ]
            },
            lot_overrides={"received_units": 10000},
        )
        order = _order_with_units(ctx, 30)
        set_clock("2026-10-01T00:00:00Z")
        order = validate_success(api.confirm_order(order["id"], SALESREP))
        assert order["locked_discount_bps"] == 0
        assert order["net_amount_cents"] == 30 * 18000


class TestVolumeRebateTiers:
    def test_volume_rebate_tier_selection_and_unit_boundaries(self, api):
        """PRD §3.5: "`rebate_bps_applied` is zero for replacement orders and
        otherwise the largest `rebate_bps` among volume-rebate tiers whose
        `min_units` the order's `total_units` meets or exceeds (zero when none
        qualify)".

        Design: Corner/calculations/volume_rebate_tier_selection_and_unit_boundaries
        """
        ctx = setup_market(
            program_overrides={
                "volume_rebate_tiers": [
                    {"min_units": 500, "rebate_bps": 300},
                    {"min_units": 1000, "rebate_bps": 500},
                ]
            },
            lot_overrides={"received_units": 50000},
        )
        set_clock("2027-02-01T00:00:00Z")  # past the early-order cutoff: 0bps
        orders = {n: _order_with_units(ctx, n) for n in (499, 500, 1000)}

        below = validate_success(api.confirm_order(orders[499]["id"], SALESREP))
        assert below["rebate_bps_applied"] == 0
        assert below["net_amount_cents"] == 499 * 18000

        at_first = validate_success(api.confirm_order(orders[500]["id"], SALESREP))
        assert at_first["rebate_bps_applied"] == 300
        assert at_first["rebate_amount_cents"] == 270000
        assert at_first["net_amount_cents"] == 500 * 18000 - 270000

        at_second = validate_success(api.confirm_order(orders[1000]["id"], SALESREP))
        assert at_second["rebate_bps_applied"] == 500
        assert at_second["rebate_amount_cents"] == 900000
        assert at_second["net_amount_cents"] == 1000 * 18000 - 900000


class TestImmediateConsistency:
    def test_immediate_consistency_confirm_response_matches_read(self, api):
        """PRD §3.5: "On success, confirmation locks the season's pricing onto
        the order."

        Design: Corner/consistency_model/immediate_consistency_confirm_response_matches_read
        """
        ctx = setup_market()
        set_clock("2027-01-10T00:00:00Z")
        order = create_draft_order(ctx["grower"], ctx["program"])
        add_line(order, ctx["variety"]["id"], 10)

        confirmed = validate_success(api.confirm_order(order["id"], SALESREP))
        assert confirmed["status"] == "CONFIRMED"

        reread = validate_success(api.get_order(order["id"], SALESREP))
        assert reread["status"] == confirmed["status"]
        assert reread["locked_discount_bps"] == confirmed["locked_discount_bps"]
        assert reread["net_amount_cents"] == confirmed["net_amount_cents"]
        assert reread["gross_amount_cents"] == confirmed["gross_amount_cents"]
