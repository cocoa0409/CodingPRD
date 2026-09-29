"""Order admission against a production window: the spoilage-reserve capacity
test and the annual cottage-food revenue cap.

Both gates run on the same POST /orders request, and both are boundary rules
whose "before" and "after" readings differ. The harness restarts the API server
before every test, so each test below builds its whole world from scratch
through the endpoints of PRD 4.
"""

from test_helpers import fixtures as fx
from test_helpers import (
    DINER_ONE_HEADERS,
    DINER_THREE_HEADERS,
    DINER_TWO_HEADERS,
    ApiErrorId,
    assert_capacity_triple,
    assert_charge_breakdown,
    assert_cook,
    assert_order,
    assert_production_window,
    order_payload,
    validate_error,
    validate_success,
)

# --------------------------------------------------------------------------
# Shared world builders. Every helper is a plain function called from inside a
# test, so nothing leaks between tests.
# --------------------------------------------------------------------------

#: A 40-meal window carrying two orders of 20 and 10 meals, so the committed
#: count is 30, the reserve is ceil(30 * 0.10) == 3 and the effective capacity
#: read before any further admission is 40 - 3 == 37.
_DECLARED_CAPACITY_MEALS = 40
_COMMITTED_MEALS = 30
_PRE_ADMISSION_RESERVE_MEALS = 3
_PRE_ADMISSION_EFFECTIVE_MEALS = 37
_UNIT_PRICE_CENTS = 1200

#: The New Hampshire cap walk: a 6001-cent ceiling stepped in four-cent moves by
#: a 1999-cent dish (quantity 3 -> 5997) and a 4-cent dish.
_NH_CAP_CENTS = 6001
_BIG_UNIT_PRICE_CENTS = 1999
_TINY_UNIT_PRICE_CENTS = 4


def _window_holding_thirty_committed_meals(api):
    """An OPEN 40-meal window whose committed count already stands at 30.

    The two seeding orders are 20 and 10 meals, both admitted comfortably below
    their own pre-admission bounds, so the interesting boundary is the third.
    """
    setup = fx.selling_cook(
        api,
        cook_overrides={"legal_name": "Dee Nakamura", "weekly_capacity_meals": 40},
        item_overrides={
            "name": "Tamale Dozen",
            "food_category": "NON_TCS",
            "allergens": ["MILK"],
            "shelf_life_days": 6,
            "unit_price_cents": _UNIT_PRICE_CENTS,
        },
        window_overrides={"capacity_meals": _DECLARED_CAPACITY_MEALS},
    )
    setup["order_twenty"] = fx.order_in_scenario(
        api, setup, quantity=20, diner_headers=DINER_ONE_HEADERS
    )
    setup["order_ten"] = fx.order_in_scenario(
        api, setup, quantity=10, diner_headers=DINER_TWO_HEADERS
    )
    return setup


def _cook_at_the_new_hampshire_cap_edge(api):
    """An ACTIVE New Hampshire cook under a 6001-cent annual cap.

    Two APPROVED dishes are priced so the cap can be walked in four-cent steps:
    a 1999-cent pie and a 4-cent mint. Nothing has captured, so both the
    recognised revenue and the in-flight exposure start at zero.
    """
    setup = fx.selling_cook(
        api,
        state_code="NH",
        policy_overrides={
            "cottage_food_annual_cap_cents": _NH_CAP_CENTS,
            "allowed_kitchen_types": ["HOME_COTTAGE", "HOME_INSPECTED"],
        },
        cook_overrides={
            "legal_name": "Lena Fournier",
            "claimed_kitchen_type": "HOME_COTTAGE",
            "weekly_capacity_meals": 10,
        },
        item_overrides={
            "name": "Big Pie",
            "food_category": "BAKED_NON_TCS",
            "allergens": ["WHEAT"],
            "shelf_life_days": 5,
            "unit_price_cents": _BIG_UNIT_PRICE_CENTS,
        },
        window_overrides={"capacity_meals": 10},
        zone_overrides={"postal_codes": ["03101"]},
        inspection_decision="WAIVE",
    )
    setup["big_item"] = setup.menu_item
    setup["tiny_item"] = fx.add_approved_item(
        api,
        setup,
        name="Tiny Mint",
        food_category="BAKED_NON_TCS",
        allergens=[],
        allergen_free_attested=True,
        shelf_life_days=5,
        unit_price_cents=_TINY_UNIT_PRICE_CENTS,
    )
    return setup


