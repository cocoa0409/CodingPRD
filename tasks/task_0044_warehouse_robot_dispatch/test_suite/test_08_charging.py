"""Charging lifecycle: dock, queue, charge progression, completion,
station availability and queue advance.

PRD section 3.8 governs charging.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock,
    api_client,
    create_charging_station,
    create_fleet,
    create_map_node,
    create_robot,
    dock_robot,
    get_robot,
    queue_charger,
    setup_charging_queue_two_robots,
    validate_error,
    validate_success,
)


class TestDocking:
    def test_dock_marks_station_occupied_and_creates_session(self):
        """PRD section 3.8: 'On success, a ChargingSession row is
        created with status CHARGING, with start_battery_pct copied from
        the robot's battery_pct, and with started_at set to the current
        clock; the station flips to OCCUPIED and records
        occupying_robot_id; the robot's operational_state becomes
        CHARGING and its charging_station_id points at the station.'

        Claim: a fresh :dock makes the station OCCUPIED, the robot
        CHARGING with charging_station_id set, and creates a
        ChargingSession with start_battery_pct == robot.battery_pct at
        dock time.
        """
        fleet = create_fleet()
        n = create_map_node(fleet["id"], kind="CHARGER", x=0, y=0)
        station = create_charging_station(fleet["id"], node_id=n["id"])
        robot = create_robot(
            fleet["id"], position_node_id=n["id"], battery_pct=50
        )
        session = dock_robot(fleet["id"], robot["id"])
        assert session["status"] == "CHARGING"
        assert session["start_battery_pct"] == 50
        # Read the station
        from test_helpers.api_client import api_client as _api
        resp = _api.get_charging_station(
            fleet["id"], station["id"], TEST_USERS["operator_headers"]
        )
        s = validate_success(resp, expected_status=200)
        assert s["status"] == "OCCUPIED"
        assert s["occupying_robot_id"] == robot["id"]
        refreshed_robot = get_robot(fleet["id"], robot["id"])
        assert refreshed_robot["operational_state"] == "CHARGING"
        assert refreshed_robot["charging_station_id"] == station["id"]

    def test_dock_on_unavailable_station_rejected(self):
        """PRD section 3.8: 'The station's status must be AVAILABLE;
        otherwise the dock is rejected with ERR_CHARGER_UNAVAILABLE.'

        Claim: docking at an OCCUPIED station -> ERR_CHARGER_UNAVAILABLE.
        """
        fleet, n, station, ra, rb = setup_charging_queue_two_robots()
        # rb is queued; try to :dock rb directly while station is OCCUPIED.
        # But rb is already in WAITING_CHARGER, so PRD section 3.8 says
        # the precondition (Robot.operational_state in IDLE/EXECUTING/
        # WAITING_RIGHT_OF_WAY) blocks :dock. So we create a fresh
        # robot rc to attempt the dock instead.
        rc = create_robot(
            fleet["id"], position_node_id=n["id"], battery_pct=80
        )
        resp = api_client.dock_robot(
            fleet["id"], rc["id"], TEST_USERS["operator_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_CHARGER_UNAVAILABLE.value)


class TestChargeTrigger:
    def test_trigger_forced_low_when_battery_at_or_below_threshold(self):
        """PRD section 3.8: 'The session's trigger is FORCED_LOW when
        battery_pct is at or below Fleet.charging_low_threshold_pct...'

        Claim: docking a robot with battery_pct == 20 (default
        low_threshold) yields trigger='FORCED_LOW'.
        """
        fleet = create_fleet()
        n = create_map_node(fleet["id"], kind="CHARGER", x=0, y=0)
        create_charging_station(fleet["id"], node_id=n["id"])
        robot = create_robot(
            fleet["id"], position_node_id=n["id"], battery_pct=20
        )
        session = dock_robot(fleet["id"], robot["id"])
        assert session["trigger"] == "FORCED_LOW"

    def test_trigger_opportunity_when_idle_within_opportunity_band(self):
        """PRD section 3.8: 'OPPORTUNITY when the robot is IDLE and
        battery_pct is strictly above Fleet.charging_low_threshold_pct
        and at or below Fleet.charging_opportunity_pct; and MANUAL
        otherwise.'

        Claim: docking an IDLE robot with battery_pct=60 yields
        trigger='OPPORTUNITY' (default opportunity_pct=60).
        """
        fleet = create_fleet()
        n = create_map_node(fleet["id"], kind="CHARGER", x=0, y=0)
        create_charging_station(fleet["id"], node_id=n["id"])
        robot = create_robot(
            fleet["id"], position_node_id=n["id"], battery_pct=60
        )
        session = dock_robot(fleet["id"], robot["id"])
        assert session["trigger"] == "OPPORTUNITY"

    def test_trigger_manual_otherwise(self):
        """PRD section 3.8: 'OPPORTUNITY when the robot is IDLE and
        battery_pct is strictly above Fleet.charging_low_threshold_pct
        and at or below Fleet.charging_opportunity_pct; and MANUAL
        otherwise. The closed enum set is FORCED_LOW, OPPORTUNITY, and
        MANUAL.'

        Claim: docking a robot with battery_pct=90 (above opportunity
        band) yields trigger='MANUAL'.
        """
        fleet = create_fleet()
        n = create_map_node(fleet["id"], kind="CHARGER", x=0, y=0)
        create_charging_station(fleet["id"], node_id=n["id"])
        robot = create_robot(
            fleet["id"], position_node_id=n["id"], battery_pct=90
        )
        session = dock_robot(fleet["id"], robot["id"])
        assert session["trigger"] == "MANUAL"


class TestChargeProgression:
    def test_advance_clock_progresses_battery(self):
        """PRD section 3.8: 'During each clock advance, every robot
        whose operational_state was CHARGING at the start of the advance
        progresses its battery. The system computes the percentage
        gained as delta_seconds multiplied by the station's
        charge_rate_pct_per_second, adds it to the robot's current
        battery_pct, and caps the result at 100.'

        Claim: at charge_rate_pct_per_second=1 and battery=50, after
        :advance_clock delta_seconds=10, battery_pct=60.
        """
        fleet = create_fleet()
        n = create_map_node(fleet["id"], kind="CHARGER", x=0, y=0)
        create_charging_station(
            fleet["id"], node_id=n["id"], charge_rate_pct_per_second=1
        )
        robot = create_robot(
            fleet["id"], position_node_id=n["id"], battery_pct=50
        )
        dock_robot(fleet["id"], robot["id"])
        advance_clock(fleet["id"], 10)
        refreshed = get_robot(fleet["id"], robot["id"])
        assert refreshed["battery_pct"] == 60

    def test_battery_clamps_at_100(self):
        """PRD section 3.8: '...and caps the result at 100.' and
        PRD section 2.9: 'any battery percentage greater than 100 is
        clamped to exactly 100.'

        Claim: robot at 95 with charge_rate=1 after delta=10s -> 100.
        """
        fleet = create_fleet()
        n = create_map_node(fleet["id"], kind="CHARGER", x=0, y=0)
        create_charging_station(
            fleet["id"], node_id=n["id"], charge_rate_pct_per_second=1
        )
        robot = create_robot(
            fleet["id"], position_node_id=n["id"], battery_pct=95
        )
        dock_robot(fleet["id"], robot["id"])
        advance_clock(fleet["id"], 10)
        refreshed = get_robot(fleet["id"], robot["id"])
        assert refreshed["battery_pct"] == 100
