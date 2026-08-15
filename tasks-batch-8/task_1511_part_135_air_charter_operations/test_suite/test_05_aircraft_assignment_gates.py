"""Aircraft assignment lifecycle: confirm gates, release discipline,
supersede semantics, and the two interval-conflict regimes."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId,
    create_owner, create_aircraft, set_clock, create_window,
    complete_window, release_assignment,
    setup_quoted_trip, setup_booked_trip, setup_trip_with_confirmed_aircraft,
    create_assignment, confirm_assignment,
    make_ops_admin_headers, make_dispatch_manager_headers,
    make_maintenance_controller_headers,
)

OPS_ADMIN = make_ops_admin_headers()
DISPATCH_MANAGER = make_dispatch_manager_headers()
MAINTENANCE_CONTROLLER = make_maintenance_controller_headers()


def _two_booked_trips_one_aircraft(trip2_departure):
    """Trip1 dep 2026-08-10T10:00:00Z with a 120min leg, CONFIRMED on the
    shared tail (buffered occupancy [09:15, 12:45)); trip2 with a 60min leg
    departing at trip2_departure, BOOKED with a TENTATIVE assignment on the
    same tail. Returns (aircraft, asg2)."""
    owner = create_owner(name="Owner O", contact_email="o@x.com")
    aircraft = create_aircraft(owner["id"], tail_number="N110OV")
    ctx1 = setup_booked_trip(legs=((120, "REVENUE", False),), customer_name="Cust O1")
    asg1 = confirm_assignment(create_assignment(ctx1[0]["id"], aircraft["id"])["id"])
    assert asg1["status"] == "CONFIRMED"
    trip2, _legs2 = setup_booked_trip(
        legs=((60, "REVENUE", False),), origin_icao="KTEB", destination_icao="KLAX",
        departure_at=trip2_departure, pay_in_full=False, customer_name="Cust O2")
    asg2 = create_assignment(trip2["id"], aircraft["id"])
    return aircraft, asg2


# ---------------------------------------------------------------------------
# Queue A: cross_entity_state_dependency / confirm_requires_aircraft_available
# ---------------------------------------------------------------------------

def test_confirm_rejected_while_aircraft_in_maintenance_hold(api):
    """PRD §3.5: "The aircraft must be `AVAILABLE`
    (`ERR_AIRCRAFT_NOT_AVAILABLE`) and listed on the operator's FAA
    operations specifications, with `on_ops_spec` true
    (`ERR_AIRCRAFT_NOT_ON_OPS_SPEC`)."
    PRD §2.4: "a maintenance window in `PLANNED` status whose `starts_at` has
    been reached activates — provided its aircraft is not `IN_TRIP`, since
    activation is skipped while the tail is flying and re-evaluated on the
    next clock set — moving the window to `ACTIVE` and an `AVAILABLE`
    aircraft to `MAINTENANCE_HOLD`."

    Design: Difficulty/cross_entity_state_dependency/confirm_requires_aircraft_available
    """
    owner = create_owner(name="Owner M", contact_email="m@x.com")
    aircraft = create_aircraft(owner["id"], tail_number="N800MW")
    create_window(aircraft["id"], window_type="AOG_REPAIR",
                  starts_at="2026-08-01T00:00:00Z", ends_at="2026-08-02T00:00:00Z")
    set_clock("2026-08-01T12:00:00Z")  # activates the window -> MAINTENANCE_HOLD
    trip, _legs = setup_booked_trip(legs=((60, "REVENUE", False),), pay_in_full=False,
                                    customer_name="Cust M")
    asg = create_assignment(trip["id"], aircraft["id"])
    resp = api_client.confirm_aircraft_assignment(asg["id"], DISPATCH_MANAGER)
    validate_error(resp, ApiErrorId.ERR_AIRCRAFT_NOT_AVAILABLE)


def test_confirm_succeeds_after_maintenance_hold_clears(api):
    """PRD §3.5: "When the completed window was the last `ACTIVE` window on
    the tail and the accumulated airframe time sits below the check-due
    threshold, the aircraft leaves `MAINTENANCE_HOLD` for `AVAILABLE`."
    PRD §3.5: "All gates passing moves the assignment to `CONFIRMED`."

    Design: Difficulty/cross_entity_state_dependency/confirm_requires_aircraft_available
    """
    owner = create_owner(name="Owner M", contact_email="m@x.com")
    aircraft = create_aircraft(owner["id"], tail_number="N800MW")
    window = create_window(aircraft["id"], window_type="AOG_REPAIR",
                           starts_at="2026-08-01T00:00:00Z",
                           ends_at="2026-08-02T00:00:00Z")
    set_clock("2026-08-01T12:00:00Z")
    trip, _legs = setup_booked_trip(legs=((60, "REVENUE", False),), pay_in_full=False,
                                    customer_name="Cust M")
    asg = create_assignment(trip["id"], aircraft["id"])
    validate_error(api_client.confirm_aircraft_assignment(asg["id"], DISPATCH_MANAGER),
                   ApiErrorId.ERR_AIRCRAFT_NOT_AVAILABLE)

    completed = complete_window(window["id"])
    assert completed["status"] == "COMPLETED"
    aircraft_after = validate_success(api_client.get_aircraft(aircraft["id"], OPS_ADMIN), 200)
    assert aircraft_after["status"] == "AVAILABLE"
    confirmed = confirm_assignment(asg["id"])
    assert confirmed["status"] == "CONFIRMED"


# ---------------------------------------------------------------------------
# Queue A: resource_temporal_overlap / aircraft_buffered_overlap_conflict
# ---------------------------------------------------------------------------

def test_confirm_rejected_when_buffered_intervals_intersect(api):
    """PRD §3.5: "No other `CONFIRMED` assignment on the same tail may have a
    buffered half-open occupancy interval intersecting this one
    (`ERR_AIRCRAFT_SCHEDULE_CONFLICT`)."
    PRD §2.8: "An aircraft assignment occupies its tail over a buffered,
    half-open interval: `occupied_start_at` is the trip's `departure_at`
    minus a 45-minute turnaround buffer, and `occupied_end_at` is the trip's
    `departure_at` plus the sum of the planned block minutes of all the
    trip's legs plus the same 45-minute turnaround buffer."

    Design: Difficulty/resource_temporal_overlap/aircraft_buffered_overlap_conflict
    """
    # Trip2 dep 13:29 -> occupied [12:44, 14:59) intersects trip1's end 12:45.
    _aircraft, asg2 = _two_booked_trips_one_aircraft("2026-08-10T13:29:00Z")
    resp = api_client.confirm_aircraft_assignment(asg2["id"], DISPATCH_MANAGER)
    validate_error(resp, ApiErrorId.ERR_AIRCRAFT_SCHEDULE_CONFLICT)
    # Rejection leaves the assignment TENTATIVE.
    asg2_after = validate_success(
        api_client.get_aircraft_assignment(asg2["id"], OPS_ADMIN), 200)
    assert asg2_after["status"] == "TENTATIVE"


def test_schedule_conflict_clears_once_prior_assignment_released(api):
    """PRD §3.5: "No other `CONFIRMED` assignment on the same tail may have a
    buffered half-open occupancy interval intersecting this one
    (`ERR_AIRCRAFT_SCHEDULE_CONFLICT`)."
    PRD §3.5: "An assignment can also be released outright while it is
    `TENTATIVE` or `CONFIRMED`..."

    Design: Difficulty/resource_temporal_overlap/aircraft_buffered_overlap_conflict
    """
    _aircraft, asg2 = _two_booked_trips_one_aircraft("2026-08-10T13:29:00Z")
    validate_error(api_client.confirm_aircraft_assignment(asg2["id"], DISPATCH_MANAGER),
                   ApiErrorId.ERR_AIRCRAFT_SCHEDULE_CONFLICT)
    # Release the blocking CONFIRMED assignment: no other CONFIRMED
    # assignment remains, so the same confirm now passes.
    asg1_rows, _m = validate_paginated(
        api_client.list_aircraft_assignments(
            OPS_ADMIN, params={"aircraft_id": _aircraft["id"], "status": "CONFIRMED"}))
    assert len(asg1_rows) == 1
    release_assignment(asg1_rows[0]["id"])
    confirmed = confirm_assignment(asg2["id"])
    assert confirmed["status"] == "CONFIRMED"


# ---------------------------------------------------------------------------
# Queue A: compensating_invariant / aircraft_release_no_drift
# ---------------------------------------------------------------------------

def test_confirm_then_release_leaves_aircraft_available(api):
    """PRD §3.5: "All gates passing moves the assignment to `CONFIRMED`. An
    assignment can also be released outright while it is `TENTATIVE` or
    `CONFIRMED`; releasing an already-`RELEASED` assignment is rejected with
    `ERR_ASSIGNMENT_ALREADY_RELEASED`."
    Invariant: confirm and release are assignment-side transitions; the
    aircraft itself stays `AVAILABLE` throughout.

    Design: Difficulty/compensating_invariant/aircraft_release_no_drift
    """
    ctx = setup_trip_with_confirmed_aircraft(
        aircraft_overrides={"tail_number": "N220ND", "initial_airframe_minutes": 1000},
        pay_in_full=False, customer_name="Cust N")
    aircraft = ctx["aircraft"]
    released = release_assignment(ctx["assignment"]["id"])
    assert released["status"] == "RELEASED"
    aircraft_after = validate_success(api_client.get_aircraft(aircraft["id"], OPS_ADMIN), 200)
    assert aircraft_after["status"] == "AVAILABLE"


def test_assignment_transitions_do_not_mutate_aircraft_row(api):
    """PRD §2.5: "The `version` is a system-managed integer that increments
    by one on every mutation, including mutations applied by system
    cascades."
    Invariant: confirm-then-release touches only the assignment; the
    aircraft's accumulated airframe minutes and version are unchanged.

    Design: Difficulty/compensating_invariant/aircraft_release_no_drift
    """
    ctx = setup_trip_with_confirmed_aircraft(
        aircraft_overrides={"tail_number": "N220ND", "initial_airframe_minutes": 1000},
        pay_in_full=False, customer_name="Cust N")
    aircraft_at_create = ctx["aircraft"]
    release_assignment(ctx["assignment"]["id"])
    after = validate_success(api_client.get_aircraft(aircraft_at_create["id"], OPS_ADMIN), 200)
    assert after["total_airframe_minutes"] == 1000, "no flight logged -> no drift"
    assert after["version"] == aircraft_at_create["version"], (
        "assignment transitions never mutate the aircraft row")


# ---------------------------------------------------------------------------
# Queue B: state_machines / confirm_twice_rejected
# ---------------------------------------------------------------------------

def test_confirm_twice_rejected(api):
    """PRD §3.5: "Confirming an assignment is where the fleet gates bite, and
    each gate maps to its own error. The assignment must be `TENTATIVE`
    (`ERR_ASSIGNMENT_NOT_TENTATIVE` otherwise)."

    Design: Corner/state_machines/confirm_twice_rejected
    """
    ctx = setup_trip_with_confirmed_aircraft(pay_in_full=False, customer_name="Cust CT")
    resp = api_client.confirm_aircraft_assignment(ctx["assignment"]["id"], DISPATCH_MANAGER)
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_TENTATIVE)


# ---------------------------------------------------------------------------
# Queue B: state_machines / release_released_rejected
# ---------------------------------------------------------------------------

def test_release_released_assignment_rejected(api):
    """PRD §3.5: "An assignment can also be released outright while it is
    `TENTATIVE` or `CONFIRMED`; releasing an already-`RELEASED` assignment is
    rejected with `ERR_ASSIGNMENT_ALREADY_RELEASED`."

    Design: Corner/state_machines/release_released_rejected
    """
    owner = create_owner(name="Owner RL", contact_email="rl@x.com")
    aircraft = create_aircraft(owner["id"], tail_number="N900RL")
    trip, _legs = setup_quoted_trip(legs=((60, "REVENUE", False),), customer_name="Cust RL")
    asg = create_assignment(trip["id"], aircraft["id"])
    release_assignment(asg["id"])
    resp = api_client.release_aircraft_assignment(asg["id"], DISPATCH_MANAGER)
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_ALREADY_RELEASED)


# ---------------------------------------------------------------------------
# Queue B: errors / category_mismatch_confirm_rejected
# ---------------------------------------------------------------------------

def test_confirm_category_mismatch_rejected(api):
    """PRD §3.5: "Finally the aircraft's `category` must equal the trip's
    `requested_category` (`ERR_CATEGORY_MISMATCH`)."

    Design: Corner/errors/category_mismatch_confirm_rejected
    """
    owner = create_owner(name="Owner CM", contact_email="cm@x.com")
    aircraft = create_aircraft(owner["id"], tail_number="N110CM", category="TURBOPROP",
                               seats=6, hourly_rate_cents=140000)
    trip, _legs = setup_booked_trip(legs=((60, "REVENUE", False),), pay_in_full=False,
                                    customer_name="Cust CM")  # LIGHT_JET request
    asg = create_assignment(trip["id"], aircraft["id"])
    resp = api_client.confirm_aircraft_assignment(asg["id"], DISPATCH_MANAGER)
    validate_error(resp, ApiErrorId.ERR_CATEGORY_MISMATCH)


# ---------------------------------------------------------------------------
# Queue B: errors / not_on_ops_spec_confirm_rejected
# ---------------------------------------------------------------------------

def test_confirm_aircraft_not_on_ops_spec_rejected(api):
    """PRD §3.5: "The aircraft must be `AVAILABLE`
    (`ERR_AIRCRAFT_NOT_AVAILABLE`) and listed on the operator's FAA
    operations specifications, with `on_ops_spec` true
    (`ERR_AIRCRAFT_NOT_ON_OPS_SPEC`)."

    Design: Corner/errors/not_on_ops_spec_confirm_rejected
    """
    owner = create_owner(name="Owner OS", contact_email="os@x.com")
    aircraft = create_aircraft(owner["id"], tail_number="N220OS", on_ops_spec=False)
    trip, _legs = setup_booked_trip(legs=((60, "REVENUE", False),), pay_in_full=False,
                                    customer_name="Cust OS")
    asg = create_assignment(trip["id"], aircraft["id"])
    resp = api_client.confirm_aircraft_assignment(asg["id"], DISPATCH_MANAGER)
    validate_error(resp, ApiErrorId.ERR_AIRCRAFT_NOT_ON_OPS_SPEC)


# ---------------------------------------------------------------------------
# Queue B: endpoints / assignment_create_supersedes_prior_tentative
# ---------------------------------------------------------------------------

def test_assignment_create_supersedes_prior_tentative(api):
    """PRD §3.5: "The new assignment is born `TENTATIVE`, any prior
    `TENTATIVE` assignment on the same trip is released in the same motion,
    the buffered occupancy window is computed per §2.8, and the trip's
    `version` increments."

    Design: Corner/endpoints/assignment_create_supersedes_prior_tentative
    """
    owner = create_owner(name="Owner SP", contact_email="sp@x.com")
    aircraft1 = create_aircraft(owner["id"], tail_number="N700SP")
    aircraft2 = create_aircraft(owner["id"], tail_number="N701SP")
    trip, _legs = setup_booked_trip(legs=((60, "REVENUE", False),), pay_in_full=False,
                                    customer_name="Cust SP")
    asg1 = create_assignment(trip["id"], aircraft1["id"])
    assert asg1["status"] == "TENTATIVE"
    asg2 = create_assignment(trip["id"], aircraft2["id"])
    assert asg2["status"] == "TENTATIVE"
    asg1_after = validate_success(
        api_client.get_aircraft_assignment(asg1["id"], DISPATCH_MANAGER), 200)
    assert asg1_after["status"] == "RELEASED", "superseded by the new create"


# ---------------------------------------------------------------------------
# Queue B: errors / maintenance_touching_closed_interval_rejected
# ---------------------------------------------------------------------------

def test_window_touching_confirmed_flight_interval_rejected(api):
    """PRD §2.8: "Maintenance windows and weather advisories, by contrast,
    use closed intervals on both ends, and the maintenance-conflict test is
    deliberately stricter: a maintenance window conflicts with a flight when
    the window's closed interval from `starts_at` to `ends_at` intersects the
    raw flight interval running from `departure_at` to `departure_at` plus
    the total planned block minutes — and touching endpoints count as
    intersection."

    Design: Corner/errors/maintenance_touching_closed_interval_rejected
    """
    # Confirmed trip flies [10:00, 12:00]; the window starts exactly at 12:00.
    ctx = setup_trip_with_confirmed_aircraft(
        aircraft_overrides={"tail_number": "N990MT"},
        legs=((120, "REVENUE", False),), customer_name="Cust MT")
    resp = api_client.create_maintenance_window(
        {"aircraft_id": ctx["aircraft"]["id"], "window_type": "ANNUAL",
         "starts_at": "2026-08-10T12:00:00Z", "ends_at": "2026-08-10T18:00:00Z"},
        MAINTENANCE_CONTROLLER)
    validate_error(resp, ApiErrorId.ERR_MAINTENANCE_CONFLICT)


# ---------------------------------------------------------------------------
# Queue B: complexity_layers / adjacent_buffered_assignments_allowed
# ---------------------------------------------------------------------------

def test_adjacent_buffered_assignments_allowed(api):
    """PRD §2.8: "When two confirmed assignments on the same tail are tested
    for conflict, the test is intersection of half-open intervals — one
    assignment ending exactly when another begins does not conflict."

    Design: Corner/complexity_layers/adjacent_buffered_assignments_allowed
    """
    # Trip2 dep 13:30 -> occupied start 12:45 == trip1 occupied end 12:45.
    _aircraft, asg2 = _two_booked_trips_one_aircraft("2026-08-10T13:30:00Z")
    resp = api_client.confirm_aircraft_assignment(asg2["id"], DISPATCH_MANAGER)
    confirmed = validate_success(resp, expected_status=200)
    assert confirmed["status"] == "CONFIRMED", "exact half-open adjacency is allowed"
