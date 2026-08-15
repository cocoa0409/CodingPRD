"""Turn windows, pilot overlap, quiet hours, noise class, departure gating."""
from test_helpers import (
    ApiErrorId,
    create_aircraft,
    create_flight,
    create_pilot,
    create_route,
    get_flight,
    is_valid_uuid,
    set_clock,
    setup_ops_env,
    TEST_USERS,
    validate_error,
)

DISP = TEST_USERS["dispatcher_headers"]

_GATE_ORDER_QUOTE = (
    "the pilot must be AVAILABLE — a FATIGUE_LOCKED pilot cannot be "
    "assigned, `ERR_PILOT_NOT_AVAILABLE` — then the pilot's projected flight "
    "time and duty span for that UTC date must admit the new block "
    "(`ERR_PILOT_FLIGHT_TIME_EXCEEDED`, then "
    "`ERR_PILOT_DUTY_LIMIT_EXCEEDED`; §3.4), then the aircraft must be "
    "AVAILABLE (`ERR_AIRCRAFT_NOT_AVAILABLE` when IN_MAINTENANCE or "
    "GROUNDED), then a route whose `min_aircraft_noise_class` is QUIET_ONLY "
    "demands an aircraft whose `noise_class` is QUIET "
    "(`ERR_AIRCRAFT_NOISE_CLASS_INSUFFICIENT`), then a noise-sensitive route "
    "flown by a non-QUIET aircraft may not depart with its minute-of-day "
    "inside the base's quiet-hours window (`ERR_QUIET_HOURS_VIOLATION`), "
    "then the departure must be strictly in the future "
    "(`ERR_DEPARTURE_IN_PAST`), then the aircraft's turnaround-buffered "
    "interval and the pilot's plain block interval must each be free of "
    "conflicts (`ERR_AIRCRAFT_TURN_CONFLICT`, `ERR_PILOT_SCHEDULE_OVERLAP`), "
    "and finally the route must be ACTIVE (`ERR_ROUTE_SUSPENDED`)."
)


def _two_aircraft_two_pilots(env):
    a2 = create_aircraft(tail_number="N2")
    p2 = create_pilot(display_name="Pat Two", certificate_no="C2")
    return a2, p2


def test_aircraft_departure_inside_turn_buffer_rejected(api):
    """PRD §3.3: "An aircraft is occupied from a flight's
    `scheduled_departure_utc` to its `scheduled_arrival_utc` plus the route's
    `turn_minutes`, half-open: a candidate conflicts when its departure falls
    strictly before an existing flight's buffered end and that flight's
    departure falls strictly before the candidate's buffered end, which means
    a departure exactly at the previous flight's buffered end is allowed."

    Design: Difficulty/resource_temporal_overlap/aircraft_turn_buffer_vs_pilot_adjacency_semantics
    """
    env = setup_ops_env()
    _a2, p2 = _two_aircraft_two_pilots(env)
    # F1 on A1 dep 08:00, arr 08:25, SHORT turn 15 -> occupied [08:00, 08:40).
    create_flight(env, "2026-08-03T08:00:00Z")

    resp = api.create_flight(
        {
            "base_id": env["base"]["id"],
            "route_id": env["route"]["id"],
            "aircraft_id": env["aircraft"]["id"],
            "pilot_id": p2["id"],
            "scheduled_departure_utc": "2026-08-03T08:39:00Z",
        },
        DISP,
    )
    validate_error(resp, ApiErrorId.ERR_AIRCRAFT_TURN_CONFLICT)

    # Departure exactly at the buffered end 08:40 is allowed (half-open end).
    f2 = create_flight(env, "2026-08-03T08:40:00Z", pilot=p2)
    assert is_valid_uuid(f2["id"])


def test_pilot_departure_at_exact_previous_arrival_allowed(api):
    """PRD §3.3: "A pilot is occupied over the plain half-open block from
    departure to arrival with no buffer, so a departure exactly at the
    previous flight's arrival is allowed."
    PRD §3.3: "Both gates consider only flights on the same UTC date in
    SCHEDULED, DELAYED, BOARDING, MANIFEST_CLOSED, or DISPATCHED; cancelled
    and completed flights do not block."

    Design: Difficulty/resource_temporal_overlap/aircraft_turn_buffer_vs_pilot_adjacency_semantics
    """
    env = setup_ops_env()
    a2, _p2 = _two_aircraft_two_pilots(env)
    # F1: A1 + P1 dep 08:00, arrival 08:25.
    create_flight(env, "2026-08-03T08:00:00Z")

    # The same pilot departs another aircraft at exactly 08:25 — the pilot
    # interval [08:00, 08:25) is plain half-open, so no overlap.
    f3 = create_flight(env, "2026-08-03T08:25:00Z", aircraft=a2)
    assert is_valid_uuid(f3["id"])


