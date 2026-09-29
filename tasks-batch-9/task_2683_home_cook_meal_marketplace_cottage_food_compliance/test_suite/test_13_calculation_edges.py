"""Money and score formulas of the home-cook meal marketplace.

Every amount here is an integer number of cents and every expected value is the
one the PRD's own arithmetic produces: the charge breakdown and its half-up
rounding direction, commission tier selection at the inclusive-below /
exclusive-at boundary, revenue recognition's inclusion set, the three-bucket
refund waterfall, the once-only rounding of the decayed safety charge, the
cold-chain surcharge constants, hub ranking, and the cap-warning threshold.
"""

from test_helpers import (
    DINER_ONE_HEADERS,
    DINER_THREE_HEADERS,
    DINER_TWO_HEADERS,
    assert_charge_breakdown,
    assert_money_is_integer,
    assert_refund_three_bucket_identity,
)
from test_helpers import fixtures as fx


# ==========================================================================
# Order charge breakdown and rounding direction
# ==========================================================================
def test_01_diner_service_fee_rounds_half_up_and_total_is_the_persisted_sum(api):
    """A subtotal of 1830 cents carries a 165-cent service fee, not 164, and the total persists.

    PRD: "`diner_service_fee_cents` is nine percent of `subtotal_cents`, rounded half up to a whole cent."
    Design: Corner/calculations/order_charge_breakdown_correct_result_and_rounding_direction
    """
    setup = fx.selling_cook(
        api,
        item_overrides={"unit_price_cents": 610},
        window_overrides={"capacity_meals": 20},
        zone_overrides={"max_cold_chain_minutes": 240},
    )
    assert setup.menu_item["unit_price_cents"] == 610
    assert setup.menu_item["review_status"] == "APPROVED"

    order = fx.order_in_scenario(api, setup, quantity=3)

    assert_money_is_integer(
        order,
        "unit_price_cents_snapshot",
        "subtotal_cents",
        "diner_service_fee_cents",
        "cold_chain_surcharge_cents",
        "total_charge_cents",
    )
    assert order["unit_price_cents_snapshot"] == 610
    assert order["subtotal_cents"] == 1830
    # 1830 * 0.09 == 164.70, which rounds half up to 165; truncation would give 164.
    assert order["diner_service_fee_cents"] == 165
    # The surcharge cannot be known until the order is routed.
    assert order["cold_chain_surcharge_cents"] == 0
    assert order["total_charge_cents"] == 1995
    assert_charge_breakdown(order)

    reread = fx.read_order(api, order["id"])
    assert reread["total_charge_cents"] == 1995
    assert reread["diner_service_fee_cents"] == 165
    assert reread["cold_chain_surcharge_cents"] == 0


def test_02_commission_rounds_half_up_and_cook_earnings_are_the_exact_complement(api):
    """A subtotal of 1830 cents at 0.225 yields 412 cents of commission and 1418 of earnings.

    PRD: "`platform_commission_cents` is `subtotal_cents` multiplied by that rate, rounded half up to a whole cent, and `cook_earnings_cents` is `subtotal_cents` less `platform_commission_cents`."
    Design: Corner/calculations/order_charge_breakdown_correct_result_and_rounding_direction
    """
    setup = fx.selling_cook(
        api,
        item_overrides={"unit_price_cents": 610},
        window_overrides={"capacity_meals": 20},
        zone_overrides={"max_cold_chain_minutes": 240},
    )
    assert setup.cook["ytd_gross_sales_cents"] == 0

    order = fx.order_in_scenario(api, setup, quantity=3)

    assert_money_is_integer(order, "platform_commission_cents", "cook_earnings_cents")
    assert order["subtotal_cents"] == 1830
    assert float(order["commission_rate"]) == 0.225
    # 1830 * 0.225 == 411.75, which rounds half up to 412; truncation would give 411.
    assert order["platform_commission_cents"] == 412
    assert order["cook_earnings_cents"] == 1418
    assert order["cook_earnings_cents"] == order["subtotal_cents"] - 412

    reread = fx.read_order(api, order["id"])
    assert reread["platform_commission_cents"] == 412
    assert reread["cook_earnings_cents"] == 1418


