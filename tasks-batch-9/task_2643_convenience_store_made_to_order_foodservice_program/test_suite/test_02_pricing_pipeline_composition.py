"""Money that only comes out right when the pinned evaluation order is honoured:
per-line rounding before summation, and the catering fee taken after the discount.
Plus the labor pipeline, whose per-station ceilings resist any blended rate.
"""

from test_helpers import fixtures as X
from test_helpers.assertions import assert_staffing_plan
from prd_bench_local_runner.testing import validate_success


def _lunch_store(api, clock="2026-08-01T11:00:00Z"):
    """A store trading in LUNCH with labor published for the service date."""
    X.set_clock(api, clock)
    store = X.create_store(api, is_fuel_site=False)
    X.transition_daypart(api, store["id"], "LUNCH")
    X.create_published_plan(api, store["id"], daypart="LUNCH")
    return store


def _two_wrap_lines_under_a_sandwich_percentage(api):
    """Two separate lines of two Chicken Wraps under a 1500-basis-point rule.

    Each line grosses 1010 cents, so fifteen percent of a line is exactly
    151.5 cents — the half-cent that forces the rounding order into the open.
    """
    store = _lunch_store(api)
    wrap = X.create_wrap(api, included_premium_count=0, is_catering_eligible=True)
    promo = X.create_promotion_rule(
        api,
        code="SANDWICH15",
        kind="DAYPART_BUNDLE",
        discount_kind="PCT_PER_LINE",
        discount_bp=1500,
        max_discount_cents=5000,
        min_food_subtotal_cents=0,
        valid_dayparts=["LUNCH"],
        target_station="SANDWICH",
        stacking_rank=10,
    )
    order = X.create_draft_order(api, store["id"], channel="TOUCHSCREEN")
    line_a = X.add_order_line(api, order["id"], wrap["id"], 2)
    line_b = X.add_order_line(api, order["id"], wrap["id"], 2)
    return store, promo, order, line_a, line_b


def test_percentage_discount_is_rounded_on_each_line_before_the_lines_are_summed(
    api, terminal
):
    """Two lines each landing on the half-cent round up individually, so the order
    discount is 304 rather than the 303 a single rounding of the combined gross
    would produce.

    PRD: "each line's `line_discount_cents` is that line's `line_gross_cents`
    multiplied by the rule's `discount_bp` and divided by ten thousand, **rounded
    half up per line**, and the raw discount is the sum of those already-rounded
    per-line figures."

    Design: Difficulty/combinatorial_formula/promotion_discount_rounds_per_line_then_sums_to_304_not_303
    """
    _store, promo, order, line_a, line_b = _two_wrap_lines_under_a_sandwich_percentage(api)

    placed = validate_success(api.place_order(order["id"], {}, terminal))

    assert placed["subtotal_gross_cents"] == 2020
    assert placed["applied_promotion_id"] == promo["id"]
    assert placed["promo_discount_cents"] == 304
    assert placed["promo_discount_cents"] != 303
    assert placed["service_fee_cents"] == 0
    assert placed["total_cents"] == 1716

    after_a = X.read_order_line(api, line_a["id"])
    after_b = X.read_order_line(api, line_b["id"])
    assert after_a["line_discount_cents"] == 152
    assert after_b["line_discount_cents"] == 152


def test_each_discounted_line_nets_its_own_gross_minus_its_own_rounded_share(api, terminal):
    """The per-line figures are the discount of record: each line nets 858 and the
    two of them add up to exactly the order's discount.

    PRD: "The identity that the per-line discounts sum to the order's discount
    always holds. Each line's `line_net_cents` is finally its `line_gross_cents`
    minus its `line_discount_cents`."

    Design: Difficulty/combinatorial_formula/promotion_discount_rounds_per_line_then_sums_to_304_not_303
    """
    _store, _promo, order, line_a, line_b = _two_wrap_lines_under_a_sandwich_percentage(api)

    placed = validate_success(api.place_order(order["id"], {}, terminal))

    after_a = X.read_order_line(api, line_a["id"])
    after_b = X.read_order_line(api, line_b["id"])
    assert after_a["line_gross_cents"] == 1010
    assert after_b["line_gross_cents"] == 1010
    assert after_a["line_net_cents"] == 858
    assert after_b["line_net_cents"] == 858
    assert (
        after_a["line_discount_cents"] + after_b["line_discount_cents"]
        == placed["promo_discount_cents"]
    )


def _catering_tray_under_a_flat_discount(api):
    """Twelve hoagies grossing 10788 with a flat 2000-cent tray discount.

    Eight percent of the discounted 8788 is 703 cents; eight percent of the
    gross would be 863, so the two readings of the pipeline diverge visibly.
    """
    store = _lunch_store(api)
    hoagie = X.create_hoagie(api)
    promo = X.create_promotion_rule(
        api,
        code="TRAY2000",
        kind="DAYPART_BUNDLE",
        discount_kind="CENTS_OFF",
        discount_cents=2000,
        discount_bp=None,
        max_discount_cents=2000,
        min_food_subtotal_cents=5000,
        valid_dayparts=["LUNCH"],
        target_station="ALL",
        stacking_rank=20,
    )
    order = X.create_draft_catering_order(
        api, store["id"], "2026-08-02T00:00:00Z", "2026-08-02T00:30:00Z"
    )
    line = X.add_order_line(api, order["id"], hoagie["id"], 12)
    return store, promo, order, line


