"""Corner queue B — rbac section instances."""
import pytest

from test_helpers import (
    get_success_data, validate_success, validate_error, ApiErrorId,
    create_airport, create_terminal, create_segment, create_passenger,
    create_assist_request, create_leg, submit_request, set_clock,
    make_agent_headers, api_client, TEST_USERS,
)


ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["ops_manager_headers"]
REQ = TEST_USERS["requester_headers"]
DISP = TEST_USERS["dispatcher_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]


class TestAgentCannotDispatch:
    def test_agent_cannot_dispatch(self, api):
        """PRD §2.1: "A request whose role is well-formed but not on the
        endpoint's authorized-roles list is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."
        PRD §4: POST /maa/legs/{id}/dispatch is `Dispatcher`-only.

        Design: Corner/rbac/agent_cannot_dispatch
        """
        set_clock("2026-06-15T10:00:00Z")
        airport = create_airport(iata_code="PVD", meet_buffer_minutes=15)
        terminal = create_terminal(airport["id"], code="M", requires_secure_escort=False)
        segment = create_segment(
            airport["id"], terminal["id"], flight_no="PVD1",
            direction="ARRIVAL", scheduled_utc="2026-06-16T10:00:00Z",
        )
        passenger = create_passenger(
            full_name="P PVD", dob="1990-01-01", mobility_code="WCHR",
            airline_pnr="PVD1",
        )
        request = create_assist_request(
            passenger["id"], bill_to="AIRLINE", service_tier="STANDARD",
            companion_count=0,
        )
        leg = create_leg(request["id"], segment["id"],
                         leg_kind="MEET_ARRIVAL", pickup_zone="Z")
        set_clock("2026-06-16T09:00:00Z")
        submit_request(request["id"])
        cur = get_success_data(api_client.get_assist_request(request["id"], DISP))
        # Attempt dispatch as Agent
        resp = api_client.dispatch_leg(
            leg["id"],
            {"expected_assist_request_version": cur["version"]},
            make_agent_headers("agent_x"),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


class TestBillingClerkCannotRunOps:
    def test_billing_clerk_cannot_run_ops(self, api):
        """PRD §2.1: "A request whose role is well-formed but not on the
        endpoint's authorized-roles list is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."
        PRD §4: POST /maa/airports/{id}/run_ops is `OpsManager`-only.

        Design: Corner/rbac/billing_clerk_cannot_run_ops
        """
        airport = create_airport(iata_code="BOI", meet_buffer_minutes=15)
        resp = api_client.run_ops(airport["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
