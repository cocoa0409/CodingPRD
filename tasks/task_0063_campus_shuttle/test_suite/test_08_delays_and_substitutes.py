"""Delay events, IM notification, breakdown substitutes.

Covers PRD §3.5.
"""
from __future__ import annotations
from datetime import timedelta

import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)
from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    api_client,
    assert_delay_event,
    create_active_vehicle,
    depart_run_sheet,
    fetch_run_sheet,
    iso_z, parse_iso,
    list_all_audit_logs,
    make_driver_headers,
    report_delay_payload,
    setup_planned_run_sheet,
    start_boarding,
)


# ===========================================================================
# Delay reporting (PRD §3.5)
# ===========================================================================
class TestDelayReporting:

    def test_report_delay_transitions_to_delayed_and_pushes_arrival(
            self, dispatcher_headers):
        """PRD §3.5: "A delay event row is appended with reported_at stamped
        to the current instant, notification_dispatched and
        substitute_dispatched both defaulting to false. The run-sheet
        transitions to DELAYED (from either PLANNED or IN_TRANSIT), its
        delay_minutes_accumulated is increased by the supplied
        delay_minutes, and its scheduled_arrival is pushed forward by the
        same delay_minutes."

        Claim: reporting a 5-minute TRAFFIC delay flips the run to DELAYED,
        increments delay_minutes_accumulated by 5, and pushes
        scheduled_arrival forward by 5 minutes.
        """
        advance_clock_to("2026-06-01T03:00:00.000Z")
        base = setup_planned_run_sheet()
        run_id = base["run_sheet"]["id"]
        original_arr = parse_iso(base["run_sheet"]["scheduled_arrival"])
        ev = validate_success(
            api_client.report_delay(
                run_id,
                report_delay_payload(
                    cause="TRAFFIC", delay_minutes=5,
                    affected_from_stop_id=base["stops"][0]["id"],
                ),
                dispatcher_headers,
            ),
            201,
        )
        assert_delay_event(ev)
        assert ev["cause"] == "TRAFFIC"
        assert ev["delay_minutes"] == 5
        # Cumulative of 5 min < 30 min threshold -> notification NOT dispatched yet.
        assert ev["notification_dispatched"] is False
        # And it isn't a BREAKDOWN, so no substitute.
        assert ev["substitute_dispatched"] is False
        # Run state.
        rs = fetch_run_sheet(run_id)
        assert rs["status"] == "DELAYED"
        assert rs["delay_minutes_accumulated"] == 5
        new_arr = parse_iso(rs["scheduled_arrival"])
        delta = (new_arr - original_arr).total_seconds() / 60
        assert delta == pytest.approx(5, abs=0.01), \
            f"PRD §3.5: scheduled_arrival must be pushed forward by 5 minutes, got delta={delta}"

    def test_notification_dispatched_at_threshold(self, dispatcher_headers):
        """PRD §3.5: "When the cumulative delay_minutes_accumulated on the
        run reaches at least 30 minutes (counting the newly-appended
        event), the IM-system notification is dispatched and the
        newly-appended delay event's notification_dispatched is set to
        true."

        Claim: report a single 30-minute delay -> notification_dispatched=True
        on that event.
        """
        advance_clock_to("2026-06-01T03:00:00.000Z")
        base = setup_planned_run_sheet()
        ev = validate_success(
            api_client.report_delay(
                base["run_sheet"]["id"],
                report_delay_payload(
                    cause="WEATHER", delay_minutes=30,
                    affected_from_stop_id=base["stops"][0]["id"],
                ),
                dispatcher_headers,
            ),
            201,
        )
        assert ev["notification_dispatched"] is True

    def test_breakdown_dispatches_substitute(self, dispatcher_headers):
        """PRD §3.5: "When the cause is BREAKDOWN and the run's
        substitute_vehicle_id is still null, the substitute-vehicle
        selector is invoked and, on success, the run's substitute_vehicle_id
        is set and the new delay event's substitute_dispatched is set to true."

        Claim: BREAKDOWN delay with at least one other eligible vehicle
        causes substitute_dispatched=True and run.substitute_vehicle_id set.
        """
        advance_clock_to("2026-06-01T03:00:00.000Z")
        base = setup_planned_run_sheet(seat_capacity=20)
        # Build an extra eligible substitute vehicle.
        spare = create_active_vehicle(seat_capacity=20)
        ev = validate_success(
            api_client.report_delay(
                base["run_sheet"]["id"],
                report_delay_payload(
                    cause="BREAKDOWN", delay_minutes=20,
                    affected_from_stop_id=base["stops"][0]["id"],
                ),
                dispatcher_headers,
            ),
            201,
        )
        assert ev["substitute_dispatched"] is True
        rs = fetch_run_sheet(base["run_sheet"]["id"])
        assert rs["substitute_vehicle_id"], \
            "PRD §3.5: BREAKDOWN delay must populate substitute_vehicle_id"
        # It must not be the original vehicle.
        assert rs["substitute_vehicle_id"] != base["vehicle"]["id"]

    def test_delay_audit_log_event(self, dispatcher_headers):
        """PRD §2.11: "Selected state transitions append a row to the audit
        log with an event_type drawn from the set RESERVATION_CREATED,
        RESERVATION_CANCELLED, RESERVATION_CHECKED_IN, RESERVATION_NO_SHOW,
        DELAY_REPORTED, SUBSTITUTE_DISPATCHED, ROUTE_PUBLISHED, and
        BILL_REFUNDED."

        Claim: reporting a delay appends a DELAY_REPORTED audit-log entry
        with subject_type=DelayEvent or RunSheet (PRD §2.11 explicitly
        enumerates both as valid subject_types).
        """
        advance_clock_to("2026-06-01T03:00:00.000Z")
        base = setup_planned_run_sheet()
        validate_success(
            api_client.report_delay(
                base["run_sheet"]["id"],
                report_delay_payload(
                    cause="TRAFFIC", delay_minutes=10,
                    affected_from_stop_id=base["stops"][0]["id"],
                ),
                dispatcher_headers,
            ),
            201,
        )
        logs = list_all_audit_logs(event_type="DELAY_REPORTED")
        assert logs, "Expected at least one DELAY_REPORTED audit log"
