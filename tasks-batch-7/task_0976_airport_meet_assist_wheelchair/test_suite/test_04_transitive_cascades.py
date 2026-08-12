"""Difficulty queue A — transitive_cascade instances."""
import pytest

from test_helpers import (
    get_success_data, validate_success, ApiErrorId,
    create_airport, create_terminal, create_segment, create_passenger,
    create_assist_request, create_leg, create_agent, create_wheelchair,
    submit_request, dispatch_leg, set_clock,
    walk_assignment_to_handed_off,
    make_agent_headers,
    api_client, TEST_USERS,
)


ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["ops_manager_headers"]
REQ = TEST_USERS["requester_headers"]
DISP = TEST_USERS["dispatcher_headers"]


# ---------------------------------------------------------------------------
# Design: Difficulty/transitive_cascade/lockdown_cascade_airport_to_leg_to_assignment_to_chair_to_agent_count
# ---------------------------------------------------------------------------

class TestLockdownCascade:
    def _setup_dispatched_at_bos(self):
        set_clock("2026-06-15T10:00:00Z")
        airport = create_airport(iata_code="BOS", meet_buffer_minutes=15)
        terminal = create_terminal(airport["id"], code="E", requires_secure_escort=False)
        segment = create_segment(
            airport["id"], terminal["id"], flight_no="JB1",
            direction="ARRIVAL", scheduled_utc="2026-06-16T10:00:00Z",
        )
        passenger = create_passenger(
            full_name="P BOS", dob="1980-01-01", mobility_code="WCHC",
            airline_pnr="BB1",
        )
        request = create_assist_request(
            passenger["id"], bill_to="AIRLINE", service_tier="STANDARD",
            companion_count=0,
        )
        leg = create_leg(request["id"], segment["id"],
                         leg_kind="MEET_ARRIVAL", pickup_zone="Z")
        set_clock("2026-06-16T09:00:00Z")
        request = submit_request(request["id"])
        agent = create_agent(
            airport["id"], display_name="BOS Ag",
            shift_start_utc="2026-06-16T08:00:00Z",
            shift_end_utc="2026-06-16T20:00:00Z",
        )
        wheelchair = create_wheelchair(
            airport["id"], asset_tag="WC-BOS-1",
            chair_class="POWER", is_wchc_rated=True,
        )
        assignment = dispatch_leg(leg["id"], request["id"], DISP)
        # Move to DEGRADED (provisional recompute; assignments untouched)
        get_success_data(api_client.set_airport_posture(
            airport["id"], {"posture": "DEGRADED"}, OPS,
        ))
        return airport, agent, wheelchair, request, leg, assignment

    def test_lockdown_cascades_leg_assignment_chair_agent(self, api):
        """PRD §3.7: "**DEGRADED → LOCKDOWN.** Every service leg at this airport
        in `PLANNED`, `DISPATCHED`, or `AT_PICKUP` transitions to `CANCELLED`. Each
        cancelled leg bubbles up: when every leg of a request is in `CANCELLED` or
        `FAILED`, the parent request's `request_status` becomes `FAILED`, its
        provisional invoice (if any) is voided, and `billing_status` returns to
        `UNBILLED`. Wheelchairs in `CHECKED_OUT` whose assignment's leg was just
        cancelled return to `AVAILABLE` without decrementing `usage_count`."

        Design: Difficulty/transitive_cascade/lockdown_cascade_airport_to_leg_to_assignment_to_chair_to_agent_count
        """
        airport, agent, wheelchair, request, leg, assignment = self._setup_dispatched_at_bos()
        # Pre-condition: assignment DISPATCHED, chair CHECKED_OUT, agent count 1
        pre_agent = get_success_data(api_client.get_agent(agent["id"], OPS))
        assert pre_agent["active_assignment_count"] == 1
        pre_chair = get_success_data(api_client.get_wheelchair(wheelchair["id"], OPS))
        assert pre_chair["status"] == "CHECKED_OUT"
        # Trigger LOCKDOWN
        get_success_data(api_client.set_airport_posture(
            airport["id"], {"posture": "LOCKDOWN"}, OPS,
        ))
        # Assert depth-4 cascade
        leg_after = get_success_data(api_client.get_leg(leg["id"], DISP))
        assert leg_after["status"] == "CANCELLED"
        asg_after = get_success_data(api_client.get_assignment(assignment["id"], DISP))
        assert asg_after["status"] == "CANCELLED"
        chair_after = get_success_data(api_client.get_wheelchair(wheelchair["id"], OPS))
        assert chair_after["status"] == "AVAILABLE"
        agent_after = get_success_data(api_client.get_agent(agent["id"], OPS))
        assert agent_after["active_assignment_count"] == 0
        req_after = get_success_data(api_client.get_assist_request(request["id"], DISP))
        assert req_after["request_status"] == "FAILED"
        assert req_after["billing_status"] == "UNBILLED"

    def test_lockdown_voids_provisional_invoice(self, api):
        """PRD §3.7: "its provisional invoice (if any) is voided."

        Design: Difficulty/transitive_cascade/lockdown_cascade_airport_to_leg_to_assignment_to_chair_to_agent_count
        """
        airport, agent, wheelchair, request, leg, assignment = self._setup_dispatched_at_bos()
        # Capture provisional invoice pre-lockdown
        inv_pre = get_success_data(api_client.list_request_invoices(
            request["id"], TEST_USERS["billing_clerk_headers"],
        ))
        prov_pre = [i for i in inv_pre if i["invoice_kind"] == "PROVISIONAL"]
        assert len(prov_pre) == 1
        assert prov_pre[0]["status"] == "OPEN"
        # Lockdown
        get_success_data(api_client.set_airport_posture(
            airport["id"], {"posture": "LOCKDOWN"}, OPS,
        ))
        # Provisional invoice is now VOID
        inv_post = get_success_data(api_client.list_request_invoices(
            request["id"], TEST_USERS["billing_clerk_headers"],
        ))
        prov_post = [i for i in inv_post if i["invoice_kind"] == "PROVISIONAL"]
        assert prov_post[0]["status"] == "VOID"


