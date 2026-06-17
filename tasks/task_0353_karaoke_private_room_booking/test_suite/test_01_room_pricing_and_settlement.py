"""Room pricing: forward-looking quote vs chronological settlement, peak-straddle,
rounding order, package flat price, and overage settlement.

Covers difficulty queue rules dual_variant_calc / combinatorial_formula and the
corner calculations section.
"""
from test_helpers import (
    validate_success,
    setup_base, create_held_reservation, confirm_reservation,
    create_confirmed_reservation, create_checked_in_reservation,
    create_group_package, add_fb_order, close_reservation,
    set_clock, check_in_reservation,
)


def test_quoted_forward_vs_settled_chronological_diverge(api):
    """PRD §3.3: "The two exact segment costs are summed first, and only that sum
    is rounded — once, half-up, to whole cents — to yield `quoted_room_subtotal_cents`."
    PRD §3.4: "The `settled_room_subtotal` is chronological: it prices the actually
    occupied interval, from `checked_in_at` up to `actual_end_utc`, walked minute by
    minute in time order, so a session that drifted into or out of the peak window is
    charged for the real minutes it used rather than the planned ones — this is
    precisely why settled can diverge from quoted."

    Quote prices the booked 20:00-22:00 (120 peak min @ LARGE 6000/60 * 1.5 = 18000).
    Settlement prices the actual 20:00-22:30 with overage: 120 peak min (18000) + the
    20 overage minutes past 22:10 at peak*2.0 (20 * 100 * 1.5 * 2 = 6000) plus the
    10 free grace minutes 22:00-22:10 at peak (10 * 100 * 1.5 = 1500) = 25500.

    Design: Difficulty/dual_variant_calc/room_quoted_forward_vs_settled_chronological_diverge
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000,
                             "fb_minimum_cents": 0},
        clock_utc="2026-07-01T19:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    res = create_held_reservation(
        venue, room, customer,
        "2026-07-01T20:00:00.000Z", "2026-07-01T22:00:00.000Z", party_size=8,
    )
    confirmed = confirm_reservation(res, customer)
    assert confirmed["quoted_room_subtotal_cents"] == 18000
    assert confirmed["deposit_cents"] == 3600

    set_clock(venue["id"], "2026-07-01T20:00:00.000Z")
    check_in_reservation(confirmed)
    closed = close_reservation(confirmed, "2026-07-01T22:30:00.000Z")
    assert closed["settled_room_subtotal_cents"] == 25500
    assert closed["settled_room_subtotal_cents"] != closed["quoted_room_subtotal_cents"]


def test_fb_shortfall_package_credit_vs_no_credit_diverge(api):
    """PRD §3.4: "The package credit is the package's `included_fb_credit_cents` when
    a package is attached, and 0 otherwise; the effective food-and-beverage figure is
    the consumed amount plus that credit."
    PRD §3.4: "when the effective figure is below the floor, `fb_shortfall_cents` is the
    floor minus the effective figure; when the effective figure equals or exceeds the
    floor, `fb_shortfall_cents` is 0."

    Identical consumed 1500 and identical floor 5000: the no-credit reservation owes
    5000-1500=3500; the package reservation (credit 4000) has effective 5500 >= 5000 so
    owes 0.

    Design: Difficulty/dual_variant_calc/fb_shortfall_package_credit_vs_no_credit_diverge
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000,
                             "fb_minimum_cents": 5000},
        clock_utc="2026-07-02T17:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    pkg = create_group_package(
        venue["id"], base["room_type"]["id"], name="Bash",
        flat_price_cents=20000, included_hours=2.0, included_fb_credit_cents=4000,
    )

    # Reservation A (no package) 18:00-20:00; Reservation B (package) 20:00-22:00.
    res_a = create_held_reservation(venue, room, customer,
                                    "2026-07-02T18:00:00.000Z", "2026-07-02T20:00:00.000Z",
                                    party_size=4)
    res_b = create_held_reservation(venue, room, customer,
                                    "2026-07-02T20:00:00.000Z", "2026-07-02T22:00:00.000Z",
                                    party_size=8, group_package_id=pkg["id"])
    confirm_reservation(res_a, customer)
    confirm_reservation(res_b, customer)

    set_clock(venue["id"], "2026-07-02T18:00:00.000Z")
    check_in_reservation(res_a)
    add_fb_order(res_a, customer, unit_price_cents=1500, quantity=1, description="Snack A")
    closed_a = close_reservation(res_a, "2026-07-02T19:30:00.000Z")

    set_clock(venue["id"], "2026-07-02T20:00:00.000Z")
    check_in_reservation(res_b)
    add_fb_order(res_b, customer, unit_price_cents=1500, quantity=1, description="Snack B")
    closed_b = close_reservation(res_b, "2026-07-02T21:30:00.000Z")

    assert closed_a["fb_shortfall_cents"] == 3500
    assert closed_b["fb_shortfall_cents"] == 0
    assert closed_a["fb_shortfall_cents"] != closed_b["fb_shortfall_cents"]


