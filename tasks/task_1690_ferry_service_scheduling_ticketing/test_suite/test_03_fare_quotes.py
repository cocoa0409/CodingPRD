"""Fare quotation: seasonal variants, pinned rounding order, the 22-foot
vehicle band boundary, and per-class passenger rates.

Reference rates used throughout (integer cents): passenger standard 1000,
resident 800, commuter 600; vehicle standard base 2000, oversize base 4000
(unless overridden), overlength 100/ft; fuel surcharge pinned at submission
(index 350 -> 100, index 200 -> 0).
"""
from test_helpers import (
    assert_booking,
    create_booking,
    create_customer,
    create_fare_schedule,
    create_route,
    create_sailing,
    create_vessel,
    crew_sailing_to_class_minimum,
    open_sailing,
    set_clock,
    setup_open_sailing,
    submit_and_approve,
)

def test_peak_quote_applies_vehicle_multiplier(api):
    """PRD §3.5: "On a `PEAK` sailing, the fully computed vehicle component —
    base plus any overlength surcharge — is multiplied by 1.25 and rounded
    half-up to whole cents before the passenger and surcharge components are
    added."
    PRD §3.5: "`OFF_PEAK` sailings use the base formula with no multiplier."

    Design: Difficulty/dual_variant_calc/fare_quote_peak_vs_off_peak
    """
    route = create_route(route_code="SEA-BI", crossing_minutes=35, turnaround_minutes=15)
    vessel = create_vessel(
        vessel_name="MV Kittitas",
        vehicle_deck_linear_feet=200,
        passenger_capacity=600,
        crew_class="MEDIUM",
    )
    fs_off = create_fare_schedule(
        route["id"],
        season="OFF_PEAK",
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2026-11-01T00:00:00Z",
    )
    submit_and_approve(fs_off["id"], 350)
    fs_peak = create_fare_schedule(
        route["id"],
        season="PEAK",
        effective_from="2026-06-01T00:00:00Z",
        effective_to="2026-08-01T00:00:00Z",
    )
    submit_and_approve(fs_peak["id"], 350)

    s_peak = create_sailing(
        route["id"], vessel["id"], departure_time="2026-07-01T10:00:00Z", season="PEAK"
    )
    crew_sailing_to_class_minimum(s_peak["id"], "MEDIUM", "2026-07-01")
    s_off = create_sailing(
        route["id"], vessel["id"], departure_time="2026-09-01T10:00:00Z", season="OFF_PEAK"
    )
    crew_sailing_to_class_minimum(s_off["id"], "MEDIUM", "2026-09-01")

    customer = create_customer(full_name="Std Pat", fare_class="STANDARD")

    set_clock("2026-06-15T00:00:00Z")
    open_sailing(s_peak["id"])
    peak_booking = create_booking(
        s_peak["id"], customer, passenger_count=2, has_vehicle=True, vehicle_length_feet=18
    )

    set_clock("2026-08-15T00:00:00Z")
    open_sailing(s_off["id"])
    off_booking = create_booking(
        s_off["id"], customer, passenger_count=2, has_vehicle=True, vehicle_length_feet=18
    )

    assert_booking(peak_booking)
    assert_booking(off_booking)
    # PEAK: 2*1000 + round_half_up(2000*1.25)=2500 + 100*2 = 4700
    assert peak_booking["quoted_fare_cents"] == 4700, (
        f"PEAK quote must apply the 1.25 vehicle multiplier: expected 4700, "
        f"got {peak_booking['quoted_fare_cents']}"
    )
    # OFF_PEAK: 2*1000 + 2000 + 100*2 = 4200
    assert off_booking["quoted_fare_cents"] == 4200, (
        f"OFF_PEAK quote must use the base formula: expected 4200, "
        f"got {off_booking['quoted_fare_cents']}"
    )
    assert peak_booking["quoted_fare_cents"] != off_booking["quoted_fare_cents"], (
        "identical party and rates must quote differently across seasons"
    )


