"""Dispatch booking sweep, weather posture gating, and the weather cascade."""
from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    carry_flight_to_manifest_closed,
    check_in_booking,
    close_manifest,
    confirm_booking,
    create_booking,
    create_flight,
    dispatch_flight,
    get_base,
    get_booking,
    get_flight,
    list_credits_for_booking,
    open_boarding,
    passenger_entry,
    pilot_ack,
    set_clock,
    setup_ops_env,
    TEST_USERS,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_weather_observation_payload
from test_helpers.fixtures import create_season

DISP = TEST_USERS["dispatcher_headers"]
DISP2 = TEST_USERS["dispatcher_2_headers"]
AGENT = TEST_USERS["booking_agent_headers"]


def test_dispatch_marks_no_show_and_expires_held(api):
    """PRD §3.7: "Dispatch stamps `actual_departure_utc` with the current
    instant, records `dispatched_by_user_id`, and cleans house: bookings
    still in CONFIRMED become NO_SHOW — the entire `paid_cents` is retained
    as `retained_fee_cents` with no refund and no credit — and bookings still
    in HELD become EXPIRED."
    PRD §3.7: "A successful close freezes `manifested_fuel_lb`,
    `actual_gross_weight_lb`, `actual_cg_in`, and
    `manifested_passenger_count` — the count of checked-in passengers on the
    manifested bookings — moves every CHECKED_IN booking of the flight to
    MANIFESTED, and increments the flight's `version` by one."

    Design: Corner/state_machines/dispatch_marks_no_show_and_expires_held
    """
    env = setup_ops_env()
    flight = create_flight(env, "2026-08-03T14:00:00Z")
    b1 = create_booking(flight["id"], [passenger_entry("P0", 150)],
                        contact_name="A", contact_email="a@x.com")
    b2 = create_booking(flight["id"], [passenger_entry("P1", 150)],
                        contact_name="B", contact_email="b@x.com")
    b3 = create_booking(flight["id"], [passenger_entry("P2", 150)],
                        contact_name="C", contact_email="c@x.com")
    confirm_booking(b1["id"], b1["quoted_total_cents"])
    confirm_booking(b2["id"], b2["quoted_total_cents"])
    check_in_booking(b1["id"], 150)  # only B1's passenger checks in

    pilot_ack(flight["id"], env["pilot"]["id"])  # while SCHEDULED
    open_boarding(flight["id"])
    closed = close_manifest(flight["id"])
    assert closed["manifested_passenger_count"] == 1

    set_clock("2026-08-03T14:00:00Z")
    dispatched = dispatch_flight(flight["id"], dispatcher=DISP2)
    assert dispatched["status"] == "DISPATCHED"
    # NO_SHOW / EXPIRED bookings release their seats; only MANIFESTED B1
    # still counts toward seats_booked.
    assert dispatched["seats_booked"] == 1

    b1_after = get_booking(b1["id"])
    assert b1_after["status"] == "MANIFESTED", "manifested bookings untouched"

    b2_after = get_booking(b2["id"])
    assert b2_after["status"] == "NO_SHOW"
    assert b2_after["retained_fee_cents"] == 25000
    assert b2_after["refunded_card_cents"] == 0
    assert b2_after["credited_cents"] == 0

    b3_after = get_booking(b3["id"])
    assert b3_after["status"] == "EXPIRED"


def _setup_weather_hold_scenario(api):
    """MANIFEST_CLOSED flight (zero passengers) departing 15:30 — outside the
    adverse observation window [13:55, 14:55) — with posture WEATHER_HOLD at
    14:00. Returns (env, flight_id)."""
    env = setup_ops_env(clock="2026-08-03T13:00:00Z")
    flight = create_flight(env, "2026-08-03T15:30:00Z")
    pilot_ack(flight["id"], env["pilot"]["id"])
    open_boarding(flight["id"])
    close_manifest(flight["id"])
    # Adverse: ceiling 800 < default minimum 1000; valid [13:55, 14:55).
    validate_success(
        api.create_weather_observation(
            create_weather_observation_payload(
                env["base"]["id"], "2026-08-03T13:55:00Z",
                ceiling_ft=800, visibility_sm=5, wind_kt=10,
            ),
            DISP,
        ),
        expected_status=201,
    )
    set_clock("2026-08-03T14:00:00Z")
    return env, flight["id"]


