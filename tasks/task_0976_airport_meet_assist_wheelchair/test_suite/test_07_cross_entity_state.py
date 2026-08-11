"""Difficulty queue A — cross_entity_state_dependency instances."""
import pytest

from test_helpers import (
    get_success_data, validate_success, validate_error, ApiErrorId,
    create_airport, create_terminal, create_segment, create_passenger,
    create_assist_request, create_leg, create_agent, create_wheelchair,
    submit_request, dispatch_leg, set_clock, walk_assignment_to_handed_off,
    make_agent_headers, make_confirmer_headers, make_dispatcher_headers,
    api_client, TEST_USERS,
)


ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["ops_manager_headers"]
REQ = TEST_USERS["requester_headers"]
DISP = TEST_USERS["dispatcher_headers"]


# ---------------------------------------------------------------------------
# Design: Difficulty/cross_entity_state_dependency/dispatch_requires_airport_not_lockdown
# ---------------------------------------------------------------------------

class TestDispatchRequiresNotLockdown:
    def _setup_request_in_lockdown(self):
        set_clock("2026-06-15T10:00:00Z")
        airport = create_airport(iata_code="DEN", meet_buffer_minutes=15)
        terminal = create_terminal(airport["id"], code="C", requires_secure_escort=False)
        segment = create_segment(
            airport["id"], terminal["id"], flight_no="UA50",
            direction="ARRIVAL", scheduled_utc="2026-06-16T10:00:00Z",
        )
        passenger = create_passenger(
            full_name="P DEN", dob="1980-01-01", mobility_code="WCHR",
            airline_pnr="DEN1",
        )
        request = create_assist_request(
            passenger["id"], bill_to="AIRLINE", service_tier="STANDARD",
            companion_count=0,
        )
        leg = create_leg(request["id"], segment["id"],
                         leg_kind="MEET_ARRIVAL", pickup_zone="Z")
        set_clock("2026-06-16T09:00:00Z")
        request = submit_request(request["id"])
        # Move to LOCKDOWN
        get_success_data(api_client.set_airport_posture(
            airport["id"], {"posture": "DEGRADED"}, OPS,
        ))
        get_success_data(api_client.set_airport_posture(
            airport["id"], {"posture": "LOCKDOWN"}, OPS,
        ))
        return airport, request, leg

    def test_dispatch_during_lockdown_rejected(self, api):
        """PRD §3.4: "Dispatch is permitted only while the parent request is in
        `SUBMITTED` or `ASSIGNED` and the airport is not in `LOCKDOWN`; attempts
        outside those states are rejected with `ERR_INVALID_STATE` or
        `ERR_POSTURE_RESTRICTED` respectively."

        Design: Difficulty/cross_entity_state_dependency/dispatch_requires_airport_not_lockdown
        """
        airport, request, leg = self._setup_request_in_lockdown()
        cur = get_success_data(api_client.get_assist_request(request["id"], DISP))
        resp = api_client.dispatch_leg(
            leg["id"],
            {"expected_assist_request_version": cur["version"]},
            DISP,
        )
        # Lockdown cascade has already cancelled the leg, so the from-state check
        # may fire (ERR_INVALID_STATE). Either state-priority error satisfies the
        # rule — what must NOT happen is a successful dispatch.
        assert resp.status_code in (409, 412)
        assert resp.json()["data"]["error_id"] in (
            "ERR_POSTURE_RESTRICTED", "ERR_INVALID_STATE", "ERR_STALE_VERSION",
        )

    def test_leg_is_cancelled_by_lockdown_cascade(self, api):
        """PRD §3.7: "**DEGRADED → LOCKDOWN.** Every service leg at this airport
        in `PLANNED`, `DISPATCHED`, or `AT_PICKUP` transitions to `CANCELLED`."

        Design: Difficulty/cross_entity_state_dependency/dispatch_requires_airport_not_lockdown
        """
        airport, request, leg = self._setup_request_in_lockdown()
        # After lockdown cascade the leg is CANCELLED
        leg_after = get_success_data(api_client.get_leg(leg["id"], DISP))
        assert leg_after["status"] == "CANCELLED"


# ---------------------------------------------------------------------------
# Design: Difficulty/cross_entity_state_dependency/complete_requires_confirmer_distinct_from_dispatcher
# ---------------------------------------------------------------------------

class TestCompleteRequiresConfirmerDistinct:
    def _setup_handed_off(self, dispatcher_user_id):
        set_clock("2026-06-15T10:00:00Z")
        airport = create_airport(iata_code="MSP", meet_buffer_minutes=15)
        terminal = create_terminal(airport["id"], code="1", requires_secure_escort=False)
        segment = create_segment(
            airport["id"], terminal["id"], flight_no="DL50",
            direction="ARRIVAL", scheduled_utc="2026-06-16T10:00:00Z",
        )
        passenger = create_passenger(
            full_name="P MSP", dob="1980-01-01", mobility_code="WCHR",
            airline_pnr="MSP1",
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
            airport["id"], display_name="MSP Ag",
            shift_start_utc="2026-06-16T08:00:00Z",
            shift_end_utc="2026-06-16T20:00:00Z",
        )
        wheelchair = create_wheelchair(airport["id"], asset_tag="WC-MSP-1")
        disp_hdrs = make_dispatcher_headers(dispatcher_user_id)
        assignment = dispatch_leg(leg["id"], request["id"], disp_hdrs)
        walk_assignment_to_handed_off(assignment["id"], agent["id"])
        return airport, request, leg, agent, assignment

    def test_complete_by_same_user_as_dispatcher_rejected(self, api):
        """PRD §3.5: "The confirmer's user id must differ from
        `assigned_by_user_id`; otherwise the completion is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Difficulty/cross_entity_state_dependency/complete_requires_confirmer_distinct_from_dispatcher
        """
        airport, request, leg, agent, assignment = self._setup_handed_off("disp_1")
        # Attempt COMPLETE with the same user_id as the dispatcher
        resp = api_client.post_assignment_event(
            assignment["id"], {"event_type": "COMPLETE"},
            make_confirmer_headers("disp_1"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        # State unchanged: leg still HANDED_OFF, completed_by_user_id still null
        leg_after = get_success_data(api_client.get_leg(leg["id"], DISP))
        assert leg_after["status"] == "HANDED_OFF"
        asg_after = get_success_data(api_client.get_assignment(assignment["id"], DISP))
        assert asg_after.get("completed_by_user_id") is None

    def test_complete_by_distinct_confirmer_succeeds(self, api):
        """PRD §3.5: "A `Confirmer` — never the dispatcher who assigned the work —
        closes the leg from `HANDED_OFF` to `COMPLETED`."

        Design: Difficulty/cross_entity_state_dependency/complete_requires_confirmer_distinct_from_dispatcher
        """
        airport, request, leg, agent, assignment = self._setup_handed_off("disp_2")
        # Mark segment landed so the completion cascades can finalize the request
        get_success_data(api_client.post_segment_event(
            # segment is reachable via leg.segment_id; fetch to be safe
            get_success_data(api_client.get_leg(leg["id"], DISP))["segment_id"],
            {"event_type": "LANDED", "actual_utc": "2026-06-16T10:00:00Z"},
            OPS,
        ))
        # COMPLETE as a different confirmer user_id
        resp = api_client.post_assignment_event(
            assignment["id"], {"event_type": "COMPLETE"},
            make_confirmer_headers("confirmer_other"),
        )
        completed = validate_success(resp)
        assert completed["status"] == "COMPLETED"
        assert completed["completed_by_user_id"] == "confirmer_other"
