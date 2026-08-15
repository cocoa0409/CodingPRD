"""Maintenance event forecasting chains and compliance filing cycles."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    setup_owner_and_aircraft, create_event, create_filing,
    DEFAULT_CLOCK_UTC, TEST_USERS,
)

FO = TEST_USERS["flight_ops_headers"]
MP = TEST_USERS["maintenance_planner_headers"]
CO = TEST_USERS["compliance_officer_headers"]


def test_event_complete_spawns_successor_forecast(api):
    """PRD §3.5: "Completion by the `MaintenancePlanner` moves a `SCHEDULED`
    event to `COMPLETED`, stamps `completed_at` from the logical clock,
    captures `actual_aircraft_hours` as the aircraft's `total_time_hours` at
    the completion instant, and then auto-spawns the successor: a new
    `MaintenanceEvent` in `FORECAST` whose `previous_event_id` is the completed
    event, whose `event_code` and `interval_hours` match the completed event,
    and whose `due_at_aircraft_hours` is the completed event's
    `actual_aircraft_hours` plus `interval_hours`."
    PRD §2.5: "Before any operator sets it, the logical clock reads exactly
    2026-08-01T00:00:00Z and never falls back to wall-clock time."
    PRD §3.5: "The chain of successors is browsable: the event list accepts a
    `previous_event_id` filter that returns exactly the successors spawned from
    a given event."

    Design: Corner/state_machines/event_complete_spawns_successor_forecast
    """
    _owner, aircraft = setup_owner_and_aircraft(tail_number="N310JX")
    event = create_event(aircraft["id"], event_code="INSPECTION_100H",
                         interval_hours=100.0, due_at_aircraft_hours=350.0)
    validate_success(
        api.schedule_event(event["id"], {"scheduled_date": "2026-08-03"}, MP), 200
    )

    completed = validate_success(api.complete_event(event["id"], MP), 200)
    assert completed["status"] == "COMPLETED"
    assert completed["actual_aircraft_hours"] == pytest.approx(0.0), (
        "fresh aircraft: total_time_hours at completion is 0.0"
    )
    # completed_at is stamped from the logical clock, still at its default.
    assert completed["completed_at"].startswith("2026-08-01T00:00:00"), (
        f"completed_at must read the default logical clock, got "
        f"{completed['completed_at']}"
    )

    data, meta = validate_paginated(
        api.list_events(MP, params={"previous_event_id": event["id"]})
    )
    assert meta["total_count"] == 1, (
        f"exactly one successor must be spawned, got {meta['total_count']}"
    )
    successor = data[0]
    assert successor["status"] == "FORECAST"
    assert successor["event_code"] == "INSPECTION_100H"
    assert successor["interval_hours"] == pytest.approx(100.0)
    # due = actual_aircraft_hours (0.0) + interval_hours (100.0)
    assert successor["due_at_aircraft_hours"] == pytest.approx(100.0)


def test_filing_reject_refile_cycle(api):
    """PRD §3.6: "Filing submission moves a `DRAFT` filing to `FILED` and
    stamps `filed_at` from the logical clock; the same action re-files a
    `REJECTED` filing back to `FILED`. On either filing or re-filing,
    `reference_no` and `valid_until` are replaced by the request values when
    present."
    PRD §3.6: "Recording the authority's decision against a `FILED` filing
    carries an `outcome` — `ACCEPTED` or `REJECTED` — and optional `notes`; the
    decision moves the filing to the named status and records the notes in
    `decision_notes`."

    Design: Corner/state_machines/filing_reject_refile_cycle
    """
    _owner, aircraft = setup_owner_and_aircraft(tail_number="N290JX")
    filing = create_filing(
        aircraft["id"], filing_kind="REGISTRATION", authority="FAA Registry",
        reference_no="REG-1", valid_until="2026-12-31",
    )
    validate_success(api.file_filing(filing["id"], {}, CO), 200)
    rejected = validate_success(
        api.record_decision(
            filing["id"],
            {"outcome": "REJECTED", "notes": "reference number illegible"},
            CO,
        ),
        200,
    )
    assert rejected["status"] == "REJECTED"

    refiled = validate_success(
        api.file_filing(
            filing["id"], {"reference_no": "REG-2", "valid_until": "2027-06-30"}, CO
        ),
        200,
    )
    assert refiled["status"] == "FILED"
    assert refiled["reference_no"] == "REG-2"
    assert refiled["valid_until"] == "2027-06-30"

    accepted = validate_success(
        api.record_decision(filing["id"], {"outcome": "ACCEPTED"}, CO), 200
    )
    assert accepted["status"] == "ACCEPTED"