# ==========================================================================
# Commission tier selection at the 1,000,000-cent boundary
# ==========================================================================
def test_03_first_order_takes_tier_one_and_lands_ytd_gross_on_the_boundary(api):
    """An order priced from a zero year-to-date gross takes 0.225 even as it reaches the tier ceiling.

    PRD: "Commission is tiered on the cook's **year-to-date gross sales as they stand before this order is admitted**, so an order never moves its own tier."
    Design: Corner/calculations/commission_tier_boundary_at_exactly_one_million_selects_tier_2
    """
    setup = fx.selling_cook(
        api,
        item_overrides={"unit_price_cents": 50000},
        window_overrides={"capacity_meals": 20},
        zone_overrides={"max_cold_chain_minutes": 240},
    )
    assert setup.cook["ytd_gross_sales_cents"] == 0

    order_a = fx.routed_order(api, setup, quantity=20)
    assert order_a["subtotal_cents"] == 1000000
    assert float(order_a["commission_rate"]) == 0.225
    assert order_a["platform_commission_cents"] == 225000
    assert order_a["cook_earnings_cents"] == 775000

    fx.open_window_into_production(api, setup)
    order_a = fx.hand_off_order(api, setup, order_a)
    order_a = fx.deliver_order(api, order_a)
    assert order_a["payment_status"] == "CAPTURED"

    cook = fx.read_cook(api, setup.cook_id)
    assert_money_is_integer(cook, "ytd_gross_sales_cents", "ytd_cottage_revenue_cents")
    assert cook["ytd_gross_sales_cents"] == 1000000
    assert cook["ytd_cottage_revenue_cents"] == 1000000
    # 1000000 / 5000000 == 0.20, well below the cap-warning ratio.
    assert cook["cap_status"] == "UNDER_CAP"


def test_04_cook_at_exactly_one_million_cents_of_gross_sales_takes_the_tier_two_rate(api):
    """A cook sitting on exactly 1,000,000 cents of gross sales is priced at 0.185, not 0.225.

    PRD: "The boundaries are inclusive-below and exclusive-at, so a cook sitting at exactly 1,000,000 cents of year-to-date gross sales takes the 0.185 rate, not the 0.225 rate."
    Design: Corner/calculations/commission_tier_boundary_at_exactly_one_million_selects_tier_2
    """
    setup = fx.selling_cook(
        api,
        item_overrides={"unit_price_cents": 50000},
        window_overrides={"capacity_meals": 20},
        zone_overrides={"max_cold_chain_minutes": 240},
    )
    second_window = fx.open_production_window(
        api,
        setup.cook,
        week_start_date="2026-08-10",
        order_cutoff_at="2026-08-12T00:00:00Z",
        handoff_start_at="2026-08-15T16:00:00Z",
        handoff_end_at="2026-08-15T18:00:00Z",
        capacity_meals=20,
    )

    order_a = fx.routed_order(api, setup, quantity=20)
    fx.open_window_into_production(api, setup)
    order_a = fx.hand_off_order(api, setup, order_a)
    fx.deliver_order(api, order_a)
    assert fx.read_cook(api, setup.cook_id)["ytd_gross_sales_cents"] == 1000000

    order_b = fx.place_order(
        api,
        setup.menu_item["id"],
        second_window["id"],
        setup.zone["id"],
        quantity=1,
        diner_headers=DINER_TWO_HEADERS,
    )

    assert order_b["subtotal_cents"] == 50000
    assert float(order_b["commission_rate"]) == 0.185
    assert order_b["platform_commission_cents"] == 9250
    assert order_b["cook_earnings_cents"] == 40750
    assert order_b["total_charge_cents"] == 54500
    assert_charge_breakdown(order_b)

    reread = fx.read_order(api, order_b["id"])
    assert float(reread["commission_rate"]) == 0.185
    assert reread["platform_commission_cents"] == 9250


