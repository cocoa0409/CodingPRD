"""Trip scheduling gates: agreement status, maintenance currency, insurance,
and the aircraft turnaround buffer (PRD §3.4)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    setup_pending_agreement, setup_active_agreement, setup_dispatch_ready,
    setup_owner_and_aircraft,
    create_trip, approve_charter_trip, assign_duty, create_event,
    file_accepted_insurance, setup_qualified_crew_pair,
    TEST_USERS,
)

AE = TEST_USERS["account_executive_headers"]
FO = TEST_USERS["flight_ops_headers"]


def _setup_approved_charter_with_pending_agreement(api):
    """PENDING agreement (never activated) + owner-approved CHARTER trip."""
    scenario = setup_pending_agreement(tail_number="N150JX")
    trip = create_trip(
        scenario["aircraft"]["id"], trip_use="CHARTER",
        departure_at="2026-08-06T08:00:00Z", block_hours_est=5.0,
        charter_quote_cents=900000, arrive_icao="KMIA",
    )
    approve_charter_trip(trip["id"], scenario["owner"]["id"])
    return scenario, trip


def test_schedule_requires_active_agreement(api):
    """PRD §3.4: "Five gates are evaluated in fixed order. (1) Agreement: the
    aircraft's management agreement must be `ACTIVE`, else
    `ERR_AGREEMENT_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/trip_schedule_requires_active_agreement
    """
    _scenario, trip = _setup_approved_charter_with_pending_agreement(api)

    res = api.schedule_trip(trip["id"], FO)
    validate_error(res, "ERR_AGREEMENT_INVALID_STATE", expected_status=409)


def test_schedule_rejection_preserves_trip_and_agreement_state(api):
    """PRD §3.4: "Five gates are evaluated in fixed order. (1) Agreement: the
    aircraft's management agreement must be `ACTIVE`, else
    `ERR_AGREEMENT_INVALID_STATE`."
    PRD §2.8: "Within the trip-scheduling gate stack specifically, the
    agreement-status check runs first, then the maintenance-overdue check, then
    the insurance-currency check, then the crew-complement check, and finally
    the aircraft-overlap check."

    Design: Difficulty/cross_entity_state_dependency/trip_schedule_requires_active_agreement
    """
    scenario, trip = _setup_approved_charter_with_pending_agreement(api)

    res = api.schedule_trip(trip["id"], FO)
    validate_error(res, "ERR_AGREEMENT_INVALID_STATE", expected_status=409)

    current_trip = validate_success(api.get_trip(trip["id"], FO), 200)
    assert current_trip["status"] == "APPROVED", (
        f"failed schedule must not move the trip, got {current_trip['status']}"
    )
    current_agreement = validate_success(
        api.get_agreement(scenario["agreement"]["id"], AE), 200
    )
    assert current_agreement["status"] == "PENDING"


def _setup_trip_with_insurance(api, valid_until):
    """ACTIVE agreement + ACCEPTED INSURANCE_COI with the given valid_until +
    OWNER_USE trip (auto-APPROVED) departing 2026-08-20. No crew assigned."""
    scenario = setup_active_agreement(tail_number="N160JX")
    aircraft_id = scenario["aircraft"]["id"]
    file_accepted_insurance(aircraft_id, valid_until=valid_until,
                            reference_no="COI-1601")
    trip = create_trip(
        aircraft_id, departure_at="2026-08-20T08:00:00Z", block_hours_est=3.0
    )
    assert trip["status"] == "APPROVED"
    return scenario, trip


def test_schedule_with_expired_insurance_rejected(api):
    """PRD §3.4: "(3) Insurance: an `ACCEPTED` `ComplianceFiling` of kind
    `INSURANCE_COI` whose `valid_until` is on or after the calendar date of
    `departure_at` must exist for the aircraft, else
    `ERR_INSURANCE_NOT_CURRENT`."

    Design: Difficulty/cross_entity_state_dependency/trip_schedule_requires_current_insurance_filing
    """
    _scenario, trip = _setup_trip_with_insurance(api, valid_until="2026-08-01")

    res = api.schedule_trip(trip["id"], FO)
    validate_error(res, "ERR_INSURANCE_NOT_CURRENT", expected_status=409)

    current = validate_success(api.get_trip(trip["id"], FO), 200)
    assert current["status"] == "APPROVED"


def test_schedule_insurance_valid_on_departure_date_passes_gate(api):
    """PRD §3.4: "(3) Insurance: an `ACCEPTED` `ComplianceFiling` of kind
    `INSURANCE_COI` whose `valid_until` is on or after the calendar date of
    `departure_at` must exist for the aircraft, else
    `ERR_INSURANCE_NOT_CURRENT`."
    PRD §3.4: "(4) Crew complement: the trip must hold at least one `ASSIGNED`
    duty assignment with `duty_role` `PIC` held by a `QUALIFIED` `CAPTAIN`, and
    at least one `ASSIGNED` assignment with `duty_role` `SIC` held by a
    `QUALIFIED` `FIRST_OFFICER`, else `ERR_CREW_COMPLEMENT_INCOMPLETE`."
    PRD §2.8: "Within the trip-scheduling gate stack specifically, the
    agreement-status check runs first, then the maintenance-overdue check, then
    the insurance-currency check, then the crew-complement check, and finally
    the aircraft-overlap check."

    valid_until exactly equal to the departure calendar date satisfies the
    insurance gate ("on or after"), so the failure surfaces at the next gate:
    no crew are assigned, hence ERR_CREW_COMPLEMENT_INCOMPLETE.

    Design: Difficulty/cross_entity_state_dependency/trip_schedule_requires_current_insurance_filing
    """
    _scenario, trip = _setup_trip_with_insurance(api, valid_until="2026-08-20")

    res = api.schedule_trip(trip["id"], FO)
    validate_error(res, "ERR_CREW_COMPLEMENT_INCOMPLETE", expected_status=409)


def test_maintenance_overdue_at_exact_due_hours_blocks_schedule(api):
    """PRD §3.4: "(2) Maintenance: no `MaintenanceEvent` of the aircraft in
    `FORECAST` or `SCHEDULED` status may have `due_at_aircraft_hours` at or
    below the aircraft's current `total_time_hours` — an event due exactly at
    the current hour reading already counts as overdue, and any such event
    blocks scheduling with `ERR_MAINTENANCE_OVERDUE`."

    Design: Corner/state_machines/maintenance_overdue_at_exact_due_hours_blocks_schedule
    """
    scenario = setup_dispatch_ready(tail_number="N320JX")
    aircraft_id = scenario["aircraft"]["id"]
    # Fresh aircraft: total_time_hours is 0.0; due exactly at 0.0 is overdue.
    create_event(aircraft_id, due_at_aircraft_hours=0.0)
    trip = create_trip(aircraft_id, departure_at="2026-08-06T08:00:00Z",
                       block_hours_est=3.0)
    assign_duty(trip["id"], scenario["captain"]["id"], "PIC",
                "2026-08-06T06:00:00Z", "2026-08-06T12:00:00Z")
    assign_duty(trip["id"], scenario["first_officer"]["id"], "SIC",
                "2026-08-06T06:00:00Z", "2026-08-06T12:00:00Z")

    res = api.schedule_trip(trip["id"], FO)
    validate_error(res, "ERR_MAINTENANCE_OVERDUE", expected_status=409)

    current = validate_success(api.get_trip(trip["id"], FO), 200)
    assert current["status"] == "APPROVED"


def _setup_turnaround_scenario(api):
    """Dispatch-ready aircraft; T1 SCHEDULED occupying [08:00, 12:00] on
    2026-08-10; T2 APPROVED departing 13:00 (exactly 1h gap); T3 APPROVED
    departing 17:30 (0.5h after T2's 17:00 end). Crew assigned on all three.
    """
    scenario = setup_dispatch_ready(tail_number="N180JX")
    aircraft_id = scenario["aircraft"]["id"]
    captain = scenario["captain"]
    first_officer = scenario["first_officer"]

    t1 = create_trip(aircraft_id, departure_at="2026-08-10T08:00:00Z",
                     block_hours_est=4.0)
    assign_duty(t1["id"], captain["id"], "PIC",
                "2026-08-10T06:00:00Z", "2026-08-10T12:00:00Z")
    assign_duty(t1["id"], first_officer["id"], "SIC",
                "2026-08-10T06:00:00Z", "2026-08-10T12:00:00Z")
    t1 = validate_success(api.schedule_trip(t1["id"], FO), 200)

    t2 = create_trip(aircraft_id, departure_at="2026-08-10T13:00:00Z",
                     block_hours_est=4.0)
    assign_duty(t2["id"], captain["id"], "PIC",
                "2026-08-10T12:00:00Z", "2026-08-10T17:00:00Z")
    assign_duty(t2["id"], first_officer["id"], "SIC",
                "2026-08-10T12:00:00Z", "2026-08-10T17:00:00Z")

    t3 = create_trip(aircraft_id, departure_at="2026-08-10T17:30:00Z",
                     block_hours_est=2.0, arrive_icao="KBOS")
    assign_duty(t3["id"], captain["id"], "PIC",
                "2026-08-10T17:00:00Z", "2026-08-10T19:00:00Z")
    assign_duty(t3["id"], first_officer["id"], "SIC",
                "2026-08-10T17:00:00Z", "2026-08-10T19:00:00Z")
    return scenario, t1, t2, t3


def test_turnaround_exactly_one_hour_passes(api):
    """PRD §3.4: "(5) Aircraft occupancy: the candidate trip's occupancy
    interval — running from `departure_at` for `block_hours_est` hours — must
    leave a turnaround buffer of at least one hour to every other `SCHEDULED`
    or `COMPLETED` trip of the same aircraft; a gap of exactly one hour passes,
    and anything shorter is rejected with `ERR_AIRCRAFT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/aircraft_trips_require_turnaround_buffer
    """
    _scenario, t1, t2, _t3 = _setup_turnaround_scenario(api)
    assert t1["status"] == "SCHEDULED"

    # T2 [13:00, 17:00] leaves exactly 1.0h to T1's [08:00, 12:00].
    scheduled = validate_success(api.schedule_trip(t2["id"], FO), 200)
    assert scheduled["status"] == "SCHEDULED"


def test_turnaround_half_hour_gap_rejected(api):
    """PRD §3.4: "(5) Aircraft occupancy: the candidate trip's occupancy
    interval — running from `departure_at` for `block_hours_est` hours — must
    leave a turnaround buffer of at least one hour to every other `SCHEDULED`
    or `COMPLETED` trip of the same aircraft; a gap of exactly one hour passes,
    and anything shorter is rejected with `ERR_AIRCRAFT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/aircraft_trips_require_turnaround_buffer
    """
    _scenario, _t1, t2, t3 = _setup_turnaround_scenario(api)
    validate_success(api.schedule_trip(t2["id"], FO), 200)

    # T3 [17:30, 19:30] leaves only 0.5h to T2's [13:00, 17:00].
    res = api.schedule_trip(t3["id"], FO)
    validate_error(res, "ERR_AIRCRAFT_OVERLAP", expected_status=409)

    current = validate_success(api.get_trip(t3["id"], FO), 200)
    assert current["status"] == "APPROVED"


def test_trips_list_pagination_defaults(api):
    """PRD §2.3: "List endpoints accept two query parameters, `limit` and
    `offset`. The default `limit` is 10; the minimum accepted value is 1 and
    the maximum is 100. The default `offset` is 0."
    PRD §2.3: "The `meta` block of a list response carries four pagination
    fields — `limit`, `offset`, `total_count`, and `has_more` — alongside the
    standard `api_request_id` and `api_request_timestamp`."

    Design: Corner/endpoints/trips_list_pagination_defaults
    """
    _owner, aircraft = setup_owner_and_aircraft(tail_number="N470JX")
    for day in range(3, 14):
        create_trip(
            aircraft["id"], departure_at=f"2026-08-{day:02d}T08:00:00Z",
            block_hours_est=2.0,
        )

    res = api.list_aircraft_trips(aircraft["id"], FO)
    data, meta = validate_paginated(res)
    assert len(data) == 10, f"default limit is 10, got {len(data)}"
    assert meta["total_count"] == 11
    assert meta["has_more"] is True
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    body = res.json()
    assert body["response_type"] == "array"
    assert isinstance(body["meta"]["api_request_id"], str)
