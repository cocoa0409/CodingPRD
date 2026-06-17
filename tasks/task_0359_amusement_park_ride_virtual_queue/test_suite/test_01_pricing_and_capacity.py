"""Calculation tests: slot capacity, posted wait, and Lightning Lane pricing.

Covers the dual-variant price/capacity calculations and the combinatorial
price/capacity formulas from the difficulty index, plus the corner-index
calculation correctness instances.
"""
from test_helpers import (
    validate_success,
    create_park, set_clock, create_ride, create_window, create_guest, create_plan,
    book_vq, setup_park_ride_window, setup_loaded_ride_for_peak_price,
    make_park_admin_headers, make_ride_operator_headers, make_guest_headers, api_client,
)

ADMIN = make_park_admin_headers()
OPERATOR = make_ride_operator_headers()


# ----------------------------------------------------------------------
# return_window_slot_capacity
# ----------------------------------------------------------------------

def test_slot_capacity_full_hour_window(api):
    """PRD §3.1: "take the window's length in whole minutes ... multiply the
    ride's `hourly_throughput` by that length divided by 60, multiply again by
    the virtual-queue supply fraction of 0.40 ... and floor the result to a whole
    number of slots."

    A 60-min window on throughput 100 -> floor(100 * 1.0 * 0.40) = 40.

    Design: Corner/calculations/computed_slot_capacity_full_hour
    """
    park = create_park()
    ride = create_ride(park["id"], hourly_throughput=100)
    resp = api.create_return_window(
        ride["id"],
        {"window_start_utc": "2026-06-15T10:00:00.000Z",
         "window_end_utc": "2026-06-15T11:00:00.000Z"},
        ADMIN,
    )
    data = validate_success(resp, expected_status=201)
    assert data["slot_capacity"] == 40, f"expected 40 slots, got {data['slot_capacity']}"


def test_slot_capacity_truncates_minutes_then_floors_product(api):
    """PRD §3.1: "take the window's length in whole minutes ... multiply the
    ride's `hourly_throughput` by that length divided by 60, multiply again by
    the virtual-queue supply fraction of 0.40 ... and floor the result to a whole
    number of slots."

    A 90-min window on throughput 100 -> floor(100 * (90/60) * 0.40) = floor(60.0) = 60.

    Design: Difficulty/combinatorial_formula/slot_capacity_minute_truncation_then_floor_order
    """
    park = create_park()
    ride = create_ride(park["id"], hourly_throughput=100, name="RT")
    resp = api.create_return_window(
        ride["id"],
        {"window_start_utc": "2026-06-15T10:00:00.000Z",
         "window_end_utc": "2026-06-15T11:30:00.000Z"},
        ADMIN,
    )
    data = validate_success(resp, expected_status=201)
    assert data["slot_capacity"] == 60, f"expected 60 slots, got {data['slot_capacity']}"
    assert data["window_status"] == "OPEN"


def test_slot_capacity_floors_to_zero_for_short_window(api):
    """PRD §3.1: "A window so short that this raw figure is below 1 floors to a
    `slot_capacity` of 0; such a window is still created but accepts no
    virtual-queue bookings from the outset, behaving as exhausted-equivalent while
    remaining distinct from an expired window."

    10-min window on throughput 10 -> floor(10 * (10/60) * 0.40) = floor(0.666) = 0.

    Design: Corner/entities/zero_capacity_window_computed_to_zero
    """
    park = create_park()
    ride = create_ride(park["id"], hourly_throughput=10, name="R10")
    resp = api.create_return_window(
        ride["id"],
        {"window_start_utc": "2026-06-15T10:00:00.000Z",
         "window_end_utc": "2026-06-15T10:10:00.000Z"},
        ADMIN,
    )
    data = validate_success(resp, expected_status=201)
    assert data["slot_capacity"] == 0, f"expected 0 slots, got {data['slot_capacity']}"
    assert data["window_status"] == "OPEN"


# ----------------------------------------------------------------------
# posted_wait_estimate
# ----------------------------------------------------------------------