# ==========================================================================
# Revenue recognition: which orders count
# ==========================================================================
def test_05_recognition_counts_only_the_captured_order_and_ignores_authorized_and_voided(api):
    """Of three orders on one window only the captured one feeds the cook's revenue counters.

    PRD: "For the calendar year of the logical clock, the cook's **recognised** amount is the sum of `subtotal_cents` over that cook's orders whose `effective_year` equals that year and whose `payment_status` is `CAPTURED`, `PARTIALLY_REFUNDED` or `REFUNDED`; orders still `AUTHORIZED`, orders `VOIDED`, and orders whose `effective_year` is still null contribute nothing."
    Design: Corner/calculations/cottage_revenue_counts_only_captured_orders_and_ignores_authorized_and_voided
    """
    setup = fx.selling_cook(
        api,
        item_overrides={"unit_price_cents": 400},
        window_overrides={"capacity_meals": 20},
        zone_overrides={"max_cold_chain_minutes": 240},
    )
    order_one = fx.order_in_scenario(api, setup, quantity=2, diner_headers=DINER_ONE_HEADERS)
    order_two = fx.order_in_scenario(api, setup, quantity=1, diner_headers=DINER_TWO_HEADERS)
    order_three = fx.order_in_scenario(api, setup, quantity=1, diner_headers=DINER_THREE_HEADERS)
    assert order_one["subtotal_cents"] == 800
    assert order_two["subtotal_cents"] == 400
    assert order_three["subtotal_cents"] == 400

    fx.route_order(api, order_one["id"])
    fx.route_order(api, order_two["id"])
    fx.cancel_order(api, order_three)

    fx.open_window_into_production(api, setup)
    order_one = fx.hand_off_order(api, setup, order_one)
    order_one = fx.deliver_order(api, order_one)

    assert order_one["payment_status"] == "CAPTURED"
    assert order_one["effective_year"] == 2026

    # The IN_PRODUCTION sweep spares routed orders, so order two is still in flight.
    reread_two = fx.read_order(api, order_two["id"])
    assert reread_two["fulfillment_status"] == "ROUTED"
    assert reread_two["payment_status"] == "AUTHORIZED"
    assert reread_two["effective_year"] is None
    assert fx.read_order(api, order_three["id"])["payment_status"] == "VOIDED"

    cook = fx.read_cook(api, setup.cook_id)
    assert_money_is_integer(cook, "ytd_gross_sales_cents", "ytd_cottage_revenue_cents")
    assert cook["ytd_gross_sales_cents"] == 800
    assert cook["ytd_cottage_revenue_cents"] == 800
    assert cook["cap_status"] == "UNDER_CAP"
    # Only order one's cook earnings are pending: 800 - round_half_up(800 * 0.225) == 620.
    assert cook["pending_payout_cents"] == 620

    summary = fx.read_compliance_summary(api, setup.cook_id)
    assert summary["ytd_cottage_revenue_cents"] == 800
    assert summary["cap_status"] == "UNDER_CAP"


# ==========================================================================
# The refund waterfall
# ==========================================================================
def _captured_order_at_610_times_three(api):
    """One CAPTURED order: subtotal 1830, commission 412, cook earnings 1418, total 1995."""
    setup = fx.selling_cook(
        api,
        item_overrides={"unit_price_cents": 610},
        window_overrides={"capacity_meals": 20},
        zone_overrides={"max_cold_chain_minutes": 240},
    )
    order = fx.routed_order(api, setup, quantity=3)
    fx.open_window_into_production(api, setup)
    order = fx.hand_off_order(api, setup, order)
    order = fx.deliver_order(api, order)
    assert order["payment_status"] == "CAPTURED"
    assert order["subtotal_cents"] == 1830
    assert order["platform_commission_cents"] == 412
    assert order["cook_earnings_cents"] == 1418
    assert order["total_charge_cents"] == 1995
    return setup, order


