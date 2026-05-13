"""Anomaly sweep, audit log accumulation, and external-sync emissions.

PRD §3.9 (sweep), §2.9 (audit), §3.12 (external sync).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    create_bike,
    create_region,
    create_rider,
    create_workorder_payload,
    emit_event_payload,
    find_audit_logs,
    get_bike,
    list_audit_logs,
    patch_bike,
    run_sweep,
    setup_basic_ride_scenario,
    setup_region_with_bikes,
    shelf_bike_on,
    start_ride,
    validate_error,
    validate_success,
    ADMIN,
    OPERATOR,
)


class TestAnomalySweep:
    def test_sweep_returns_opened_count(self, api):
        """PRD §3.9: 'The sweep returns the opened_count.'"""
        out = run_sweep()
        assert "opened_count" in out, (
            "PRD §3.9: sweep returns opened_count"
        )
        assert isinstance(out["opened_count"], int)
        assert out["opened_count"] >= 0

    def test_long_stationary_triggers_workorder(self, api):
        """PRD §3.9: 'A bike whose clock_minutes - last_motion_minute
        is at least LONG_STATIONARY_THRESHOLD_MIN (1440 minutes — one
        day) gets a work order with cause LONG_STATIONARY.'"""
        region, bikes = setup_region_with_bikes(num_bikes=1)
        # Set last_motion to the current clock (which is 0)
        advance_clock(1500)
        out = run_sweep()
        assert out["opened_count"] >= 1
        # Find the work order opened for the bike. Paginate via region
        # filter (PRD §4: list-workorders supports region_id filter) so
        # cumulative state across the session can't overflow the window.
        from test_helpers import list_workorders
        offset = 0
        match = []
        while True:
            wos = list_workorders(
                limit=100, offset=offset, region_id=region["id"],
            )
            match.extend(
                w for w in wos
                if w.get("bike_id") == bikes[0]["id"]
                and w.get("cause") == "LONG_STATIONARY"
            )
            if len(wos) < 100:
                break
            offset += 100
        assert match, (
            "PRD §3.9: long-stationary bike gets cause LONG_STATIONARY"
        )

    def test_low_battery_e_bike_triggers_workorder(self, api):
        """PRD §3.9: 'A bike whose battery_pct is at most
        LOW_BATTERY_THRESHOLD_PCT (20%) gets a work order with cause
        LOW_BATTERY.'"""
        region = create_region(deployment_quota=10,
                               low_density_threshold=0,
                               high_density_threshold=999)
        bike = create_bike(model="E_BIKE", battery_pct=100)
        shelf_bike_on(region["id"], bike["id"])
        # Now drop battery to threshold
        patch_bike(bike["id"], battery_pct=20)
        run_sweep()
        # Paginate via region_id filter to dodge cumulative-state overflow.
        from test_helpers import list_workorders
        offset = 0
        match = []
        while True:
            wos = list_workorders(
                limit=100, offset=offset, region_id=region["id"],
            )
            match.extend(
                w for w in wos
                if w.get("bike_id") == bike["id"]
                and w.get("cause") == "LOW_BATTERY"
            )
            if len(wos) < 100:
                break
            offset += 100
        assert match, (
            "PRD §3.9: low-battery bike gets cause LOW_BATTERY"
        )


class TestAuditLog:
    def test_unlock_writes_ride_unlock_audit(self, api):
        """PRD §2.9: 'Every state-changing action that mutates money,
        fleet state, geofence configuration, or external-system
        synchronization writes an entry.'"""
        ctx = setup_basic_ride_scenario(wallet_balance_cents=10000)
        ride = start_ride(ctx["rider"], ctx["bike"])
        # PRD §4: GET /audit-logs filters include subject_id — narrow
        # server-side so the test isn't subject to cumulative state from
        # prior tests overflowing a single page.
        rows = list_audit_logs(subject_id=ride["id"], limit=100)
        match = find_audit_logs(rows, subject_type="Ride",
                                action="RIDE_UNLOCK")
        # PRD §3.4 (cross-referenced from §2.9): 'An audit entry tagged
        # RIDE_UNLOCK is written.'
        assert any(r.get("subject_id") == ride["id"] for r in match), (
            "PRD §3.4: 'An audit entry tagged RIDE_UNLOCK is written.'"
        )


class TestExternalSync:
    def test_emit_event_writes_external_sync_audit(self, api):
        """PRD §3.12: 'An admin-only test-driving emission capability
        accepts a target_system, subject_type, subject_id, and payload
        and writes the same kind of audit entry without otherwise
        mutating state.'"""
        ctx = setup_basic_ride_scenario(wallet_balance_cents=10000)
        ride = start_ride(ctx["rider"], ctx["bike"])
        resp = api.emit_event(
            emit_event_payload(
                target_system="payment",
                subject_type="Ride",
                subject_id=ride["id"],
                payload={"foo": "bar"},
            ),
            ADMIN,
        )
        validate_success(resp, expected_status=200)
        # Filter by subject_id server-side; cumulative state across the
        # test session can easily overflow a single 100-row page.
        rows = list_audit_logs(
            event_kind="EXTERNAL_SYNC", subject_id=ride["id"], limit=100,
        )
        assert any(r.get("subject_id") == ride["id"] for r in rows), (
            "PRD §3.12: emission writes an EXTERNAL_SYNC audit entry"
        )


class TestRbacRejections:
    def test_rider_cannot_advance_clock(self, api, rider_headers):
        """PRD §4: 'POST /_clock/advance — Admin' (Admin-only)."""
        resp = api.advance_clock({"minutes": 1}, rider_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    def test_operator_cannot_create_region(self, api, operator_headers):
        """PRD §4: 'POST /regions — Admin' (Admin-only)."""
        from test_helpers import create_region_payload
        resp = api.create_region(create_region_payload(), operator_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    def test_rider_cannot_void_ride(self, api):
        """PRD §4: 'POST /rides/{ride_id}/void — Admin' (Admin-only)."""
        from test_helpers import settle_simple_standard_ride, make_rider_headers
        ctx = setup_basic_ride_scenario(wallet_balance_cents=10000)
        ride = start_ride(ctx["rider"], ctx["bike"])
        resp = api.void_ride(
            ride["id"], make_rider_headers(ctx["rider"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)
