"""Pilot duty ledger: scheduled projection vs actual ledger, limits, fatigue."""
from test_helpers import (
    ApiErrorId,
    create_flight,
    fly_empty_flight,
    get_pilot,
    is_valid_uuid,
    list_duty_days,
    set_clock,
    setup_ops_env,
    TEST_USERS,
    validate_error,
    validate_success,
)

DISP = TEST_USERS["dispatcher_headers"]
DISP2 = TEST_USERS["dispatcher_2_headers"]
OPS = TEST_USERS["ops_admin_headers"]

ROUTE_240 = {
    "route_code": "RD",
    "tier": "STANDARD",
    "duration_minutes": 240,
    "base_seat_price_cents": 10000,
    "fuel_required_lb": 400,
}


def _setup_two_completed_flights(api):
    """One pilot flies F1 08:00-09:30 and F2 13:00-14:30 actual on 2026-08-03
    (scheduled block 240 min each). Returns (env, pilot_id)."""
    env = setup_ops_env(route_overrides=dict(ROUTE_240))
    f1 = create_flight(env, "2026-08-03T08:00:00Z")
    f2 = create_flight(env, "2026-08-03T13:00:00Z")
    pilot_id = env["pilot"]["id"]
    fly_empty_flight(f1["id"], pilot_id,
                     depart_at="2026-08-03T08:00:00Z",
                     complete_at="2026-08-03T09:30:00Z")
    fly_empty_flight(f2["id"], pilot_id,
                     depart_at="2026-08-03T13:00:00Z",
                     complete_at="2026-08-03T14:30:00Z")
    return env, pilot_id


def test_duty_day_projection_counts_completed_flights_at_block_time(api):
    """PRD §3.4: "`flight_minutes_scheduled` sums `duration_minutes` over the
    pilot's flights that UTC date in SCHEDULED, DELAYED, BOARDING,
    MANIFEST_CLOSED, DISPATCHED, or COMPLETED — cancelled flights are
    excluded."
    PRD §3.4: "The chronological variant is the actual ledger, written at
    flight completion: `flight_minutes_actual` gains the whole-minute floor
    of the airborne interval from `actual_departure_utc` to
    `actual_arrival_utc`."

    Design: Difficulty/dual_variant_calc/duty_scheduled_projection_vs_actual_ledger
    """
    env, pilot_id = _setup_two_completed_flights(api)
    rows = list_duty_days(pilot_id, duty_date="2026-08-03")
    assert len(rows) == 1
    # Scheduled-projection variant counts full block times even though both
    # flights completed 150 minutes early: 240 + 240 == 480.
    assert rows[0]["flight_minutes_scheduled"] == 480


def test_assignment_gate_uses_projection_not_actual_ledger(api):
    """PRD §3.4: "The candidate's block time is added, and the sum must be at
    most eight hours; eight hours exactly is permitted, one minute more is
    rejected with `ERR_PILOT_FLIGHT_TIME_EXCEEDED`."
    PRD §3.4: "The chronological variant is the actual ledger, written at
    flight completion: `flight_minutes_actual` gains the whole-minute floor
    of the airborne interval from `actual_departure_utc` to
    `actual_arrival_utc`."

    Design: Difficulty/dual_variant_calc/duty_scheduled_projection_vs_actual_ledger
    """
    env, pilot_id = _setup_two_completed_flights(api)
    rows = list_duty_days(pilot_id, duty_date="2026-08-03")
    # Actual-ledger variant over the same day: 90 + 90 == 180 airborne min.
    assert rows[0]["flight_minutes_actual"] == 180

    # The gate consults the projection (480 + 240 == 720 > 480) even though
    # the actual ledger shows only 180 minutes.
    resp = api.create_flight(
        {
            "base_id": env["base"]["id"],
            "route_id": env["route"]["id"],
            "aircraft_id": env["aircraft"]["id"],
            "pilot_id": pilot_id,
            "scheduled_departure_utc": "2026-08-03T18:00:00Z",
        },
        DISP,
    )
    validate_error(resp, ApiErrorId.ERR_PILOT_FLIGHT_TIME_EXCEEDED)


def test_flight_minutes_exactly_480_allowed(api):
    """PRD §3.4: "The candidate's block time is added, and the sum must be at
    most eight hours; eight hours exactly is permitted, one minute more is
    rejected with `ERR_PILOT_FLIGHT_TIME_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/duty_limit_exact_boundary_allows_and_exceeds_rejects
    """
    env = setup_ops_env(route_overrides=dict(ROUTE_240))
    f1 = create_flight(env, "2026-08-03T08:00:00Z")
    assert is_valid_uuid(f1["id"])
    # 240 + 240 == 480 exactly: the <= boundary is inclusive.
    f2 = create_flight(env, "2026-08-03T13:00:00Z")
    assert is_valid_uuid(f2["id"])
    rows = list_duty_days(env["pilot"]["id"], duty_date="2026-08-03")
    assert rows[0]["flight_minutes_scheduled"] == 480