def test_06_platform_fault_refund_skips_the_cook_bucket_and_caps_the_commission_bucket(api):
    """A 500-cent platform-fault refund reverses the whole 412 of commission and absorbs 88.

    PRD: "When `fault_party` is `PLATFORM`, the cook is spared entirely: `cook_chargeback_cents` is zero, `commission_reversed_cents` is the lesser of the full refund amount and the commission bucket's capacity, and `platform_absorbed_cents` takes the remainder."
    Design: Corner/calculations/refund_waterfall_drains_buckets_in_the_fault_specific_order
    """
    setup, order = _captured_order_at_610_times_three(api)

    refund = fx.record_refund(
        api,
        order["id"],
        reason="PLATFORM_ERROR",
        fault_party="PLATFORM",
        refund_amount_cents=500,
        settle_immediately=True,
    )

    assert_money_is_integer(
        refund,
        "refund_amount_cents",
        "cook_chargeback_cents",
        "commission_reversed_cents",
        "platform_absorbed_cents",
    )
    assert refund["cook_chargeback_cents"] == 0
    assert refund["commission_reversed_cents"] == 412
    assert refund["platform_absorbed_cents"] == 88
    assert_refund_three_bucket_identity(refund)
    assert refund["status"] == "SETTLED"

    reread = fx.read_order(api, order["id"])
    assert reread["refunded_cents"] == 500
    assert reread["cook_chargeback_cents"] == 0
    assert reread["commission_reversed_cents"] == 412
    assert reread["platform_absorbed_cents"] == 88
    assert reread["payment_status"] == "PARTIALLY_REFUNDED"

    cook = fx.read_cook(api, setup.cook_id)
    # 1830 - (0 + 412): platform_absorbed_cents is never subtracted.
    assert cook["ytd_cottage_revenue_cents"] == 1418


def test_07_cook_fault_refund_draws_bucket_one_and_finds_the_commission_bucket_drained(api):
    """A 300-cent cook-fault refund charges the cook 300 after an earlier refund emptied commission.

    PRD: "When `fault_party` is `COOK`, the refund drains bucket one first, then two, then three: `cook_chargeback_cents` is the lesser of the refund amount and the cook bucket's capacity; that allocation is deducted from the amount still to be placed; `commission_reversed_cents` is the lesser of what remains and the commission bucket's capacity; that too is deducted; and `platform_absorbed_cents` takes everything left."
    Design: Corner/calculations/refund_waterfall_drains_buckets_in_the_fault_specific_order
    """
    setup, order = _captured_order_at_610_times_three(api)

    first = fx.record_refund(
        api,
        order["id"],
        reason="PLATFORM_ERROR",
        fault_party="PLATFORM",
        refund_amount_cents=500,
        settle_immediately=True,
    )
    assert first["commission_reversed_cents"] == 412

    second = fx.record_refund(
        api,
        order["id"],
        reason="QUALITY",
        fault_party="COOK",
        refund_amount_cents=300,
    )

    # The cook bucket still holds 1418 of headroom, so it absorbs the whole 300.
    assert second["cook_chargeback_cents"] == 300
    assert second["commission_reversed_cents"] == 0
    assert second["platform_absorbed_cents"] == 0
    assert_refund_three_bucket_identity(second)
    assert second["status"] == "PENDING"

    reread = fx.read_order(api, order["id"])
    assert reread["refunded_cents"] == 800
    assert reread["cook_chargeback_cents"] == 300
    assert reread["commission_reversed_cents"] == 412
    assert reread["platform_absorbed_cents"] == 88
    assert reread["payment_status"] == "PARTIALLY_REFUNDED"
    assert fx.read_cook(api, setup.cook_id)["pending_payout_cents"] == 1118


