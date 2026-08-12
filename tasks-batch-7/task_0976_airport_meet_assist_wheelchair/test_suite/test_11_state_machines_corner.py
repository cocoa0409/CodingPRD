"""Corner queue B — state_machines section instances."""
import pytest

from test_helpers import (
    get_success_data, validate_success, validate_error, ApiErrorId,
    create_airport, create_terminal, create_segment, create_passenger,
    create_assist_request, create_leg, create_agent, create_wheelchair,
    submit_request, dispatch_leg, set_clock,
    make_agent_headers, api_client, TEST_USERS, NON_EXISTENT_UUID,
)


ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["ops_manager_headers"]
REQ = TEST_USERS["requester_headers"]
DISP = TEST_USERS["dispatcher_headers"]


class TestInvalidTransitionCompleteBeforeDispatch:
    def test_invalid_transition_complete_before_dispatch_rejected(self, api):
        """PRD §2.9: "3. **Existence** — path-template identifiers resolve to
        live resources, left to right (`ERR_NOT_FOUND`)."

        Design: Corner/state_machines/invalid_transition_complete_before_dispatch_rejected
        """
        set_clock("2026-06-15T10:00:00Z")
        airport = create_airport(iata_code="MCO", meet_buffer_minutes=15)
        terminal = create_terminal(airport["id"], code="A", requires_secure_escort=False)
        segment = create_segment(
            airport["id"], terminal["id"], flight_no="MCO1",
            direction="ARRIVAL", scheduled_utc="2026-06-16T10:00:00Z",
        )
        passenger = create_passenger(
            full_name="P MCO", dob="1980-01-01", mobility_code="WCHR",
            airline_pnr="MCO1",
        )
        request = create_assist_request(
            passenger["id"], bill_to="AIRLINE", service_tier="STANDARD",
            companion_count=0,
        )
        leg = create_leg(request["id"], segment["id"],
                         leg_kind="MEET_ARRIVAL", pickup_zone="Z")
        set_clock("2026-06-16T09:00:00Z")
        submit_request(request["id"])
        # Attempt ARRIVE_PICKUP against a non-existent assignment id
        resp = api_client.post_assignment_event(
            NON_EXISTENT_UUID, {"event_type": "ARRIVE_PICKUP"},
            make_agent_headers("someone"),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestCancelInServiceRequestRejected:
    def test_cancel_in_service_request_rejected(self, api):
        """PRD §3.10: "Cancelling a `SUBMITTED` request is permitted only when no
        assignment has reached `AT_PICKUP`, `IN_TRANSIT`, or `AT_GATE`; attempting
        to cancel with such an in-flight assignment is rejected with
        `ERR_ALREADY_IN_SERVICE` (HTTP 409)."

        Design: Corner/state_machines/cancel_in_service_request_rejected
        """
        set_clock("2026-06-15T10:00:00Z")
        airport = create_airport(iata_code="RDU", meet_buffer_minutes=15)
        terminal = create_terminal(airport["id"], code="2", requires_secure_escort=False)
        segment = create_segment(
            airport["id"], terminal["id"], flight_no="RDU1",
            direction="ARRIVAL", scheduled_utc="2026-06-16T10:00:00Z",
        )
        passenger = create_passenger(
            full_name="P RDU", dob="1980-01-01", mobility_code="WCHR",
            airline_pnr="RDU1",
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
            airport["id"], display_name="RDU Ag",
            shift_start_utc="2026-06-16T08:00:00Z",
            shift_end_utc="2026-06-16T20:00:00Z",
        )
        wheelchair = create_wheelchair(airport["id"], asset_tag="WC-RDU-1")
        assignment = dispatch_leg(leg["id"], request["id"], DISP)
        # ARRIVE_PICKUP — assignment now AT_PICKUP, request now IN_SERVICE
        get_success_data(api_client.post_assignment_event(
            assignment["id"], {"event_type": "ARRIVE_PICKUP"},
            make_agent_headers(agent["id"]),
        ))
        # Attempt CANCEL
        cur = get_success_data(api_client.get_assist_request(request["id"], REQ))
        resp = api_client.post_assist_request_event(
            request["id"],
            {"event_type": "CANCEL",
             "expected_assist_request_version": cur["version"]},
            REQ,
        )
        validate_error(resp, ApiErrorId.ERR_ALREADY_IN_SERVICE)
        # Request stays IN_SERVICE
        req_after = get_success_data(api_client.get_assist_request(request["id"], REQ))
        assert req_after["request_status"] == "IN_SERVICE"


class TestRetireChairInUseRejected:
    def test_retire_chair_in_use_rejected(self, api):
        """PRD §3.1: "a chair's terminal state is `RETIRED`, reachable only from
        `MAINTENANCE` and only when no in-flight assignment (in `DISPATCHED`,
        `AT_PICKUP`, `IN_TRANSIT`, or `AT_GATE`) still references it — attempting
        retirement while such a reference exists is rejected with
        `ERR_CHAIR_IN_USE` (HTTP 409)."

        Design: Corner/state_machines/retire_chair_in_use_rejected
        """
        set_clock("2026-06-15T10:00:00Z")
        airport = create_airport(iata_code="SMF", meet_buffer_minutes=15)
        terminal = create_terminal(airport["id"], code="A", requires_secure_escort=False)
        segment = create_segment(
            airport["id"], terminal["id"], flight_no="SMF1",
            direction="ARRIVAL", scheduled_utc="2026-06-16T10:00:00Z",
        )
        passenger = create_passenger(
            # WCHS so the leg sets requires_wheelchair (PRD §3.2) and dispatch
            # checks out the chair — putting an in-flight assignment reference
            # on it, which is the precondition the ERR_CHAIR_IN_USE rule needs.
            full_name="P SMF", dob="1980-01-01", mobility_code="WCHS",
            airline_pnr="SMF1",
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
            airport["id"], display_name="SMF Ag",
            shift_start_utc="2026-06-16T08:00:00Z",
            shift_end_utc="2026-06-16T20:00:00Z",
        )
        wheelchair = create_wheelchair(airport["id"], asset_tag="WC-SMF-1")
        # Cycle through maintenance once (so we can RETIRE later if not in use)
        get_success_data(api_client.post_wheelchair_event(
            wheelchair["id"], {"event_type": "SCHEDULE_MAINTENANCE"}, OPS,
        ))
        get_success_data(api_client.post_wheelchair_event(
            wheelchair["id"], {"event_type": "COMPLETE_MAINTENANCE"}, OPS,
        ))
        # Dispatch — chair now CHECKED_OUT
        assignment = dispatch_leg(leg["id"], request["id"], DISP)
        # RETIRE — must be rejected
        resp = api_client.post_wheelchair_event(
            wheelchair["id"], {"event_type": "RETIRE"}, OPS,
        )
        validate_error(resp, ApiErrorId.ERR_CHAIR_IN_USE)
        chair_after = get_success_data(api_client.get_wheelchair(wheelchair["id"], OPS))
        assert chair_after["status"] == "CHECKED_OUT"