def test_quoted_peak_straddle_nonlinear_branch(api):
    """PRD §3.3: "the server first counts the whole minutes in the booked interval as
    `booked_minutes`, then counts how many of those minutes have a local minute-of-day
    inside the half-open peak window `[peak_start_minute, peak_end_minute)` as the peak
    minutes, with the remaining minutes treated as off-peak."
    PRD §3.3: "The off-peak cost is the off-peak minute count times that per-minute base;
    the peak cost is the peak minute count times that per-minute base times the venue's
    `peak_multiplier`."

    A 17:30-19:30 LARGE (6000) booking straddles the 18:00 peak start: 30 off-peak min
    (30 * 100 = 3000) + 90 peak min (90 * 100 * 1.5 = 13500) = 16500; deposit 3300.

    Design: Difficulty/combinatorial_formula/quoted_peak_straddle_nonlinear_branch
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000,
                             "fb_minimum_cents": 0},
        clock_utc="2026-07-02T16:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    res = create_held_reservation(venue, room, customer,
                                  "2026-07-02T17:30:00.000Z", "2026-07-02T19:30:00.000Z",
                                  party_size=6)
    confirmed = confirm_reservation(res, customer)
    assert confirmed["quoted_room_subtotal_cents"] == 16500
    assert confirmed["deposit_cents"] == 3300


def test_quoted_rounding_order_sum_then_round(api):
    """PRD §2.6: "The governing rule for room pricing is **sum-then-round**: exact
    per-minute or per-segment costs are accumulated at full precision first, and the
    accumulated total is rounded exactly once, at the end, to the nearest whole cent
    using the round-half-up convention (a value exactly halfway between two cents rounds
    up to the larger cent)."

    SMALL base 3500, 17:40-18:15: 20 off-peak min (20 * 3500/60 = 1166.66..) + 15 peak
    min (15 * 3500/60 * 1.5 = 1312.5) = 2479.16.. rounded once -> 2479. The forbidden
    round-then-sum order would yield 2480.

    Design: Difficulty/combinatorial_formula/quoted_rounding_order_sum_then_round
    """
    base = setup_base(
        room_type_overrides={"name": "SMALL", "capacity": 4, "base_hourly_rate_cents": 3500,
                             "fb_minimum_cents": 0},
        clock_utc="2026-07-04T16:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    res = create_held_reservation(venue, room, customer,
                                  "2026-07-04T17:40:00.000Z", "2026-07-04T18:15:00.000Z",
                                  party_size=2)
    confirmed = confirm_reservation(res, customer)
    assert confirmed["quoted_room_subtotal_cents"] == 2479


def test_settled_within_plan_no_overage(api):
    """PRD §3.4: "A session whose `actual_end_utc` is at or before `slot_end_utc` plus
    `overage_grace_minutes` incurs no overage multiplier at all (pure peak/off-peak on
    the actual minutes)".

    LARGE 6000, checked in 20:00, closed 21:30 (within slot_end 22:00): 90 peak minutes
    at 100 * 1.5 = 13500, no overage.

    Design: Corner/calculations/settled_within_plan_no_overage_variant
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000},
        clock_utc="2026-08-07T19:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    res = create_checked_in_reservation(
        venue, room, customer,
        "2026-08-07T20:00:00.000Z", "2026-08-07T22:00:00.000Z",
        checkin_clock_utc="2026-08-07T20:00:00.000Z",
    )
    closed = close_reservation(res, "2026-08-07T21:30:00.000Z")
    assert closed["settled_room_subtotal_cents"] == 13500


