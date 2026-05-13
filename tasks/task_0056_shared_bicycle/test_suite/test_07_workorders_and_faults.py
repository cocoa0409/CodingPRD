"""Work orders, fault reporting, SLA accounting.

PRD §3.5 (fault reports) and §3.6 (work order lifecycle and SLA).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    assign_workorder_payload,
    assign_workorder,
    bike_fault_report_payload,
    cancel_workorder,
    create_funded_rider,
    create_workorder,
    create_workorder_payload,
    find_workorder_for_bike,
    get_bike,
    get_region,
    list_workorders,
    make_rider_headers,
    report_fault_during_ride,
    resolve_workorder_payload,
    resolve_workorder,
    setup_basic_ride_scenario,
    setup_region_with_bikes,
    start_ride,
    validate_error,
    validate_success,
    ADMIN,
    OPERATOR,
)


class TestBikeFaultReport:
    """PRD §3.5: rider/operator reports a fault on a parked bike."""

    def test_bike_fault_report_opens_workorder_and_locks_out(self, api):
        """PRD §3.5: 'On success the bike's status is flipped from
        AVAILABLE → FAULT (locking it out of new rides — this is
        fault-bike isolation), the category is appended to
        fault_categories, a new WorkOrder is opened with cause
        USER_REPORT, status OPEN.'"""
        region, bikes = setup_region_with_bikes(num_bikes=1)
        from test_helpers import api_client
        validate_success(api_client.fault_report_bike(
            bikes[0]["id"], bike_fault_report_payload(category="BRAKE"),
            OPERATOR,
        ), expected_status=201)
        bike = get_bike(bikes[0]["id"])
        assert bike["status"] == "FAULT"
        assert "BRAKE" in bike["fault_categories"]
        wo = find_workorder_for_bike(bikes[0]["id"], status="OPEN")
        assert wo["cause"] == "USER_REPORT"

    def test_bike_fault_report_decrements_available_count(self, api):
        """PRD §3.5: 'the region's available_count decrements with
        density_posture recomputed accordingly.'"""
        region, bikes = setup_region_with_bikes(num_bikes=1)
        from test_helpers import api_client
        api_client.fault_report_bike(
            bikes[0]["id"], bike_fault_report_payload(category="FLAT_TIRE"),
            OPERATOR,
        )
        region = get_region(region["id"])
        assert region["available_count"] == 0


class TestRideFaultReport:
    """PRD §3.5: mid-ride fault — penalty waived."""

    def test_mid_ride_fault_settles_ride_with_waived_penalty(self, api):
        """PRD §3.5: 'On success the ride is auto-ended through the same
        settlement formula above, with one critical exception:
        penalty_cents is forced to 0 regardless of what end_fence_kind
        turns out to be.'"""
        from test_helpers import (
            setup_region_with_restricted_zone, create_funded_rider,
        )
        ctx = setup_region_with_restricted_zone(
            center_lat=30.5, center_lng=120.5, side=0.05,
            out_of_zone_penalty_cents=500,
            num_bikes=1,
        )
        rider = create_funded_rider(wallet_balance_cents=10000)
        ride = start_ride(rider, ctx["bikes"][0])
        advance_clock(10)
        settled = report_fault_during_ride(
            ride,
            end_lat=ctx["restricted_lat"], end_lng=ctx["restricted_lng"],
            category="FLAT_TIRE",
            rider_id=rider["id"],
        )
        assert settled["penalty_cents"] == 0, (
            "PRD §3.5: penalty_cents is forced to 0 regardless of "
            "end_fence_kind"
        )
        assert settled["status"] == "SETTLED"

    def test_mid_ride_fault_flips_bike_to_fault_not_available(self, api):
        """PRD §3.5: 'The bike does not become AVAILABLE: it transitions
        IN_USE → FAULT, the rider's category is appended to
        fault_categories.'"""
        ctx = setup_basic_ride_scenario(wallet_balance_cents=10000)
        ride = start_ride(ctx["rider"], ctx["bike"])
        advance_clock(5)
        report_fault_during_ride(
            ride, end_lat=10.0, end_lng=10.0, category="BRAKE",
            rider_id=ctx["rider"]["id"],
        )
        bike = get_bike(ctx["bike"]["id"])
        assert bike["status"] == "FAULT", (
            "PRD §3.5: bike transitions IN_USE → FAULT"
        )
        assert "BRAKE" in bike["fault_categories"]