def test_08_shared_fault_refund_halves_the_full_amount_and_the_platform_takes_the_complement(api):
    """A 101-cent shared-fault refund charges the cook 51 and drops the exact complement 50 on the platform.

    PRD: "When `fault_party` is `SHARED`, the cook's target is computed **first, from the full refund amount** — fifty percent of `refund_amount_cents`, rounded half up to a whole cent — and only then capped: `cook_chargeback_cents` is the lesser of that target and the cook bucket's capacity; the remainder after that allocation flows into `commission_reversed_cents` capped at the commission bucket's capacity; and `platform_absorbed_cents` receives the exact arithmetic complement."
    Design: Corner/calculations/refund_waterfall_drains_buckets_in_the_fault_specific_order
    """
    setup, order = _captured_order_at_610_times_three(api)

    fx.record_refund(
        api,
        order["id"],
        reason="PLATFORM_ERROR",
        fault_party="PLATFORM",
        refund_amount_cents=500,
        settle_immediately=True,
    )
    fx.record_refund(
        api,
        order["id"],
        reason="QUALITY",
        fault_party="COOK",
        refund_amount_cents=300,
    )

    third = fx.record_refund(
        api,
        order["id"],
        reason="LATE",
        fault_party="SHARED",
        refund_amount_cents=101,
    )

    # round_half_up(101 * 0.50) == round_half_up(50.5) == 51, capped at 1118 of headroom.
    assert third["cook_chargeback_cents"] == 51
    assert third["commission_reversed_cents"] == 0
    assert third["platform_absorbed_cents"] == 50
    assert_refund_three_bucket_identity(third)

    reread = fx.read_order(api, order["id"])
    assert reread["refunded_cents"] == 901
    assert reread["cook_chargeback_cents"] == 351
    assert reread["commission_reversed_cents"] == 412
    assert reread["platform_absorbed_cents"] == 138
    assert (
        reread["cook_chargeback_cents"]
        + reread["commission_reversed_cents"]
        + reread["platform_absorbed_cents"]
        == reread["refunded_cents"]
    )
    # 901 is strictly below the 1995 total charge, so the order stays partially refunded.
    assert reread["payment_status"] == "PARTIALLY_REFUNDED"

    cook = fx.read_cook(api, setup.cook_id)
    assert cook["ytd_cottage_revenue_cents"] == 1067
    assert cook["pending_payout_cents"] == 1067


# ==========================================================================
# The safety score: one rounding on the summed decayed charge
# ==========================================================================
def test_09_safety_score_rounds_half_up_once_on_the_summed_decayed_charge(api):
    """Two 26-week-old MINOR incidents charge 3 points in total, not 1 point each.

    PRD: "The decayed contributions are summed as exact decimals and half-up rounding is applied **once** to the total charge, never per incident."
    Design: Corner/calculations/safety_score_rounds_once_on_the_summed_decayed_charge
    """
    fx.create_state_policy(api)
    fx.reset_clock(api)
    cook = fx.register_cook(api)
    assert cook["safety_score"] == 100

    first = fx.report_incident(
        api,
        cook["id"],
        severity="MINOR",
        description="disclaimer missing on one box",
        occurred_at="2026-07-30T10:00:00Z",
    )
    second = fx.report_incident(
        api,
        cook["id"],
        severity="MINOR",
        description="net weight missing on one box",
        occurred_at="2026-07-30T11:00:00Z",
    )
    for incident_id in (first["id"], second["id"]):
        fx.triage_incident(api, incident_id, "ACCEPT")
        fx.adjudicate_incident(api, incident_id, "SUBSTANTIATE", resolution_note="photo confirms")

    at_creation = fx.read_compliance_summary(api, cook["id"])
    # Age 0 weeks: full weight 1.00, so the charge is 5 + 5 == 10.
    assert at_creation["safety_score"] == 90
    assert at_creation["substantiated_incident_count"] == 2

    # 175 days after creation is floor(175 / 7) == 25 whole weeks: half weight 0.50.
    fx.set_clock(api, "2027-01-23T00:00:00Z")
    at_25_weeks = fx.read_compliance_summary(api, cook["id"])
    assert at_25_weeks["safety_score"] == 95

    # 182 days is exactly 26 whole weeks: quarter weight 0.25, charge 1.25 + 1.25 == 2.50.
    fx.set_clock(api, "2027-01-30T00:00:00Z")
    at_26_weeks = fx.read_compliance_summary(api, cook["id"])
    # round_half_up(2.50) == 3, so the score is 97; per-incident rounding would give 98.
    assert at_26_weeks["safety_score"] == 97
    assert at_26_weeks["provisional_safety_score"] == 97
    assert at_26_weeks["compliance_standing"] == "CLEAR"
    assert fx.read_cook(api, cook["id"])["safety_score"] == 97