def _place(api, setup, menu_item_id, quantity, diner_headers):
    """Raw POST /orders so a test can assert the status code itself."""
    payload = order_payload(
        menu_item_id, setup.window["id"], setup.zone["id"], quantity=quantity
    )
    return api.create_order(payload, diner_headers)


# --------------------------------------------------------------------------
# The reserve is derived from the pre-admission committed count
# --------------------------------------------------------------------------
def test_01_admission_rejects_one_meal_past_the_pre_admission_effective_capacity(api):
    """An eight-meal order onto a 30-of-37 window is refused and the window is left untouched.

    PRD: "Fourth, the order is admitted only when the pre-admission committed count plus the requested `quantity` is less than or equal to that effective capacity; a total exactly equal to the effective capacity is admitted, and one meal more is rejected with `ERR_WINDOW_CAPACITY_EXCEEDED`."
    Design: Difficulty/combinatorial_formula/spoilage_reserve_evaluated_before_admission
    """
    setup = _window_holding_thirty_committed_meals(api)
    before = fx.read_window(api, setup.window["id"])
    assert_capacity_triple(
        before, committed_meals=_COMMITTED_MEALS, capacity_meals=_DECLARED_CAPACITY_MEALS
    )

    resp = _place(api, setup, setup.menu_item["id"], 8, DINER_THREE_HEADERS)

    validate_error(resp, ApiErrorId.WINDOW_CAPACITY_EXCEEDED, 422)
    after = fx.read_window(api, setup.window["id"])
    assert_production_window(
        after,
        capacity_meals=_DECLARED_CAPACITY_MEALS,
        committed_meals=_COMMITTED_MEALS,
        spoilage_reserve_meals=_PRE_ADMISSION_RESERVE_MEALS,
        effective_capacity_meals=_PRE_ADMISSION_EFFECTIVE_MEALS,
        status="OPEN",
    )


def test_02_admission_admits_a_total_exactly_equal_to_the_effective_capacity(api):
    """A seven-meal order onto the same 30-of-37 window is admitted at exactly the bound.

    PRD: "Second, the spoilage reserve is computed from that pre-admission count — ten percent of it, rounded up to a whole meal."
    Design: Difficulty/combinatorial_formula/spoilage_reserve_evaluated_before_admission
    """
    setup = _window_holding_thirty_committed_meals(api)

    resp = _place(api, setup, setup.menu_item["id"], 7, DINER_THREE_HEADERS)

    order = validate_success(resp, 201)
    assert_order(
        order,
        quantity=7,
        unit_price_cents_snapshot=_UNIT_PRICE_CENTS,
        subtotal_cents=8400,
        fulfillment_status="PLACED",
        payment_status="AUTHORIZED",
        production_window_id=setup.window["id"],
    )
    assert_charge_breakdown(order)


def test_03_persisted_capacity_triple_is_re_derived_from_the_post_admission_count(api):
    """After the boundary admission the window persists 37 committed, 4 reserved and 36 effective.

    PRD: "Once the order is admitted, however, the persisted fields are refreshed from the new picture: `committed_meals` becomes the pre-admission count plus the admitted `quantity`, `spoilage_reserve_meals` is re-derived as ten percent of that new committed count rounded up, and `effective_capacity_meals` is re-derived as `capacity_meals` less the new reserve."
    Design: Difficulty/combinatorial_formula/spoilage_reserve_evaluated_before_admission
    """
    setup = _window_holding_thirty_committed_meals(api)
    validate_success(_place(api, setup, setup.menu_item["id"], 7, DINER_THREE_HEADERS), 201)

    window = fx.read_window(api, setup.window["id"])

    assert_production_window(
        window,
        capacity_meals=_DECLARED_CAPACITY_MEALS,
        committed_meals=37,
        spoilage_reserve_meals=4,
        effective_capacity_meals=36,
        status="OPEN",
    )
    assert_capacity_triple(window, committed_meals=37, capacity_meals=_DECLARED_CAPACITY_MEALS)


