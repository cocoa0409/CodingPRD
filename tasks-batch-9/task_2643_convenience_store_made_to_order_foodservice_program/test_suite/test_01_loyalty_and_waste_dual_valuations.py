"""The same event valued twice: points at commit versus at settlement, and a
write-off valued at food cost versus at retail.
"""

from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_batch_quantity_ledger,
    assert_loyalty_ledger,
    assert_store_readiness,
    assert_tier_for_lifetime_points,
    assert_waste_log,
)
from test_helpers.test_users import FOOD_SAFETY_LEAD_HEADERS, SHIFT_LEAD_HEADERS
from prd_bench_local_runner.testing import validate_paginated, validate_success


def _catering_combo_order(api):
    """A catering tray priced under a fuel-and-food combo for a near-PLUS member.

    Six Italian Hoagies at 899 gross 5394. A fuel-and-food rule takes 900 off,
    an eight-percent catering fee on the discounted food adds 500, and the
    member sits at 480 points with 12.5 gallons pumped inside the look-back.
    """
    X.set_clock(api, "2026-08-01T11:00:00Z")
    store = X.create_store(api, is_fuel_site=True)
    X.transition_daypart(api, store["id"], "LUNCH")
    X.create_published_plan(api, store["id"], daypart="LUNCH")
    hoagie = X.create_hoagie(api)
    promo = X.create_promotion_rule(
        api,
        code="FUELFOOD900",
        kind="FUEL_FOOD_COMBO",
        discount_kind="CENTS_OFF",
        discount_cents=900,
        discount_bp=None,
        max_discount_cents=900,
        min_food_subtotal_cents=3000,
        requires_fuel_gallons=8,
        valid_dayparts=["LUNCH"],
        target_station="ALL",
        stacking_rank=10,
    )
    account = X.create_loyalty_account(api, member_code="MBR-0001", email="member1@example.com")
    X.seed_points(api, account["id"], 480, "GOODWILL_SEED")
    X.record_fuel(
        api,
        account["id"],
        gallons=12.5,
        price_per_gallon_cents=329,
        occurred_at="2026-07-25T08:00:00Z",
    )
    order = X.create_draft_catering_order(
        api,
        store["id"],
        "2026-08-02T00:00:00Z",
        "2026-08-02T00:30:00Z",
        loyalty_account_id=account["id"],
    )
    X.add_order_line(api, order["id"], hoagie["id"], 6)
    return store, promo, account, order


def test_catering_combo_commit_prices_the_tray_and_prints_provisional_points(api, terminal):
    """Commit fixes the gross subtotal, the flat combo discount, the catering fee
    and the receipt's provisional accrual read at the member's pre-order tier.

    PRD: "Its basis is the order's `total_cents`, which **includes** any catering
    `service_fee_cents`, and its multiplier is read from the member's `tier` as it
    stands *before* this order's own accrual: 10000 basis points at `BASIC`"

    Design: Difficulty/dual_variant_calc/loyalty_points_provisional_vs_final_diverge_on_catering_fuel_combo
    """
    _store, promo, _account, order = _catering_combo_order(api)

    placed = validate_success(api.place_order(order["id"], {}, terminal))

    assert placed["subtotal_gross_cents"] == 5394
    assert placed["applied_promotion_id"] == promo["id"]
    assert placed["promo_discount_cents"] == 900
    assert placed["service_fee_cents"] == 500
    assert placed["total_cents"] == 4994
    # 4994 cents at 10000 basis points is 49.94 points, truncated to 49.
    assert placed["points_provisional"] == 49


def test_settlement_recomputes_final_points_on_the_fee_free_basis_at_the_lifted_tier(
    api, terminal
):
    """Settlement's accrual excludes the catering fee, re-reads the tier the
    provisional accrual just unlocked, and adds the fuel-combo bonus, so it
    lands above the provisional figure on the very same order.

    PRD: "Its basis is the order's `subtotal_gross_cents` minus its
    `promo_discount_cents` and therefore **excludes** any catering
    `service_fee_cents`, because fees never earn points."

    Design: Difficulty/dual_variant_calc/loyalty_points_provisional_vs_final_diverge_on_catering_fuel_combo
    """
    _store, _promo, _account, order = _catering_combo_order(api)
    placed = validate_success(api.place_order(order["id"], {}, terminal))
    validate_success(api.authorize_order(order["id"], {"tender_type": "CARD"}, terminal))

    settled = validate_success(api.settle_order(order["id"], {}, terminal))

    # 4494 cents at the PLUS multiplier of 12500 basis points is 56.175 points,
    # truncated to 56, plus the flat 50-point fuel-and-food bonus.
    assert settled["points_final"] == 106
    assert settled["points_provisional"] == placed["points_provisional"] == 49
    assert settled["points_final"] - settled["points_provisional"] == 57
    assert settled["settlement_status"] == "SETTLED"