def test_peak_quote_vehicle_multiplier_for_smaller_party(api):
    """PRD §3.5: "On a `PEAK` sailing, the fully computed vehicle component —
    base plus any overlength surcharge — is multiplied by 1.25 and rounded
    half-up to whole cents before the passenger and surcharge components are
    added."

    Design: Difficulty/dual_variant_calc/fare_quote_peak_vs_off_peak
    """
    setup = setup_open_sailing(
        season="PEAK",
        departure_time="2026-07-01T10:00:00Z",
        effective_from="2026-06-01T00:00:00Z",
        effective_to="2026-08-01T00:00:00Z",
        clock="2026-06-15T00:00:00Z",
        fuel_price_index_cents=350,
    )
    customer = create_customer(full_name="Std Pat", fare_class="STANDARD")
    booking = create_booking(
        setup["sailing"]["id"],
        customer,
        passenger_count=1,
        has_vehicle=True,
        vehicle_length_feet=18,
    )
    # PEAK: 1*1000 + round_half_up(2000*1.25)=2500 + 100*2 = 3700
    assert booking["quoted_fare_cents"] == 3700, (
        f"PEAK 1-pax 18-ft quote must be 3700, got {booking['quoted_fare_cents']}"
    )


def test_peak_oversize_quote_rounds_after_multiplication(api):
    """PRD §3.5: "Rounding each per-foot surcharge first and then summing is
    forbidden, because it yields different cents; the multiplier applies to
    the complete vehicle figure exactly once."
    PRD §3.5: "On a `PEAK` sailing, the fully computed vehicle component —
    base plus any overlength surcharge — is multiplied by 1.25 and rounded
    half-up to whole cents before the passenger and surcharge components are
    added."

    Design: Difficulty/combinatorial_formula/fare_quote_peak_rounding_order_pinned
    """
    setup = setup_open_sailing(
        season="PEAK",
        departure_time="2026-07-01T10:00:00Z",
        effective_from="2026-06-01T00:00:00Z",
        effective_to="2026-08-01T00:00:00Z",
        clock="2026-06-15T00:00:00Z",
        fuel_price_index_cents=200,
        rate_overrides={"vehicle_oversize_base_cents": 4005},
    )
    customer = create_customer(full_name="Std Pat", fare_class="STANDARD")
    booking = create_booking(
        setup["sailing"]["id"],
        customer,
        passenger_count=1,
        has_vehicle=True,
        vehicle_length_feet=24,
    )
    # vehicle component: 4005 + (24-21)*100 = 4305; round_half_up(4305*1.25)
    #   = round_half_up(5381.25) = 5381 (per-foot-first rounding is forbidden);
    # total: 1000 (pax) + 5381 + 0 (surcharge, index 200) = 6381
    assert booking["quoted_fare_cents"] == 6381, (
        f"rounding must apply to the multiplied whole vehicle component: "
        f"expected 6381, got {booking['quoted_fare_cents']}"
    )


def test_peak_quote_does_not_multiply_passenger_component(api):
    """PRD §3.5: "One seasonal variant modifies the vehicle component only."
    PRD §3.5: "On a `PEAK` sailing, the fully computed vehicle component —
    base plus any overlength surcharge — is multiplied by 1.25 and rounded
    half-up to whole cents before the passenger and surcharge components are
    added."

    Design: Difficulty/combinatorial_formula/fare_quote_peak_rounding_order_pinned
    """
    setup = setup_open_sailing(
        season="PEAK",
        departure_time="2026-07-01T10:00:00Z",
        effective_from="2026-06-01T00:00:00Z",
        effective_to="2026-08-01T00:00:00Z",
        clock="2026-06-15T00:00:00Z",
        fuel_price_index_cents=350,
    )
    customer = create_customer(full_name="Walk Pat", fare_class="STANDARD")
    booking = create_booking(
        setup["sailing"]["id"], customer, passenger_count=2, has_vehicle=False
    )
    # walk-on: vehicle component is 0 (0 * 1.25 = 0); 2*1000 + 100 (pax
    # surcharge, index 350) = 2100 — the passenger component is never scaled.
    assert booking["quoted_fare_cents"] == 2100, (
        f"PEAK walk-on quote must leave the passenger component unmultiplied: "
        f"expected 2100, got {booking['quoted_fare_cents']}"
    )


