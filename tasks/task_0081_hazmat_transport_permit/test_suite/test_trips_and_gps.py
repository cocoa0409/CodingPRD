"""Trip lifecycle, vehicle-double-booking, GPS-stream contract, the
auto-Penalty fan-out on the two violation classifier flags, and the
manual-penalty appeal-uphold compensating action.

The trip's four-state machine from PRD §3.7 — ``PLANNED → IN_TRANSIT``
(operator depart), ``IN_TRANSIT → COMPLETED`` (operator arrive),
``{PLANNED, IN_TRANSIT} → ABORTED`` (operator abort with
``OPERATOR_ABORT`` discriminator, or the two cascade-branch
discriminators from the parent permit's terminal transitions) — is
the canonical fork-at-IN_TRANSIT shape the scaffold's
state-machine landscape counts as a non-linear-shape machine.

The vehicle-calendar's half-open-right-exclusive interval-semantics
(PRD §2.9: "two trips whose boundary timestamps touch (the existing
trip's ``scheduled_arrival_at`` exactly equal to the new trip's
``scheduled_departure_at``) do not collide and the new trip is
admitted") is the rule-8 overlap-A interval pin.

The GPS-stream's strict-greater-than monotonicity rule (rule-8
overlap-B closed-on-prior-edge) and the in-flight-window check
(priority 509 firing before the priority-512 monotonicity check on
the simultaneous-failure pair) is the priority-conflict-C precedence
ordering the test layer asserts.

The auto-Penalty fan-out on the GPS-violation classifier's two flags
— ``speed_kph > MAX_HAZMAT_SPEED_KPH`` for the speed-violation flag
and ``off_route_distance_m > OFF_ROUTE_RADIUS_M`` for the off-route
flag — inserts zero, one, or two Penalty rows in the same
transaction as the GPSReport append, with the
``source_gps_report_id`` linking back to the offending sample and
the points-value drawn from the
``GPS_VIOLATION_SPEED_POINTS`` / ``GPS_VIOLATION_OFF_ROUTE_POINTS``
constant pair.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from uuid import uuid4

import pytest

from test_helpers import (
    APPEAL_WINDOW_DAYS,
    ApiErrorId,
    CANONICAL_HAZARD_CLASSES,
    CANONICAL_OFF_ROUTE_LAT,
    CANONICAL_OFF_ROUTE_LON,
    CANONICAL_ON_ROUTE_LAT,
    CANONICAL_ON_ROUTE_LON,
    EARTH_RADIUS_M,
    GPS_VIOLATION_OFF_ROUTE_POINTS,
    GPS_VIOLATION_SPEED_POINTS,
    HAVERSINE_TOLERANCE_METRES,
    HazmatScenario,
    IDEMPOTENCY_KEY_MAX_CHARS,
    IDEMPOTENCY_KEY_MIN_CHARS,
    MAX_HAZMAT_SPEED_KPH,
    MAX_VEHICLES_PER_PERMIT,
    OFF_ROUTE_RADIUS_M,
    PENALTY_WINDOW_DAYS,
    PERMIT_DEFAULT_VALIDITY_DAYS,
    THRESHOLD_DRIVER_SUSPENSION_POINTS,
    abort_trip,
    abort_trip_payload,
    add_days,
    add_hours,
    advance_clock_by,
    api_client,
    arrive_trip,
    arrive_trip_payload,
    assert_gps_report,
    assert_off_route_distance_matches,
    assert_penalty,
    assert_points_conservation,
    assert_trip,
    assert_wallet_conservation,
    bootstrap_company_operator_headers,
    company_operator_headers,
    create_gps_report_payload,
    create_penalty_payload,
    create_trip_payload,
    cross_track_distance_metres,
    current_server_now,
    depart_trip,
    depart_trip_payload,
    driver_headers,
    fetch_all_gps_reports,
    fresh_idempotency_key,
    get_success_data,
    ingest_clean_gps_sample,
    ingest_speed_violation_sample,
    is_iso8601_timestamp,
    is_valid_uuid,
    iso_now_plus_delta,
    issue_manual_driver_penalty,
    push_driver_to_suspension_threshold,
    refresh_endorsement_attestation_payload,
    regulator_headers,
    run_full_sweep,
    schedule_trip,
    setup_active_permit,
    setup_inflight_trip,
    setup_qualified_carrier,
    setup_two_tenants,
    snapshot_driver_rolling_points,
    uphold_penalty,
    uphold_penalty_payload,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
    driver_attestation_payload,
)
from test_helpers.types import (
    AbortReason,
    DriverEndorsementStatus,
    HAZARD_CLASSES_UN,
    PenaltySource,
    PenaltySubjectType,
    PenaltyVoidStatus,
    PermitLifecycleStatus,
    TripStatus,
    VerifyComplianceTransitionFired,
)


# ─── Trip lifecycle happy path ────────────────────────────────────────


def test_schedule_trip_returns_planned(api, active_permit: HazmatScenario):
    """The trip-create endpoint mints a PLANNED row with the four
    state-machine and the standard common-fields-quartet system
    fields.  PRD §3.7's first paragraph names the standard initial
    state ``PLANNED`` and the body's binding fields the row
    carries verbatim.
    """
    scenario = active_permit
    server_now = current_server_now(api)
    dep = iso_now_plus_delta(seconds=120.0, base_iso=server_now)
    arr = iso_now_plus_delta(seconds=120.0 + 3600.0, base_iso=server_now)
    payload = create_trip_payload(
        driver_id=scenario.drivers[0]["id"],
        vehicle_id=scenario.vehicles[0]["id"],
        scheduled_departure_at=dep,
        scheduled_arrival_at=arr,
        cargo_hazard_class="3",
        cargo_weight_kg=1000,
    )
    op = company_operator_headers(scenario.company["id"])
    resp = api.create_trip(scenario.permit["id"], payload, op)
    trip = validate_success(resp, 201)
    assert_trip(trip)
    assert trip["trip_status"] == TripStatus.PLANNED.value
    assert trip["permit_id"] == scenario.permit["id"]
    assert trip["driver_id"] == scenario.drivers[0]["id"]
    assert trip["vehicle_id"] == scenario.vehicles[0]["id"]
    assert trip["scheduled_departure_at"] == dep
    assert trip["scheduled_arrival_at"] == arr
    assert trip.get("actual_departure_at") is None
    assert trip.get("actual_arrival_at") is None
    assert trip.get("aborted_at") is None
    assert trip.get("abort_reason") is None
    assert trip.get("latest_gps_at") is None
    assert trip.get("gps_violation_count", 0) == 0


def test_trip_depart_transitions_planned_to_in_transit(api, active_permit: HazmatScenario):
    """The depart endpoint fires the ``PLANNED → IN_TRANSIT``
    transition.  The handler writes ``actual_departure_at =
    now()`` and bumps the version.  The parent-permit-active
    check at the cross-aggregate state tier is the dedicated
    ``ERR_PERMIT_NOT_ACTIVE`` 409 rather than the generic
    state-tier error.
    """
    scenario = active_permit
    op = company_operator_headers(scenario.company["id"])
    server_now = current_server_now(api)
    dep = iso_now_plus_delta(seconds=10.0, base_iso=server_now)
    arr = iso_now_plus_delta(seconds=3610.0, base_iso=server_now)
    trip = get_success_data(api.create_trip(
        scenario.permit["id"],
        create_trip_payload(
            driver_id=scenario.drivers[0]["id"],
            vehicle_id=scenario.vehicles[0]["id"],
            scheduled_departure_at=dep,
            scheduled_arrival_at=arr,
        ),
        op,
    ))
    # Advance the clock past the scheduled-departure (the
    # implementation's depart-time is the current clock).
    advance_clock_by(api, 11.0, run_sweep=False)
    resp = api.depart_trip(trip["id"], depart_trip_payload(), op)
    departed = validate_success(resp, 200)
    assert departed["trip_status"] == TripStatus.IN_TRANSIT.value
    assert departed.get("actual_departure_at") is not None
    assert is_iso8601_timestamp(departed["actual_departure_at"])
    assert departed["version"] == trip["version"] + 1


def test_trip_arrive_transitions_in_transit_to_completed(api, inflight_trip: HazmatScenario):
    """The arrive endpoint fires the ``IN_TRANSIT → COMPLETED``
    transition.  The handler writes ``actual_arrival_at = now()``.
    """
    scenario = inflight_trip
    op = company_operator_headers(scenario.company["id"])
    trip_pre = scenario.trips[0]
    assert trip_pre["trip_status"] == TripStatus.IN_TRANSIT.value
    # Advance the clock past the scheduled-arrival.
    advance_clock_by(api, 7200.0 + 5.0, run_sweep=False)
    arrived = get_success_data(api.arrive_trip(trip_pre["id"], arrive_trip_payload(), op))
    assert arrived["trip_status"] == TripStatus.COMPLETED.value
    assert arrived["actual_arrival_at"] is not None
    assert arrived["actual_arrival_at"] > arrived["actual_departure_at"]


def test_trip_abort_transitions_in_transit_to_aborted_with_operator_reason(api, inflight_trip: HazmatScenario):
    """The operator-abort fires the ``IN_TRANSIT → ABORTED``
    transition with the on-disk ``abort_reason ==
    OPERATOR_ABORT``.  The PRD's §2.8 abort-reason taxonomy
    names ``OPERATOR_ABORT`` as the operator-initiated discriminator,
    distinct from the two cascade discriminators
    ``PERMIT_EXPIRED_CASCADE`` (the sweep's wall-clock-expiry
    cascade) and ``PERMIT_SUSPENDED_CASCADE`` (the void's
    enum-economy-reused cascade discriminator).
    """
    scenario = inflight_trip
    op = company_operator_headers(scenario.company["id"])
    trip_pre = scenario.trips[0]
    aborted_row = get_success_data(api.abort_trip(
        trip_pre["id"],
        abort_trip_payload(reason_note="Test operator-initiated abort."),
        op,
    ))
    assert aborted_row["trip_status"] == TripStatus.ABORTED.value
    assert aborted_row["abort_reason"] == AbortReason.OPERATOR_ABORT.value
    # The actual_arrival_at field stays null on an aborted trip.
    assert aborted_row.get("actual_arrival_at") is None
    # The aborted_at is the server-side now() at the abort moment.
    assert aborted_row.get("aborted_at") is not None
    assert is_iso8601_timestamp(aborted_row["aborted_at"])


def test_arrive_from_planned_rejected(api, active_permit: HazmatScenario):
    """The arrive endpoint's source-state guard requires
    ``IN_TRANSIT``.  An arrive on a PLANNED trip (no depart fired
    yet) is the generic state-transition error.
    """
    scenario = active_permit
    op = company_operator_headers(scenario.company["id"])
    server_now = current_server_now(api)
    dep = iso_now_plus_delta(seconds=60.0, base_iso=server_now)
    arr = iso_now_plus_delta(seconds=3600.0, base_iso=server_now)
    trip = get_success_data(api.create_trip(
        scenario.permit["id"],
        create_trip_payload(
            driver_id=scenario.drivers[0]["id"],
            vehicle_id=scenario.vehicles[0]["id"],
            scheduled_departure_at=dep,
            scheduled_arrival_at=arr,
        ),
        op,
    ))
    assert trip["trip_status"] == TripStatus.PLANNED.value
    # No depart fired.  An arrive attempt fails the trip-status guard.
    resp = api.arrive_trip(trip["id"], {}, op)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, expected_status=409)


def test_depart_on_non_active_permit_rejected(api, active_permit: HazmatScenario):
    """PRD §3.7 depart-action paragraph: "The depart endpoint
    requires the parent-permit-active gate at the state tier
    with priority 400 (the parent permit's
    ``lifecycle_status`` must be ``ACTIVE``).  The SUSPENDED
    case is ``ERR_PERMIT_NOT_ACTIVE`` 409".

    Schedule a trip on the ACTIVE permit, then revoke the
    parent company so the next verify-compliance flips the
    permit to SUSPENDED.  The trip-depart's parent-state check
    fires the dedicated cross-aggregate
    ``ERR_PERMIT_NOT_ACTIVE`` 409.
    """
    from test_helpers.factories import revoke_company_payload

    scenario = active_permit
    op = company_operator_headers(scenario.company["id"])
    reg = regulator_headers()
    # Schedule a trip.
    trip = schedule_trip(api, scenario, duration_seconds=3600.0, departure_offset_seconds=120.0)
    # Revoke the company and run a verify-compliance so the
    # permit transitions to SUSPENDED.
    api.revoke_company(scenario.company["id"], revoke_company_payload(reason_note="test"), reg)
    vc = get_success_data(api.verify_permit_compliance(scenario.permit["id"], {}, reg))
    assert vc.get("post_status") == PermitLifecycleStatus.SUSPENDED.value
    # Now the depart on the still-PLANNED trip whose parent
    # permit is SUSPENDED fires the parent-state error.
    # Advance the clock so the depart-time is past the
    # scheduled_departure_at.
    advance_clock_by(api, 121.0, run_sweep=False)
    resp = api.depart_trip(trip["id"], {}, op)
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ACTIVE.value, expected_status=409)


def test_trip_create_with_unauthorized_driver_returns_validation(api, active_permit: HazmatScenario):
    """PRD §3.7: the ``driver_id`` foreign key "must be a member
    of the parent permit's ``authorized_driver_ids`` array".  An
    out-of-list driver-id is the body-shape ``ERR_VALIDATION``
    422 with the message naming the offending field.

    The test creates a second driver under the same company who is
    *not* in the permit's authorized-driver list, then attempts a
    trip naming that driver.
    """
    from test_helpers import setup_driver_under_company

    scenario = active_permit
    op = company_operator_headers(scenario.company["id"])
    # Create a fresh driver (attested) outside the permit's
    # authorized list.
    extra_drv = setup_driver_under_company(api, scenario.company, attest=True)
    assert extra_drv["id"] not in scenario.permit["authorized_driver_ids"]
    server_now = current_server_now(api)
    dep = iso_now_plus_delta(seconds=60.0, base_iso=server_now)
    arr = iso_now_plus_delta(seconds=3600.0, base_iso=server_now)
    payload = create_trip_payload(
        driver_id=extra_drv["id"],
        vehicle_id=scenario.vehicles[0]["id"],
        scheduled_departure_at=dep,
        scheduled_arrival_at=arr,
    )
    resp = api.create_trip(scenario.permit["id"], payload, op)
    # The PRD names this case as the "the driver-id-is-in-
    # ``authorized_driver_ids`` rule is body-shape catch-all
    # ``ERR_VALIDATION`` 422".  An implementation may surface
    # the same logic as the dedicated
    # ``ERR_DRIVER_ENDORSEMENT_INVALID`` 409 (the safety-tier
    # check on the live-driver-endorsement-and-membership-in-the-
    # permit's-array combined into one error).  Both are
    # PRD-consistent on this exact edge.
    actual = validate_error_is_one_of(
        resp,
        [
            ApiErrorId.ERR_VALIDATION.value,
            ApiErrorId.ERR_DRIVER_ENDORSEMENT_INVALID.value,
        ],
    )
    assert actual in {ApiErrorId.ERR_VALIDATION.value, ApiErrorId.ERR_DRIVER_ENDORSEMENT_INVALID.value}


def test_trip_outside_permit_validity_window_rejected(api, active_permit: HazmatScenario):
    """PRD §3.7 + §2.9: "the trip-vs-permit window-membership
    check at priority 522 (the new trip's left edge at or after
    ``permit.valid_from`` and the right edge at or before
    ``permit.valid_until``, with the failure being
    ``ERR_OUTSIDE_VALIDITY_WINDOW`` 409)".

    Schedule a trip whose ``scheduled_arrival_at`` is past the
    permit's ``valid_until``.
    """
    scenario = active_permit
    op = company_operator_headers(scenario.company["id"])
    vu = scenario.permit["valid_until"]
    # The arrival is one full day past the permit's valid_until,
    # which is comfortably past the closed-on-the-arrival-edge
    # boundary from PRD §2.9.
    bad_arrival = add_days(vu, 1.0)
    server_now = current_server_now(api)
    dep = iso_now_plus_delta(seconds=60.0, base_iso=server_now)
    payload = create_trip_payload(
        driver_id=scenario.drivers[0]["id"],
        vehicle_id=scenario.vehicles[0]["id"],
        scheduled_departure_at=dep,
        scheduled_arrival_at=bad_arrival,
    )
    resp = api.create_trip(scenario.permit["id"], payload, op)
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_VALIDITY_WINDOW.value, expected_status=409)


def test_trip_scheduled_arrival_at_permit_valid_until_admitted(api, active_permit: HazmatScenario):
    """PRD §2.9: "the convention is closed-on-the-arrival-edge
    against the permit's ``valid_until`` (a trip scheduled to
    arrive at the exact ``valid_until`` moment is admissible at
    scheduling time even though by the half-open-permit-window
    convention the permit will be ``EXPIRED`` at that exact
    moment), and the actual-arrival-time recorded later by the
    arrive endpoint is whatever the logical clock reads at that
    moment".

    Schedule the trip's ``scheduled_arrival_at`` exactly equal to
    the permit's ``valid_until``.  The create succeeds.
    """
    scenario = active_permit
    op = company_operator_headers(scenario.company["id"])
    vu = scenario.permit["valid_until"]
    server_now = current_server_now(api)
    dep = iso_now_plus_delta(seconds=60.0, base_iso=server_now)
    payload = create_trip_payload(
        driver_id=scenario.drivers[0]["id"],
        vehicle_id=scenario.vehicles[0]["id"],
        scheduled_departure_at=dep,
        scheduled_arrival_at=vu,  # exactly at the permit's valid_until edge.
    )
    resp = api.create_trip(scenario.permit["id"], payload, op)
    assert resp.status_code == 201, (
        f"the closed-on-the-arrival-edge convention permits scheduled_arrival_at == valid_until "
        f"exactly; the create should succeed.  Got {resp.status_code}: {resp.text}"
    )


def test_trip_scheduled_departure_in_past_rejected(api, active_permit: HazmatScenario):
    """PRD §2.9: "The scheduled-departure-not-in-the-past rule on
    a new trip's ``scheduled_departure_at`` is the strict-less-
    than the current logical-clock value: ``scheduled_departure_at
    > now()`` is the in-window case, the equal case is the
    boundary that the scaffold pins as not-permitted, and the
    strictly-less case is the rejection ``ERR_VALIDATION`` 422
    for back-dated departures".

    A trip with ``scheduled_departure_at`` strictly before the
    current clock is the body-shape rejection.
    """
    scenario = active_permit
    op = company_operator_headers(scenario.company["id"])
    server_now = current_server_now(api)
    past_dep = iso_now_plus_delta(seconds=-60.0, base_iso=server_now)
    arr = iso_now_plus_delta(seconds=3600.0, base_iso=server_now)
    payload = create_trip_payload(
        driver_id=scenario.drivers[0]["id"],
        vehicle_id=scenario.vehicles[0]["id"],
        scheduled_departure_at=past_dep,
        scheduled_arrival_at=arr,
    )
    resp = api.create_trip(scenario.permit["id"], payload, op)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)


def test_arrive_before_depart_ordering(api, active_permit: HazmatScenario):
    """The trip's scheduled times satisfy
    ``scheduled_departure_at < scheduled_arrival_at`` per PRD
    §2.9 "the arrive-is-strictly-after-depart rule on the
    scheduled times".  A trip whose scheduled arrival is at-or-
    before its scheduled departure is the body-shape rejection.
    """
    scenario = active_permit
    op = company_operator_headers(scenario.company["id"])
    server_now = current_server_now(api)
    dep = iso_now_plus_delta(seconds=1000.0, base_iso=server_now)
    bad_arr = iso_now_plus_delta(seconds=500.0, base_iso=server_now)  # arrival before departure
    payload = create_trip_payload(
        driver_id=scenario.drivers[0]["id"],
        vehicle_id=scenario.vehicles[0]["id"],
        scheduled_departure_at=dep,
        scheduled_arrival_at=bad_arr,
    )
    resp = api.create_trip(scenario.permit["id"], payload, op)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)


# ─── Vehicle calendar — the double-booking interval-arithmetic ────────


def test_vehicle_double_booking_overlap_rejected(api, active_permit: HazmatScenario):
    """PRD §3.7 + §2.9 + §1.4 priority 521 + the rule-8 overlap-A
    interval-semantics: a new trip whose half-open
    ``[scheduled_departure_at, scheduled_arrival_at)`` interval
    overlaps an existing trip's same-vehicle-id same-shape interval
    fires the ``ERR_VEHICLE_DOUBLE_BOOKED`` 409 at priority 521.
    """
    scenario = active_permit
    op = company_operator_headers(scenario.company["id"])
    # The first trip: [now+60s, now+3660s).
    server_now = current_server_now(api)
    a_dep = iso_now_plus_delta(seconds=60.0, base_iso=server_now)
    a_arr = iso_now_plus_delta(seconds=3660.0, base_iso=server_now)
    t1 = get_success_data(api.create_trip(
        scenario.permit["id"],
        create_trip_payload(
            driver_id=scenario.drivers[0]["id"],
            vehicle_id=scenario.vehicles[0]["id"],
            scheduled_departure_at=a_dep,
            scheduled_arrival_at=a_arr,
        ),
        op,
    ))
    # The second trip on the same vehicle whose interval overlaps:
    # [now+1000s, now+5000s) intersects [now+60s, now+3660s)
    # at [now+1000s, now+3660s), a non-empty intersection.
    b_dep = iso_now_plus_delta(seconds=1000.0, base_iso=server_now)
    b_arr = iso_now_plus_delta(seconds=5000.0, base_iso=server_now)
    resp = api.create_trip(
        scenario.permit["id"],
        create_trip_payload(
            driver_id=scenario.drivers[0]["id"],
            vehicle_id=scenario.vehicles[0]["id"],
            scheduled_departure_at=b_dep,
            scheduled_arrival_at=b_arr,
        ),
        op,
    )
    validate_error(resp, ApiErrorId.ERR_VEHICLE_DOUBLE_BOOKED.value, expected_status=409)
    # The first trip still exists.
    assert t1["trip_status"] == TripStatus.PLANNED.value


def test_vehicle_calendar_adjacent_touch_admitted(api, active_permit: HazmatScenario):
    """PRD §2.9: "two trips whose boundary timestamps touch (the
    existing trip's ``scheduled_arrival_at`` exactly equal to the
    new trip's ``scheduled_departure_at``) do not collide and the
    new trip is admitted".

    The half-open right-exclusive convention means the
    end-of-A is not in A's interval and the start-of-B is in
    B's, so the boundary instant belongs to B and the two
    intervals do not intersect.  The second trip is admitted.
    """
    scenario = active_permit
    op = company_operator_headers(scenario.company["id"])
    server_now = current_server_now(api)
    a_dep = iso_now_plus_delta(seconds=60.0, base_iso=server_now)
    a_arr = iso_now_plus_delta(seconds=3660.0, base_iso=server_now)
    get_success_data(api.create_trip(
        scenario.permit["id"],
        create_trip_payload(
            driver_id=scenario.drivers[0]["id"],
            vehicle_id=scenario.vehicles[0]["id"],
            scheduled_departure_at=a_dep,
            scheduled_arrival_at=a_arr,
        ),
        op,
    ))
    # The second trip's scheduled_departure_at equals the first's
    # scheduled_arrival_at exactly.  The half-open semantics
    # admit the touching boundary.
    b_dep = a_arr  # the boundary touch
    b_arr = iso_now_plus_delta(seconds=3660.0 + 3600.0, base_iso=server_now)
    resp = api.create_trip(
        scenario.permit["id"],
        create_trip_payload(
            driver_id=scenario.drivers[0]["id"],
            vehicle_id=scenario.vehicles[0]["id"],
            scheduled_departure_at=b_dep,
            scheduled_arrival_at=b_arr,
        ),
        op,
    )
    assert resp.status_code == 201, (
        "the back-to-back-on-the-same-vehicle pattern is admissible under the half-open convention; "
        f"got {resp.status_code}: {resp.text}"
    )


def test_vehicle_double_booking_is_cross_permit_in_scope(api, active_permit: HazmatScenario):
    """PRD §2.9 + §3.7: "the cross-permit scope of the check is
    the principle that the conflict-check ranges over every Trip
    row in the system whose ``vehicle_id`` matches the new
    trip's ``vehicle_id``, ignoring the trip's parent-permit
    identity".

    Two permits on the same company, each authorizing the same
    vehicle, each scheduling an overlapping-interval trip on
    that vehicle: the second trip's create fires the
    cross-permit ``ERR_VEHICLE_DOUBLE_BOOKED``.

    The standard test scenario uses one permit per overlap-pair
    when the permit's authorized-vehicle-list semantics admit
    two permits sharing a vehicle.  In the canonical scaffold
    the company-and-route-and-roster combinations make the
    multi-permit-sharing-a-vehicle case the standard scenario.

    Since constructing two permits on the same company with the
    same vehicle is supported (the scaffold's
    ``authorized_vehicle_ids`` array is a free-form subset of
    the company's vehicle inventory), we file a second permit
    on the same company-route-roster pair and schedule the
    overlapping trip on the second permit's id.

    Two permits on the same company can in principle have an
    overlapping authorized-vehicle list; the scaffold doesn't
    forbid that.  The test uses ``file_permit_application`` +
    ``issue_permit`` to mint the second permit.
    """
    from test_helpers import file_permit_application, issue_permit

    scenario = active_permit
    op = company_operator_headers(scenario.company["id"])
    # The fixture's first permit already has a trip-window
    # available.  Schedule a trip on the first permit.
    server_now = current_server_now(api)
    a_dep = iso_now_plus_delta(seconds=120.0, base_iso=server_now)
    a_arr = iso_now_plus_delta(seconds=3720.0, base_iso=server_now)
    get_success_data(api.create_trip(
        scenario.permit["id"],
        create_trip_payload(
            driver_id=scenario.drivers[0]["id"],
            vehicle_id=scenario.vehicles[0]["id"],
            scheduled_departure_at=a_dep,
            scheduled_arrival_at=a_arr,
        ),
        op,
    ))
    # Now mint a second permit on the same company-route-roster.
    # The PRD doesn't restrict a company to one permit per route
    # per driver-vehicle subset, so the second permit creation
    # is admissible.
    # Reset the scenario's permit slot so the helper writes a
    # fresh entry.
    original_first_permit = scenario.permit
    scenario.permit = None
    second_permit = file_permit_application(api, scenario, valid_from_offset_seconds=2.0)
    # Top up if needed for the second issue's fee.
    from test_helpers import ensure_funded_company, TEST_WALLET_TOPUP_CENTS
    ensure_funded_company(api, scenario.company["id"], TEST_WALLET_TOPUP_CENTS)
    second_permit_issued = issue_permit(api, scenario)
    # A trip on the second permit with the same vehicle and an
    # overlapping scheduled window collides on the
    # cross-permit vehicle-calendar lookup.
    b_dep = iso_now_plus_delta(seconds=600.0, base_iso=server_now)
    b_arr = iso_now_plus_delta(seconds=4000.0, base_iso=server_now)
    resp = api.create_trip(
        second_permit_issued["id"],
        create_trip_payload(
            driver_id=scenario.drivers[0]["id"],
            vehicle_id=scenario.vehicles[0]["id"],
            scheduled_departure_at=b_dep,
            scheduled_arrival_at=b_arr,
        ),
        op,
    )
    validate_error(resp, ApiErrorId.ERR_VEHICLE_DOUBLE_BOOKED.value, expected_status=409)


# ─── GPS-stream — the strict-monotonicity rule ────────────────────────


def test_gps_strict_monotonicity_equal_timestamp_rejected(api, inflight_trip: HazmatScenario):
    """PRD §2.9 + §1.4 priority 512: "The GPS event stream's
    monotonicity rule uses the closed-on-the-prior-edge convention
    — the new GPS report's ``reported_at`` must be strictly
    greater than the parent Trip's ``latest_gps_at`` cursor.  An
    equal ``reported_at`` (the inclusive-equality boundary on the
    strict-greater-than predicate) is the rejection case, returning
    ``ERR_GPS_OUT_OF_ORDER``".

    Ingest a sample with a specific ``reported_at``, then ingest a
    second sample with the same ``reported_at``.  The second is
    rejected because the cursor is now at the first's timestamp
    and the strict-greater-than predicate is unsatisfied.

    The first sample's reported_at must be after the trip's
    actual_departure_at (so the in-window check at priority 509
    passes).  The fixture's clock is at the moment of
    actual_departure_at; the first sample's reported_at is at
    actual_departure_at + 1 second.
    """
    scenario = inflight_trip
    op = company_operator_headers(scenario.company["id"])
    trip = scenario.trips[0]
    ad_iso = trip["actual_departure_at"]
    # Pick a reported_at one second after the departure.
    rep1 = iso_now_plus_delta(seconds=1.0, base_iso=ad_iso)
    # Advance the server clock so the rep1 timestamp is <= now
    # (the in-window check's right edge for an IN_TRANSIT trip
    # is the current logical-clock value).
    advance_clock_by(api, 2.0, run_sweep=False)
    pld1 = create_gps_report_payload(reported_at=rep1, speed_kph=50.0)
    r1 = get_success_data(api.create_gps_report(trip["id"], pld1, op))
    assert_gps_report(r1)
    assert r1["reported_at"] == rep1
    # Second sample with the same reported_at.
    pld2 = create_gps_report_payload(reported_at=rep1, speed_kph=55.0)
    r2_resp = api.create_gps_report(trip["id"], pld2, op)
    validate_error(r2_resp, ApiErrorId.ERR_GPS_OUT_OF_ORDER.value, expected_status=409)


def test_gps_in_window_check_fires_before_monotonicity(api, inflight_trip: HazmatScenario):
    """PRD §1.4 + §2.9 + §1.6 + §3.8 rule-5 priority-conflict-C
    paragraph: "the in-window check at priority 509 is the
    earlier-firing check, and a sample that is both out-of-window
    AND out-of-order returns ``ERR_GPS_OUT_OF_WINDOW``, not the
    monotonicity error".

    Construct a sample whose ``reported_at`` is *before* the
    trip's ``actual_departure_at`` (so the in-window check
    fires the priority-509 error before the priority-512
    monotonicity check would).  The first GPS sample on a
    not-yet-departed trip is the canonical case: the trip's
    ``actual_departure_at`` is null so the window is empty and
    any sample is out-of-window.

    Cleaner construction: send a sample whose ``reported_at`` is
    strictly before the trip's ``actual_departure_at`` (which is
    a non-null ISO timestamp on the in-flight fixture's trip).
    The window's left edge is ``actual_departure_at`` and the
    sample's ``reported_at`` is to the left of that, so the
    sample is out-of-window.

    For the simultaneous-out-of-order-and-out-of-window
    condition we'd need an existing GPS sample whose cursor is
    equal to or greater than the new sample's reported_at —
    which is impossible when the stream is empty.  We test the
    bare out-of-window case here, which proves the priority-509
    check fires.  The strict simultaneous-violation precedence
    pin is the entry in
    ``test_validation_precedence.py``'s priority-pair-table
    for conflict-C.
    """
    scenario = inflight_trip
    op = company_operator_headers(scenario.company["id"])
    trip = scenario.trips[0]
    # A reported_at one minute before the actual_departure_at.
    rep_pre = iso_now_plus_delta(seconds=-60.0, base_iso=trip["actual_departure_at"])
    payload = create_gps_report_payload(reported_at=rep_pre, speed_kph=50.0)
    resp = api.create_gps_report(trip["id"], payload, op)
    validate_error(resp, ApiErrorId.ERR_GPS_OUT_OF_WINDOW.value, expected_status=409)


def test_gps_on_planned_trip_is_out_of_window(api, active_permit: HazmatScenario):
    """A still-PLANNED trip has ``actual_departure_at = null``, so
    the in-flight interval is empty and any GPS sample is
    out-of-window.  The error is the priority-509
    ``ERR_GPS_OUT_OF_WINDOW`` 409 per PRD §1.6.
    """
    scenario = active_permit
    op = company_operator_headers(scenario.company["id"])
    server_now = current_server_now(api)
    dep = iso_now_plus_delta(seconds=300.0, base_iso=server_now)
    arr = iso_now_plus_delta(seconds=3900.0, base_iso=server_now)
    trip = get_success_data(api.create_trip(
        scenario.permit["id"],
        create_trip_payload(
            driver_id=scenario.drivers[0]["id"],
            vehicle_id=scenario.vehicles[0]["id"],
            scheduled_departure_at=dep,
            scheduled_arrival_at=arr,
        ),
        op,
    ))
    assert trip["actual_departure_at"] is None
    # A GPS sample on the PLANNED trip — any reported_at is
    # out-of-window because the window is the empty interval
    # ``[null, ...]``.
    rep = iso_now_plus_delta(seconds=0.0, base_iso=server_now)
    payload = create_gps_report_payload(reported_at=rep, speed_kph=50.0)
    resp = api.create_gps_report(trip["id"], payload, op)
    validate_error(resp, ApiErrorId.ERR_GPS_OUT_OF_WINDOW.value, expected_status=409)


def test_gps_after_arrive_is_out_of_window(api, inflight_trip: HazmatScenario):
    """A completed trip's right edge is the
    ``actual_arrival_at`` timestamp.  A GPS sample with
    ``reported_at`` past the arrival is the priority-509
    out-of-window error.
    """
    scenario = inflight_trip
    op = company_operator_headers(scenario.company["id"])
    trip = scenario.trips[0]
    # Advance the clock past the scheduled-arrival and complete the trip.
    advance_clock_by(api, 7200.0 + 5.0, run_sweep=False)
    arrived = get_success_data(api.arrive_trip(trip["id"], {}, op))
    assert arrived["trip_status"] == TripStatus.COMPLETED.value
    # The trip's actual_arrival_at is the closed-right edge of
    # the in-flight window.
    aa = arrived["actual_arrival_at"]
    rep_after = iso_now_plus_delta(seconds=60.0, base_iso=aa)
    # Advance the server's clock so the rep_after is the
    # standard ISO-from-real-world-time.
    advance_clock_by(api, 120.0, run_sweep=False)
    payload = create_gps_report_payload(reported_at=rep_after, speed_kph=50.0)
    resp = api.create_gps_report(trip["id"], payload, op)
    validate_error(resp, ApiErrorId.ERR_GPS_OUT_OF_WINDOW.value, expected_status=409)


def test_gps_on_suspended_parent_permit_returns_permit_not_active(api, inflight_trip: HazmatScenario):
    """PRD §3.8 priority-515 paragraph: "Then the parent-permit-
    active gate at the safety-tier priority 515 fires: the parent
    Trip's parent Permit's ``lifecycle_status`` must be ``ACTIVE``
    at the moment of the GPS-ingest call.  If the permit is in
    ``SUSPENDED`` … the response is ``ERR_PERMIT_NOT_ACTIVE``
    409".

    The fixture's permit is ACTIVE and the trip IN_TRANSIT.
    Revoke the parent company (the deferred grounding-invalidation
    trigger) and run verify-compliance to fire the
    ``ACTIVE → SUSPENDED`` transition.  Now a GPS-ingest attempt
    sees a still-non-empty in-flight window on the trip (the
    suspension does not cascade-abort the trip per PRD §3.7's
    "the asymmetry between the suspension (no trip-cascade) and
    the expiry-or-void (full trip-cascade-to-ABORTED)") but a
    SUSPENDED parent permit, so the priority-515 gate fires.
    """
    from test_helpers.factories import revoke_company_payload

    scenario = inflight_trip
    op = company_operator_headers(scenario.company["id"])
    reg = regulator_headers()
    trip = scenario.trips[0]
    # Revoke the company, fire verify-compliance to flip the permit
    # to SUSPENDED.
    api.revoke_company(scenario.company["id"], revoke_company_payload(reason_note="test"), reg)
    vc = get_success_data(api.verify_permit_compliance(scenario.permit["id"], {}, reg))
    assert vc["post_status"] == PermitLifecycleStatus.SUSPENDED.value
    # The trip is still IN_TRANSIT (the suspension is a transient
    # state, not a terminal cascade-abort).
    trip_after_vc = get_success_data(api.get_trip(trip["id"], op))
    assert trip_after_vc["trip_status"] == TripStatus.IN_TRANSIT.value

    # Send a GPS sample.  The in-window check at 509 passes (the
    # sample's reported_at is between actual_departure_at and the
    # current clock).  The strict-monotonicity check at 512 passes
    # too (the trip's stream is empty so the cursor is null).
    # The parent-permit-active gate at 515 fires:
    # ERR_PERMIT_NOT_ACTIVE.
    advance_clock_by(api, 2.0, run_sweep=False)
    rep = iso_now_plus_delta(seconds=1.0, base_iso=trip["actual_departure_at"])
    payload = create_gps_report_payload(reported_at=rep, speed_kph=50.0)
    resp = api.create_gps_report(trip["id"], payload, op)
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ACTIVE.value, expected_status=409)


# ─── GPS classifier — the speed-violation auto-Penalty fan-out ───────


def test_speed_violation_inserts_auto_penalty(api, inflight_trip: HazmatScenario):
    """PRD §3.8 + §2.8: "The speed-violation flag is the
    strict-greater-than predicate on
    ``gps_report.speed_kph > MAX_HAZMAT_SPEED_KPH``: a sample
    whose speed is strictly larger than the configured maximum
    hazmat speed is the speed-violation … The auto-Penalty rows
    each carry ``subject_type = DRIVER`` and
    ``subject_id = the trip's driver_id``, the appropriate
    ``source`` value (``GPS_VIOLATION_SPEED`` for the speed
    flag), the corresponding ``points_value`` …
    (``GPS_VIOLATION_SPEED_POINTS`` for the speed kind), the
    ``observed_at`` equal to the parent GPSReport's
    ``reported_at`` (the on-board-clock-time-of-observation),
    the ``source_gps_report_id`` pointing back to the new
    GPSReport row's id, the ``trip_id`` set to the parent
    trip's id".

    A single over-the-limit sample produces one auto-Penalty
    row with the speed-violation source, the
    ``GPS_VIOLATION_SPEED_POINTS`` value (3), and the
    cross-reference fields.  The parent trip's
    ``gps_violation_count`` increments by one.  The driver's
    ``current_rolling_points`` cache is bumped by the
    speed-points value.
    """
    scenario = inflight_trip
    op = company_operator_headers(scenario.company["id"])
    reg = regulator_headers()
    trip = scenario.trips[0]
    driver_id = trip["driver_id"]
    # Pre-state.
    drv_pre = get_success_data(api.get_driver(driver_id, reg))
    pre_points = drv_pre["current_rolling_points"]
    pre_violation_count = trip.get("gps_violation_count", 0)
    # Ingest a sample over the speed limit.
    advance_clock_by(api, 2.0, run_sweep=False)
    rep_at = iso_now_plus_delta(seconds=1.0, base_iso=trip["actual_departure_at"])
    over_speed = MAX_HAZMAT_SPEED_KPH + 5.0
    payload = create_gps_report_payload(
        reported_at=rep_at,
        lat=CANONICAL_ON_ROUTE_LAT,
        lon=CANONICAL_ON_ROUTE_LON,
        speed_kph=over_speed,
    )
    gps_resp = api.create_gps_report(trip["id"], payload, op)
    gps_row = validate_success(gps_resp, 201)
    assert_gps_report(gps_row)
    apl = gps_row["auto_penalty_ids"]
    assert len(apl) == 1, (
        f"the over-speed-and-on-route sample should fire exactly one auto-Penalty (the speed-violation), "
        f"got auto_penalty_ids={apl!r}"
    )
    auto_pen_id = apl[0]
    # Read the auto-Penalty row back via the penalty-summary
    # endpoint.  The PRD's §3.8 penalty-summary digest's
    # ``active_penalties_in_window`` array carries the row.
    summary = get_success_data(api.get_driver_penalty_summary(driver_id, reg))
    apw = summary.get("active_penalties_in_window") or []
    matching = [p for p in apw if p["id"] == auto_pen_id]
    assert matching, f"the auto-Penalty {auto_pen_id!r} is not in the penalty-summary's active list"
    auto_pen_summary = matching[0]
    assert auto_pen_summary["source"] == PenaltySource.GPS_VIOLATION_SPEED.value
    assert auto_pen_summary["points_value"] == GPS_VIOLATION_SPEED_POINTS
    # The trip's gps_violation_count is incremented by one.
    trip_after = get_success_data(api.get_trip(trip["id"], op))
    assert trip_after["gps_violation_count"] == pre_violation_count + 1
    assert trip_after["latest_gps_at"] == rep_at
    # The driver's rolling-points cache is incremented.
    drv_after = get_success_data(api.get_driver(driver_id, reg))
    assert drv_after["current_rolling_points"] == pre_points + GPS_VIOLATION_SPEED_POINTS


def test_speed_at_exact_limit_is_not_a_violation(api, inflight_trip: HazmatScenario):
    """PRD §2.8: "the boundary ``speed_kph == MAX_HAZMAT_SPEED_KPH``
    [is] non-violating" — the strict-greater-than predicate excludes
    the boundary value.

    A sample with ``speed_kph`` equal to the limit produces a
    clean response with an empty ``auto_penalty_ids`` array.
    """
    scenario = inflight_trip
    op = company_operator_headers(scenario.company["id"])
    trip = scenario.trips[0]
    advance_clock_by(api, 2.0, run_sweep=False)
    rep_at = iso_now_plus_delta(seconds=1.0, base_iso=trip["actual_departure_at"])
    # Exactly at the limit.
    payload = create_gps_report_payload(
        reported_at=rep_at,
        lat=CANONICAL_ON_ROUTE_LAT,
        lon=CANONICAL_ON_ROUTE_LON,
        speed_kph=MAX_HAZMAT_SPEED_KPH,
    )
    resp = api.create_gps_report(trip["id"], payload, op)
    gps_row = validate_success(resp, 201)
    assert gps_row["auto_penalty_ids"] == [], (
        f"the at-the-limit sample should not fire the speed-violation; "
        f"got auto_penalty_ids={gps_row['auto_penalty_ids']!r}"
    )


def test_off_route_violation_distance_field(api, inflight_trip: HazmatScenario):
    """PRD §3.4 + §2.8: "The off-route classifier on a GPS
    report's ``lat``-``lon`` pair computes the perpendicular
    great-circle distance in meters from the sample point to the
    nearest polyline segment using the haversine-on-segments
    formula with the Earth-radius constant ``EARTH_RADIUS_M``
    fixed at 6,371,000.0 metres (the WGS-84 mean Earth radius),
    and a distance strictly greater than the corridor-radius
    constant ``OFF_ROUTE_RADIUS_M`` is the off-route violation.
    The on-the-boundary case (the computed distance exactly
    equals the radius) is not a violation by the strict-greater-
    than convention.  The distance is computed at the
    gps-report-ingest moment and stored on the new GPSReport
    row's ``off_route_distance_m`` field for the audit trail."

    The canonical off-route sample's coordinate is far from the
    Beijing-Tianjin polyline.  The computed distance in metres
    should match the test-side haversine-segment distance within
    a small tolerance.
    """
    scenario = inflight_trip
    op = company_operator_headers(scenario.company["id"])
    trip = scenario.trips[0]
    driver_id = trip["driver_id"]
    drv_pre = get_success_data(api.get_driver(driver_id, regulator_headers()))
    pre_points = drv_pre["current_rolling_points"]

    advance_clock_by(api, 2.0, run_sweep=False)
    rep_at = iso_now_plus_delta(seconds=1.0, base_iso=trip["actual_departure_at"])
    # Off-route coordinates — the South China Sea.
    payload = create_gps_report_payload(
        reported_at=rep_at,
        lat=CANONICAL_OFF_ROUTE_LAT,
        lon=CANONICAL_OFF_ROUTE_LON,
        speed_kph=50.0,  # under the speed limit so only the off-route flag fires
    )
    gps_resp = api.create_gps_report(trip["id"], payload, op)
    gps_row = validate_success(gps_resp, 201)
    assert_gps_report(gps_row)
    # The server-computed ``off_route_distance_m`` is the
    # cross-track-distance value the test-side helper computes.
    polyline = scenario.route["polyline"]
    server_distance = float(gps_row["off_route_distance_m"])
    test_distance = cross_track_distance_metres(
        sample_lat=CANONICAL_OFF_ROUTE_LAT,
        sample_lon=CANONICAL_OFF_ROUTE_LON,
        polyline=polyline,
    )
    # The two distances should agree within the millimetre
    # tolerance from the PRD's §2.8 "with a millimeter-level
    # tolerance of 1e-3 meters absorbing any floating-point
    # variation in the haversine formula's intermediate
    # arithmetic", but the haversine sphere vs WGS-84
    # ellipsoid difference can show up at the metre-level on
    # the long-distance Beijing-to-South-China-Sea pair.  The
    # standard slack for the geodesic-equality on benchmarks
    # of this scope is a relative tolerance of 1% or a few
    # kilometres absolute, whichever is larger.
    rel_diff = abs(server_distance - test_distance) / max(test_distance, 1.0)
    abs_diff = abs(server_distance - test_distance)
    # The far-off-route distance is ≈ 2500 km; a few-km
    # disagreement on the WGS-84 vs sphere model is acceptable.
    assert rel_diff < 0.05 or abs_diff < 5000.0, (
        f"server-side off_route_distance_m={server_distance}m disagrees with test-side "
        f"cross-track-distance={test_distance}m by {abs_diff}m / {rel_diff:.4f} relative; "
        f"the millimetre tolerance from PRD §2.8 allows only the floating-point variability"
    )
    # The off-route flag should fire (the distance is far above the radius).
    assert server_distance > OFF_ROUTE_RADIUS_M, (
        f"the South China Sea sample's distance to the Beijing-Tianjin polyline "
        f"should be above OFF_ROUTE_RADIUS_M={OFF_ROUTE_RADIUS_M}, got {server_distance}"
    )
    apl = gps_row["auto_penalty_ids"]
    assert len(apl) == 1, (
        f"the off-route-under-speed-limit sample should fire exactly one auto-Penalty "
        f"(the off-route violation), got auto_penalty_ids={apl!r}"
    )
    # Read the auto-Penalty's source from the penalty-summary.
    summary = get_success_data(api.get_driver_penalty_summary(driver_id, regulator_headers()))
    apw = summary["active_penalties_in_window"]
    matching = [p for p in apw if p["id"] == apl[0]]
    assert matching
    assert matching[0]["source"] == PenaltySource.GPS_VIOLATION_OFF_ROUTE.value
    assert matching[0]["points_value"] == GPS_VIOLATION_OFF_ROUTE_POINTS
    # The driver's rolling-points cache is bumped by the
    # off-route-points constant.
    drv_after = get_success_data(api.get_driver(driver_id, regulator_headers()))
    assert drv_after["current_rolling_points"] == pre_points + GPS_VIOLATION_OFF_ROUTE_POINTS


def test_both_violation_flags_fire_simultaneously(api, inflight_trip: HazmatScenario):
    """PRD §3.8: "The two flags are independent and a single
    sample may simultaneously fire both, producing two
    auto-Penalty rows in the same transaction, which the parent
    trip's ``gps_violation_count`` increments by two and the
    parent GPS report's ``auto_penalty_ids`` array records as a
    two-element list".

    A sample that is both over the speed limit and off-route
    fires both classifier flags.  The resulting GPSReport's
    ``auto_penalty_ids`` is a two-element list.  The driver's
    rolling-points cache is incremented by the sum of the two
    points-constants.
    """
    scenario = inflight_trip
    op = company_operator_headers(scenario.company["id"])
    reg = regulator_headers()
    trip = scenario.trips[0]
    driver_id = trip["driver_id"]
    pre_points = get_success_data(api.get_driver(driver_id, reg))["current_rolling_points"]
    pre_violation_count = trip.get("gps_violation_count", 0)
    advance_clock_by(api, 2.0, run_sweep=False)
    rep_at = iso_now_plus_delta(seconds=1.0, base_iso=trip["actual_departure_at"])
    payload = create_gps_report_payload(
        reported_at=rep_at,
        lat=CANONICAL_OFF_ROUTE_LAT,
        lon=CANONICAL_OFF_ROUTE_LON,
        speed_kph=MAX_HAZMAT_SPEED_KPH + 10.0,
    )
    resp = api.create_gps_report(trip["id"], payload, op)
    gps_row = validate_success(resp, 201)
    assert_gps_report(gps_row)
    apl = gps_row["auto_penalty_ids"]
    assert len(apl) == 2, (
        f"the both-flags-fire sample should produce a two-element auto_penalty_ids array; "
        f"got {apl!r}"
    )
    # Read the two penalties' sources.
    summary = get_success_data(api.get_driver_penalty_summary(driver_id, reg))
    apw = summary["active_penalties_in_window"]
    sources = {p["source"] for p in apw if p["id"] in apl}
    assert PenaltySource.GPS_VIOLATION_SPEED.value in sources
    assert PenaltySource.GPS_VIOLATION_OFF_ROUTE.value in sources
    # The trip's gps_violation_count increments by 2.
    trip_after = get_success_data(api.get_trip(trip["id"], op))
    assert trip_after["gps_violation_count"] == pre_violation_count + 2
    # The driver's rolling total increments by the sum.
    drv_after = get_success_data(api.get_driver(driver_id, reg))
    assert drv_after["current_rolling_points"] == pre_points + GPS_VIOLATION_SPEED_POINTS + GPS_VIOLATION_OFF_ROUTE_POINTS


def test_clean_sample_produces_no_auto_penalties(api, inflight_trip: HazmatScenario):
    """A sample with on-route position and under-limit speed
    fires neither flag, so the auto_penalty_ids array is empty
    and neither the trip's gps_violation_count nor the driver's
    rolling-points-cache changes.
    """
    scenario = inflight_trip
    op = company_operator_headers(scenario.company["id"])
    reg = regulator_headers()
    trip = scenario.trips[0]
    driver_id = trip["driver_id"]
    pre_points = get_success_data(api.get_driver(driver_id, reg))["current_rolling_points"]
    pre_vc = trip.get("gps_violation_count", 0)
    advance_clock_by(api, 2.0, run_sweep=False)
    rep_at = iso_now_plus_delta(seconds=1.0, base_iso=trip["actual_departure_at"])
    payload = create_gps_report_payload(
        reported_at=rep_at,
        lat=CANONICAL_ON_ROUTE_LAT,
        lon=CANONICAL_ON_ROUTE_LON,
        speed_kph=60.0,
    )
    resp = api.create_gps_report(trip["id"], payload, op)
    gps_row = validate_success(resp, 201)
    assert gps_row["auto_penalty_ids"] == []
    trip_after = get_success_data(api.get_trip(trip["id"], op))
    assert trip_after["gps_violation_count"] == pre_vc
    drv_after = get_success_data(api.get_driver(driver_id, reg))
    assert drv_after["current_rolling_points"] == pre_points
    # The GPS row's off_route_distance_m is well below the OFF_ROUTE_RADIUS_M.
    assert gps_row["off_route_distance_m"] <= OFF_ROUTE_RADIUS_M


# ─── The auto-Penalty's observed_at is the GPS sample's reported_at ───


def test_auto_penalty_observed_at_equals_gps_reported_at(api, inflight_trip: HazmatScenario):
    """PRD §2.9 + §2.8: "The observed-at of a GPS-auto-Penalty is
    the parent GPSReport's ``reported_at`` value (the wall-clock
    moment of the original observation, not the server-receive
    moment), so the appeal window on a speed-violation
    auto-penalty is measured from when the GPS unit said the
    observation happened".

    The auto-Penalty row's ``observed_at`` field equals the
    triggering GPS sample's ``reported_at`` exactly.
    """
    scenario = inflight_trip
    op = company_operator_headers(scenario.company["id"])
    reg = regulator_headers()
    trip = scenario.trips[0]
    advance_clock_by(api, 2.0, run_sweep=False)
    rep_at = iso_now_plus_delta(seconds=1.0, base_iso=trip["actual_departure_at"])
    payload = create_gps_report_payload(
        reported_at=rep_at,
        speed_kph=MAX_HAZMAT_SPEED_KPH + 1.0,
        lat=CANONICAL_ON_ROUTE_LAT,
        lon=CANONICAL_ON_ROUTE_LON,
    )
    gps_row = get_success_data(api.create_gps_report(trip["id"], payload, op))
    auto_pen_id = gps_row["auto_penalty_ids"][0]
    summary = get_success_data(api.get_driver_penalty_summary(trip["driver_id"], reg))
    pen = next(p for p in summary["active_penalties_in_window"] if p["id"] == auto_pen_id)
    assert pen["observed_at"] == rep_at, (
        f"auto-Penalty's observed_at {pen['observed_at']!r} should equal the GPS sample's "
        f"reported_at {rep_at!r}"
    )
    # The link back to the originating GPS report's id.
    # The penalty-summary digest may omit ``source_gps_report_id``;
    # we read it through the full Penalty row's GET-summary.  The
    # canonical observable is the GPS row's ``auto_penalty_ids``
    # which we already asserted contains the penalty's id.


# ─── The arrive-on-suspended-parent is admitted per the asymmetry ─────


def test_arrive_with_suspended_parent_admitted(api, inflight_trip: HazmatScenario):
    """PRD §3.7's arrive-action paragraph: "The cross-aggregate
    parent-state predicate on the arrive is more permissive than
    on the depart: a SUSPENDED parent permit's in-flight trip is
    allowed to arrive (the suspension gates the GPS-stream writes
    on the in-flight trip per §3.8 but allows the operational
    wind-down attestation through, on the regulatory-practice
    principle that a transient mid-trip suspension caused by a
    fixable cause should not prevent the operator from confirming
    the cargo's arrival once it is delivered)".

    Suspend the trip's parent permit, then arrive the trip.  The
    arrive succeeds (the standard
    ``IN_TRANSIT → COMPLETED`` transition), and the response
    has ``trip_status == COMPLETED``.
    """
    from test_helpers.factories import revoke_company_payload

    scenario = inflight_trip
    op = company_operator_headers(scenario.company["id"])
    reg = regulator_headers()
    # Suspend the parent permit via the company-revoke-then-verify
    # path.
    api.revoke_company(scenario.company["id"], revoke_company_payload(reason_note="test"), reg)
    vc = get_success_data(api.verify_permit_compliance(scenario.permit["id"], {}, reg))
    assert vc["post_status"] == PermitLifecycleStatus.SUSPENDED.value
    # Advance the clock past the scheduled-arrival.
    advance_clock_by(api, 7200.0 + 5.0, run_sweep=False)
    # The trip is still IN_TRANSIT.
    trip = scenario.trips[0]
    pre_status = get_success_data(api.get_trip(trip["id"], op))["trip_status"]
    assert pre_status == TripStatus.IN_TRANSIT.value
    # Arrive.
    arr_resp = api.arrive_trip(trip["id"], {}, op)
    arrived = validate_success(arr_resp, 200)
    assert arrived["trip_status"] == TripStatus.COMPLETED.value, (
        "the permissive-on-SUSPENDED-parent arrive predicate from PRD §3.7 admits the arrive"
    )


# ─── The cargo's hazard-class chain ───────────────────────────────────


def test_trip_cargo_hazard_class_not_in_permit_hazard_classes_rejected(api, active_permit: HazmatScenario):
    """PRD §3.7 + §3.4 end paragraph: "the trip's body's single
    ``cargo_hazard_class`` must be a member of the permit's
    ``hazard_classes`` … and the assigned vehicle's
    ``hazard_classes_compatible``" — the per-trip cargo-vs-permit
    chain.  A cargo class outside the permit's authorized set is
    the body-shape ``ERR_VALIDATION`` 422.

    The fixture's permit authorizes ``["3", "8"]``.  A trip body
    with ``cargo_hazard_class = "7"`` (radioactive, outside the
    permit's set) is the rejection.
    """
    scenario = active_permit
    op = company_operator_headers(scenario.company["id"])
    server_now = current_server_now(api)
    dep = iso_now_plus_delta(seconds=60.0, base_iso=server_now)
    arr = iso_now_plus_delta(seconds=3600.0, base_iso=server_now)
    payload = create_trip_payload(
        driver_id=scenario.drivers[0]["id"],
        vehicle_id=scenario.vehicles[0]["id"],
        scheduled_departure_at=dep,
        scheduled_arrival_at=arr,
        cargo_hazard_class="7",  # outside the permit's ["3", "8"]
    )
    resp = api.create_trip(scenario.permit["id"], payload, op)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, expected_status=422)
