"""Deck allocation: the pinned reserved-first split at open-booking, the
floor clamps, the read-only what-if projection, and reservation-pool
capacity enforcement."""
from test_helpers import (
    ApiErrorId,
    assert_sailing,
    confirm_booking,
    create_booking,
    create_booking_payload,
    create_customer,
    get_sailing,
    make_customer_headers,
    setup_open_sailing,
    validate_error,
    validate_success,
)


def test_open_booking_pins_off_peak_allotment_at_120(api, scheduler_admin_headers):
    """PRD §3.4: "Let the vessel's deck be D feet and let the season's
    reservation ratio be seven-tenths of the deck for `PEAK` sailings or
    six-tenths for `OFF_PEAK` sailings. The raw reservation figure is that
    product rounded down to a whole foot."
    PRD §3.4: "For example, a 200-foot vessel sailing in `PEAK` season pins
    140 feet for reservations (seven-tenths of 200, already whole) and 60 feet
    for standby; in `OFF_PEAK` it would pin 120 and 80."

    Design: Difficulty/dual_variant_calc/deck_allocation_reserved_first_vs_dynamic_ratio
    """
    setup = setup_open_sailing(
        deck_feet=200, season="OFF_PEAK", fuel_price_index_cents=200
    )
    sailing = setup["sailing"]
    assert_sailing(sailing)
    # floor(200 * 0.60) = 120; clamped: min(120, 200-40)=120, max(20,120)=120
    assert sailing["reserved_deck_allotment_feet"] == 120, (
        f"200-ft OFF_PEAK sailing must pin 120 reserved feet, got "
        f"{sailing['reserved_deck_allotment_feet']}"
    )
    assert sailing["status"] == "OPEN_FOR_BOOKING"


def test_deck_projection_ratio_differs_from_pinned_allotment(
    api, terminal_agent_headers
):
    """PRD §3.4: "A read-only what-if projection capability accepts a `ratio`
    and returns the `reserved_deck_allotment_feet` and `standby_pool_feet`
    that ratio would produce for the same vessel, applying the same floors and
    rounding."
    PRD §3.4: "The split is computed once and frozen for the sailing's life;
    it never rebalances afterward." (§2.7)

    Design: Difficulty/dual_variant_calc/deck_allocation_reserved_first_vs_dynamic_ratio
    """
    setup = setup_open_sailing(
        deck_feet=200, season="OFF_PEAK", fuel_price_index_cents=200
    )
    sailing = setup["sailing"]
    assert sailing["reserved_deck_allotment_feet"] == 120

    projection = validate_success(
        api.get_deck_projection(sailing["id"], 0.50, terminal_agent_headers)
    )
    # floor(200 * 0.50) = 100; clamps inert: min(100, 160), max(20, 100)
    assert projection["reserved_deck_allotment_feet"] == 100, (
        f"ratio 0.50 projection must yield 100 reserved feet, got "
        f"{projection['reserved_deck_allotment_feet']}"
    )
    assert projection["standby_pool_feet"] == 100, (
        f"ratio 0.50 projection must yield 100 standby feet, got "
        f"{projection['standby_pool_feet']}"
    )
    assert projection["reserved_deck_allotment_feet"] != sailing["reserved_deck_allotment_feet"], (
        "the dynamic-ratio projection must differ from the season-pinned split"
    )


def test_small_deck_reservation_floor_clamps_up(api):
    """PRD §3.4: "The pinned `reserved_deck_allotment_feet` is then the raw
    figure clamped on both sides: it never exceeds the deck minus a 40-foot
    standby floor, and it never falls below a 20-foot reservation floor — so
    even a tiny vessel keeps at least 20 reservable feet, and even a dominant
    reservation market leaves at least 40 feet for the standby lane."
    PRD §3.4: "The standby pool is whatever remains, and the two pools always
    sum to D."

    Design: Difficulty/combinatorial_formula/deck_allocation_floor_clamps
    """
    setup = setup_open_sailing(
        deck_feet=50,
        passenger_capacity=100,
        crew_class="SMALL",
        season="OFF_PEAK",
        fuel_price_index_cents=200,
        route_overrides={
            "origin_terminal": "Port Townsend",
            "destination_terminal": "Coupeville",
            "crossing_minutes": 30,
            "turnaround_minutes": 10,
        },
    )
    sailing = setup["sailing"]
    # raw = floor(50 * 0.60) = 30; min(30, 50-40=10) = 10; max(20, 10) = 20
    assert sailing["reserved_deck_allotment_feet"] == 20, (
        f"50-ft OFF_PEAK sailing must clamp up to the 20-ft reservation floor, "
        f"got {sailing['reserved_deck_allotment_feet']}"
    )
    # implied standby pool: 50 - 20 = 30 (pools sum to the deck)
    implied_standby = 50 - sailing["reserved_deck_allotment_feet"]
    assert implied_standby == 30


