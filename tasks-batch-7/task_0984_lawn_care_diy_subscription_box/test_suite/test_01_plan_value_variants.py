"""Plan pricing: provisional vs committed value variants (PRD 3.4, 3.5)."""
import test_helpers as th

ADMIN = th.TEST_USERS["platform_admin_headers"]


def test_plan_value_provisional_vs_committed_annual(api):
    """PRD 3.4: "From the moment it is created, a plan carries a `provisional_value_cents`: the sum over its plan lines of each line's `qty_units` multiplied by the catalog `list_price_cents` of that line's sku."
    PRD 3.5: "`discount_pct_locked` is written onto the plan as 0.10 for an `ANNUAL` cycle or 0.00 for a `MONTHLY` cycle, and `committed_value_cents` is computed as the plan's `provisional_value_cents` multiplied by one minus the locked discount, rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/plan_value_provisional_vs_committed
    """
    ctx = th.setup_active_subscription(
        email="pv@x.com",
        plan_lines=[
            th.plan_line("FERT-01", qty_units=4, target_month=4),
            th.plan_line("WEED-01", qty_units=2, target_month=5),
        ],
        seed_skus=("FERT-01", "WEED-01"),
        billing_cycle="ANNUAL",
    )
    # The activation response predates the subscription: committed still null.
    assert ctx["plan"]["provisional_value_cents"] == 7800, (
        f"provisional must be 4x1200 + 2x1500 = 7800, got {ctx['plan']['provisional_value_cents']}"
    )
    assert ctx["plan"]["committed_value_cents"] is None

    plan = th.validate_success(api.get_plan(ctx["plan"]["id"], ADMIN))
    assert plan["provisional_value_cents"] == 7800
    assert plan["discount_pct_locked"] == 0.10
    assert plan["committed_value_cents"] == 7020, (
        f"committed must be round_half_up(7800 x 0.90) = 7020, got {plan['committed_value_cents']}"
    )
    assert plan["provisional_value_cents"] != plan["committed_value_cents"]


def test_plan_value_committed_monthly_carries_zero_discount(api):
    """PRD 3.5: "`discount_pct_locked` is written onto the plan as 0.10 for an `ANNUAL` cycle or 0.00 for a `MONTHLY` cycle, and `committed_value_cents` is computed as the plan's `provisional_value_cents` multiplied by one minus the locked discount, rounded half up to whole cents."
    PRD 3.5: "With identical lines, a non-zero discount therefore yields a committed value below the provisional value."

    Design: Difficulty/dual_variant_calc/plan_value_provisional_vs_committed
    """
    ctx = th.setup_active_subscription(
        email="pv-monthly@x.com",
        plan_lines=[
            th.plan_line("FERT-01", qty_units=4, target_month=4),
            th.plan_line("WEED-01", qty_units=2, target_month=5),
        ],
        seed_skus=("FERT-01", "WEED-01"),
        billing_cycle="MONTHLY",
    )
    plan = th.validate_success(api.get_plan(ctx["plan"]["id"], ADMIN))
    assert plan["provisional_value_cents"] == 7800
    assert plan["discount_pct_locked"] == 0.00
    # Zero discount: committed equals provisional for identical lines.
    assert plan["committed_value_cents"] == 7800
