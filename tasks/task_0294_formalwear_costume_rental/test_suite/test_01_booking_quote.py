"""Booking-quote calculation tests (provisional quote at confirmation).

PRD §3.4 pins the rental_days span, the tiered volume discount, the rounding
order (round the per-day rate first, then multiply), and the waiver component.
"""
from test_helpers import (
    validate_success,
    set_clock, create_catalog, create_unit, create_customer, create_reservation,
    confirm,
)


def test_booking_quote_five_day_with_waiver(api):
    """PRD §3.4: "First it derives `rental_days` as the inclusive span of the rental window: take the number of whole days from `pickup_window_start_iso` to `return_window_end_iso` and add 1, so a same-day pickup and return is 1 rental-day."
    PRD §3.4: "a span of 4 to 7 days uses 0.90; a span of 8 days or more uses 0.80."
    PRD §3.4: "first compute the effective per-day rate by multiplying `daily_rate_cents` by the chosen multiplier and rounding that per-day figure half-up to whole cents, and only then multiply the rounded per-day rate by `rental_days` to obtain the rental component."
    PRD §3.4: "The waiver component is the `waiver_daily_rate_cents` multiplied by `rental_days` when `damage_waiver_opted` is true, and 0 when it is false."

    Design: Difficulty/dual_variant_calc/booking_quote_provisional_vs_final_on_reservation
    """
    set_clock()
    catalog = create_catalog(style_name="Tux A", daily_rate_cents=5000,
                             deposit_cents=20000, replacement_value_cents=80000,
                             waiver_daily_rate_cents=1200, cleaning_buffer_days=2,
                             late_fee_daily_rate_cents=2000)
    create_unit(catalog["id"], "M")
    customer = create_customer()
    resv = create_reservation(customer["id"], catalog["id"], requested_size_code="M",
                              event_date_iso="2026-09-06T00:00:00Z",
                              pickup_window_start_iso="2026-09-01T09:00:00Z",
                              return_window_end_iso="2026-09-05T09:00:00Z",
                              damage_waiver_opted=True)

    confirmed = validate_success(confirm(resv["id"]), 200)
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["rental_days"] == 5, f"expected 5 rental-days, got {confirmed['rental_days']}"
    # round(5000*0.90)=4500 *5 = 22500 rental + 1200*5 = 6000 waiver = 28500
    assert confirmed["quoted_charge_cents"] == 28500, \
        f"expected 28500, got {confirmed['quoted_charge_cents']}"


def test_booking_quote_provisional_excludes_late_and_damage(api):
    """PRD §3.4: "This quote is provisional — computed once at confirmation and never recomputed after pickup; it never includes late or damage fees, which are assessed only at settlement, and the rental component it establishes is carried forward as the rental baseline for settlement."

    Design: Difficulty/dual_variant_calc/booking_quote_provisional_vs_final_on_reservation
    """
    set_clock()
    catalog = create_catalog(style_name="Tux A2", daily_rate_cents=5000,
                             deposit_cents=20000, replacement_value_cents=80000,
                             waiver_daily_rate_cents=1200, cleaning_buffer_days=2,
                             late_fee_daily_rate_cents=2000)
    create_unit(catalog["id"], "M")
    customer = create_customer()
    resv = create_reservation(customer["id"], catalog["id"], requested_size_code="M",
                              event_date_iso="2026-09-06T00:00:00Z",
                              pickup_window_start_iso="2026-09-01T09:00:00Z",
                              return_window_end_iso="2026-09-05T09:00:00Z",
                              damage_waiver_opted=True)

    confirmed = validate_success(confirm(resv["id"]), 200)
    # The provisional quote is exactly rental (22500) + waiver (6000) = 28500 with no
    # late-fee (2000/day) or damage-fee (80000 replacement) component folded in.
    assert confirmed["quoted_charge_cents"] == 28500, \
        f"quote must exclude late/damage fees; got {confirmed['quoted_charge_cents']}"


def test_booking_quote_round_per_day_then_multiply(api):
    """PRD §3.4: "first compute the effective per-day rate by multiplying `daily_rate_cents` by the chosen multiplier and rounding that per-day figure half-up to whole cents, and only then multiply the rounded per-day rate by `rental_days` to obtain the rental component."

    Design: Difficulty/combinatorial_formula/booking_quote_round_per_day_then_multiply
    """
    set_clock()
    catalog = create_catalog(style_name="Suit D", daily_rate_cents=3333,
                             deposit_cents=20000, replacement_value_cents=80000,
                             waiver_daily_rate_cents=1200, cleaning_buffer_days=2,
                             late_fee_daily_rate_cents=2000)
    create_unit(catalog["id"], "M")
    customer = create_customer()
    resv = create_reservation(customer["id"], catalog["id"], requested_size_code="M",
                              event_date_iso="2026-09-06T00:00:00Z",
                              pickup_window_start_iso="2026-09-01T09:00:00Z",
                              return_window_end_iso="2026-09-05T09:00:00Z",
                              damage_waiver_opted=False)

    confirmed = validate_success(confirm(resv["id"]), 200)
    assert confirmed["rental_days"] == 5, f"expected 5, got {confirmed['rental_days']}"
    # round-per-day: round(3333*0.9)=3000 *5 = 15000 (NOT round(3333*0.9*5)=14999)
    assert confirmed["quoted_charge_cents"] == 15000, \
        f"round-per-day must give 15000, not 14999; got {confirmed['quoted_charge_cents']}"


def test_booking_quote_tier_boundary_three_vs_four_days(api):
    """PRD §3.4: "a span of 1 to 3 days uses a multiplier of 1.00; a span of 4 to 7 days uses 0.90; a span of 8 days or more uses 0.80."

    Design: Corner/calculations/booking_quote_tier_boundary_three_vs_four_days
    """
    set_clock()
    catalog = create_catalog(style_name="Tux H2", daily_rate_cents=5000,
                             deposit_cents=20000, replacement_value_cents=80000,
                             waiver_daily_rate_cents=1200, cleaning_buffer_days=2,
                             late_fee_daily_rate_cents=2000)
    create_unit(catalog["id"], "M")
    create_unit(catalog["id"], "M")
    cust1 = create_customer()
    cust2 = create_customer()
    resv3 = create_reservation(cust1["id"], catalog["id"], requested_size_code="M",
                               event_date_iso="2026-09-04T00:00:00Z",
                               pickup_window_start_iso="2026-09-01T09:00:00Z",
                               return_window_end_iso="2026-09-03T09:00:00Z")
    resv4 = create_reservation(cust2["id"], catalog["id"], requested_size_code="M",
                               event_date_iso="2026-09-05T00:00:00Z",
                               pickup_window_start_iso="2026-09-01T09:00:00Z",
                               return_window_end_iso="2026-09-04T09:00:00Z")

    c3 = validate_success(confirm(resv3["id"]), 200)
    c4 = validate_success(confirm(resv4["id"]), 200)
    assert c3["rental_days"] == 3
    assert c3["quoted_charge_cents"] == 15000, "3-day tier1: 5000*1.00*3 = 15000"
    assert c4["rental_days"] == 4
    assert c4["quoted_charge_cents"] == 18000, "4-day tier2: round(5000*0.90)=4500 *4 = 18000"
