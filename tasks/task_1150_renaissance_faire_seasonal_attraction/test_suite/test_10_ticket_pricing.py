"""Ticket order pricing: tiered group discounts, the DAY convenience fee, and the
group minimum-size threshold."""
from test_helpers import (
    ApiErrorId,
    create_ticket_order_payload,
    make_build_season,
    make_faire_day,
    make_season,
    set_clock,
    setup_season_build_with_sales_day,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import OPERATOR
from test_helpers.test_users import make_guest_headers


def test_ticket_order_total_cents_input_rejected(api):
    """PRD §2.9: "a `SEASON` order must omit `faire_day_id` while `DAY` and `GROUP`
    orders must include it; unknown fields are rejected. All shape failures return
    `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.5: "A `Guest` places a ticket order by naming the `season_id`, an
    `order_type` of `DAY`, `SEASON`, or `GROUP`, a `quantity` of at least 1, a
    `unit_price_cents` of zero or more, and — for `DAY` and `GROUP` orders only —
    the `faire_day_id` of the day to attend." — `total_cents` is not an input;
    pricing "is computed at placement".

    Design: Corner/entities/ticket_order_total_cents_input_rejected
    """
    season, day = setup_season_build_with_sales_day()
    payload = create_ticket_order_payload(season["id"], faire_day_id=day["id"])
    payload["total_cents"] = 1
    res = api.create_ticket_order(payload, make_guest_headers("g-sneaky@example.com"))
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_pricing_day_fee_and_season_no_discount(api):
    """PRD §3.5: "The base is the `quantity` multiplied by the `unit_price_cents`."
    PRD §3.5: "`DAY` and `SEASON` orders are never discounted. For `DAY` orders
    only, a convenience fee of 150 cents per ticket is charged on top. The order's
    `total_cents` is the base multiplied by one minus the discount fraction, rounded
    half up to whole cents, plus the convenience fee — the rounding lands on the
    discounted base before the fee is added, never on the fee."

    Design: Difficulty/combinatorial_formula/group_order_tiered_total_with_conditional_fee
    """
    set_clock()
    season, day = setup_season_build_with_sales_day(group_min_size=10)

    day_order = validate_success(
        api.create_ticket_order(
            create_ticket_order_payload(
                season["id"], order_type="DAY", quantity=3,
                unit_price_cents=3000, faire_day_id=day["id"],
            ),
            make_guest_headers("g-day@example.com"),
        ),
        201,
    )
    # 3 * 3000 = 9000 base, no discount, fee 3 * 150 = 450 -> 9450.
    assert day_order["total_cents"] == 9450
    assert day_order["discount_pct"] == 0

    season_order = validate_success(
        api.create_ticket_order(
            create_ticket_order_payload(
                season["id"], order_type="SEASON", quantity=2,
                unit_price_cents=9000,
            ),
            make_guest_headers("g-sea@example.com"),
        ),
        201,
    )
    # Non-DAY: no fee; non-GROUP: no discount -> 2 * 9000 = 18000.
    assert season_order["total_cents"] == 18000


def test_pricing_group_tiered_discounts(api):
    """PRD §3.5: "Group orders earn a discount keyed to how the `quantity` compares
    with the season's `group_min_size`: reaching the group minimum earns a
    ten-percent discount, reaching at least twice the minimum earns fifteen percent,
    and reaching at least four times the minimum earns twenty percent — the applied
    fraction is recorded as the order's `discount_pct`."

    Design: Difficulty/combinatorial_formula/group_order_tiered_total_with_conditional_fee
    """
    set_clock()
    season, day = setup_season_build_with_sales_day(group_min_size=10)

    g10 = validate_success(
        api.create_ticket_order(
            create_ticket_order_payload(
                season["id"], order_type="GROUP", quantity=10,
                unit_price_cents=3000, faire_day_id=day["id"],
            ),
            make_guest_headers("g-g10@example.com"),
        ),
        201,
    )
    # 10 >= 1x minimum: 30000 * 0.90 = 27000; GROUP carries no convenience fee.
    assert g10["total_cents"] == 27000
    assert g10["discount_pct"] == 0.10

    g20 = validate_success(
        api.create_ticket_order(
            create_ticket_order_payload(
                season["id"], order_type="GROUP", quantity=20,
                unit_price_cents=3000, faire_day_id=day["id"],
            ),
            make_guest_headers("g-g20@example.com"),
        ),
        201,
    )
    # 20 >= 2x minimum: 60000 * 0.85 = 51000.
    assert g20["total_cents"] == 51000
    assert g20["discount_pct"] == 0.15


def test_group_min_size_below_threshold_rejected(api):
    """PRD §3.5: "A `GROUP` order must also clear the season's group threshold — a
    `quantity` below the season's `group_min_size` is rejected with
    `ERR_GROUP_SIZE_BELOW_MINIMUM` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/group_min_size_exact_threshold
    """
    season, day = setup_season_build_with_sales_day(group_min_size=10)
    res = api.create_ticket_order(
        create_ticket_order_payload(
            season["id"], order_type="GROUP", quantity=9,
            unit_price_cents=3000, faire_day_id=day["id"],
        ),
        make_guest_headers("g-nine@example.com"),
    )
    validate_error(res, ApiErrorId.ERR_GROUP_SIZE_BELOW_MINIMUM, expected_status=422)


def test_group_min_size_exact_threshold_accepted(api):
    """PRD §3.5: "Group orders earn a discount keyed to how the `quantity` compares
    with the season's `group_min_size`: reaching the group minimum earns a
    ten-percent discount" — `quantity` exactly equal to `group_min_size` qualifies;
    only "a `quantity` below the season's `group_min_size` is rejected with
    `ERR_GROUP_SIZE_BELOW_MINIMUM` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/group_min_size_exact_threshold
    """
    season, day = setup_season_build_with_sales_day(group_min_size=10)
    order = validate_success(
        api.create_ticket_order(
            create_ticket_order_payload(
                season["id"], order_type="GROUP", quantity=10,
                unit_price_cents=3000, faire_day_id=day["id"],
            ),
            make_guest_headers("g-ten@example.com"),
        ),
        201,
    )
    assert order["total_cents"] == 27000
    assert order["discount_pct"] == 0.10


def test_group_tier_crossing_nineteen_vs_twenty(api):
    """PRD §3.5: "Group orders earn a discount keyed to how the `quantity` compares
    with the season's `group_min_size`: reaching the group minimum earns a
    ten-percent discount, reaching at least twice the minimum earns fifteen percent,
    and reaching at least four times the minimum earns twenty percent — the applied
    fraction is recorded as the order's `discount_pct`."

    Design: Corner/calculations/group_tier_crossing_nineteen_vs_twenty
    """
    season, day = setup_season_build_with_sales_day(group_min_size=10)
    g19 = validate_success(
        api.create_ticket_order(
            create_ticket_order_payload(
                season["id"], order_type="GROUP", quantity=19,
                unit_price_cents=3000, faire_day_id=day["id"],
            ),
            make_guest_headers("g-19@example.com"),
        ),
        201,
    )
    # 19 >= 1x but < 2x the minimum: 57000 * 0.90 = 51300.
    assert g19["total_cents"] == 51300
    assert g19["discount_pct"] == 0.10

    g20 = validate_success(
        api.create_ticket_order(
            create_ticket_order_payload(
                season["id"], order_type="GROUP", quantity=20,
                unit_price_cents=3000, faire_day_id=day["id"],
            ),
            make_guest_headers("g-20@example.com"),
        ),
        201,
    )
    # 20 >= 2x the minimum: 60000 * 0.85 = 51000 — one more ticket lowers the total.
    assert g20["total_cents"] == 51000
    assert g20["discount_pct"] == 0.15