class TestWorkOrderLifecycle:
    def test_create_workorder_flips_bike_to_fault(self, api):
        """PRD §3.6: 'The bike's status is flipped to FAULT (if not
        already).'"""
        region, bikes = setup_region_with_bikes(num_bikes=1)
        create_workorder(
            bike_id=bikes[0]["id"], cause="USER_REPORT",
            category="FLAT_TIRE", sla_minutes=240,
        )
        bike = get_bike(bikes[0]["id"])
        assert bike["status"] == "FAULT"

    def test_assign_workorder_moves_open_to_assigned(self, api):
        """PRD §3.6: 'On success the work order advances OPEN → ASSIGNED
        and assigned_operator_id is recorded.'"""
        region, bikes = setup_region_with_bikes(num_bikes=1)
        wo = create_workorder(bike_id=bikes[0]["id"])
        assigned = assign_workorder(
            wo["id"], assigned_operator_id="op-abc",
        )
        assert assigned["status"] == "ASSIGNED"
        assert assigned["assigned_operator_id"] == "op-abc"

    def test_assign_workorder_missing_operator_id_rejected(self, api):
        """PRD §3.6: 'An assigned_operator_id must be supplied — its
        absence yields ERR_OPERATOR_REQUIRED (HTTP 422).'"""
        region, bikes = setup_region_with_bikes(num_bikes=1)
        wo = create_workorder(bike_id=bikes[0]["id"])
        resp = api.assign_workorder(wo["id"], {}, OPERATOR)
        validate_error(resp, ApiErrorId.ERR_OPERATOR_REQUIRED.value, 422)

    def test_assign_workorder_when_not_open_rejected(self, api):
        """PRD §3.6: 'The work order must be OPEN — otherwise
        ERR_WORKORDER_NOT_OPEN.'"""
        region, bikes = setup_region_with_bikes(num_bikes=1)
        wo = create_workorder(bike_id=bikes[0]["id"])
        assign_workorder(wo["id"])
        # Second assign attempt on ASSIGNED
        resp = api.assign_workorder(
            wo["id"], assign_workorder_payload(assigned_operator_id="op-2"),
            OPERATOR,
        )
        validate_error(resp, ApiErrorId.ERR_WORKORDER_NOT_OPEN.value, 409)

    def test_resolve_requires_assigned(self, api):
        """PRD §3.6: 'Resolution requires the work order to be ASSIGNED
        — otherwise ERR_WORKORDER_NOT_ASSIGNED.'"""
        region, bikes = setup_region_with_bikes(num_bikes=1)
        wo = create_workorder(bike_id=bikes[0]["id"])
        resp = api.resolve_workorder(
            wo["id"], resolve_workorder_payload(resolution_note="done"),
            OPERATOR,
        )
        validate_error(resp, ApiErrorId.ERR_WORKORDER_NOT_ASSIGNED.value, 409)

    def test_resolve_flips_bike_back_to_available(self, api):
        """PRD §3.6: 'if the bike's fault_categories is now empty AND
        no other OPEN or ASSIGNED work order exists for the bike, the
        bike's status flips FAULT → AVAILABLE.'"""
        region, bikes = setup_region_with_bikes(num_bikes=1)
        wo = create_workorder(
            bike_id=bikes[0]["id"], cause="USER_REPORT",
            category="FLAT_TIRE", sla_minutes=240,
        )
        assign_workorder(wo["id"])
        resolve_workorder(wo["id"], resolution_note="all good")
        bike = get_bike(bikes[0]["id"])
        assert bike["status"] == "AVAILABLE", (
            "PRD §3.6: bike returns to AVAILABLE when last WO resolves"
        )
        assert "FLAT_TIRE" not in bike["fault_categories"], (
            "PRD §3.6: 'the matching category is cleared from the "
            "bike's fault_categories'"
        )

    def test_cancel_open_workorder_returns_bike_to_available(self, api):
        """PRD §3.6: 'Cancellation of an OPEN work order moves it OPEN
        → CANCELLED; if it was the only open work order for that bike
        and the fault_categories would consequently become empty, the
        bike flips FAULT → AVAILABLE.'"""
        region, bikes = setup_region_with_bikes(num_bikes=1)
        wo = create_workorder(
            bike_id=bikes[0]["id"], cause="USER_REPORT",
            category="FLAT_TIRE", sla_minutes=240,
        )
        cancel_workorder(wo["id"])
        bike = get_bike(bikes[0]["id"])
        assert bike["status"] == "AVAILABLE"


class TestSlaBreached:
    """PRD §3.6: 'sla_breached is a computed attribute ... For an OPEN
    or ASSIGNED work order, breach is true when the current clock_minutes
    minus opened_minute is strictly greater than sla_minutes. A duration
    exactly equal to sla_minutes is never a breach, in any state.'"""

    def test_open_workorder_at_exact_sla_not_breach(self, api):
        """PRD §3.6: 'A duration exactly equal to sla_minutes is never
        a breach, in any state.'"""
        region, bikes = setup_region_with_bikes(num_bikes=1)
        wo = create_workorder(
            bike_id=bikes[0]["id"], cause="USER_REPORT",
            category="FLAT_TIRE", sla_minutes=60,
        )
        advance_clock(60)
        # Re-read via list
        wos = list_workorders(status="OPEN", limit=100)
        match = [w for w in wos if w["id"] == wo["id"]][0]
        assert match["sla_breached"] is False, (
            "PRD §3.6: equal to sla_minutes is NOT a breach"
        )

    def test_open_workorder_one_minute_past_sla_is_breach(self, api):
        """PRD §3.6: 'For an OPEN or ASSIGNED work order, breach is
        true when the current clock_minutes minus opened_minute is
        strictly greater than sla_minutes.'"""
        region, bikes = setup_region_with_bikes(num_bikes=1)
        wo = create_workorder(
            bike_id=bikes[0]["id"], cause="USER_REPORT",
            category="FLAT_TIRE", sla_minutes=60,
        )
        advance_clock(61)
        wos = list_workorders(status="OPEN", limit=100)
        match = [w for w in wos if w["id"] == wo["id"]][0]
        assert match["sla_breached"] is True

    def test_cancelled_workorder_never_breaches(self, api):
        """PRD §3.6: 'For a CANCELLED work order, breach is always
        false — cancelled work orders never breach.'"""
        region, bikes = setup_region_with_bikes(num_bikes=1)
        wo = create_workorder(
            bike_id=bikes[0]["id"], cause="USER_REPORT",
            category="FLAT_TIRE", sla_minutes=10,
        )
        advance_clock(5000)
        cancel_workorder(wo["id"])
        wos = list_workorders(status="CANCELLED", limit=100)
        match = [w for w in wos if w["id"] == wo["id"]][0]
        assert match["sla_breached"] is False, (
            "PRD §3.6: 'cancelled work orders never breach.'"
        )