def test_vehicle_21ft_stays_in_standard_band(api):
    """PRD §3.5: "The vehicle component is zero when the booking brings no
    vehicle; otherwise it is the schedule's standard vehicle base when the
    vehicle is under 22 feet, or — at 22 feet and above — the oversize base
    plus the per-foot overlength surcharge for every foot beyond 21 (so a
    22-foot vehicle pays the oversize base plus exactly one surcharge foot,
    while a 21-foot vehicle stays in the standard band)."

    Design: Difficulty/boundary_precision_check/vehicle_length_22ft_band_boundary
    """
    setup = setup_open_sailing(fuel_price_index_cents=350)
    customer = create_customer(full_name="Std Pat", fare_class="STANDARD")
    booking = create_booking(
        setup["sailing"]["id"],
        customer,
        passenger_count=0,
        has_vehicle=True,
        vehicle_length_feet=21,
    )
    # 21 ft -> standard band: 2000 + 100*1 (vehicle component only) = 2100
    assert booking["quoted_fare_cents"] == 2100, (
        f"21-ft vehicle must price in the standard band: expected 2100, "
        f"got {booking['quoted_fare_cents']}"
    )


def test_vehicle_22ft_enters_oversize_band_with_one_surcharge_foot(api):
    """PRD §3.5: "The vehicle component is zero when the booking brings no
    vehicle; otherwise it is the schedule's standard vehicle base when the
    vehicle is under 22 feet, or — at 22 feet and above — the oversize base
    plus the per-foot overlength surcharge for every foot beyond 21 (so a
    22-foot vehicle pays the oversize base plus exactly one surcharge foot,
    while a 21-foot vehicle stays in the standard band)."

    Design: Difficulty/boundary_precision_check/vehicle_length_22ft_band_boundary
    """
    setup = setup_open_sailing(fuel_price_index_cents=350)
    customer = create_customer(full_name="Std Pat", fare_class="STANDARD")
    booking = create_booking(
        setup["sailing"]["id"],
        customer,
        passenger_count=0,
        has_vehicle=True,
        vehicle_length_feet=22,
    )
    # 22 ft -> oversize band with (22-21)=1 surcharge foot:
    # 4000 + 1*100 = 4100; + 100*1 fuel surcharge = 4200
    assert booking["quoted_fare_cents"] == 4200, (
        f"22-ft vehicle must price in the oversize band with one surcharge "
        f"foot: expected 4200, got {booking['quoted_fare_cents']}"
    )


def test_fare_class_selects_passenger_rate(api):
    """PRD §3.5: "The passenger component multiplies `passenger_count` by the
    per-crossing rate matching the customer's `fare_class`:
    `passenger_standard_cents` for `STANDARD`, `passenger_resident_cents` for
    `RESIDENT`, or `passenger_commuter_cents` for `COMMUTER`."

    Design: Corner/calculations/fare_quote_resident_and_commuter_classes
    """
    setup = setup_open_sailing(fuel_price_index_cents=350)
    sailing_id = setup["sailing"]["id"]
    resident = create_customer(full_name="Res Pat", fare_class="RESIDENT")
    commuter = create_customer(full_name="Com Pat", fare_class="COMMUTER")
    standard = create_customer(full_name="Std Pat", fare_class="STANDARD")

    res_booking = create_booking(sailing_id, resident, passenger_count=1)
    com_booking = create_booking(sailing_id, commuter, passenger_count=1)
    std_booking = create_booking(sailing_id, standard, passenger_count=1)

    # walk-on, 1 pax: rate + 100 fuel surcharge (index 350)
    assert res_booking["quoted_fare_cents"] == 900, (
        f"RESIDENT 1-pax walk-on must quote 800+100=900, got {res_booking['quoted_fare_cents']}"
    )
    assert com_booking["quoted_fare_cents"] == 700, (
        f"COMMUTER 1-pax walk-on must quote 600+100=700, got {com_booking['quoted_fare_cents']}"
    )
    assert std_booking["quoted_fare_cents"] == 1100, (
        f"STANDARD 1-pax walk-on must quote 1000+100=1100, got {std_booking['quoted_fare_cents']}"
    )
