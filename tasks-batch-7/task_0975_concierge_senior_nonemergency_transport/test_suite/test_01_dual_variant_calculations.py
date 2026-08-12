"""Dual-variant calculations: provisional quote vs final settlement, and
forward-looking driver load vs chronological worked actuals."""
from test_helpers import (
    TEST_USERS,
    create_active_rate_card,
    create_booked_ride,
    create_client,
    create_completed_ride,
    create_compliant_driver,
    dispatch_and_accept,
    execute_ride_happy_path,
    get_success_data,
    make_client_headers,
    make_driver_headers,
    set_clock,
    setup_standard_dispatch_env,
    validate_success,
    api_client,
)

COORD = TEST_USERS["coordinator_headers"]


def _setup_quote_ride():
    """ACTIVE STANDARD card, client, ACTIVE driver; ride booked for
    2026-06-01T10:00:00Z with estimates 90 min / 12 mi. Returns (client, driver, ride)."""
    client, driver = setup_standard_dispatch_env(clock="2026-05-20T09:00:00Z")
    ride = create_booked_ride(
        client["id"], scheduled_pickup_at="2026-06-01T10:00:00Z",
        estimated_duration_minutes=90, estimated_distance_miles=12)
    return client, driver, ride


def _complete_quote_ride(ride_id, driver_id):
    """Dispatch, accept, and complete the quote ride with actuals
    60 service min / 10 mi / two closed wait segments of 15 + 10 min."""
    dispatch_and_accept(ride_id, driver_id)
    return execute_ride_happy_path(
        ride_id, driver_id, "2026-06-01T10:00:00Z",
        actual_distance_miles=10, service_minutes=60,
        wait_segments=((0, 15), (60, 70)))


def test_provisional_quote_uses_estimates_with_zero_wait(api):
    """PRD §3.3: "The **provisional quote**, computed at booking and stored as
    `quoted_fare_cents`, feeds the estimated duration and distance with zero
    wait."
    PRD §3.3: "first, the hourly charge is the card's `hourly_rate_cents`
    multiplied by the applicable minutes and divided by sixty, rounded half-up
    to whole cents. Second, the mileage charge is `per_mile_cents` multiplied
    by the applicable miles, with no rounding."

    Design: Difficulty/dual_variant_calc/ride_fare_provisional_vs_final_settlement
    """
    _, _, ride = _setup_quote_ride()
    # 3000 * 90 / 60 = 4500 hourly; 150 * 12 = 1800 mileage; zero wait.
    assert ride["quoted_fare_cents"] == 6300, (
        f"provisional quote must be 6300, got {ride['quoted_fare_cents']}")
    assert ride["status"] == "SCHEDULED"


def test_final_settlement_uses_actuals_and_diverges(api):
    """PRD §3.3: "The **final settlement**, computed at completion and stored
    as `final_fare_cents`, feeds the replayed `service_minutes`, the
    driver-reported `actual_distance_miles`, and the replayed wait total."
    PRD §3.3: "Third, the wait charge is the billable wait — total wait
    minutes minus `included_wait_minutes`, floored at zero — multiplied by
    `wait_per_minute_cents`."
    PRD §3.3: "The two numbers for the same ride may therefore differ even
    though the formula is identical."

    Design: Difficulty/dual_variant_calc/ride_fare_provisional_vs_final_settlement
    """
    _, driver, ride = _setup_quote_ride()
    completed = _complete_quote_ride(ride["id"], driver["id"])
    # 3000 * 60 / 60 = 3000 hourly; 150 * 10 = 1500 mileage; (25 - 10) * 50 = 750 wait.
    assert completed["final_fare_cents"] == 5250, (
        f"final fare must be 5250, got {completed['final_fare_cents']}")
    assert completed["wait_minutes"] == 25
    assert completed["service_minutes"] == 60
    assert completed["final_fare_cents"] != ride["quoted_fare_cents"], (
        "the two variants of one formula must diverge here (6300 vs 5250)")


def _setup_driver_load_day():
    """One driver with a COMPLETED 45-minute morning ride and an ASSIGNED
    90-minute afternoon ride, both picked up on logical today 2026-06-01.
    Returns driver."""
    client, driver = setup_standard_dispatch_env(clock="2026-05-31T09:00:00Z")
    # Ride W: completed with replayed service of 45 minutes.
    create_completed_ride(
        client["id"], driver["id"], "2026-06-01T08:00:00Z",
        estimated_duration_minutes=60, estimated_distance_miles=8,
        actual_distance_miles=8, service_minutes=45)
    # Ride R2: assigned, never started.
    ride_r2 = create_booked_ride(
        client["id"], kind="APPOINTMENT", scheduled_pickup_at="2026-06-01T14:00:00Z",
        estimated_duration_minutes=90, estimated_distance_miles=10)
    dispatch_and_accept(ride_r2["id"], driver["id"])
    set_clock("2026-06-01T12:00:00Z")
    return driver


def test_forward_looking_load_counts_assigned_ride_at_estimate(api):
    """PRD §3.2: "`current_load_minutes` is the forward-looking figure: the sum
    of `estimated_duration_minutes` over the driver's rides whose pickup date
    is the logical today and whose status is `ASSIGNED`, `EN_ROUTE`, `ARRIVED`,
    or `IN_SERVICE`."

    Design: Difficulty/dual_variant_calc/driver_scheduled_load_vs_worked_actuals
    """
    driver = _setup_driver_load_day()
    data = validate_success(api.get_driver(driver["id"], COORD))
    assert data["current_load_minutes"] == 90, (
        f"only the ASSIGNED ride counts, at its 90-minute estimate; got "
        f"{data['current_load_minutes']}")


def test_worked_actuals_count_completed_ride_at_replayed_minutes(api):
    """PRD §3.2: "`day_worked_minutes` is the chronological actuals figure: the
    sum of `service_minutes` over the driver's rides with pickup date today
    that have reached `COMPLETED`."
    PRD §3.2: "The two intentionally diverge — one counts
    planned-but-unfinished work at estimated duration, the other only
    finished work at replayed duration."

    Design: Difficulty/dual_variant_calc/driver_scheduled_load_vs_worked_actuals
    """
    driver = _setup_driver_load_day()
    data = validate_success(api.get_driver(driver["id"], COORD))
    assert data["day_worked_minutes"] == 45, (
        f"only the COMPLETED ride counts, at replayed 45 minutes; got "
        f"{data['day_worked_minutes']}")
    assert data["day_worked_minutes"] != data["current_load_minutes"], (
        "the two load variants must diverge for the same driver-day (45 vs 90)")
