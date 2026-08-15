"""Standby lane: the boarding-time clearance sweep (priority bands, exact-fit
boundary, skip-over, zero-remaining walk-ons), validation ordering between
sailing posture and vehicle length, the one-WAITING-entry uniqueness rule,
and the leave-only-from-WAITING rule.

The sweep setups use a 50-ft SMALL vessel in OFF_PEAK: the pinned reservation
allotment is 20 ft (reservation floor), so the standby pool is 30 ft.
"""
from test_helpers import (
    ApiErrorId,
    begin_boarding,
    close_sailing,
    create_customer,
    create_route,
    create_sailing,
    create_standby_entry_payload,
    create_vessel,
    get_sailing,
    get_standby_entry,
    join_standby,
    make_customer_headers,
    setup_open_sailing,
    validate_error,
    validate_success,
)

SMALL_STANDBY_SETUP = dict(
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


def test_standby_sweep_priority_bands_with_skip_over(api):
    """PRD §3.7: "The sweep considers entries still `WAITING`, ranked first by
    priority band — `MEDICAL` highest, then `COMMUTER`, then `STANDARD` — and
    within a band by `queued_at`, earliest first"
    PRD §3.7: "An entry that does not fit stays `WAITING` and the sweep moves
    on: skip-over is allowed, so a small later vehicle, or a walk-on party
    needing zero feet, can still clear behind an oversize one."

    Design: Difficulty/boundary_precision_check/standby_zero_remaining_deck_still_clears_walkons
    """
    setup = setup_open_sailing(**SMALL_STANDBY_SETUP)
    sailing_id = setup["sailing"]["id"]
    assert sailing_id and setup["sailing"]["reserved_deck_allotment_feet"] == 20
    # standby pool: 50 - 20 = 30 feet

    veh_std = create_customer(full_name="Veh Pat", fare_class="STANDARD")
    med_walk = create_customer(full_name="Med Pat", fare_class="STANDARD")
    med_veh = create_customer(full_name="Med Veh", fare_class="STANDARD")

    q1 = join_standby(  # queued first, but STANDARD band
        sailing_id, veh_std, has_vehicle=True, vehicle_length_feet=30,
        passenger_count=1, priority_class="STANDARD",
    )
    q2 = join_standby(  # MEDICAL walk-on
        sailing_id, med_walk, passenger_count=1, priority_class="MEDICAL"
    )
    q3 = join_standby(  # MEDICAL 10-ft vehicle
        sailing_id, med_veh, has_vehicle=True, vehicle_length_feet=10,
        passenger_count=1, priority_class="MEDICAL",
    )

    close_sailing(sailing_id)
    boarding = begin_boarding(sailing_id)
    assert boarding["status"] == "BOARDING"

    # Sweep order: MEDICAL band first (q2 before q3 by queued_at), then q1.
    assert get_standby_entry(q2["id"])["status"] == "CLEARED", (
        "MEDICAL walk-on needs 0 ft <= 30 pool and must clear"
    )
    assert get_standby_entry(q3["id"])["status"] == "CLEARED", (
        "MEDICAL 10-ft vehicle fits the 30-ft pool and must clear"
    )
    assert get_standby_entry(q1["id"])["status"] == "WAITING", (
        "STANDARD 30-ft vehicle exceeds the 20 ft remaining after the MEDICAL "
        "clears; skip-over leaves it WAITING"
    )
    sailing_after = get_sailing(sailing_id)
    assert sailing_after["standby_cleared_feet"] == 10, (
        f"only the 10-ft MEDICAL vehicle cleared: expected 10, got "
        f"{sailing_after['standby_cleared_feet']}"
    )


def test_standby_sweep_exact_fit_and_zero_remaining_walkons(api):
    """PRD §3.7: "An entry clears when both fit — an entry needing exactly the
    remaining footage clears, since the test is "no more than," not "strictly
    less" — moving `WAITING → CALLED → CLEARED` and debiting the running
    counters, with `standby_cleared_feet` and `booked_passengers` recomputed
    on the sailing."
    PRD §3.7: "When no footage remains, only walk-on entries can clear,
    subject to passenger capacity."

    Design: Difficulty/boundary_precision_check/standby_zero_remaining_deck_still_clears_walkons
    """
    setup = setup_open_sailing(**SMALL_STANDBY_SETUP)
    sailing_id = setup["sailing"]["id"]

    exact = create_customer(full_name="Exact Fit", fare_class="STANDARD")
    walk = create_customer(full_name="Walk On", fare_class="STANDARD")
    small = create_customer(full_name="Small Veh", fare_class="STANDARD")

    q1 = join_standby(  # needs exactly the 30-ft pool
        sailing_id, exact, has_vehicle=True, vehicle_length_feet=30,
        passenger_count=1, priority_class="MEDICAL",
    )
    q2 = join_standby(  # walk-on: needs 0 ft
        sailing_id, walk, passenger_count=1, priority_class="MEDICAL"
    )
    q3 = join_standby(  # 1-ft vehicle after the pool is exhausted
        sailing_id, small, has_vehicle=True, vehicle_length_feet=1,
        passenger_count=1, priority_class="STANDARD",
    )

    close_sailing(sailing_id)
    begin_boarding(sailing_id)

    assert get_standby_entry(q1["id"])["status"] == "CLEARED", (
        "an entry needing exactly the remaining 30 feet must clear"
    )
    assert get_standby_entry(q2["id"])["status"] == "CLEARED", (
        "with 0 feet remaining, a walk-on needing 0 feet must still clear"
    )
    assert get_standby_entry(q3["id"])["status"] == "WAITING", (
        "with 0 feet remaining, a 1-ft vehicle cannot clear"
    )
    assert get_sailing(sailing_id)["standby_cleared_feet"] == 30


def test_standby_join_on_closed_sailing_reports_state_over_length(api):
    """PRD §2.11: "When a request fails several rules at once, the error it
    receives is deterministic. Every endpoint evaluates its checks in this
    fixed priority order:" — "5. Sailing posture permits the requested
    ticketing activity — otherwise `ERR_SAILING_NOT_BOOKABLE`." precedes
    "12. Standby vehicle length within the staging limit — otherwise
    `ERR_VEHICLE_LENGTH_EXCEEDS`."
    PRD §3.4: "From that instant no new bookings and no new standby entries
    are accepted — attempts to create either against a sailing that is not
    `OPEN_FOR_BOOKING` are rejected with `ERR_SAILING_NOT_BOOKABLE`."

    Design: Difficulty/priority_pair_validation_conflict/standby_join_state_beats_constraint
    """
    setup = setup_open_sailing(fuel_price_index_cents=200)
    sailing_id = setup["sailing"]["id"]
    close_sailing(sailing_id)  # BOOKING_CLOSED: posture now forbids joins
    customer = create_customer(full_name="Walk On", fare_class="COMMUTER")

    payload = create_standby_entry_payload(
        customer_id=customer["id"], has_vehicle=True, vehicle_length_feet=70,
        passenger_count=1, priority_class="STANDARD",
    )
    resp = api.join_standby_queue(
        sailing_id, payload, make_customer_headers(customer["id"])
    )
    # Both rule 5 (not OPEN_FOR_BOOKING) and rule 12 (70 ft > 60 ft staging
    # limit) are violated; the state error must win.
    validate_error(resp, ApiErrorId.ERR_SAILING_NOT_BOOKABLE)


def test_standby_join_on_unopened_sailing_reports_state_over_length(api):
    """PRD §2.11: "When a request fails several rules at once, the error it
    receives is deterministic. Every endpoint evaluates its checks in this
    fixed priority order:" — "5. Sailing posture permits the requested
    ticketing activity — otherwise `ERR_SAILING_NOT_BOOKABLE`." precedes
    "12. Standby vehicle length within the staging limit — otherwise
    `ERR_VEHICLE_LENGTH_EXCEEDS`."
    PRD §3.6: "standby vehicles longer than 60 feet cannot be staged in the
    lane at all, rejected with `ERR_VEHICLE_LENGTH_EXCEEDS` even though a
    reserved booking may legally carry up to 80 feet."

    Design: Difficulty/priority_pair_validation_conflict/standby_join_state_beats_constraint
    """
    route = create_route(route_code="SEA-BI", crossing_minutes=35, turnaround_minutes=15)
    vessel = create_vessel(vessel_name="MV Kittitas")
    sailing = create_sailing(
        route["id"], vessel["id"], departure_time="2026-09-01T10:00:00Z"
    )  # SCHEDULED: never opened
    customer = create_customer(full_name="Walk On", fare_class="COMMUTER")

    payload = create_standby_entry_payload(
        customer_id=customer["id"], has_vehicle=True, vehicle_length_feet=70,
        passenger_count=1, priority_class="STANDARD",
    )
    resp = api.join_standby_queue(
        sailing["id"], payload, make_customer_headers(customer["id"])
    )
    # SCHEDULED posture (rule 5) and 70-ft vehicle (rule 12) both fail; the
    # state error must win.
    validate_error(resp, ApiErrorId.ERR_SAILING_NOT_BOOKABLE)


def test_second_waiting_entry_same_customer_rejected(api):
    """PRD §3.6: "Two standby-specific constraints apply beyond the shared
    party rules: a customer may hold at most one `WAITING` entry per sailing
    (a second join is `ERR_DUPLICATE`)"

    Design: Corner/validations/duplicate_standby_entry_per_customer
    """
    setup = setup_open_sailing(fuel_price_index_cents=200)
    sailing_id = setup["sailing"]["id"]
    customer = create_customer(full_name="Walk On", fare_class="COMMUTER")

    first = join_standby(sailing_id, customer, passenger_count=1, priority_class="STANDARD")
    assert first["status"] == "WAITING"

    payload = create_standby_entry_payload(
        customer_id=customer["id"], has_vehicle=False, passenger_count=2,
        priority_class="STANDARD",
    )
    resp = api.join_standby_queue(
        sailing_id, payload, make_customer_headers(customer["id"])
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE)


def test_standby_leave_only_from_waiting(api):
    """PRD §3.6: "A waiting customer may leave the lane at any time, moving
    their own entry `WAITING → EXPIRED`; the entry's `customer_id` must match
    the acting `X-User-ID` (else `ERR_NOT_RESOURCE_OWNER`), and only a
    `WAITING` entry may be left this way — attempting to leave from any other
    status is rejected with `ERR_INVALID_STATE`."

    Design: Corner/endpoints/standby_leave_only_from_waiting
    """
    setup = setup_open_sailing(fuel_price_index_cents=200)
    sailing_id = setup["sailing"]["id"]
    customer = create_customer(full_name="Walk On", fare_class="COMMUTER")
    entry = join_standby(sailing_id, customer, passenger_count=1, priority_class="STANDARD")

    headers = make_customer_headers(customer["id"])
    left = validate_success(api.leave_standby_queue(entry["id"], headers))
    assert left["status"] == "EXPIRED", (
        f"leaving a WAITING entry must move it to EXPIRED, got {left['status']}"
    )

    resp = api.leave_standby_queue(entry["id"], headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