def test_standby_floor_clamps_reserved_from_above(api):
    """PRD §3.4: "The pinned `reserved_deck_allotment_feet` is then the raw
    figure clamped on both sides: it never exceeds the deck minus a 40-foot
    standby floor, and it never falls below a 20-foot reservation floor — so
    even a tiny vessel keeps at least 20 reservable feet, and even a dominant
    reservation market leaves at least 40 feet for the standby lane."

    Design: Difficulty/combinatorial_formula/deck_allocation_floor_clamps
    """
    setup = setup_open_sailing(
        deck_feet=100,
        passenger_capacity=300,
        crew_class="SMALL",
        season="PEAK",
        departure_time="2026-07-01T10:00:00Z",
        effective_from="2026-06-01T00:00:00Z",
        effective_to="2026-08-01T00:00:00Z",
        clock="2026-06-15T00:00:00Z",
        fuel_price_index_cents=200,
    )
    sailing = setup["sailing"]
    # raw = floor(100 * 0.70) = 70; min(70, 100-40=60) = 60; max(20, 60) = 60
    assert sailing["reserved_deck_allotment_feet"] == 60, (
        f"100-ft PEAK sailing must clamp down to the 40-ft standby floor "
        f"(reserved 60), got {sailing['reserved_deck_allotment_feet']}"
    )
    implied_standby = 100 - sailing["reserved_deck_allotment_feet"]
    assert implied_standby == 40


def test_deck_projection_is_read_only(api, terminal_agent_headers):
    """PRD §3.4: "This projection never mutates the sailing: the pinned
    allotment is frozen at open time for the sailing's entire life."

    Design: Corner/endpoints/deck_projection_is_read_only
    """
    setup = setup_open_sailing(
        deck_feet=200, season="OFF_PEAK", fuel_price_index_cents=200
    )
    sailing = setup["sailing"]
    assert sailing["reserved_deck_allotment_feet"] == 120

    projection = validate_success(
        api.get_deck_projection(sailing["id"], 0.50, terminal_agent_headers)
    )
    assert projection["reserved_deck_allotment_feet"] == 100
    assert projection["standby_pool_feet"] == 100

    after = validate_success(api.get_sailing(sailing["id"], terminal_agent_headers))
    assert after["reserved_deck_allotment_feet"] == 120, (
        f"projection must not mutate the pinned allotment: expected 120, got "
        f"{after['reserved_deck_allotment_feet']}"
    )


def test_reservation_pool_capacity_boundary(api, scheduler_admin_headers):
    """PRD §3.5: "Capacity is enforced at quote time against the pinned pools:
    the requested vehicle feet must fit within the reservation pool after
    accounting for `reserved_vehicle_feet` already held, and the requested
    passengers must fit within `passenger_capacity` after `booked_passengers`;
    shortfalls are rejected with `ERR_CAPACITY_EXCEEDED`."

    Design: Corner/validations/capacity_exceeded_on_booking_create
    """
    setup = setup_open_sailing(
        deck_feet=200, season="OFF_PEAK", fuel_price_index_cents=200
    )
    sailing = setup["sailing"]
    assert sailing["reserved_deck_allotment_feet"] == 120

    customer = create_customer(full_name="Big Rig", fare_class="STANDARD")
    booking80 = create_booking(
        sailing["id"], customer, passenger_count=1, has_vehicle=True,
        vehicle_length_feet=80,
    )
    confirm_booking(booking80["id"], customer)
    assert get_sailing(sailing["id"])["reserved_vehicle_feet"] == 80

    # 80 + 41 = 121 > 120: does not fit within the reservation pool
    over_payload = create_booking_payload(
        customer_id=customer["id"],
        passenger_count=0,
        has_vehicle=True,
        vehicle_length_feet=41,
    )
    resp = api.create_booking(
        sailing["id"], over_payload, make_customer_headers(customer["id"])
    )
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)

    # 80 + 40 = 120 <= 120: fits exactly ("fit within" is inclusive)
    fit_payload = create_booking_payload(
        customer_id=customer["id"],
        passenger_count=0,
        has_vehicle=True,
        vehicle_length_feet=40,
    )
    created = validate_success(
        api.create_booking(
            sailing["id"], fit_payload, make_customer_headers(customer["id"])
        ),
        expected_status=201,
    )
    assert created["status"] == "RESERVED"
    assert get_sailing(sailing["id"])["reserved_vehicle_feet"] == 120
