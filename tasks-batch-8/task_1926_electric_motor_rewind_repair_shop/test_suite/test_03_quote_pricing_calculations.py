"""Quote pricing claims (PRD §3.3): tiered labor, marginal shop supplies,
rush/emergency premiums, failure-risk tiers, and the pinned TCO-adjusted
recommendation variant."""
from test_helpers import (
    TEST_USERS,
    assert_quote,
    create_customer,
    create_motor,
    create_shop,
    create_quote_issue_payload,
    diagnose_work_order,
    get_work_order_version,
    intake_work_order,
    issue_quote,
    record_core_loss_test,
    record_incoming_test,
    setup_diagnosed_work_order,
    setup_quoted_work_order,
    validate_success,
)

ESTIMATOR = TEST_USERS["estimator_headers"]


def _issue(api, shop_id, wo_id):
    version = get_work_order_version(shop_id, wo_id)
    return validate_success(
        api.issue_quote(shop_id, wo_id, create_quote_issue_payload(version), ESTIMATOR), 201
    )


def test_tco_quote_line_items_labor_supplies_no_rush(api):
    """PRD §3.3: "The rewind labor charge `rewind_labor_cents` is the work
    order's `rewind_hours` multiplied by the selected rate, exact in integer
    cents."
    PRD §3.3: "When the sum exceeds $1,000.00, the surcharge is the first
    $1,000.00 multiplied by `supplies_low_pct` plus only the excess above
    $1,000.00 multiplied by `supplies_high_pct` — the higher marginal rate
    never touches the first tier."

    Design: Difficulty/dual_variant_calc/quote_recommendation_flips_under_tco_when_core_loss_fails
    """
    bundle = setup_quoted_work_order(
        rewind_hours=12,
        materials_cents=38000,
        replacement_cost_cents=260000,
        core_loss_watts=3800,
        motor_overrides={"rated_kw": 75, "frame_mm": 200, "manufacture_year": 2008},
    )
    quote = bundle["quote"]
    assert_quote(quote)
    # 12 h * 8500c small-tier rate; base 140000c straddles the 100000c break:
    # 8000 + 40000*0.06 = 10400; STANDARD priority pays no rush premium.
    assert quote["rewind_labor_cents"] == 102000
    assert quote["shop_supplies_cents"] == 10400
    assert quote["rush_premium_cents"] == 0
    assert quote["rewind_total_cents"] == 150400


def test_tco_adjusted_recommendation_flips_to_replace(api):
    """PRD §3.3: "If any core-loss test record on this work order carries a
    `FAIL` verdict, `risk_pct` is pinned at 0.35 regardless of age — the
    core-loss failure dominates the age tiers."
    PRD §3.3: "The stored `recommendation`, however, is always the conservative
    total-cost-of-ownership decision: `REWIND` when `tco_total_cents` is at or
    below the threshold, `REPLACE` otherwise, and the quote's `variant` field
    is pinned to `TCO_ADJUSTED` to record which basis produced it."

    Design: Difficulty/dual_variant_calc/quote_recommendation_flips_under_tco_when_core_loss_fails
    """
    bundle = setup_quoted_work_order(
        rewind_hours=12,
        materials_cents=38000,
        replacement_cost_cents=260000,
        core_loss_watts=3800,
        motor_overrides={"rated_kw": 75, "frame_mm": 200, "manufacture_year": 2008},
    )
    quote = bundle["quote"]
    # risk 0.35 -> risk_cost = round(150400 * 0.35) = 52640; tco = 203040.
    # Threshold = round(0.65 * 260000) = 169000. As-quoted total 150400 would
    # sit at or below it, but the stored decision is the TCO basis.
    assert quote["risk_pct"] == 0.35
    assert quote["risk_cost_cents"] == 52640
    assert quote["tco_total_cents"] == 203040
    assert quote["recommendation"] == "REPLACE"
    assert quote["variant"] == "TCO_ADJUSTED"


def test_emergency_premium_stacks_on_supplies(api):
    """PRD §3.3: "An `EMERGENCY` job pays half again as much: the same subtotal
    multiplied by `rush_premium_pct` and then by 1.5, rounded half-up."
    PRD §3.3: "The as-quoted rewind price `rewind_total_cents` is the sum of
    the labor, materials, supplies, and rush lines."

    Design: Difficulty/combinatorial_formula/rush_premium_stacks_on_supplies_after_tiered_labor
    """
    bundle = setup_quoted_work_order(
        priority="EMERGENCY",
        rewind_hours=10,
        materials_cents=20000,
        replacement_cost_cents=999999,
        motor_overrides={"rated_kw": 30, "frame_mm": 200, "manufacture_year": 2020},
    )
    quote = bundle["quote"]
    # Subtotal 113300 -> round(113300 * 0.35 * 1.5) = 59483.
    assert quote["rush_premium_cents"] == 59483
    assert quote["rewind_total_cents"] == 172783