# ---------------------------------------------------------------------------
# Design: Difficulty/transitive_cascade/incident_critical_resolve_cascade_to_agent_suspend_to_assignment_requeue
# ---------------------------------------------------------------------------

class TestIncidentCriticalCascade:
    def _setup_in_transit_at_dfw(self):
        set_clock("2026-06-15T10:00:00Z")
        airport = create_airport(iata_code="DFW", meet_buffer_minutes=15)
        terminal = create_terminal(airport["id"], code="A", requires_secure_escort=False)
        segment = create_segment(
            airport["id"], terminal["id"], flight_no="AA100",
            direction="ARRIVAL", scheduled_utc="2026-06-16T10:00:00Z",
        )
        passenger = create_passenger(
            # WCHS so the leg's requires_wheelchair flag is set (PRD §3.2) and
            # the dispatch actually checks out the wheelchair created below.
            full_name="P DFW", dob="1980-01-01", mobility_code="WCHS",
            airline_pnr="DD1",
        )
        request = create_assist_request(
            passenger["id"], bill_to="AIRLINE", service_tier="STANDARD",
            companion_count=0,
        )
        leg = create_leg(request["id"], segment["id"],
                         leg_kind="MEET_ARRIVAL", pickup_zone="Z")
        set_clock("2026-06-16T09:00:00Z")
        request = submit_request(request["id"])
        agent = create_agent(
            airport["id"], display_name="DFW Ag",
            shift_start_utc="2026-06-16T08:00:00Z",
            shift_end_utc="2026-06-16T20:00:00Z",
        )
        wheelchair = create_wheelchair(airport["id"], asset_tag="WC-DFW-1")
        assignment = dispatch_leg(leg["id"], request["id"], DISP)
        # Walk to IN_TRANSIT
        agent_hdrs = make_agent_headers(agent["id"])
        get_success_data(api_client.post_assignment_event(
            assignment["id"], {"event_type": "ARRIVE_PICKUP"}, agent_hdrs,
        ))
        get_success_data(api_client.post_assignment_event(
            assignment["id"], {"event_type": "DEPART_PICKUP"}, agent_hdrs,
        ))
        return airport, agent, wheelchair, request, leg, assignment

    def test_incident_critical_resolve_suspends_agent_and_cancels_assignment(self, api):
        """PRD §3.8: "when the linked assignment's agent is `ACTIVE`, that agent
        transitions to `SUSPENDED` and the full unassign cascade of §3.7 fires:
        in-flight assignments become `CANCELLED`, their parent legs return to
        `PLANNED`, and held chairs return to `AVAILABLE` without decrementing
        `usage_count`."

        Design: Difficulty/transitive_cascade/incident_critical_resolve_cascade_to_agent_suspend_to_assignment_requeue
        """
        airport, agent, wheelchair, request, leg, assignment = self._setup_in_transit_at_dfw()
        # Open CRITICAL incident as the agent
        incident = get_success_data(api_client.create_incident(
            {"assignment_id": assignment["id"], "kind": "FALL",
             "severity": "CRITICAL", "description": "Passenger fell"},
            make_agent_headers(agent["id"]),
        ))
        # ACK
        get_success_data(api_client.post_incident_event(
            incident["id"], {"event_type": "ACK"}, OPS,
        ))
        # RESOLVE
        resolved = get_success_data(api_client.post_incident_event(
            incident["id"], {"event_type": "RESOLVE"}, OPS,
        ))
        assert resolved["status"] == "RESOLVED"
        # Cascade assertions
        agent_after = get_success_data(api_client.get_agent(agent["id"], OPS))
        assert agent_after["status"] == "SUSPENDED"
        asg_after = get_success_data(api_client.get_assignment(assignment["id"], DISP))
        assert asg_after["status"] == "CANCELLED"
        leg_after = get_success_data(api_client.get_leg(leg["id"], DISP))
        assert leg_after["status"] == "PLANNED"
        chair_after = get_success_data(api_client.get_wheelchair(wheelchair["id"], OPS))
        assert chair_after["status"] == "AVAILABLE"
        assert agent_after["active_assignment_count"] == 0

    def test_incident_critical_resolve_returns_leg_to_planned_not_cancelled(self, api):
        """PRD §3.10: "the direct cancel from the agent-suspend cascade which
        leaves the leg rebookable in `PLANNED`." (Distinguishes rebookable-PLANNED
        from direct-CANCEL_ASSIGN's CANCELLED.)

        Design: Difficulty/transitive_cascade/incident_critical_resolve_cascade_to_agent_suspend_to_assignment_requeue
        """
        airport, agent, wheelchair, request, leg, assignment = self._setup_in_transit_at_dfw()
        incident = get_success_data(api_client.create_incident(
            {"assignment_id": assignment["id"], "kind": "MEDICAL",
             "severity": "CRITICAL", "description": "Medical"},
            make_agent_headers(agent["id"]),
        ))
        get_success_data(api_client.post_incident_event(
            incident["id"], {"event_type": "ACK"}, OPS,
        ))
        get_success_data(api_client.post_incident_event(
            incident["id"], {"event_type": "RESOLVE"}, OPS,
        ))
        leg_after = get_success_data(api_client.get_leg(leg["id"], DISP))
        # Rebookable: PLANNED, not CANCELLED
        assert leg_after["status"] == "PLANNED"
        # Chair usage_count is NOT decremented — just returns to AVAILABLE
        chair_after = get_success_data(api_client.get_wheelchair(wheelchair["id"], OPS))
        assert chair_after["status"] == "AVAILABLE"
        assert chair_after["usage_count"] == 1  # still reflects the original checkout