def test_rotation_seq_ordered_by_departure(api):
    """PRD §3.3: "its `rotation_seq` is assigned per aircraft per UTC date by
    ordering that aircraft's non-cancelled flights by departure ascending and
    numbering from 1"

    Design: Corner/calculations/rotation_seq_ordered_by_departure
    """
    env = setup_ops_env()
    # Created out of order: 16:00 first, then 08:00, then 09:00.
    f3 = create_flight(env, "2026-08-03T16:00:00Z")
    f1 = create_flight(env, "2026-08-03T08:00:00Z")
    f2 = create_flight(env, "2026-08-03T09:00:00Z")

    assert get_flight(f1["id"])["rotation_seq"] == 1
    assert get_flight(f2["id"])["rotation_seq"] == 2
    assert get_flight(f3["id"])["rotation_seq"] == 3


def test_pilot_schedule_overlap_rejected(api):
    """PRD §3.3: "A pilot is occupied over the plain half-open block from
    departure to arrival with no buffer, so a departure exactly at the
    previous flight's arrival is allowed."
    PRD §3.3: "then the aircraft's turnaround-buffered interval and the
    pilot's plain block interval must each be free of conflicts
    (`ERR_AIRCRAFT_TURN_CONFLICT`, `ERR_PILOT_SCHEDULE_OVERLAP`), and finally
    the route must be ACTIVE (`ERR_ROUTE_SUSPENDED`)."

    Design: Corner/validations/pilot_schedule_overlap_rejected
    """
    env = setup_ops_env()
    a2, p2 = _two_aircraft_two_pilots(env)
    # F1: A1 + P1 occupied [08:00, 08:25).
    create_flight(env, "2026-08-03T08:00:00Z")

    # P1 again at 08:15 on A2: pilot intervals intersect even though the
    # aircraft rule passes on A2.
    resp = api.create_flight(
        {
            "base_id": env["base"]["id"],
            "route_id": env["route"]["id"],
            "aircraft_id": a2["id"],
            "pilot_id": env["pilot"]["id"],
            "scheduled_departure_utc": "2026-08-03T08:15:00Z",
        },
        DISP,
    )
    validate_error(resp, ApiErrorId.ERR_PILOT_SCHEDULE_OVERLAP)

    # The same slot with a free pilot passes.
    f2 = create_flight(env, "2026-08-03T08:15:00Z", aircraft=a2, pilot=p2)
    assert is_valid_uuid(f2["id"])


def test_delay_into_turn_conflict_rejected(api):
    """PRD §3.3: "A dispatcher may also DELAY a SCHEDULED flight, supplying
    `new_departure_utc` strictly in the future — a departure at or before now
    is rejected with `ERR_DEPARTURE_IN_PAST`; the turn, quiet-hours,
    noise-class, and duty gates re-pass at the new slot, after which
    `scheduled_departure_utc` is replaced, `scheduled_arrival_utc` and
    `rotation_seq` are recomputed, and the duty-day ledgers of the former and
    new dates are both adjusted."

    Design: Corner/validations/delay_into_turn_conflict_rejected
    """
    env = setup_ops_env()
    _a2, p2 = _two_aircraft_two_pilots(env)
    # F1 (A1, P1) 08:00-08:25; F2 (A1, P2) 09:00-09:25, buffered to 09:40.
    f1 = create_flight(env, "2026-08-03T08:00:00Z")
    create_flight(env, "2026-08-03T09:00:00Z", pilot=p2)

    resp = api.flight_event(
        f1["id"],
        {"event_type": "DELAY", "new_departure_utc": "2026-08-03T09:20:00Z"},
        DISP,
    )
    validate_error(resp, ApiErrorId.ERR_AIRCRAFT_TURN_CONFLICT)

    after = get_flight(f1["id"])
    assert after["scheduled_departure_utc"].startswith("2026-08-03T08:00")
    assert after["status"] == "SCHEDULED", "failed delay leaves the slot unchanged"