# ==========================================================================
# Cold-chain surcharge constants, landed at routing
# ==========================================================================
def _cold_chain_world(api):
    """An ACTIVE cook with a refrigerated dish, a same-day-hot dish and a 120-minute handoff."""
    setup = fx.selling_cook(
        api,
        item_overrides={"unit_price_cents": 400},
        zone_overrides={"max_cold_chain_minutes": 240},
    )
    setup["cold_item"] = fx.add_approved_item(
        api,
        setup,
        name="Chilled Rice Pudding",
        food_category="NON_TCS",
        allergens=["MILK"],
        shelf_life_days=3,
        requires_refrigeration=True,
        handoff_mode="BATCH_COOK_AND_CHILL",
        unit_price_cents=400,
    )
    setup["hot_item"] = fx.add_approved_item(
        api,
        setup,
        name="Hot Focaccia",
        food_category="BAKED_NON_TCS",
        allergens=["WHEAT"],
        shelf_life_days=2,
        requires_refrigeration=False,
        handoff_mode="SAME_DAY_HOT",
        unit_price_cents=400,
    )
    return setup


def test_10_refrigerated_door_delivery_pays_seventy_five_cents_per_meal_at_routing(api):
    """Routing a refrigerated dish into a door-delivery zone adds 75 cents for each of two meals.

    PRD: "When it is true and the zone's `service_mode` is `DOOR_DELIVERY`, the surcharge is 75 cents per meal, multiplied by the order's `quantity`."
    Design: Corner/calculations/cold_chain_surcharge_constant_is_selected_by_service_mode_and_refrigeration
    """
    setup = _cold_chain_world(api)

    order = fx.order_in_scenario(api, setup, quantity=2, menu_item_id=setup.cold_item["id"])
    assert order["subtotal_cents"] == 800
    assert order["diner_service_fee_cents"] == 72
    assert order["cold_chain_surcharge_cents"] == 0
    assert order["total_charge_cents"] == 872

    routed = fx.route_order(api, order["id"])

    assert_money_is_integer(routed, "cold_chain_surcharge_cents", "total_charge_cents")
    assert routed["cold_chain_surcharge_cents"] == 150
    assert routed["total_charge_cents"] == 1022
    assert routed["routing_mode"] == "BATCH_COOK_AND_CHILL"
    # The service fee is computed from the subtotal alone and never from the surcharge.
    assert routed["diner_service_fee_cents"] == 72
    assert routed["subtotal_cents"] == 800
    assert_charge_breakdown(routed)


def test_11_refrigerated_hub_pickup_pays_the_cheaper_forty_cents_per_meal(api):
    """Routing the same refrigerated dish into a hub-pickup zone adds 40 cents for each of two meals.

    PRD: "When it is true and the zone's `service_mode` is `HUB_PICKUP`, the surcharge is the cheaper 40 cents per meal, again multiplied by `quantity` — consolidation at a hub is genuinely less cold-chain work than individual doorstep drops."
    Design: Corner/calculations/cold_chain_surcharge_constant_is_selected_by_service_mode_and_refrigeration
    """
    setup = _cold_chain_world(api)
    hub_zone = fx.create_delivery_zone(
        api,
        setup.policy["id"],
        state_code="CA",
        service_mode="HUB_PICKUP",
        postal_codes=["94103"],
        max_cold_chain_minutes=240,
    )
    hub = fx.create_pickup_hub(
        api,
        hub_zone["id"],
        name="SoMa Hub",
        address="9 Folsom St",
        slot_capacity_orders=5,
        hub_window_start_at="2026-08-08T15:00:00Z",
        hub_window_end_at="2026-08-08T19:00:00Z",
    )

    order = fx.order_in_scenario(
        api, setup, quantity=2, menu_item_id=setup.cold_item["id"], zone_id=hub_zone["id"]
    )
    assert order["cold_chain_surcharge_cents"] == 0

    routed = fx.route_order(api, order["id"])

    assert routed["cold_chain_surcharge_cents"] == 80
    assert routed["total_charge_cents"] == 952
    assert routed["routing_mode"] == "BATCH_COOK_AND_CHILL"
    assert routed["pickup_hub_id"] == hub["id"]
    assert routed["diner_service_fee_cents"] == 72
    assert_charge_breakdown(routed)
    assert fx.read_hub(api, hub["id"])["assigned_order_count"] == 1