# --------------------------------------------------------------------------
# The cottage-food cap: a three-point walk over `projected <= cap`
# --------------------------------------------------------------------------
def test_04_placement_admits_a_projection_four_cents_below_the_cap(api):
    """A 5997-cent order against a 6001-cent cap is admitted with no revenue recognised yet.

    PRD: "The projection is the cook's `ytd_cottage_revenue_cents` plus that in-flight exposure plus the new order's own `subtotal_cents`."
    Design: Difficulty/boundary_precision_check/cottage_cap_admission_at_exactly_the_cap
    """
    setup = _cook_at_the_new_hampshire_cap_edge(api)

    resp = _place(api, setup, setup.big_item["id"], 3, DINER_ONE_HEADERS)

    order = validate_success(resp, 201)
    assert_order(
        order,
        quantity=3,
        unit_price_cents_snapshot=_BIG_UNIT_PRICE_CENTS,
        subtotal_cents=5997,
        fulfillment_status="PLACED",
        payment_status="AUTHORIZED",
    )
    assert_charge_breakdown(order)


def test_05_placement_rejects_a_projection_four_cents_above_the_cap(api):
    """With 5997 cents in flight, a further eight-cent order projects 6005 and is refused.

    PRD: "The order is admitted only when the projection is less than or equal to the cap; a projection exactly equal to the cap is admitted, and anything above it is `ERR_COTTAGE_CAP_EXCEEDED`."
    Design: Difficulty/boundary_precision_check/cottage_cap_admission_at_exactly_the_cap
    """
    setup = _cook_at_the_new_hampshire_cap_edge(api)
    fx.order_in_scenario(
        api,
        setup,
        quantity=3,
        diner_headers=DINER_ONE_HEADERS,
        menu_item_id=setup.big_item["id"],
    )

    resp = _place(api, setup, setup.tiny_item["id"], 2, DINER_TWO_HEADERS)

    validate_error(resp, ApiErrorId.COTTAGE_CAP_EXCEEDED, 422)


def test_06_placement_admits_a_projection_exactly_equal_to_the_cap(api):
    """With 5997 cents in flight, a four-cent order projects exactly 6001 and is admitted.

    PRD: "The order is admitted only when the projection is less than or equal to the cap; a projection exactly equal to the cap is admitted, and anything above it is `ERR_COTTAGE_CAP_EXCEEDED`."
    Design: Difficulty/boundary_precision_check/cottage_cap_admission_at_exactly_the_cap
    """
    setup = _cook_at_the_new_hampshire_cap_edge(api)
    fx.order_in_scenario(
        api,
        setup,
        quantity=3,
        diner_headers=DINER_ONE_HEADERS,
        menu_item_id=setup.big_item["id"],
    )

    resp = _place(api, setup, setup.tiny_item["id"], 1, DINER_THREE_HEADERS)

    order = validate_success(resp, 201)
    assert_order(
        order,
        quantity=1,
        unit_price_cents_snapshot=_TINY_UNIT_PRICE_CENTS,
        subtotal_cents=4,
        fulfillment_status="PLACED",
        payment_status="AUTHORIZED",
    )


def test_07_in_flight_money_at_the_cap_leaves_cap_status_under_cap(api):
    """Orders admitted right up to the cap recognise nothing, so the cook stays UNDER_CAP.

    PRD: "It reads only the **recognised** amount, `ytd_cottage_revenue_cents`, ignoring in-flight money entirely: when recognised revenue is greater than or equal to the cap, `cap_status` is `CAP_REACHED`; otherwise, when recognised revenue divided by the cap is greater than or equal to ninety percent, `cap_status` is `CAP_WARNING`; otherwise it is `UNDER_CAP`."
    Design: Difficulty/boundary_precision_check/cottage_cap_admission_at_exactly_the_cap
    """
    setup = _cook_at_the_new_hampshire_cap_edge(api)
    fx.order_in_scenario(
        api,
        setup,
        quantity=3,
        diner_headers=DINER_ONE_HEADERS,
        menu_item_id=setup.big_item["id"],
    )
    validate_error(
        _place(api, setup, setup.tiny_item["id"], 2, DINER_TWO_HEADERS),
        ApiErrorId.COTTAGE_CAP_EXCEEDED,
        422,
    )
    validate_success(_place(api, setup, setup.tiny_item["id"], 1, DINER_THREE_HEADERS), 201)

    cook = fx.read_cook(api, setup.cook_id)
    window = fx.read_window(api, setup.window["id"])

    assert_cook(
        cook,
        cap_status="UNDER_CAP",
        ytd_cottage_revenue_cents=0,
        ytd_gross_sales_cents=0,
        compliance_standing="CLEAR",
        onboarding_status="ACTIVE",
    )
    assert_capacity_triple(window, committed_meals=4, capacity_meals=10)