def test_quiet_hours_violation_and_boundary(api):
    """PRD §3.3: "then a noise-sensitive route flown by a non-QUIET aircraft
    may not depart with its minute-of-day inside the base's quiet-hours
    window (`ERR_QUIET_HOURS_VIOLATION`), then the departure must be strictly
    in the future (`ERR_DEPARTURE_IN_PAST`)"
    PRD §2.8: "Quiet hours are expressed as minutes since 00:00 UTC on the
    operating base, from `quiet_hours_start_min_utc` inclusive to
    `quiet_hours_end_min_utc` exclusive."

    Design: Corner/validations/quiet_hours_violation_and_boundary
    """
    env = setup_ops_env(
        route_overrides={"route_code": "NS", "noise_sensitive": True,
                         "noise_zones": ["VILLAGE"]},
    )
    a_quiet = env["aircraft"]  # QUIET
    a_std = create_aircraft(tail_number="NS1", noise_class="STANDARD")

    # Minute 90 (01:30) is inside [60, 780): STANDARD aircraft rejected.
    resp = api.create_flight(
        {
            "base_id": env["base"]["id"],
            "route_id": env["route"]["id"],
            "aircraft_id": a_std["id"],
            "pilot_id": env["pilot"]["id"],
            "scheduled_departure_utc": "2026-08-03T01:30:00Z",
        },
        DISP,
    )
    validate_error(resp, ApiErrorId.ERR_QUIET_HOURS_VIOLATION)

    # A QUIET aircraft at the same minute is exempt from the window.
    f_quiet = create_flight(env, "2026-08-03T01:30:00Z", aircraft=a_quiet)
    assert is_valid_uuid(f_quiet["id"])

    # Minute 780 (13:00) is the exclusive end -> allowed.
    f_end = create_flight(env, "2026-08-03T13:00:00Z", aircraft=a_std)
    assert is_valid_uuid(f_end["id"])

    # Minute 59 (00:59 next day) is before the window start -> allowed.
    f_before = create_flight(env, "2026-08-04T00:59:00Z", aircraft=a_std)
    assert is_valid_uuid(f_before["id"])


def test_quiet_only_route_rejects_standard_aircraft(api):
    """PRD §3.3: "then a route whose `min_aircraft_noise_class` is QUIET_ONLY
    demands an aircraft whose `noise_class` is QUIET
    (`ERR_AIRCRAFT_NOISE_CLASS_INSUFFICIENT`)"

    Design: Corner/validations/quiet_only_route_rejects_standard_aircraft
    """
    env = setup_ops_env(
        route_overrides={"route_code": "RQ",
                         "min_aircraft_noise_class": "QUIET_ONLY"},
    )
    a_std = create_aircraft(tail_number="NS1", noise_class="STANDARD")

    resp = api.create_flight(
        {
            "base_id": env["base"]["id"],
            "route_id": env["route"]["id"],
            "aircraft_id": a_std["id"],
            "pilot_id": env["pilot"]["id"],
            "scheduled_departure_utc": "2026-08-03T14:00:00Z",
        },
        DISP,
    )
    validate_error(resp, ApiErrorId.ERR_AIRCRAFT_NOISE_CLASS_INSUFFICIENT)

    # A QUIET aircraft on the same route and slot succeeds (the route is not
    # noise_sensitive, so the quiet-hours window is irrelevant here).
    f_ok = create_flight(env, "2026-08-03T14:00:00Z")
    assert is_valid_uuid(f_ok["id"])


def test_departure_in_past_rejected(api):
    """PRD §3.3: "then the departure must be strictly in the future
    (`ERR_DEPARTURE_IN_PAST`)"
    PRD §3.3: "A dispatcher may also DELAY a SCHEDULED flight, supplying
    `new_departure_utc` strictly in the future — a departure at or before now
    is rejected with `ERR_DEPARTURE_IN_PAST`"
    PRD §2.8: "Expiry checks fire at the boundary itself — a hold or credit
    whose `expires_at` is at or before the current instant is expired — while
    a scheduled departure must be strictly in the future."

    Design: Corner/validations/departure_in_past_rejected
    """
    env = setup_ops_env(clock="2026-08-03T12:00:00Z")
    f1 = create_flight(env, "2026-08-03T14:00:00Z")

    # 11:59 < now -> rejected.
    resp = api.create_flight(
        {
            "base_id": env["base"]["id"],
            "route_id": env["route"]["id"],
            "aircraft_id": env["aircraft"]["id"],
            "pilot_id": env["pilot"]["id"],
            "scheduled_departure_utc": "2026-08-03T11:59:00Z",
        },
        DISP,
    )
    validate_error(resp, ApiErrorId.ERR_DEPARTURE_IN_PAST)

    # 12:00 == now is not strictly future -> rejected.
    resp = api.create_flight(
        {
            "base_id": env["base"]["id"],
            "route_id": env["route"]["id"],
            "aircraft_id": env["aircraft"]["id"],
            "pilot_id": env["pilot"]["id"],
            "scheduled_departure_utc": "2026-08-03T12:00:00Z",
        },
        DISP,
    )
    validate_error(resp, ApiErrorId.ERR_DEPARTURE_IN_PAST)

    # DELAY re-checks the new slot against now (11:30 is in the past).
    resp = api.flight_event(
        f1["id"],
        {"event_type": "DELAY", "new_departure_utc": "2026-08-03T11:30:00Z"},
        DISP,
    )
    validate_error(resp, ApiErrorId.ERR_DEPARTURE_IN_PAST)
    assert get_flight(f1["id"])["scheduled_departure_utc"].startswith(
        "2026-08-03T14:00"
    ), "failed DELAY mutates nothing"