def test_12_non_refrigerated_dish_pays_no_surcharge_even_on_door_delivery(api):
    """A dish needing no refrigeration is charged zero surcharge and routes same-day hot.

    PRD: "When the dish's `requires_refrigeration` is false, `cold_chain_surcharge_cents` stays at zero."
    Design: Corner/calculations/cold_chain_surcharge_constant_is_selected_by_service_mode_and_refrigeration
    """
    setup = _cold_chain_world(api)

    order = fx.order_in_scenario(api, setup, quantity=2, menu_item_id=setup.hot_item["id"])
    assert order["subtotal_cents"] == 800
    assert order["total_charge_cents"] == 872

    routed = fx.route_order(api, order["id"])

    # The refrigeration test comes first, so the larger door-delivery constant is never reached.
    assert routed["cold_chain_surcharge_cents"] == 0
    assert routed["total_charge_cents"] == 872
    assert routed["diner_service_fee_cents"] == 72
    assert routed["routing_mode"] == "SAME_DAY_HOT"
    assert_charge_breakdown(routed)


# ==========================================================================
# Hub selection: filter, then rank, then break ties
# ==========================================================================
def test_13_hub_selection_ranks_on_free_slots_then_on_the_earliest_staffed_window(api):
    """Three successive routings pick the emptiest hub, then the earliest-staffed of two tied hubs.

    PRD: "**Stage two ranks the survivors**: primarily by remaining free slots — `slot_capacity_orders` less `assigned_order_count` — in descending order, so the emptiest hub wins; then, among hubs tied on free slots, by `hub_window_start_at` ascending, so the earliest-staffed hub wins; then, among hubs tied on both, by `created_at` ascending."
    Design: Corner/calculations/hub_selector_filters_then_ranks_by_free_slots_then_breaks_ties_on_window_start
    """
    setup = fx.selling_cook(
        api,
        item_overrides={"unit_price_cents": 400},
        window_overrides={"capacity_meals": 20},
        zone_overrides={"service_mode": "HUB_PICKUP", "max_cold_chain_minutes": 240},
    )
    zone_id = setup.zone["id"]
    # Five slots, staffed 15:00-19:00, so it fully contains the 16:00-18:00 handoff.
    hub_a = fx.create_pickup_hub(
        api,
        zone_id,
        name="Hub A Early",
        address="1 Alpha St",
        slot_capacity_orders=5,
        hub_window_start_at="2026-08-08T15:00:00Z",
        hub_window_end_at="2026-08-08T19:00:00Z",
    )
    # Equally empty, but staffed half an hour later, so it loses the tie-break.
    hub_b = fx.create_pickup_hub(
        api,
        zone_id,
        name="Hub B Late",
        address="2 Bravo St",
        slot_capacity_orders=5,
        hub_window_start_at="2026-08-08T15:30:00Z",
        hub_window_end_at="2026-08-08T19:00:00Z",
    )
    # Opens after the handoff has already started, so it never survives the filter.
    hub_c = fx.create_pickup_hub(
        api,
        zone_id,
        name="Hub C Opens Late",
        address="3 Charlie St",
        slot_capacity_orders=5,
        hub_window_start_at="2026-08-08T16:30:00Z",
        hub_window_end_at="2026-08-08T19:00:00Z",
    )
    # Eligible and staffed earliest of all, but only one free slot, so it ranks last.
    hub_d = fx.create_pickup_hub(
        api,
        zone_id,
        name="Hub D Tiny",
        address="4 Delta St",
        slot_capacity_orders=1,
        hub_window_start_at="2026-08-08T14:00:00Z",
        hub_window_end_at="2026-08-08T20:00:00Z",
    )

    first = fx.route_order(api, fx.order_in_scenario(api, setup, quantity=1)["id"])
    second = fx.route_order(
        api,
        fx.order_in_scenario(api, setup, quantity=1, diner_headers=DINER_TWO_HEADERS)["id"],
    )
    third = fx.route_order(
        api,
        fx.order_in_scenario(api, setup, quantity=1, diner_headers=DINER_THREE_HEADERS)["id"],
    )

    # Both five-slot hubs start empty, so the earlier-staffed one wins the first order.
    assert first["pickup_hub_id"] == hub_a["id"]
    # Hub A now has four free slots against Hub B's five, so free slots decide.
    assert second["pickup_hub_id"] == hub_b["id"]
    # Four free slots each again, so the window-start tie-break sends it back to Hub A.
    assert third["pickup_hub_id"] == hub_a["id"]

    assert fx.read_hub(api, hub_a["id"])["assigned_order_count"] == 2
    assert fx.read_hub(api, hub_b["id"])["assigned_order_count"] == 1
    assert fx.read_hub(api, hub_c["id"])["assigned_order_count"] == 0
    hub_d_row = fx.read_hub(api, hub_d["id"])
    assert hub_d_row["assigned_order_count"] == 0
    assert hub_d_row["status"] == "OPEN"


