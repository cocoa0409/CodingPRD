"""Difficulty queue A — resource_temporal_overlap instances."""
import pytest

from test_helpers import (
    get_success_data, validate_success, validate_error, ApiErrorId,
    create_airport, create_terminal, create_segment, create_passenger,
    create_assist_request, create_leg, create_agent, create_wheelchair,
    submit_request, dispatch_leg, set_clock,
    api_client, TEST_USERS,
)


ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["ops_manager_headers"]
REQ = TEST_USERS["requester_headers"]
DISP = TEST_USERS["dispatcher_headers"]


# ---------------------------------------------------------------------------
# Design: Difficulty/resource_temporal_overlap/agent_assignment_half_open_adjacency_no_conflict
# ---------------------------------------------------------------------------

class TestAgentHalfOpenAdjacency:
    def test_adjacent_assignments_on_same_agent_both_dispatch(self, api):
        """PRD §3.4: "Overlap is a half-open interval intersection. An existing
        assignment of the agent overlaps the candidate leg when the assignment is
        in `DISPATCHED`, `AT_PICKUP`, `IN_TRANSIT`, or `AT_GATE`, and the half-open
        interval from its `scheduled_pickup_utc` to its `scheduled_completion_utc`
        intersects the half-open interval from the leg's `scheduled_pickup_utc` to
        that time plus the estimated transfer duration. Adjacency — where one
        interval's end equals the other's start — is **not** a conflict."

        Design: Difficulty/resource_temporal_overlap/agent_assignment_half_open_adjacency_no_conflict
        """
        set_clock("2026-06-15T08:00:00Z")
        airport = create_airport(iata_code="BWI", meet_buffer_minutes=15)
        terminal = create_terminal(airport["id"], code="A", requires_secure_escort=False)
        # L1: ARRIVAL at 09:00 → pickup 08:45, +45min → [08:45, 09:30)
        seg1 = create_segment(
            airport["id"], terminal["id"], flight_no="WN1",
            direction="ARRIVAL", scheduled_utc="2026-06-16T09:00:00Z",
        )
        # L2: ARRIVAL at 09:45 → pickup 09:30, +45min → [09:30, 10:15). Adjacent to L1.
        seg2 = create_segment(
            airport["id"], terminal["id"], flight_no="WN2",
            direction="ARRIVAL", scheduled_utc="2026-06-16T09:45:00Z",
        )
        passenger = create_passenger(
            full_name="P BWI", dob="1980-01-01", mobility_code="WCHR",
            airline_pnr="BWI1",
        )
        request = create_assist_request(
            passenger["id"], bill_to="AIRLINE", service_tier="STANDARD",
            companion_count=0,
        )
        leg1 = create_leg(request["id"], seg1["id"],
                          leg_kind="MEET_ARRIVAL", pickup_zone="Z1")
        leg2 = create_leg(request["id"], seg2["id"],
                          leg_kind="MEET_ARRIVAL", pickup_zone="Z2")
        set_clock("2026-06-16T08:00:00Z")
        request = submit_request(request["id"])
        agent = create_agent(
            airport["id"], display_name="BWI Ag",
            shift_start_utc="2026-06-16T08:00:00Z",
            shift_end_utc="2026-06-16T20:00:00Z",
        )
        wc1 = create_wheelchair(airport["id"], asset_tag="WC-BWI-1")
        wc2 = create_wheelchair(airport["id"], asset_tag="WC-BWI-2")
        asg1 = dispatch_leg(leg1["id"], request["id"], DISP)
        # Trigger: dispatch leg2 — half-open adjacency means SAME agent is selected
        asg2 = dispatch_leg(leg2["id"], request["id"], DISP)
        assert asg2["agent_id"] == agent["id"], (
            "Adjacency must not exclude the same agent from the second dispatch"
        )
        agent_after = get_success_data(api_client.get_agent(agent["id"], DISP))
        assert agent_after["active_assignment_count"] == 2

    def test_overlapping_assignments_force_different_agent(self, api):
        """PRD §3.4: "An agent with an overlapping assignment is excluded."

        Design: Difficulty/resource_temporal_overlap/agent_assignment_half_open_adjacency_no_conflict
        """
        set_clock("2026-06-15T08:00:00Z")
        airport = create_airport(iata_code="BWI", meet_buffer_minutes=15)
        terminal = create_terminal(airport["id"], code="A", requires_secure_escort=False)
        # Both legs overlap: same pickup window
        seg1 = create_segment(
            airport["id"], terminal["id"], flight_no="WN3",
            direction="ARRIVAL", scheduled_utc="2026-06-16T09:00:00Z",
        )
        seg2 = create_segment(
            airport["id"], terminal["id"], flight_no="WN4",
            direction="ARRIVAL", scheduled_utc="2026-06-16T09:05:00Z",
        )
        passenger = create_passenger(
            full_name="P BWI2", dob="1980-01-01", mobility_code="WCHR",
            airline_pnr="BWI2",
        )
        request = create_assist_request(
            passenger["id"], bill_to="AIRLINE", service_tier="STANDARD",
            companion_count=0,
        )
        leg1 = create_leg(request["id"], seg1["id"],
                          leg_kind="MEET_ARRIVAL", pickup_zone="Z1")
        leg2 = create_leg(request["id"], seg2["id"],
                          leg_kind="MEET_ARRIVAL", pickup_zone="Z2")
        set_clock("2026-06-16T08:00:00Z")
        request = submit_request(request["id"])
        agent1 = create_agent(
            airport["id"], display_name="BWI Ag1",
            shift_start_utc="2026-06-16T08:00:00Z",
            shift_end_utc="2026-06-16T20:00:00Z",
        )
        agent2 = create_agent(
            airport["id"], display_name="BWI Ag2",
            shift_start_utc="2026-06-16T08:00:00Z",
            shift_end_utc="2026-06-16T20:00:00Z",
        )
        wc1 = create_wheelchair(airport["id"], asset_tag="WC-BWI-3")
        wc2 = create_wheelchair(airport["id"], asset_tag="WC-BWI-4")
        asg1 = dispatch_leg(leg1["id"], request["id"], DISP)
        asg2 = dispatch_leg(leg2["id"], request["id"], DISP)
        # Overlap → second dispatch picks the OTHER agent
        assert asg1["agent_id"] != asg2["agent_id"]


