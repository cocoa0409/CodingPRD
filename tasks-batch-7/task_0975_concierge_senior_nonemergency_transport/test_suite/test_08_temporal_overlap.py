"""Temporal overlap: buffered driver windows vs unbuffered rate-card windows —
touching boundaries never conflict, one unit inside always does."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_booked_ride,
    create_rate_card_payload,
    get_success_data,
    make_driver_headers,
    setup_standard_dispatch_env,
    validate_error,
    validate_success,
    api_client,
)

COORD = TEST_USERS["coordinator_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def _setup_driver_window_rides():
    """One ACTIVE driver; three rides on 2026-06-15: R1 10:00 est 60
    (window [09:30, 11:30)), R2 11:59 est 30 (overlaps by one minute),
    R3 12:00 est 30 (touches exactly). R2 offered first, then R1 offered and
    accepted. Returns (driver, r1, r2, r3, asg2)."""
    client, driver = setup_standard_dispatch_env(clock="2026-06-12T09:00:00Z")
    r1 = create_booked_ride(client["id"], scheduled_pickup_at="2026-06-15T10:00:00Z",
                            estimated_duration_minutes=60)
    r2 = create_booked_ride(client["id"], scheduled_pickup_at="2026-06-15T11:59:00Z",
                            estimated_duration_minutes=30, estimated_distance_miles=5)
    r3 = create_booked_ride(client["id"], scheduled_pickup_at="2026-06-15T12:00:00Z",
                            estimated_duration_minutes=30, estimated_distance_miles=5)
    asg2 = get_success_data(api_client.dispatch_ride(r2["id"], COORD))
    asg1 = get_success_data(api_client.dispatch_ride(r1["id"], COORD))
    get_success_data(api_client.respond_assignment(
        asg1["id"], {"decision": "ACCEPT"}, make_driver_headers(driver["id"])))
    return driver, r1, r2, r3, asg2


def test_buffered_window_one_minute_inside_is_rejected(api):
    """PRD §3.5: "The buffered window a ride occupies on a driver is the
    half-open interval from thirty minutes before its pickup to thirty minutes
    after its estimated end; two occupied windows conflict exactly when each
    starts strictly before the other ends, so windows that merely touch do not
    conflict."
    PRD §3.5: "a newly created buffered-window conflict with
    `ERR_RIDE_OVERLAP_DRIVER`"

    Design: Difficulty/resource_temporal_overlap/driver_buffered_window_touching_vs_overlap
    """
    driver, _, r2, _, asg2 = _setup_driver_window_rides()
    # R2 window [11:29, 12:59) starts strictly before R1's end 11:30.
    resp = api_client.respond_assignment(
        asg2["id"], {"decision": "ACCEPT"}, make_driver_headers(driver["id"]))
    validate_error(resp, ApiErrorId.ERR_RIDE_OVERLAP_DRIVER)
    asg = validate_success(api_client.get_assignment(asg2["id"], COORD))
    assert asg["status"] == "OFFERED"
    ride = validate_success(api_client.get_ride(r2["id"], COORD))
    assert ride["status"] == "DISPATCHING"


def test_buffered_window_touching_exactly_is_accepted(api):
    """PRD §3.5: "two occupied windows conflict exactly when each starts
    strictly before the other ends, so windows that merely touch do not
    conflict."
    PRD §3.5: "A clean acceptance moves the ride to `ASSIGNED`, sets
    `assigned_driver_id`, stamps `responded_at`, and appends an `ACCEPTED`
    event."

    Design: Difficulty/resource_temporal_overlap/driver_buffered_window_touching_vs_overlap
    """
    driver, _, _, r3, _ = _setup_driver_window_rides()
    asg3 = get_success_data(api_client.dispatch_ride(r3["id"], COORD))
    accepted = get_success_data(api_client.respond_assignment(
        asg3["id"], {"decision": "ACCEPT"}, make_driver_headers(driver["id"])))
    assert accepted["status"] == "ACCEPTED"
    ride = validate_success(api_client.get_ride(r3["id"], COORD))
    assert ride["status"] == "ASSIGNED", (
        "R3 window [11:30, 13:00) touches R1's end 11:30 exactly — no conflict")


def _create_three_cards():
    card_a = get_success_data(api_client.create_rate_card(
        create_rate_card_payload(effective_from="2026-01-01", effective_to="2026-07-01"),
        ADMIN))
    card_b = get_success_data(api_client.create_rate_card(
        create_rate_card_payload(effective_from="2026-07-01", effective_to="2027-01-01",
                                 hourly_rate_cents=3200, per_mile_cents=155),
        ADMIN))
    card_c = get_success_data(api_client.create_rate_card(
        create_rate_card_payload(effective_from="2026-06-30", effective_to="2026-12-01",
                                 hourly_rate_cents=3100, per_mile_cents=152),
        ADMIN))
    return card_a, card_b, card_c


def test_rate_card_windows_touching_at_boundary_both_activate(api):
    """PRD §3.3: "Activation requires an internally valid window —
    `effective_from` strictly before `effective_to`, else
    `ERR_RATE_WINDOW_INVALID` — and requires that no other `ACTIVE` card of the
    same `service_class` have a window intersecting this one; windows that
    touch at a boundary do not intersect, and a true intersection is rejected
    with `ERR_RATE_WINDOW_OVERLAP`."
    PRD §2.5: "Two half-open windows that merely touch at a boundary — one
    ending exactly where the next begins — do not intersect."

    Design: Difficulty/resource_temporal_overlap/rate_card_window_touching_vs_overlap
    """
    card_a, card_b, _ = _create_three_cards()
    a = get_success_data(api_client.activate_rate_card(card_a["id"], ADMIN))
    assert a["status"] == "ACTIVE"
    b = get_success_data(api_client.activate_rate_card(card_b["id"], ADMIN))
    assert b["status"] == "ACTIVE", (
        "[2026-01-01, 2026-07-01) and [2026-07-01, 2027-01-01) touch — allowed")


def test_rate_card_window_one_day_inside_is_rejected(api):
    """PRD §3.3: "a true intersection is rejected with
    `ERR_RATE_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/rate_card_window_touching_vs_overlap
    """
    card_a, _, card_c = _create_three_cards()
    get_success_data(api_client.activate_rate_card(card_a["id"], ADMIN))
    resp = api_client.activate_rate_card(card_c["id"], ADMIN)
    # [2026-06-30, 2026-12-01) intersects [2026-01-01, 2026-07-01) on 06-30.
    validate_error(resp, ApiErrorId.ERR_RATE_WINDOW_OVERLAP)
    card = validate_success(api_client.get_rate_card(card_c["id"], ADMIN))
    assert card["status"] == "DRAFT"