def test_dispatch_rejected_while_base_in_weather_hold(api):
    """PRD §3.2: "Posture gates two later operations: opening boarding and
    dispatch both refuse while the base sits in WEATHER_HOLD, rejected with
    `ERR_WEATHER_HOLD_ACTIVE`."
    PRD §3.2: "every flight of that base in SCHEDULED, DELAYED, BOARDING, or
    MANIFEST_CLOSED whose `scheduled_departure_utc` falls within the window
    from `observed_at` inclusive to `validity_until` exclusive is cancelled
    to CANCELLED_WEATHER with `cancel_reason` WEATHER"

    Design: Difficulty/cross_entity_state_dependency/dispatch_gated_by_base_weather_posture
    """
    env, flight_id = _setup_weather_hold_scenario(api)
    assert get_base(env["base"]["id"])["posture"] == "WEATHER_HOLD"
    # The 15:30 departure is outside [13:55, 14:55), so no cancellation.
    assert get_flight(flight_id)["status"] == "MANIFEST_CLOSED"

    resp = api.flight_event(flight_id, {"event_type": "DISPATCH"}, DISP2)
    validate_error(resp, ApiErrorId.ERR_WEATHER_HOLD_ACTIVE)


def test_dispatch_succeeds_after_observation_validity_expires(api):
    """PRD §3.2: "Posture is WEATHER_HOLD exactly when that observation
    exists, is adverse, and now is strictly before its `validity_until`; in
    every other case posture is NORMAL."
    PRD §3.2: "When a newer non-adverse observation becomes governing, or the
    adverse observation's validity passes, the base returns WEATHER_HOLD →
    NORMAL — but nothing restores the cancelled flights; that is a deliberate
    one-way door."
    PRD §3.7: "Dispatch stamps `actual_departure_utc` with the current
    instant, records `dispatched_by_user_id`"

    Design: Difficulty/cross_entity_state_dependency/dispatch_gated_by_base_weather_posture
    """
    env, flight_id = _setup_weather_hold_scenario(api)
    validate_error(
        api.flight_event(flight_id, {"event_type": "DISPATCH"}, DISP2),
        ApiErrorId.ERR_WEATHER_HOLD_ACTIVE,
    )

    # validity_until 14:55 has passed by 15:10 -> posture NORMAL.
    set_clock("2026-08-03T15:10:00Z")
    assert get_base(env["base"]["id"])["posture"] == "NORMAL"

    dispatched = dispatch_flight(flight_id, dispatcher=DISP2)
    assert dispatched["status"] == "DISPATCHED"
    assert_instant_equals(dispatched["actual_departure_utc"],
                          "2026-08-03T15:10:00Z", "actual_departure_utc")
    assert dispatched["dispatched_by_user_id"] == "disp-2"


def test_open_boarding_blocked_during_weather_hold(api):
    """PRD §3.2: "Posture gates two later operations: opening boarding and
    dispatch both refuse while the base sits in WEATHER_HOLD, rejected with
    `ERR_WEATHER_HOLD_ACTIVE`."
    PRD §3.2: "Posture is WEATHER_HOLD exactly when that observation exists,
    is adverse, and now is strictly before its `validity_until`; in every
    other case posture is NORMAL."

    Design: Corner/validations/open_boarding_blocked_during_weather_hold
    """
    env = setup_ops_env(clock="2026-08-03T14:00:00Z")
    flight = create_flight(env, "2026-08-03T16:00:00Z")
    # Adverse observation valid [15:00, 16:00); the 16:00 departure sits
    # outside the half-open cancellation window, so the flight survives.
    validate_success(
        api.create_weather_observation(
            create_weather_observation_payload(
                env["base"]["id"], "2026-08-03T15:00:00Z",
                ceiling_ft=800, visibility_sm=5, wind_kt=10,
            ),
            DISP,
        ),
        expected_status=201,
    )
    set_clock("2026-08-03T15:30:00Z")
    assert get_flight(flight["id"])["status"] == "SCHEDULED"

    resp = api.flight_event(flight["id"], {"event_type": "OPEN_BOARDING"}, DISP)
    validate_error(resp, ApiErrorId.ERR_WEATHER_HOLD_ACTIVE)

    # At 16:00 now == validity_until: strict-< fails, posture NORMAL.
    set_clock("2026-08-03T16:00:00Z")
    boarded = open_boarding(flight["id"])
    assert boarded["status"] == "BOARDING"


def test_weather_posture_latest_observation_wins(api):
    """PRD §3.2: "The governing observation is the one with the greatest
    `observed_at` at or before now, ties broken by the greatest `created_at`.
    Posture is WEATHER_HOLD exactly when that observation exists, is adverse,
    and now is strictly before its `validity_until`; in every other case
    posture is NORMAL."
    PRD §3.2: "When a newer non-adverse observation becomes governing, or the
    adverse observation's validity passes, the base returns WEATHER_HOLD →
    NORMAL — but nothing restores the cancelled flights; that is a deliberate
    one-way door."

    Design: Corner/calculations/weather_posture_latest_observation_wins
    """
    set_clock("2026-08-03T12:00:00Z")
    from test_helpers.fixtures import create_base
    base = create_base()

    o1 = validate_success(
        api.create_weather_observation(
            create_weather_observation_payload(
                base["id"], "2026-08-03T11:30:00Z",
                ceiling_ft=800, visibility_sm=5, wind_kt=10,
            ),
            DISP,
        ),
        expected_status=201,
    )
    assert o1["adverse"] is True
    # 12:00 < validity 12:30 -> HOLD.
    assert get_base(base["id"])["posture"] == "WEATHER_HOLD"

    o2 = validate_success(
        api.create_weather_observation(
            create_weather_observation_payload(
                base["id"], "2026-08-03T11:45:00Z",
                ceiling_ft=5000, visibility_sm=10, wind_kt=8,
            ),
            DISP,
        ),
        expected_status=201,
    )
    assert o2["adverse"] is False
    # The 11:45 observation supersedes the still-valid 11:30 one.
    assert get_base(base["id"])["posture"] == "NORMAL"


