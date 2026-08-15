"""Weight-and-balance: provisional estimate vs final manifest, CG envelope."""
from test_helpers import (
    ApiErrorId,
    assert_cg,
    check_in_booking,
    close_manifest,
    confirm_booking,
    create_booking,
    create_flight,
    get_booking,
    get_flight,
    is_valid_uuid,
    list_passengers_for_booking,
    open_boarding,
    passenger_entry,
    setup_ops_env,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

DISP = TEST_USERS["dispatcher_headers"]
AGENT = TEST_USERS["booking_agent_headers"]


def _setup_four_pax_boarding(api, declared=180, actuals=(200, 180, 150, 150),
                             departure="2026-08-03T14:00:00Z"):
    """Flight in BOARDING with one CONFIRMED 4-passenger booking, all checked in.

    Returns (env, flight_id, booking_id).
    """
    env = setup_ops_env()
    flight = create_flight(env, departure)
    booking = create_booking(
        flight["id"], [passenger_entry(f"P{i}", declared) for i in range(4)]
    )
    confirm_booking(booking["id"], booking["quoted_total_cents"])
    check_in_booking(booking["id"], list(actuals))
    open_boarding(flight["id"])
    return env, flight["id"], booking["id"]


def test_manifest_estimate_counts_declared_plus_allowance_with_full_fuel(api):
    """PRD §3.5: "The estimate adds the aircraft's `empty_weight_lb`, a
    five-pound allowance on top of each passenger's `declared_weight_lb`
    across this flight's bookings in HELD, CONFIRMED, or CHECKED_IN including
    the new booking's own passengers, and the route's full
    `fuel_required_lb` — the provisional estimate never trims fuel, which is
    precisely how it diverges from the final manifest of §3.7."

    Design: Difficulty/dual_variant_calc/manifest_provisional_estimate_vs_final_actual
    """
    env = setup_ops_env()
    flight = create_flight(env, "2026-08-03T14:00:00Z")
    booking = create_booking(
        flight["id"], [passenger_entry(f"P{i}", 180) for i in range(4)]
    )
    # Provisional variant: 1500 + 4*(180+5) + 300 (full planned fuel).
    estimate = get_flight(flight["id"])["estimated_gross_weight_lb"]
    assert estimate == 2540, f"provisional estimate: expected 2540, got {estimate}"

    # Finish the lifecycle so both variants are exercised on this flight.
    confirm_booking(booking["id"], booking["quoted_total_cents"])
    check_in_booking(booking["id"], [200, 180, 150, 150])
    open_boarding(flight["id"])
    closed = close_manifest(flight["id"])
    assert closed["status"] == "MANIFEST_CLOSED"
    assert estimate != closed["actual_gross_weight_lb"], (
        "identical passenger set, two valid algorithms, different pounds"
    )


def test_final_manifest_uses_actual_weights_and_trims_fuel(api):
    """PRD §3.7: "First, passenger weight is summed from `actual_weight_lb`
    over the checked-in passengers of this flight's CHECKED_IN bookings — the
    final manifest uses scale weights with no allowance, unlike the
    estimate."
    PRD §3.7: "Third, `manifested_fuel_lb` is the smaller of the route's
    `fuel_required_lb` and the fuel budget — fuel is trimmed to fit, never
    the passengers."
    PRD §3.7: "Seventh, `actual_cg_in` is that moment divided by the gross
    weight, rounded half-up to two decimal places, and must sit inside the
    envelope from `cg_forward_limit_in` to `cg_aft_limit_in` with both bounds
    inclusive, else `ERR_CG_OUT_OF_ENVELOPE`."

    Design: Difficulty/dual_variant_calc/manifest_provisional_estimate_vs_final_actual
    """
    env, flight_id, booking_id = _setup_four_pax_boarding(api)
    closed = close_manifest(flight_id)
    assert closed["status"] == "MANIFEST_CLOSED"
    # Final variant over the SAME passengers: pax 200+180+150+150 == 680;
    # fuel budget 2600-1500-680 == 420 -> manifested min(300, 420) == 300;
    # gross 1500+680+300 == 2480.
    assert closed["manifested_fuel_lb"] == 300
    assert closed["actual_gross_weight_lb"] == 2480
    # moment = 82500 + 200*40 + 180*40 + 150*80 + 150*80 + 300*60 = 139700
    # CG = round_half_up(139700 / 2480, 2) == 56.33
    assert_cg(closed["actual_cg_in"], 56.33)
    assert closed["manifested_passenger_count"] == 4


def test_manifest_fuel_trims_against_mtow_budget(api):
    """PRD §3.7: "Second, the fuel budget is what remains of
    `max_takeoff_weight_lb` after subtracting `empty_weight_lb` and that
    passenger weight."
    PRD §3.7: "Third, `manifested_fuel_lb` is the smaller of the route's
    `fuel_required_lb` and the fuel budget — fuel is trimmed to fit, never
    the passengers."

    Design: Difficulty/combinatorial_formula/manifest_fuel_pax_circular_pinned_order
    """
    env = setup_ops_env()
    flight = create_flight(env, "2026-08-03T14:00:00Z")
    booking = create_booking(
        flight["id"], [passenger_entry(f"P{i}", 250) for i in range(3)]
    )
    confirm_booking(booking["id"], booking["quoted_total_cents"])
    check_in_booking(booking["id"], [280, 270, 270])
    open_boarding(flight["id"])
    closed = close_manifest(flight["id"])
    # pax 820 -> fuel budget 2600-1500-820 == 280 -> manifested min(300, 280).
    assert closed["manifested_fuel_lb"] == 280, (
        "fuel adapts to passengers, not vice versa"
    )


def test_manifest_gross_recomputed_after_fuel_trim(api):
    """PRD §3.7: "Fifth, `actual_gross_weight_lb` — empty weight plus
    passenger weight plus manifested fuel — must not exceed
    `max_takeoff_weight_lb`, equality allowed, else
    `ERR_GROSS_WEIGHT_EXCEEDED`."
    PRD §3.7: "A successful close freezes `manifested_fuel_lb`,
    `actual_gross_weight_lb`, `actual_cg_in`, and
    `manifested_passenger_count` — the count of checked-in passengers on the
    manifested bookings — moves every CHECKED_IN booking of the flight to
    MANIFESTED, and increments the flight's `version` by one."

    Design: Difficulty/combinatorial_formula/manifest_fuel_pax_circular_pinned_order
    """
    env = setup_ops_env()
    flight = create_flight(env, "2026-08-03T14:00:00Z")
    booking = create_booking(
        flight["id"], [passenger_entry(f"P{i}", 250) for i in range(3)]
    )
    confirm_booking(booking["id"], booking["quoted_total_cents"])
    check_in_booking(booking["id"], [280, 270, 270])
    open_boarding(flight["id"])
    closed = close_manifest(flight["id"])
    assert closed["status"] == "MANIFEST_CLOSED"
    # Gross is recomputed AFTER the trim: 1500 + 820 + 280 == 2600 == MTOW,
    # and equality is allowed.
    assert closed["actual_gross_weight_lb"] == 2600
    # moment = 82500 + 280*40 + 270*40 + 270*80 + 280*60 = 142900
    # CG = round_half_up(142900 / 2600, 2) == 54.96
    assert_cg(closed["actual_cg_in"], 54.96)
    assert get_booking(booking["id"])["status"] == "MANIFESTED"


def test_cg_inclusive_envelope_boundary(api):
    """PRD §3.7: "Seventh, `actual_cg_in` is that moment divided by the gross
    weight, rounded half-up to two decimal places, and must sit inside the
    envelope from `cg_forward_limit_in` to `cg_aft_limit_in` with both bounds
    inclusive, else `ERR_CG_OUT_OF_ENVELOPE`."
    PRD §2.8: "Two windows are instead inclusive at both bounds: the rolling
    complaint-quota window, and the center-of-gravity envelope."

    Design: Corner/calculations/cg_inclusive_envelope_boundary
    """
    env = setup_ops_env()
    from test_helpers.fixtures import create_aircraft
    a1 = create_aircraft(tail_number="N1", cg_aft_limit_in=54.25)
    a2 = create_aircraft(tail_number="N2", cg_aft_limit_in=54.24)
    f1 = create_flight(env, "2026-08-03T14:00:00Z", aircraft=a1)
    f2 = create_flight(env, "2026-08-04T14:00:00Z", aircraft=a2)

    for flight in (f1, f2):
        booking = create_booking(flight["id"], [passenger_entry("PX", 200)])
        confirm_booking(booking["id"], booking["quoted_total_cents"])
        check_in_booking(booking["id"], 200)
        open_boarding(flight["id"])

    # One pax 200 lb at seat 0 (arm 40): moment 82500+8000+300*60 == 108500,
    # gross 2000, CG == 54.25 exactly.
    closed = close_manifest(f1["id"])
    assert closed["status"] == "MANIFEST_CLOSED"
    assert closed["actual_gross_weight_lb"] == 2000
    assert_cg(closed["actual_cg_in"], 54.25)  # == aft limit 54.25, inclusive

    resp = api.close_manifest(
        f2["id"],
        {"expected_flight_version": get_flight(f2["id"])["version"]},
        DISP,
    )
    validate_error(resp, ApiErrorId.ERR_CG_OUT_OF_ENVELOPE)
    after = get_flight(f2["id"])
    assert after["status"] == "BOARDING"
    assert after["actual_cg_in"] is None, "failed close freezes nothing"


def test_booking_estimate_gate_rejects_overweight(api):
    """PRD §3.5: "A total above `max_takeoff_weight_lb` is rejected with
    `ERR_GROSS_WEIGHT_EXCEEDED`; a total exactly at the limit is allowed."
    PRD §3.5: "Two gates guard the create, evaluated after existence and in
    this order: the provisional weight estimate, then seat capacity."

    Design: Corner/validations/booking_estimate_gate_rejects_overweight
    """
    env = setup_ops_env()
    flight = create_flight(env, "2026-08-03T14:00:00Z")

    # Estimate 1500 + 4*195 + 300 == 2580 <= 2600 -> allowed.
    ok = create_booking(
        flight["id"], [passenger_entry(f"P{i}", 190) for i in range(4)],
        contact_name="A", contact_email="a@x.com",
    )
    assert is_valid_uuid(ok["id"])

    # Candidate 4 x 250: estimate 1500 + 780 + 1020 + 300 == 3600 > 2600.
    resp = api.create_booking(
        {
            "flight_id": flight["id"],
            "contact_name": "B",
            "contact_email": "b@x.com",
            "passengers": [passenger_entry(f"P{i}", 250) for i in range(4, 8)],
        },
        AGENT,
    )
    validate_error(resp, ApiErrorId.ERR_GROSS_WEIGHT_EXCEEDED)

    bookings, meta = validate_paginated(
        api.list_bookings(AGENT, params={"flight_id": flight["id"]})
    )
    assert meta["total_count"] == 1, "rejected create persists nothing"


def test_close_manifest_fuel_below_minimum(api):
    """PRD §3.7: "Fourth, the trimmed fuel must be at least the minimum:
    `fuel_required_lb` scaled by sixty percent, rounded half-up to whole
    pounds; falling short is rejected with `ERR_FUEL_BELOW_MINIMUM`."

    Design: Corner/validations/close_manifest_fuel_below_minimum
    """
    env = setup_ops_env()
    flight = create_flight(env, "2026-08-03T14:00:00Z")
    booking = create_booking(
        flight["id"], [passenger_entry(f"P{i}", 150) for i in range(4)]
    )
    confirm_booking(booking["id"], booking["quoted_total_cents"])
    check_in_booking(booking["id"], [235, 235, 235, 235])
    open_boarding(flight["id"])

    # pax 940 -> fuel budget 2600-1500-940 == 160 -> manifested 160, but
    # min fuel is round_half_up(300 * 0.6) == 180 -> rejected.
    resp = api.close_manifest(
        flight["id"],
        {"expected_flight_version": get_flight(flight["id"])["version"]},
        DISP,
    )
    validate_error(resp, ApiErrorId.ERR_FUEL_BELOW_MINIMUM)
    after = get_flight(flight["id"])
    assert after["status"] == "BOARDING"
    assert after["manifested_fuel_lb"] is None, "no freeze on failure"


def test_close_manifest_from_scheduled_rejected(api):
    """PRD §3.7: "Closing the manifest is the weight-and-balance reckoning,
    an OCC-guarded write requiring `expected_flight_version` (§2.6) from
    BOARDING, and it evaluates in a pinned order because the fuel and weight
    figures couple."
    PRD §2.9: "6. **State** — the target resource is in a state that permits
    the requested transition; terminal states reject every transition.
    Failure: `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/close_manifest_from_scheduled_rejected
    """
    env = setup_ops_env()
    flight = create_flight(env, "2026-08-03T14:00:00Z")
    # OCC version matches (captured at creation); the from-state gate rejects.
    resp = api.close_manifest(
        flight["id"], {"expected_flight_version": flight["version"]}, DISP
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_flight(flight["id"])
    assert after["status"] == "SCHEDULED"
    assert after["actual_gross_weight_lb"] is None