# ---------------------------------------------------------------------------
# Design: Difficulty/resource_temporal_overlap/wheelchair_capacity_shared_pool_aggregate_conflict
# ---------------------------------------------------------------------------

class TestWheelchairSharedPoolConflict:
    def _setup_two_overlapping_legs_one_chair(self):
        set_clock("2026-06-15T08:00:00Z")
        airport = create_airport(iata_code="MDW", meet_buffer_minutes=15)
        terminal = create_terminal(airport["id"], code="M", requires_secure_escort=False)
        seg1 = create_segment(
            airport["id"], terminal["id"], flight_no="WN10",
            direction="ARRIVAL", scheduled_utc="2026-06-16T09:00:00Z",
        )
        seg2 = create_segment(
            airport["id"], terminal["id"], flight_no="WN11",
            direction="ARRIVAL", scheduled_utc="2026-06-16T09:10:00Z",
        )
        passenger = create_passenger(
            full_name="P MDW", dob="1980-01-01", mobility_code="WCHC",
            airline_pnr="MDW1",
        )
        request = create_assist_request(
            passenger["id"], bill_to="AIRLINE", service_tier="STANDARD",
            companion_count=0,
        )
        leg1 = create_leg(request["id"], seg1["id"],
                          leg_kind="MEET_ARRIVAL", pickup_zone="Z1")
        leg2 = create_leg(request["id"], seg2["id"],
                          leg_kind="MEET_ARRIVAL", pickup_zone="Z2")
        set_clock("2026-06-16T08:00:00Z")
        request = submit_request(request["id"])
        agent1 = create_agent(
            airport["id"], display_name="MDW Ag1",
            shift_start_utc="2026-06-16T08:00:00Z",
            shift_end_utc="2026-06-16T20:00:00Z",
        )
        agent2 = create_agent(
            airport["id"], display_name="MDW Ag2",
            shift_start_utc="2026-06-16T08:00:00Z",
            shift_end_utc="2026-06-16T20:00:00Z",
        )
        wheelchair = create_wheelchair(
            airport["id"], asset_tag="WC-MDW-1",
            chair_class="POWER", is_wchc_rated=True,
        )
        return airport, request, leg1, leg2, agent1, agent2, wheelchair

    def test_second_overlapping_dispatch_returns_no_available_wheelchair(self, api):
        """PRD §3.4: "An empty wheelchair pool is rejected with
        `ERR_NO_AVAILABLE_WHEELCHAIR` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/wheelchair_capacity_shared_pool_aggregate_conflict
        """
        airport, request, leg1, leg2, ag1, ag2, wc = (
            self._setup_two_overlapping_legs_one_chair()
        )
        # First dispatch takes the only chair
        asg1 = dispatch_leg(leg1["id"], request["id"], DISP)
        # Second overlapping dispatch — chair is CHECKED_OUT, no other chair available
        cur = get_success_data(api_client.get_assist_request(request["id"], DISP))
        resp = api_client.dispatch_leg(
            leg2["id"],
            {"expected_assist_request_version": cur["version"]},
            DISP,
        )
        validate_error(resp, ApiErrorId.ERR_NO_AVAILABLE_WHEELCHAIR)

    def test_chair_remains_checked_out_after_failed_second_dispatch(self, api):
        """PRD §3.4: "The selected chair transitions from `AVAILABLE` to
        `CHECKED_OUT`." A failed second dispatch must not change the chair state.

        Design: Difficulty/resource_temporal_overlap/wheelchair_capacity_shared_pool_aggregate_conflict
        """
        airport, request, leg1, leg2, ag1, ag2, wc = (
            self._setup_two_overlapping_legs_one_chair()
        )
        asg1 = dispatch_leg(leg1["id"], request["id"], DISP)
        cur = get_success_data(api_client.get_assist_request(request["id"], DISP))
        api_client.dispatch_leg(
            leg2["id"],
            {"expected_assist_request_version": cur["version"]},
            DISP,
        )
        chair = get_success_data(api_client.get_wheelchair(wc["id"], DISP))
        assert chair["status"] == "CHECKED_OUT"
        # leg2 still PLANNED — dispatch failed
        leg2_after = get_success_data(api_client.get_leg(leg2["id"], DISP))
        assert leg2_after["status"] == "PLANNED"
