"""River-condition readings: flow banding, weather-hold posture, and the UNSAFE trip
cancellation cascade."""
from test_helpers import validate_success, validate_error
from test_helpers import TEST_USERS
from test_helpers.fixtures import (
    create_trip, setup_open_trip, create_reservation, setup_confirmed_reservation,
)
from test_helpers.factories import create_condition_reading_payload

MGR = TEST_USERS["outfitter_manager_headers"]
RESV = TEST_USERS["reservationist_headers"]
SAFETY = TEST_USERS["safety_officer_headers"]


# ── UNSAFE reading -> full cascade (depth-4 transitive chain) ──

def test_unsafe_reading_cancels_trip_and_refunds(api):
    """PRD §3.7: "it is `UNSAFE` in every other case, that is when `flow_cfs` is below
    `safe_flow_min` or above `marginal_flow_max`."
    PRD §3.7: "An `UNSAFE` reading cancels the trip outright, transitioning it to
    `CANCELLED` and triggering the full trip-cancellation cascade described in §3.9."
    PRD §3.9: "Each such reservation whose `payment_status` is `DEPOSIT_PAID` or `SETTLED`
    moves to `REFUNDED`, and the trip's `deposits_held_cents` is recomputed as the refunds land."

    Design: Difficulty/transitive_cascade/unsafe_reading_cancels_trip_releases_gear_depth4
    """
    ctx = setup_confirmed_reservation(
        api, party_size=1, deposit_cents=3000, with_gear=True, sign=False,
        pay_deposit=True, guest_weight=200, guest_age=29,
    )
    reading = validate_success(
        api.create_condition_reading(create_condition_reading_payload(ctx["trip"]["id"], 4500), SAFETY), 201)
    assert reading["resulting_band"] == "UNSAFE"
    trip = validate_success(api.get_trip(ctx["trip"]["id"], MGR), 200)
    assert trip["status"] == "CANCELLED"
    assert trip["deposits_held_cents"] == 0
    res = validate_success(api.get_reservation(ctx["res"]["id"], RESV), 200)
    assert res["fulfillment_status"] == "CANCELLED"
    assert res["payment_status"] == "REFUNDED"


def test_unsafe_reading_releases_gear_to_inventory(api):
    """PRD §3.9: "Each cancelled reservation's `ASSIGNED` gear assignments move to
    `RELEASED`, each release returning its gear item to `AVAILABLE`."

    Design: Difficulty/transitive_cascade/unsafe_reading_cancels_trip_releases_gear_depth4
    """
    ctx = setup_confirmed_reservation(
        api, party_size=1, deposit_cents=3000, with_gear=True, sign=False,
        pay_deposit=True, guest_weight=200, guest_age=29,
    )
    validate_success(api.create_condition_reading(
        create_condition_reading_payload(ctx["trip"]["id"], 4500), SAFETY), 201)
    gasg = validate_success(api.get_gear_assignment(ctx["gasg"]["id"], RESV), 200)
    assert gasg["status"] == "RELEASED"
    item = validate_success(api.get_gear_item(ctx["pfd"]["id"], RESV), 200)
    assert item["status"] == "AVAILABLE"


# ── MARGINAL reading -> WEATHER_HOLD; confirm blocked ──

def test_marginal_reading_moves_trip_to_weather_hold(api):
    """PRD §3.7: "A `MARGINAL` reading holds the trip: a trip in `OPEN` or `FULL`
    transitions to `WEATHER_HOLD`, and while a trip is on `WEATHER_HOLD` both reservation
    confirmation and check-in are blocked."

    Design: Difficulty/cross_entity_state_dependency/confirm_blocked_when_trip_in_weather_hold
    """
    trip, _, _ = setup_open_trip(api)
    validate_success(api.create_condition_reading(
        create_condition_reading_payload(trip["id"], 3500), SAFETY), 201)  # 3000 < 3500 <= 4000 -> MARGINAL
    trip_after = validate_success(api.get_trip(trip["id"], MGR), 200)
    assert trip_after["status"] == "WEATHER_HOLD"


def test_confirm_blocked_while_trip_in_weather_hold(api):
    """PRD §3.7: "A `MARGINAL` reading holds the trip: a trip in `OPEN` or `FULL`
    transitions to `WEATHER_HOLD`, and while a trip is on `WEATHER_HOLD` both reservation
    confirmation and check-in are blocked."
    PRD §3.2: "The parent trip must be bookable — its `status` must be `OPEN` or `FULL` —
    otherwise `ERR_TRIP_NOT_BOOKABLE`."

    Design: Difficulty/cross_entity_state_dependency/confirm_blocked_when_trip_in_weather_hold
    """
    trip, _, _ = setup_open_trip(api)
    res = create_reservation(api, trip["id"], party_size=2, deposit_cents=6000)
    validate_success(api.create_condition_reading(
        create_condition_reading_payload(trip["id"], 3500), SAFETY), 201)
    validate_error(api.confirm_reservation(res["id"], RESV), "ERR_TRIP_NOT_BOOKABLE")


# ── Corner: SAFE upper-bound inclusive keeps trip OPEN ──

def test_flow_safe_upper_bound_inclusive_keeps_trip_open(api):
    """PRD §3.7: "the band is `SAFE` when `flow_cfs` is greater than or equal to
    `safe_flow_min` and less than or equal to `safe_flow_max`"
    PRD §3.7: "All three named bounds are inclusive: a flow exactly equal to
    `safe_flow_max` is `SAFE`, while the smallest amount above it is `MARGINAL`."

    Design: Corner/calculations/flow_band_safe_upper_bound_inclusive_keeps_trip_open
    """
    trip, _, _ = setup_open_trip(api)  # safe_flow_max default 3000
    reading = validate_success(api.create_condition_reading(
        create_condition_reading_payload(trip["id"], 3000), SAFETY), 201)
    assert reading["resulting_band"] == "SAFE"
    trip_after = validate_success(api.get_trip(trip["id"], MGR), 200)
    assert trip_after["status"] == "OPEN"


# ── Corner: RBAC on condition readings ──

def test_reservationist_cannot_record_condition_reading(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not permitted
    to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/reservationist_cannot_record_condition_reading_returns_forbidden
    """
    trip = create_trip(api, difficulty_class="CLASS_III")
    resp = api.create_condition_reading(create_condition_reading_payload(trip["id"], 1500), RESV)
    validate_error(resp, "ERR_FORBIDDEN_ROLE")