def test_package_quote_uses_flat_price(api):
    """PRD §3.3: "When the reservation carries a `group_package_id`, the quote is simply
    the package's `flat_price_cents`; the package's included hours and any potential
    overage are not charged at quote time, because the forward-looking quote assumes the
    party stays within plan."

    Package flat 20000 -> quoted_room_subtotal_cents == 20000; deposit 0.2 * 20000 = 4000.

    Design: Corner/calculations/package_quote_uses_flat_price_variant
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000},
        clock_utc="2026-08-08T10:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    pkg = create_group_package(
        venue["id"], base["room_type"]["id"], name="Bash",
        flat_price_cents=20000, included_hours=2.0, included_fb_credit_cents=4000,
    )
    res = create_held_reservation(venue, room, customer,
                                  "2026-08-08T19:00:00.000Z", "2026-08-08T21:00:00.000Z",
                                  party_size=8, group_package_id=pkg["id"])
    confirmed = confirm_reservation(res, customer)
    assert confirmed["quoted_room_subtotal_cents"] == 20000
    assert confirmed["deposit_cents"] == 4000


def test_close_settlement_totals_visible_in_same_response(api):
    """PRD §3.4: "Finally, `final_total_cents` is the settled room subtotal plus the
    consumed food-and-beverage amount plus the food-and-beverage shortfall, less the
    already-collected `deposit_cents` (the deposit is credited against the bill), with
    the result never allowed to fall below 0".

    LARGE 6000 fb_minimum 5000, 20:00-22:00 booked, closed 22:30 (overage): settled
    25500, deposit 3600, fb_consumed 3000, fb_shortfall 5000-3000=2000,
    final = 25500 + 3000 + 2000 - 3600 = 26900.

    Design: Corner/consistency_model/close_settlement_totals_visible_in_same_response
    """
    base = setup_base(
        room_type_overrides={"name": "LARGE", "capacity": 12, "base_hourly_rate_cents": 6000,
                             "fb_minimum_cents": 5000},
        clock_utc="2026-08-27T19:00:00.000Z",
    )
    venue, room, customer = base["venue"], base["room"], base["customer"]
    res = create_checked_in_reservation(
        venue, room, customer,
        "2026-08-27T20:00:00.000Z", "2026-08-27T22:00:00.000Z",
        checkin_clock_utc="2026-08-27T20:00:00.000Z",
    )
    assert res["deposit_cents"] == 3600
    add_fb_order(res, customer, unit_price_cents=1500, quantity=2, description="Drinks")
    data = validate_success(
        api.close_reservation(res["id"], {"actual_end_utc": "2026-08-27T22:30:00.000Z"},
                              _fd_headers()),
        200,
    )
    assert data["settled_room_subtotal_cents"] == 25500
    assert data["deposit_cents"] == 3600
    assert data["fb_consumed_cents"] == 3000
    assert data["fb_shortfall_cents"] == 2000
    assert data["final_total_cents"] == 26900


def _fd_headers():
    from test_helpers import make_front_desk_headers
    return make_front_desk_headers()