def test_flight_minutes_above_480_rejected(api):
    """PRD §3.4: "The candidate's block time is added, and the sum must be at
    most eight hours; eight hours exactly is permitted, one minute more is
    rejected with `ERR_PILOT_FLIGHT_TIME_EXCEEDED`."
    PRD §3.3: "then the pilot's projected flight time and duty span for that
    UTC date must admit the new block (`ERR_PILOT_FLIGHT_TIME_EXCEEDED`, then
    `ERR_PILOT_DUTY_LIMIT_EXCEEDED`; §3.4)"

    Design: Difficulty/boundary_precision_check/duty_limit_exact_boundary_allows_and_exceeds_rejects
    """
    env = setup_ops_env(route_overrides=dict(ROUTE_240))
    create_flight(env, "2026-08-03T08:00:00Z")
    create_flight(env, "2026-08-03T13:00:00Z")

    # 480 + 240 == 720 > 480 -> rejected; the ledger stays at 480.
    resp = api.create_flight(
        {
            "base_id": env["base"]["id"],
            "route_id": env["route"]["id"],
            "aircraft_id": env["aircraft"]["id"],
            "pilot_id": env["pilot"]["id"],
            "scheduled_departure_utc": "2026-08-03T18:00:00Z",
        },
        DISP,
    )
    validate_error(resp, ApiErrorId.ERR_PILOT_FLIGHT_TIME_EXCEEDED)
    rows = list_duty_days(env["pilot"]["id"], duty_date="2026-08-03")
    assert rows[0]["flight_minutes_scheduled"] == 480


def test_duty_span_limit_840_boundary(api):
    """PRD §3.4: "`duty_minutes_projected` spans from forty-five minutes
    before the earliest scheduled departure among the pilot's active flights
    plus the candidate, to fifteen minutes after the latest scheduled arrival
    among them, and must be at most fourteen hours — again equality is
    allowed, overflow rejected with `ERR_PILOT_DUTY_LIMIT_EXCEEDED`."

    Design: Corner/calculations/duty_span_limit_840_boundary
    """
    env = setup_ops_env(route_overrides=dict(ROUTE_240))
    create_flight(env, "2026-08-03T08:00:00Z")  # arr 12:00, span so far 300

    # Candidate 17:01 -> arr 21:01 -> span (21:01+15) - (08:00-45) == 841.
    resp = api.create_flight(
        {
            "base_id": env["base"]["id"],
            "route_id": env["route"]["id"],
            "aircraft_id": env["aircraft"]["id"],
            "pilot_id": env["pilot"]["id"],
            "scheduled_departure_utc": "2026-08-03T17:01:00Z",
        },
        DISP,
    )
    validate_error(resp, ApiErrorId.ERR_PILOT_DUTY_LIMIT_EXCEEDED)

    # Candidate 17:00 -> arr 21:00 -> span exactly 840 -> allowed
    # (flight minutes 240 + 240 == 480 pass the flight-time gate).
    f2 = create_flight(env, "2026-08-03T17:00:00Z")
    assert is_valid_uuid(f2["id"])
    rows = list_duty_days(env["pilot"]["id"], duty_date="2026-08-03")
    assert rows[0]["duty_minutes_projected"] == 840
    assert rows[0]["flight_minutes_scheduled"] == 480


def test_fatigue_lock_then_run_ops_reset(api):
    """PRD §3.4: "The moment the running total reaches or exceeds eight
    hours, the pilot flips AVAILABLE → FATIGUE_LOCKED, and a FATIGUE_LOCKED
    pilot cannot be assigned to new flights."
    PRD §3.3: "the pilot must be AVAILABLE — a FATIGUE_LOCKED pilot cannot be
    assigned, `ERR_PILOT_NOT_AVAILABLE`"
    PRD §3.4: "In one invocation it expires every HELD booking whose
    `expires_at` is at or before now (§3.8), expires every rebooking credit
    whose `expires_at` has likewise arrived, and closes every OPEN `DutyDay`
    whose `duty_date` is before the current UTC date, moving it OPEN →
    CLOSED."
    PRD §3.4: "A pilot left with no remaining OPEN duty-day returns
    FATIGUE_LOCKED → AVAILABLE. Each run increments the base's
    `ops_run_index` by one."

    Design: Corner/state_machines/fatigue_lock_then_run_ops_reset
    """
    env = setup_ops_env(route_overrides=dict(ROUTE_240))
    pilot_id = env["pilot"]["id"]
    f1 = create_flight(env, "2026-08-03T08:00:00Z")
    f2 = create_flight(env, "2026-08-03T13:00:00Z")
    # Both flights flown for their full 240-minute block: 240 + 240 == 480.
    fly_empty_flight(f1["id"], pilot_id,
                     depart_at="2026-08-03T08:00:00Z",
                     complete_at="2026-08-03T12:00:00Z")
    fly_empty_flight(f2["id"], pilot_id,
                     depart_at="2026-08-03T13:00:00Z",
                     complete_at="2026-08-03T17:00:00Z")

    assert get_pilot(pilot_id)["status"] == "FATIGUE_LOCKED"

    resp = api.create_flight(
        {
            "base_id": env["base"]["id"],
            "route_id": env["route"]["id"],
            "aircraft_id": env["aircraft"]["id"],
            "pilot_id": pilot_id,
            "scheduled_departure_utc": "2026-08-04T08:00:00Z",
        },
        DISP,
    )
    validate_error(resp, ApiErrorId.ERR_PILOT_NOT_AVAILABLE)

    # Next-day batch tick closes the stale duty day and resets the lock.
    set_clock("2026-08-04T00:00:00Z")
    run_result = validate_success(api.run_ops(env["base"]["id"], OPS))
    assert run_result["ops_run_index"] == 1

    rows = list_duty_days(pilot_id, duty_date="2026-08-03")
    assert rows[0]["status"] == "CLOSED"
    assert rows[0]["flight_minutes_actual"] == 480

    assert get_pilot(pilot_id)["status"] == "AVAILABLE"
    f3 = create_flight(env, "2026-08-05T08:00:00Z")
    assert is_valid_uuid(f3["id"]), "assignment allowed again on a fresh day"
