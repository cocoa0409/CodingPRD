"""Flight lifecycle: delay/accept, terminal lockdown, boarding, ack, SoD,
maintenance cycle."""
from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    carry_flight_to_manifest_closed,
    close_manifest,
    create_flight,
    create_pilot,
    get_flight,
    is_valid_uuid,
    make_pilot_headers,
    open_boarding,
    pilot_ack,
    set_clock,
    setup_ops_env,
    TEST_USERS,
    validate_error,
    validate_success,
)

DISP = TEST_USERS["dispatcher_headers"]
DISP2 = TEST_USERS["dispatcher_2_headers"]
OPS = TEST_USERS["ops_admin_headers"]


def test_flight_delay_accept_round_trip(api):
    """PRD §3.3: "A dispatcher may also DELAY a SCHEDULED flight, supplying
    `new_departure_utc` strictly in the future — a departure at or before now
    is rejected with `ERR_DEPARTURE_IN_PAST`; the turn, quiet-hours,
    noise-class, and duty gates re-pass at the new slot, after which
    `scheduled_departure_utc` is replaced, `scheduled_arrival_utc` and
    `rotation_seq` are recomputed, and the duty-day ledgers of the former and
    new dates are both adjusted."
    PRD §3.3: "Accepting the delayed slot moves DELAYED → SCHEDULED with no
    field changes."

    Design: Corner/state_machines/flight_delay_accept_round_trip
    """
    env = setup_ops_env()
    flight = create_flight(env, "2026-08-03T14:00:00Z")

    delayed = validate_success(
        api.flight_event(
            flight["id"],
            {"event_type": "DELAY", "new_departure_utc": "2026-08-03T16:00:00Z"},
            DISP,
        )
    )
    assert delayed["status"] == "DELAYED"
    assert_instant_equals(delayed["scheduled_departure_utc"],
                          "2026-08-03T16:00:00Z", "scheduled_departure_utc")
    # Arrival is recomputed: 16:00 + 25 minutes.
    assert_instant_equals(delayed["scheduled_arrival_utc"],
                          "2026-08-03T16:25:00Z", "scheduled_arrival_utc")

    accepted = validate_success(
        api.flight_event(flight["id"], {"event_type": "ACCEPT_DELAY"}, DISP)
    )
    assert accepted["status"] == "SCHEDULED"
    # ACCEPT_DELAY keeps the delayed slot; no field changes.
    assert_instant_equals(accepted["scheduled_departure_utc"],
                          "2026-08-03T16:00:00Z", "scheduled_departure_utc")


def test_cancelled_flight_terminal_lockdown(api):
    """PRD §2.9: "6. **State** — the target resource is in a state that
    permits the requested transition; terminal states reject every
    transition. Failure: `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.8: "Whether the trigger is the weather cascade of §3.2, the route
    suspension of §3.9, the aircraft grounding of §3.1, or a dispatcher's own
    weather or ops cancellation — available from SCHEDULED, DELAYED,
    BOARDING, or MANIFEST_CLOSED, stamping `cancel_reason` WEATHER or
    OPS_MANUAL respectively, with an optional `reason` note on the event"

    Design: Corner/state_machines/cancelled_flight_terminal_lockdown
    """
    env = setup_ops_env()
    flight = create_flight(env, "2026-08-05T14:00:00Z")

    cancelled = validate_success(
        api.flight_event(
            flight["id"], {"event_type": "CANCEL_OPS", "reason": "manual"}, DISP
        )
    )
    assert cancelled["status"] == "CANCELLED_OPS"
    assert cancelled["cancel_reason"] == "OPS_MANUAL"

    for event in ("OPEN_BOARDING", "DISPATCH", "COMPLETE"):
        resp = api.flight_event(flight["id"], {"event_type": event}, DISP2)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    assert get_flight(flight["id"])["status"] == "CANCELLED_OPS"


