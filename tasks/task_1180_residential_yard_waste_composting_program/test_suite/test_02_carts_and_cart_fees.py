"""Carts: size tiers, per-household limit, delivery lifecycle, and fee accrual."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_cart,
    create_cart,
    create_cart_payload,
    create_household,
    create_subscription,
    create_zone,
    deliver_cart,
    get_subscription,
    make_resident_headers,
    make_supervisor_headers,
    set_clock,
    setup_active_household,
    validate_error,
    validate_success,
)


def test_extra_cart_fee_ordering_first_cart_exempt(api, admin_headers):
    """PRD section 3.3: "a 35-gallon cart carries no surcharge, a 64-gallon cart
    adds 1500 cents ($15.00), and a 96-gallon cart adds 3000 cents ($30.00), and
    each cart exposes this figure as its own `surcharge_cents`" and "then add an
    extra-cart fee of 2500 cents ($25.00) for every cart beyond the first — the
    first cart is exempt from the extra-cart fee."

    Design: Corner/calculations/extra_cart_fee_ordering_first_cart_exempt
    """
    ctx = setup_active_household(service_model="OPT_IN", base_seasonal_fee_cents=12000)
    household, sub = ctx["household"], ctx["subscription"]

    cart1 = create_cart(household, sub["id"], 35)
    assert_cart(cart1)
    assert cart1["surcharge_cents"] == 0

    cart2 = create_cart(household, sub["id"], 96)
    assert_cart(cart2)
    assert cart2["surcharge_cents"] == 3000

    sub_after = get_subscription(sub["id"])
    assert sub_after["cart_fees_cents"] == 5500
    assert sub_after["total_due_cents"] == 17500


def test_cart_create_invalid_enum_size_returns_invalid_request(api, admin_headers):
    """PRD section 2.8: "Required fields are present, types are correct, enum
    members are valid, and ranges hold: `gallons` at least 1,
    `quantity_bundles` between 1 and 10 inclusive, `weight_lbs` greater than 0,
    `window_end` later than `window_start`, `violation_codes` non-empty exactly
    when the inspection result is a tagged outcome, a ticket's `service_date`
    weekday matching the route's weekday, a route's effective window inside its
    zone's season window, and no unknown fields. Any violation yields
    `ERR_INVALID_REQUEST`." PRD section 3.3: "a `size_gallons` tier of `35`,
    `64`, or `96`".

    Design: Corner/entities/cart_create_invalid_enum_size_returns_invalid_request
    """
    zone = create_zone()
    household = create_household(zone["id"])
    sub = create_subscription(household, season_year=2026)

    res = api.create_cart(
        create_cart_payload(household["id"], sub["id"], 50),
        make_resident_headers(household["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_cart_limit_exceeded_third_cart(api, admin_headers):
    """PRD section 3.3: "a household may hold at most two carts in `REQUESTED`
    or `DELIVERED` status at once — a third request fails with
    `ERR_CART_LIMIT_EXCEEDED`."

    Design: Corner/validations/cart_limit_exceeded_third_cart
    """
    ctx = setup_active_household(service_model="OPT_IN", base_seasonal_fee_cents=12000)
    household, sub = ctx["household"], ctx["subscription"]

    create_cart(household, sub["id"], 35)
    create_cart(household, sub["id"], 64)
    res = api.create_cart(
        create_cart_payload(household["id"], sub["id"], 96),
        make_resident_headers(household["id"]),
    )
    validate_error(res, ApiErrorId.ERR_CART_LIMIT_EXCEEDED)

    # The two surviving carts cost 0 + 1500 surcharges plus one 2500 extra-cart fee.
    sub_after = get_subscription(sub["id"])
    assert sub_after["cart_fees_cents"] == 4000


def test_cart_deliver_twice_rejected(api, admin_headers, supervisor_headers):
    """PRD section 3.3: "A `RouteSupervisor` marks it delivered, which requires
    the cart to be `REQUESTED` (otherwise `ERR_INVALID_STATE`), stamps
    `delivered_at` with the logical clock, and moves the cart to `DELIVERED`."

    Design: Corner/state_machines/cart_deliver_twice_rejected
    """
    ctx = setup_active_household(service_model="OPT_IN")
    cart = create_cart(ctx["household"], ctx["subscription"]["id"], 35)
    assert cart["status"] == "REQUESTED"

    delivered = deliver_cart(cart["id"])
    assert delivered["status"] == "DELIVERED"
    assert delivered["delivered_at"] is not None

    res = api.deliver_cart(cart["id"], supervisor_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_subscription_expiry_and_cart_retrieval_by_clock(api, admin_headers):
    """PRD section 3.1: "When a zone's season ends — the clock date passes
    `season_end_date` — every subscription of every household in that zone that
    is still `PENDING_PAYMENT`, `ACTIVE`, or `SUSPENDED` transitions to
    `EXPIRED`." PRD section 3.3: "When the owning subscription is cancelled or
    expires, each `DELIVERED` cart moves to `RETRIEVAL_SCHEDULED`; once the
    clock date passes fourteen days beyond the zone's `season_end_date`, the
    cart moves to `RETRIEVED`".

    Design: Corner/state_machines/subscription_expiry_and_cart_retrieval_by_clock
    """
    ctx = setup_active_household(service_model="OPT_IN")
    cart = create_cart(ctx["household"], ctx["subscription"]["id"], 35)
    set_clock("2026-05-15T00:00:00Z")
    cart = deliver_cart(cart["id"])
    assert cart["status"] == "DELIVERED"

    # 2026-11-20 is past season end (2026-10-31) and past the +14 day retrieval lag.
    set_clock("2026-11-20T00:00:00Z")

    sub_after = get_subscription(ctx["subscription"]["id"])
    assert sub_after["status"] == "EXPIRED"
    cart_after = validate_success(api.get_cart(cart["id"], admin_headers), 200)
    assert cart_after["status"] == "RETRIEVED"