def test_member_ledger_absorbs_both_accruals_and_settles_on_the_higher_tier(api, terminal):
    """The account carries the sum of the two accruals, nothing is reversed, and
    the tier ends where the accumulated lifetime earnings put it.

    PRD: "That delta is added to the account's `points_balance` and to its
    `lifetime_points_earned`, the `tier` is re-derived, and the account's
    `version` increments by one."

    Design: Difficulty/dual_variant_calc/loyalty_points_provisional_vs_final_diverge_on_catering_fuel_combo
    """
    _store, _promo, account, order = _catering_combo_order(api)
    validate_success(api.place_order(order["id"], {}, terminal))
    validate_success(api.authorize_order(order["id"], {"tender_type": "CARD"}, terminal))
    validate_success(api.settle_order(order["id"], {}, terminal))

    after = X.read_loyalty_account(api, account["id"])

    assert after["points_balance"] == 586
    assert after["lifetime_points_earned"] == 586
    assert after["points_reversed_total"] == 0
    assert after["tier"] == "PLUS"
    assert_loyalty_ledger(after)
    assert_tier_for_lifetime_points(after)


def _pretzel_batch_on_hold(api):
    """Forty soft pretzels baked and pulled into slot 1 of a bakery case.

    Ingredient cost is 40 cents a unit against a 199-cent shelf price, so the
    two valuation bases of one write-off pull apart by a wide margin.
    """
    X.set_clock(api, "2026-08-01T11:00:00Z")
    store = X.create_store(api, is_fuel_site=False)
    X.transition_daypart(api, store["id"], "LUNCH")
    unit = X.create_bakery_case(api, store["id"])
    pretzel = X.create_pretzel(api)
    batch = X.create_holding_batch(
        api,
        store["id"],
        pretzel["id"],
        unit["id"],
        slot_index=1,
        planned_qty=40,
        bake_start_at="2026-08-01T11:00:00Z",
    )
    return store, unit, pretzel, batch


def test_quality_write_off_is_valued_on_both_the_food_cost_and_retail_bases(api, associate):
    """One write-off event carries an ingredient-cost figure and a shelf-price
    figure side by side, and the retail figure is the larger of the two.

    PRD: "The **food-cost valuation** of a write-off is the quantity multiplied by
    the item's `unit_food_cost_cents`; the **retail valuation** of the same
    write-off is the quantity multiplied by the item's `base_price_cents`."

    Design: Difficulty/dual_variant_calc/waste_valuation_food_cost_vs_retail_diverge_on_quality_discard
    """
    _store, _unit, _pretzel, batch = _pretzel_batch_on_hold(api)

    validate_success(
        api.discard_production_batch(
            batch["id"],
            {
                "qty": 24,
                "reason": "QUALITY_REJECT",
                "expected_batch_version": batch["version"],
            },
            associate,
        )
    )

    rows, meta = validate_paginated(api.list_batch_waste_logs(batch["id"], SHIFT_LEAD_HEADERS))
    assert meta["total_count"] == 1
    assert_waste_log(
        rows[0],
        {
            "production_batch_id": batch["id"],
            "qty": 24,
            "reason": "QUALITY_REJECT",
            "food_cost_cents": 960,
            "retail_value_cents": 4776,
        },
    )
    assert rows[0]["retail_value_cents"] - rows[0]["food_cost_cents"] == 3816


def test_only_the_food_cost_basis_accumulates_onto_the_store_waste_ledger(api, associate):
    """The store's running waste money moves by the ingredient-cost figure alone;
    the shelf-price figure never touches it. The batch keeps its slot because
    sixteen sellable units are left.

    PRD: "Only the food-cost basis accumulates onto the store's
    `waste_cost_cents_mtd`; the retail basis is aggregated on demand for the
    inspection summary."

    Design: Difficulty/dual_variant_calc/waste_valuation_food_cost_vs_retail_diverge_on_quality_discard
    """
    store, _unit, _pretzel, batch = _pretzel_batch_on_hold(api)
    assert store["waste_cost_cents_mtd"] == 0

    validate_success(
        api.discard_production_batch(
            batch["id"],
            {
                "qty": 24,
                "reason": "QUALITY_REJECT",
                "expected_batch_version": batch["version"],
            },
            associate,
        )
    )

    after_store = X.read_store(api, store["id"])
    assert after_store["waste_cost_cents_mtd"] == 960

    after_batch = X.read_batch(api, batch["id"])
    assert after_batch["remaining_qty"] == 16
    assert after_batch["discarded_qty"] == 24
    assert after_batch["status"] == "HOLDING"
    assert_batch_quantity_ledger(after_batch)


def test_inspection_summary_reports_the_food_cost_ledger_and_the_retail_exposure(api, associate):
    """The readiness read publishes both bases at once: the operational waste
    money and the separately aggregated shelf-price exposure.

    PRD: "The `retail_waste_exposure_cents` figure sums the `retail_value_cents`
    of every waste record belonging to the store's batches."

    Design: Difficulty/dual_variant_calc/waste_valuation_food_cost_vs_retail_diverge_on_quality_discard
    """
    store, _unit, _pretzel, batch = _pretzel_batch_on_hold(api)

    validate_success(
        api.discard_production_batch(
            batch["id"],
            {
                "qty": 24,
                "reason": "QUALITY_REJECT",
                "expected_batch_version": batch["version"],
            },
            associate,
        )
    )

    readiness = validate_success(
        api.get_store_readiness(store["id"], FOOD_SAFETY_LEAD_HEADERS)
    )
    assert_store_readiness(
        readiness,
        {"food_cost_waste_cents_mtd": 960, "retail_waste_exposure_cents": 4776},
    )