def test_open_boarding_twice_second_rejected(api):
    """PRD §3.7: "When the flight's slot approaches, a dispatcher opens
    boarding — SCHEDULED → BOARDING, or DELAYED → BOARDING — permitted only
    while the base posture is NORMAL."
    PRD §2.9: "6. **State** — the target resource is in a state that permits
    the requested transition; terminal states reject every transition.
    Failure: `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/open_boarding_twice_second_rejected
    """
    env = setup_ops_env()
    flight = create_flight(env, "2026-08-03T14:00:00Z")

    first = open_boarding(flight["id"])
    assert first["status"] == "BOARDING"

    # BOARDING is not a valid from-state for OPEN_BOARDING.
    resp = api.flight_event(flight["id"], {"event_type": "OPEN_BOARDING"}, DISP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_dispatch_rejected_until_pilot_acknowledges(api):
    """PRD §3.7: "Dispatch turns the aircraft loose: MANIFEST_CLOSED →
    DISPATCHED. Its three guards evaluate in order — base posture must be
    NORMAL (`ERR_WEATHER_HOLD_ACTIVE`), then segregation of duties demands
    the dispatching dispatcher differ from the one recorded in
    `created_by_user_id` (`ERR_SEGREGATION_OF_DUTY`, HTTP 403), then the
    assigned pilot must have acknowledged (`ERR_PILOT_ACK_REQUIRED`)."

    Design: Corner/state_machines/dispatch_requires_pilot_ack_then_succeeds
    """
    env = setup_ops_env()
    flight = create_flight(env, "2026-08-03T14:00:00Z")  # created by disp-1
    open_boarding(flight["id"])
    closed = close_manifest(flight["id"])
    assert closed["status"] == "MANIFEST_CLOSED"
    set_clock("2026-08-03T14:00:00Z")

    # Posture NORMAL, disp-2 differs from creator: only the ack guard can
    # fire while pilot_acknowledged is false.
    resp = api.flight_event(flight["id"], {"event_type": "DISPATCH"}, DISP2)
    validate_error(resp, ApiErrorId.ERR_PILOT_ACK_REQUIRED)
    assert get_flight(flight["id"])["status"] == "MANIFEST_CLOSED"


def test_dispatch_succeeds_after_pilot_ack(api):
    """PRD §3.7: "Dispatch stamps `actual_departure_utc` with the current
    instant, records `dispatched_by_user_id`, and cleans house: bookings
    still in CONFIRMED become NO_SHOW — the entire `paid_cents` is retained
    as `retained_fee_cents` with no refund and no credit — and bookings still
    in HELD become EXPIRED."
    PRD §3.3: "The assigned pilot acknowledges the flight through a PILOT_ACK
    — a self-transition accepted from SCHEDULED → SCHEDULED or DELAYED →
    DELAYED — whose `X-User-ID` must equal the flight's `pilot_id`
    (`ERR_PILOT_MISMATCH` otherwise) and which sets `pilot_acknowledged` to
    true."

    Design: Corner/state_machines/dispatch_requires_pilot_ack_then_succeeds
    """
    env = setup_ops_env()
    flight = create_flight(env, "2026-08-03T14:00:00Z")  # created by disp-1
    pilot_ack(flight["id"], env["pilot"]["id"])  # while SCHEDULED
    open_boarding(flight["id"])
    close_manifest(flight["id"])
    set_clock("2026-08-03T14:00:00Z")

    dispatched = validate_success(
        api.flight_event(flight["id"], {"event_type": "DISPATCH"}, DISP2)
    )
    assert dispatched["status"] == "DISPATCHED"
    assert_instant_equals(dispatched["actual_departure_utc"],
                          "2026-08-03T14:00:00Z", "actual_departure_utc")
    assert dispatched["dispatched_by_user_id"] == "disp-2"


def test_pilot_ack_ownership_enforced(api):
    """PRD §3.3: "The assigned pilot acknowledges the flight through a
    PILOT_ACK — a self-transition accepted from SCHEDULED → SCHEDULED or
    DELAYED → DELAYED — whose `X-User-ID` must equal the flight's `pilot_id`
    (`ERR_PILOT_MISMATCH` otherwise) and which sets `pilot_acknowledged` to
    true."

    Design: Corner/state_machines/pilot_ack_ownership_enforced
    """
    env = setup_ops_env()
    other = create_pilot(display_name="Pat Two", certificate_no="C2")
    flight = create_flight(env, "2026-08-03T14:00:00Z")

    resp = api.flight_event(
        flight["id"], {"event_type": "PILOT_ACK"}, make_pilot_headers(other["id"])
    )
    validate_error(resp, ApiErrorId.ERR_PILOT_MISMATCH)

    ack1 = pilot_ack(flight["id"], env["pilot"]["id"])
    assert ack1["pilot_acknowledged"] is True
    assert ack1["status"] == "SCHEDULED", "self-transition, no state change"

    # A repeat ack is the same legal self-transition: flag stays true.
    ack2 = pilot_ack(flight["id"], env["pilot"]["id"])
    assert ack2["pilot_acknowledged"] is True
    assert ack2["status"] == "SCHEDULED"


def test_aircraft_maintenance_cycle_gates_scheduling(api):
    """PRD §3.1: "Placing it into maintenance is refused while any of its
    flights sits in SCHEDULED, DELAYED, BOARDING, or MANIFEST_CLOSED with a
    departure now or later; otherwise it transitions AVAILABLE →
    IN_MAINTENANCE, and ending maintenance returns IN_MAINTENANCE →
    AVAILABLE."
    PRD §3.3: "then the aircraft must be AVAILABLE
    (`ERR_AIRCRAFT_NOT_AVAILABLE` when IN_MAINTENANCE or GROUNDED)"

    Design: Corner/state_machines/aircraft_maintenance_cycle_gates_scheduling
    """
    env = setup_ops_env()

    in_maint = validate_success(
        api.aircraft_event(env["aircraft"]["id"],
                           {"event_type": "START_MAINTENANCE"}, OPS)
    )
    assert in_maint["status"] == "IN_MAINTENANCE"

    # Scheduling against an IN_MAINTENANCE tail fails the availability gate.
    resp = api.create_flight(
        {
            "base_id": env["base"]["id"],
            "route_id": env["route"]["id"],
            "aircraft_id": env["aircraft"]["id"],
            "pilot_id": env["pilot"]["id"],
            "scheduled_departure_utc": "2026-08-03T14:00:00Z",
        },
        DISP,
    )
    validate_error(resp, ApiErrorId.ERR_AIRCRAFT_NOT_AVAILABLE)

    avail = validate_success(
        api.aircraft_event(env["aircraft"]["id"],
                           {"event_type": "END_MAINTENANCE"}, OPS)
    )
    assert avail["status"] == "AVAILABLE"

    flight = create_flight(env, "2026-08-03T14:00:00Z")
    assert is_valid_uuid(flight["id"])

    # With a future active flight on the tail, START_MAINTENANCE is refused.
    resp = api.aircraft_event(env["aircraft"]["id"],
                              {"event_type": "START_MAINTENANCE"}, OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_dispatch_segregation_of_duties(api):
    """PRD §3.7: "Dispatch turns the aircraft loose: MANIFEST_CLOSED →
    DISPATCHED. Its three guards evaluate in order — base posture must be
    NORMAL (`ERR_WEATHER_HOLD_ACTIVE`), then segregation of duties demands
    the dispatching dispatcher differ from the one recorded in
    `created_by_user_id` (`ERR_SEGREGATION_OF_DUTY`, HTTP 403), then the
    assigned pilot must have acknowledged (`ERR_PILOT_ACK_REQUIRED`)."

    Design: Corner/rbac/dispatch_segregation_of_duties
    """
    env = setup_ops_env()
    # Flight created by disp-1; pilot acks while SCHEDULED.
    flight = create_flight(env, "2026-08-03T14:00:00Z")
    carry_flight_to_manifest_closed(flight["id"], env["pilot"]["id"])
    set_clock("2026-08-03T14:00:00Z")

    # The dispatcher who created the flight may not dispatch it.
    resp = api.flight_event(flight["id"], {"event_type": "DISPATCH"}, DISP)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTY)

    dispatched = validate_success(
        api.flight_event(flight["id"], {"event_type": "DISPATCH"}, DISP2)
    )
    assert dispatched["status"] == "DISPATCHED"
    assert dispatched["dispatched_by_user_id"] == "disp-2"