# ==========================================================================
# The cap-warning threshold
# ==========================================================================
def test_14_recognised_revenue_at_exactly_ninety_percent_of_the_cap_warns(api):
    """Capturing 1800 cents against a 2000-cent cap sets CAP_WARNING without delisting the dish.

    PRD: "It reads only the **recognised** amount, `ytd_cottage_revenue_cents`, ignoring in-flight money entirely: when recognised revenue is greater than or equal to the cap, `cap_status` is `CAP_REACHED`; otherwise, when recognised revenue divided by the cap is greater than or equal to ninety percent, `cap_status` is `CAP_WARNING`; otherwise it is `UNDER_CAP`."
    Design: Corner/calculations/cap_warning_utilization_constant_fires_at_exactly_ninety_percent
    """
    setup = fx.selling_cook(
        api,
        state_code="TX",
        policy_overrides={"cottage_food_annual_cap_cents": 2000},
        item_overrides={"unit_price_cents": 900},
        window_overrides={"capacity_meals": 20},
    )
    cook_id = setup.cook["id"]

    order = fx.order_in_scenario(api, setup, quantity=2)
    assert order["subtotal_cents"] == 1800

    # Before capture the money is in flight, so the classification has not moved.
    before = fx.read_compliance_summary(api, cook_id)
    assert before["ytd_cottage_revenue_cents"] == 0
    assert before["cap_status"] == "UNDER_CAP"

    order = fx.route_order(api, order["id"])
    fx.open_window_into_production(api, setup)
    order = fx.hand_off_order(api, setup, order)
    order = fx.deliver_order(api, order)
    assert order["payment_status"] == "CAPTURED"

    after = fx.read_compliance_summary(api, cook_id)
    assert_money_is_integer(after, "ytd_cottage_revenue_cents")
    # 1800 / 2000 is exactly nine tenths, which is the warning threshold, not the cap.
    assert after["ytd_cottage_revenue_cents"] == 1800
    assert after["cap_status"] == "CAP_WARNING"
    assert after["approved_menu_item_count"] == 1

    cook = fx.read_cook(api, cook_id)
    assert cook["cap_status"] == "CAP_WARNING"
    assert cook["ytd_cottage_revenue_cents"] == 1800

    # A warning is not the cap, so nothing is delisted.
    item = fx.read_menu_item(api, setup.menu_item["id"])
    assert item["review_status"] == "APPROVED"
    assert item["delist_reason"] is None
    assert item["label_compliance_status"] == "COMPLIANT"