def _setup_weather_cascade(api):
    """CONFIRMED booking (1 pax, quote 30000 under the 12000-bps PEAK season)
    on a flight departing 13:00; clock 12:00. Returns (env, flight, booking)."""
    env = setup_ops_env(clock="2026-08-03T12:00:00Z")
    create_season(label="PEAK", start_date="2026-06-01", end_date="2026-09-01",
                  multiplier_bps=12000)
    flight = create_flight(env, "2026-08-03T13:00:00Z")
    booking = create_booking(flight["id"], [passenger_entry("P0", 150)])
    # 25000 * 1.20 season; load 0% parity; Monday weekday.
    assert booking["quoted_total_cents"] == 30000
    confirm_booking(booking["id"], 30000)
    return env, flight, booking


def _post_adverse_observation(api, base_id):
    return validate_success(
        api.create_weather_observation(
            create_weather_observation_payload(
                base_id, "2026-08-03T12:30:00Z",
                ceiling_ft=800, visibility_sm=5, wind_kt=10,
            ),
            DISP,
        ),
        expected_status=201,
    )


def test_adverse_observation_cancels_in_window_flight(api):
    """PRD §3.2: "When a newly posted adverse observation becomes the
    governing one, the base flips NORMAL → WEATHER_HOLD and the weather
    cascade fires: every flight of that base in SCHEDULED, DELAYED, BOARDING,
    or MANIFEST_CLOSED whose `scheduled_departure_utc` falls within the
    window from `observed_at` inclusive to `validity_until` exclusive is
    cancelled to CANCELLED_WEATHER with `cancel_reason` WEATHER, and the
    booking cascade of §3.8 runs on each."
    PRD §3.8: "the bookings move the same way: HELD bookings become EXPIRED
    with no refund; CONFIRMED and CHECKED_IN bookings become CREDITED, their
    `credited_cents` set to `paid_cents`, and a `RebookingCredit` is minted
    for `paid_cents` plus `credits_applied_cents`"

    Design: Difficulty/transitive_cascade/weather_observation_cancellation_cascade
    """
    env, flight, booking = _setup_weather_cascade(api)
    obs = _post_adverse_observation(api, env["base"]["id"])
    assert obs["adverse"] is True  # ceiling 800 < 1000

    after = get_flight(flight["id"])
    # 13:00 departure is inside [12:30, 13:30).
    assert after["status"] == "CANCELLED_WEATHER"
    assert after["cancel_reason"] == "WEATHER"

    b_after = get_booking(booking["id"])
    assert b_after["status"] == "CREDITED"
    assert b_after["credited_cents"] == 30000


def test_weather_cascade_credits_booking_and_holds_posture(api):
    """PRD §3.8: "the bookings move the same way: HELD bookings become
    EXPIRED with no refund; CONFIRMED and CHECKED_IN bookings become
    CREDITED, their `credited_cents` set to `paid_cents`, and a
    `RebookingCredit` is minted for `paid_cents` plus
    `credits_applied_cents`"
    PRD §3.8: "`issued_at` stamps the logical clock at minting, and
    `expires_at` is exactly 365 days later"
    PRD §3.2: "A base's `posture` is computed on read, never stored."

    Design: Difficulty/transitive_cascade/weather_observation_cancellation_cascade
    """
    env, flight, booking = _setup_weather_cascade(api)
    _post_adverse_observation(api, env["base"]["id"])

    credits = list_credits_for_booking(booking["id"])
    assert len(credits) == 1
    # paid 30000 + credits_applied 0 minted at logical now 12:00.
    assert credits[0]["amount_cents"] == 30000
    assert credits[0]["status"] == "ISSUED"
    assert_instant_equals(credits[0]["expires_at"], "2027-08-03T12:00:00Z",
                          "credit expires_at")

    set_clock("2026-08-03T12:45:00Z")
    # 12:45 < validity 13:30 and the 12:30 observation is governing.
    assert get_base(env["base"]["id"])["posture"] == "WEATHER_HOLD"