def test_posted_wait_open_baseline(api):
    """PRD §3.8: "standby demand is the ride's `booked_slot_count` plus a baseline
    of 20 notional standby guests, and the posted wait is that demand divided by
    the ride's `hourly_throughput`, multiplied by 60 to convert hours to minutes,
    then rounded up to the next whole minute."

    Fresh ride: booked_slot_count 0, throughput 100 -> ceil((0+20)/100*60) = ceil(12.0) = 12.

    Design: Corner/calculations/computed_posted_wait_open_baseline
    """
    park = create_park()
    resp = api.create_ride(park["id"], {"name": "R", "hourly_throughput": 100}, ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["posted_wait_minutes"] == 12, \
        f"expected 12 minutes, got {data['posted_wait_minutes']}"


def test_posted_wait_recomputes_after_booking(api):
    """PRD §3.8: "standby demand is the ride's `booked_slot_count` plus a baseline
    of 20 notional standby guests, and the posted wait is that demand divided by
    the ride's `hourly_throughput`, multiplied by 60 to convert hours to minutes,
    then rounded up to the next whole minute."

    After one VIRTUAL_QUEUE booking: booked_slot_count 1, throughput 100 ->
    ceil((1+20)/100*60) = ceil(12.6) = 13.

    Design: Corner/cross_cutting_complexity_layers/derived_booked_slot_count_after_confirm
    """
    park, ride, window = setup_park_ride_window(hourly_throughput=100)
    guest = create_guest(park["id"], full_name="G1")
    book_vq(ride["id"], guest["id"], window["id"], window["version"])
    resp = api.get_ride(ride["id"], ADMIN)
    data = validate_success(resp)
    assert data["booked_slot_count"] == 1, f"expected booked_slot_count 1, got {data['booked_slot_count']}"
    assert data["posted_wait_minutes"] == 13, \
        f"expected 13 minutes, got {data['posted_wait_minutes']}"


def test_posted_wait_zero_when_ride_down(api):
    """PRD §3.8: "A ride that is not operating posts zero: when the ride's
    `operational_status` is `DOWN` or `CLOSED`, `posted_wait_minutes` is 0
    regardless of its booked load, serving as a not-operating sentinel."

    Design: Difficulty/dual_variant_calc/posted_wait_operating_vs_down_on_ride
    """
    park, ride, window = setup_park_ride_window(hourly_throughput=100)
    guest = create_guest(park["id"], full_name="G1")
    book_vq(ride["id"], guest["id"], window["id"], window["version"])
    resp = api.declare_down(ride["id"], OPERATOR)
    data = validate_success(resp)
    assert data["operational_status"] == "DOWN"
    assert data["posted_wait_minutes"] == 0, \
        f"DOWN ride must post 0, got {data['posted_wait_minutes']}"


# ----------------------------------------------------------------------
# lightning_lane_price
# ----------------------------------------------------------------------

def test_lightning_lane_open_flat_price(api):
    """PRD §3.6: "when the posture is `OPEN` the surged figure is simply the base
    with no multiplier ... for a `MULTI_PASS` plan the surged figure is rounded
    half-up to whole cents directly."

    Unloaded ride (ride_load 0 < 0.75 -> OPEN), MULTI_PASS price 1500, surge 2.0
    -> charged_cents = 1500 (no surge).

    Design: Corner/calculations/computed_lightning_lane_open_flat_price
    """
    park = create_park()
    ride = create_ride(park["id"], hourly_throughput=100)
    guest = create_guest(park["id"], full_name="G1")
    plan = create_plan(park["id"], tier="MULTI_PASS", price_cents=1500,
                       max_concurrent_holds=3, surge_multiplier=2.0)
    resp = api.create_lightning_lane_purchase(
        {"park_id": park["id"], "guest_id": guest["id"],
         "ride_id": ride["id"], "plan_id": plan["id"]},
        make_guest_headers(guest["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["charged_cents"] == 1500, f"expected 1500, got {data['charged_cents']}"
    assert data["hold_status"] == "ACTIVE"


def test_lightning_lane_peak_surge_applied(api):
    """PRD §3.6: "the ride contributes a `PEAK` posture when that load is at or
    above the ride-peak-load threshold of 0.75 ... when the posture is `PEAK` the
    base is multiplied by the plan's `surge_multiplier` to give a surged figure ...
    for a `MULTI_PASS` plan the surged figure is rounded half-up to whole cents directly."

    Loaded ride (ride_load 2/2 = 1.0 >= 0.75 -> PEAK), MULTI_PASS base 1500 x surge 2.0
    -> charged_cents = 3000.

    Design: Difficulty/dual_variant_calc/lightning_lane_price_peak_vs_open_on_purchase
    """
    park, ride, window, buyer, plan = setup_loaded_ride_for_peak_price(
        price_cents=1500, surge_multiplier=2.0, tier="MULTI_PASS",
    )
    resp = api.create_lightning_lane_purchase(
        {"park_id": park["id"], "guest_id": buyer["id"],
         "ride_id": ride["id"], "plan_id": plan["id"]},
        make_guest_headers(buyer["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["charged_cents"] == 3000, f"expected 3000 (1500x2 PEAK surge), got {data['charged_cents']}"
    assert data["hold_status"] == "ACTIVE"


def test_lightning_lane_single_pass_cap_binds_before_round(api):
    """PRD §3.6: "Then the tier cap is applied before rounding: for a `SINGLE_PASS`
    plan the charge is the lesser of the surged figure and the single-pass cap of
    9900 cents, after which it is rounded half-up to whole cents ... The cap is
    therefore taken first and the rounding second — that order is fixed."

    SINGLE_PASS at PEAK: base 8000 x surge 2.0 = 16000, capped to min(16000, 9900) = 9900.

    Design: Difficulty/combinatorial_formula/lightning_lane_price_nested_min_and_branches
    """
    park, ride, window, buyer, plan = setup_loaded_ride_for_peak_price(
        price_cents=8000, surge_multiplier=2.0, tier="SINGLE_PASS",
    )
    # Buyer GB already holds a VQ reservation; the SINGLE_PASS purchase is a
    # separate hold. Buy under the SINGLE_PASS plan as the GA filler (no LL hold yet).
    ga = create_guest(park["id"], full_name="GAbuyer", height_cm=170)
    resp = api.create_lightning_lane_purchase(
        {"park_id": park["id"], "guest_id": ga["id"],
         "ride_id": ride["id"], "plan_id": plan["id"]},
        make_guest_headers(ga["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["charged_cents"] == 9900, \
        f"SINGLE_PASS surged 16000 must cap to 9900, got {data['charged_cents']}"