def test_catering_fee_is_taken_on_the_discounted_food_not_on_the_gross(api, terminal):
    """Eight percent of the post-discount food total gives 703 cents of service
    fee; the same percentage of the undiscounted gross would give 863.

    PRD: "For a `CATERING` order it is whichever is larger: a floor of 500 cents,
    or the discounted food figure multiplied by 800 basis points and divided by ten
    thousand"

    Design: Difficulty/combinatorial_formula/catering_service_fee_evaluated_after_discount_not_on_gross
    """
    _store, promo, order, _line = _catering_tray_under_a_flat_discount(api)

    placed = validate_success(api.place_order(order["id"], {}, terminal))

    assert placed["subtotal_gross_cents"] == 10788
    assert placed["applied_promotion_id"] == promo["id"]
    assert placed["promo_discount_cents"] == 2000
    assert placed["service_fee_cents"] == 703
    assert placed["service_fee_cents"] != 863


def test_the_fee_is_added_after_the_discount_and_never_earns_its_own_discount(api, terminal):
    """The order total is gross minus discount plus fee — 9491, not the 9651 that a
    fee taken on the gross would yield — and the fee itself is outside the
    promotion's reach.

    PRD: "step six computes `total_cents` as the gross subtotal minus the discount
    plus the service fee. The service fee is never part of promotion eligibility,
    and the fee never charges itself."

    Design: Difficulty/combinatorial_formula/catering_service_fee_evaluated_after_discount_not_on_gross
    """
    _store, _promo, order, _line = _catering_tray_under_a_flat_discount(api)

    placed = validate_success(api.place_order(order["id"], {}, terminal))

    assert placed["total_cents"] == 9491
    assert placed["total_cents"] != 9651
    assert (
        placed["total_cents"]
        == placed["subtotal_gross_cents"]
        - placed["promo_discount_cents"]
        + placed["service_fee_cents"]
    )


def test_labor_minutes_follow_the_two_station_ceilings_not_the_headline_forecast(
    api, manager
):
    """Three plans all forecasting 300 transactions land on 780 and 600 minutes as
    the made-to-order share moves, because each station's hours are rounded up
    before the two terms meet.

    PRD: "the made-to-order count divided by a throughput of 18 transactions per
    labor hour and rounded up to a whole hour, then converted to minutes by
    multiplying by 60; plus the grab-and-go count divided by a throughput of 45
    transactions per labor hour and likewise rounded up to a whole hour"

    Design: Difficulty/combinatorial_formula/staffing_labor_minutes_depend_on_station_split_not_total_forecast
    """
    X.set_clock(api, "2026-08-01T09:00:00Z")
    store = X.create_store(api, is_fuel_site=False)

    # A half-and-half split: 150 made-to-order over 18/hour is 9 hours, 150
    # grab-and-go over 45/hour is 4 hours, so 13 hours of labor.
    plan_a = X.create_staffing_plan(
        api, store["id"], service_date="2026-08-01", daypart="LUNCH",
        forecast_txn_count=300, mto_share_bp=5000,
    )
    # Shifting the split to 30 percent gives 90 and 210: 5 hours plus 5 hours.
    plan_b = X.create_staffing_plan(
        api, store["id"], service_date="2026-08-02", daypart="LUNCH",
        forecast_txn_count=300, mto_share_bp=3000,
    )

    assert_staffing_plan(plan_a, {"planned_labor_minutes": 780, "status": "DRAFT"})
    assert_staffing_plan(plan_b, {"planned_labor_minutes": 600, "status": "DRAFT"})
    assert plan_a["forecast_txn_count"] == plan_b["forecast_txn_count"] == 300


def test_a_breakfast_plan_carries_the_flat_bakery_preparation_block(api, manager):
    """The same 300-transaction, half-and-half split costs 900 minutes at
    BREAKFAST: the thirteen station hours plus two flat hours of bakery prep,
    with the off-peak multiplier left at ten thousand basis points.

    PRD: "plus a flat two hours of bakery preparation, that is 120 minutes, when
    and only when the plan's daypart is `BREAKFAST`."

    Design: Difficulty/combinatorial_formula/staffing_labor_minutes_depend_on_station_split_not_total_forecast
    """
    X.set_clock(api, "2026-08-01T09:00:00Z")
    store = X.create_store(api, is_fuel_site=False)

    lunch_plan = X.create_staffing_plan(
        api, store["id"], service_date="2026-08-01", daypart="LUNCH",
        forecast_txn_count=300, mto_share_bp=5000,
    )
    breakfast_plan = X.create_staffing_plan(
        api, store["id"], service_date="2026-08-03", daypart="BREAKFAST",
        forecast_txn_count=300, mto_share_bp=5000,
    )

    assert breakfast_plan["planned_labor_minutes"] == 900
    assert breakfast_plan["planned_labor_minutes"] - lunch_plan["planned_labor_minutes"] == 120
    assert breakfast_plan["peak_multiplier_bp"] == 10000
    assert lunch_plan["peak_multiplier_bp"] == 10000
    assert breakfast_plan["status"] == "DRAFT"