def test_emergency_labor_and_supplies_tier_composition(api):
    """PRD §3.3: "`labor_rate_small_cents` when the frame is at or below 200
    millimetres"
    PRD §3.3: "The surcharge is rounded half-up to integer cents exactly once,
    after the tier split."

    Design: Difficulty/combinatorial_formula/rush_premium_stacks_on_supplies_after_tiered_labor
    """
    bundle = setup_quoted_work_order(
        priority="EMERGENCY",
        rewind_hours=10,
        materials_cents=20000,
        replacement_cost_cents=999999,
        motor_overrides={"rated_kw": 30, "frame_mm": 200, "manufacture_year": 2020},
    )
    quote = bundle["quote"]
    # 10 h * 8500c; base 105000c -> 100000*0.08 + 5000*0.06 = 8300.
    assert quote["rewind_labor_cents"] == 85000
    assert quote["rewind_materials_cents"] == 20000
    assert quote["shop_supplies_cents"] == 8300


def test_rush_zero_for_standard_priority(api):
    """PRD §3.3: "A `STANDARD` job pays nothing: `rush_premium_cents` is zero.
    A `RUSH` job pays the subtotal — labor plus materials plus supplies, after
    the supplies rounding — multiplied by the shop's `rush_premium_pct`,
    rounded half-up."

    Design: Corner/calculations/rush_zero_for_standard_priority
    """
    shop = create_shop()
    customer = create_customer(shop["id"])
    quotes = {}
    for serial, priority in (("M-R1", "STANDARD"), ("M-R2", "RUSH")):
        motor = create_motor(shop["id"], customer["id"], serial_number=serial, rated_kw=30)
        wo = intake_work_order(shop["id"], customer["id"], motor["id"], priority)
        record_incoming_test(shop["id"], wo["id"])
        diagnose_work_order(
            shop["id"], wo["id"], rewind_hours=10, materials_cents=20000,
            replacement_cost_cents=999999,
        )
        quotes[priority] = _issue(api, shop["id"], wo["id"])

    standard = quotes["STANDARD"]
    assert standard["rush_premium_cents"] == 0
    assert standard["rewind_total_cents"] == 113300  # 85000 + 20000 + 8300

    rush = quotes["RUSH"]
    assert rush["rush_premium_cents"] == 39655  # round(113300 * 0.35)
    assert rush["rewind_total_cents"] == 152955


def test_core_loss_input_set_only_counts_current_work_order(api):
    """PRD §3.3: "Age in years is the logical clock's current year minus the
    motor's `manufacture_year`. If any core-loss test record on this work order
    carries a `FAIL` verdict, `risk_pct` is pinned at 0.35 regardless of age —
    the core-loss failure dominates the age tiers. Otherwise, an age of fifteen
    years or more yields 0.25, an age of eight years or more but under fifteen
    yields 0.15, and anything younger yields 0.08."

    Design: Corner/calculations/core_loss_input_set_only_core_loss_records_count
    """
    shop = create_shop()
    customer = create_customer(shop["id"])
    quotes = {}
    for serial, with_core_fail in (("M-C1", True), ("M-C2", False)):
        motor = create_motor(
            shop["id"], customer["id"], serial_number=serial, rated_kw=75, frame_mm=200
        )
        wo = intake_work_order(shop["id"], customer["id"], motor["id"], "STANDARD")
        record_incoming_test(shop["id"], wo["id"])
        if with_core_fail:
            record_core_loss_test(shop["id"], wo["id"], 3800)  # 3800/75000 > 5%
        diagnose_work_order(
            shop["id"], wo["id"], rewind_hours=12, materials_cents=38000,
            replacement_cost_cents=260000,
        )
        quotes[with_core_fail] = _issue(api, shop["id"], wo["id"])

    failed = quotes[True]
    clean = quotes[False]
    assert failed["risk_pct"] == 0.35
    assert failed["recommendation"] == "REPLACE"
    # Age 2026 - 2020 = 6 years: base tier; tco 150400 + 12032 <= 169000.
    assert clean["risk_pct"] == 0.08
    assert clean["recommendation"] == "REWIND"
