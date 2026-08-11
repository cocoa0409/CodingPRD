"""Difficulty queue A — non_linear_state_machine instances."""
import pytest

from test_helpers import (
    get_success_data, validate_success, validate_error, ApiErrorId,
    create_airport, create_terminal, create_segment, create_passenger,
    create_assist_request, create_leg, create_agent, create_wheelchair,
    submit_request, dispatch_leg, set_clock, setup_completed_request,
    walk_assignment_to_handed_off, complete_assignment,
    make_agent_headers, make_billing_clerk_headers, make_dispatcher_headers,
    api_client, TEST_USERS,
)


ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["ops_manager_headers"]
REQ = TEST_USERS["requester_headers"]
DISP = TEST_USERS["dispatcher_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]


# ---------------------------------------------------------------------------
# Design: Difficulty/non_linear_state_machine/assist_request_parallel_dimensions_request_x_billing
# ---------------------------------------------------------------------------

class TestAssistRequestParallelDimensions:
    def _setup_completed(self):
        return setup_completed_request(
            iata_code="PHX",
            meet_buffer_minutes=15,
            requires_secure_escort=False,
            scheduled_utc="2026-06-20T10:00:00Z",
            actual_utc="2026-06-20T10:00:00Z",
            leg_kind="MEET_ARRIVAL",
            passenger_overrides={
                "full_name": "Para P", "dob": "1975-04-04",
                "mobility_code": "WCHR", "airline_pnr": "PP1",
            },
            request_overrides={"bill_to": "AIRLINE", "service_tier": "STANDARD",
                               "companion_count": 0},
            clock_at_submit="2026-06-20T09:00:00Z",
            dispatcher_user_id="disp_phx",
            confirmer_user_id="conf_phx",
        )

    def test_dispute_does_not_change_request_status(self, api):
        """PRD §3.6: "`DISPUTE` moves an `OPEN` final invoice and the parent's
        `billing_status` to `DISPUTED`; this does **not** roll back `request_status`
        — the dispute blocks only the settlement step."

        Design: Difficulty/non_linear_state_machine/assist_request_parallel_dimensions_request_x_billing
        """
        out = self._setup_completed()
        final_inv = next(
            i for i in out["invoices"] if i["invoice_kind"] == "FINAL"
        )
        # Pre-condition: request COMPLETED, billing FINALIZED
        assert out["request"]["request_status"] == "COMPLETED"
        assert out["request"]["billing_status"] == "FINALIZED"
        # DISPUTE
        disp_resp = api_client.post_invoice_event(
            final_inv["id"],
            {"event_type": "DISPUTE",
             "expected_invoice_version": final_inv["version"]},
            make_billing_clerk_headers("clerk_d"),
        )
        validate_success(disp_resp)
        req_after = get_success_data(
            api_client.get_assist_request(out["request"]["id"], CLERK),
        )
        assert req_after["request_status"] == "COMPLETED", (
            "DISPUTE must not change request_status"
        )
        assert req_after["billing_status"] == "DISPUTED"

    def test_dispute_then_resolve_paid_reaches_paid_while_request_stays_completed(self, api):
        """PRD §3.6: "From `DISPUTED`, the clerk may `RESOLVE_PAID` to reach `PAID`."

        Design: Difficulty/non_linear_state_machine/assist_request_parallel_dimensions_request_x_billing
        """
        out = self._setup_completed()
        final_inv = next(i for i in out["invoices"] if i["invoice_kind"] == "FINAL")
        # DISPUTE then RESOLVE_PAID
        disp_resp = api_client.post_invoice_event(
            final_inv["id"],
            {"event_type": "DISPUTE",
             "expected_invoice_version": final_inv["version"]},
            make_billing_clerk_headers("clerk_d"),
        )
        disputed = validate_success(disp_resp)
        res_resp = api_client.post_invoice_event(
            final_inv["id"],
            {"event_type": "RESOLVE_PAID",
             "expected_invoice_version": disputed["version"]},
            make_billing_clerk_headers("clerk_d"),
        )
        paid = validate_success(res_resp)
        assert paid["status"] == "PAID"
        req_after = get_success_data(
            api_client.get_assist_request(out["request"]["id"], CLERK),
        )
        assert req_after["request_status"] == "COMPLETED"
        assert req_after["billing_status"] == "PAID"


# ---------------------------------------------------------------------------
# Design: Difficulty/non_linear_state_machine/agent_status_cycle_active_suspended_active_rejoins_pool
# ---------------------------------------------------------------------------

class TestAgentStatusCycle:
    def test_agent_can_be_suspended_reinstated_suspended_again(self, api):
        """PRD §3.8: "The same cascade runs when an `OpsManager` explicitly
        suspends an agent — and the reverse transition, reinstatement from
        `SUSPENDED` back to `ACTIVE`, has no side effects."

        Design: Difficulty/non_linear_state_machine/agent_status_cycle_active_suspended_active_rejoins_pool
        """
        set_clock("2026-06-15T10:00:00Z")
        airport = create_airport(iata_code="PDX", meet_buffer_minutes=15)
        agent = create_agent(
            airport["id"], display_name="Cyclic A",
            shift_start_utc="2026-06-15T08:00:00Z",
            shift_end_utc="2026-06-15T20:00:00Z",
        )
        assert agent["status"] == "ACTIVE"
        # SUSPEND
        s1 = api_client.post_agent_event(
            agent["id"], {"event_type": "SUSPEND", "reason": "first"}, OPS,
        )
        assert validate_success(s1)["status"] == "SUSPENDED"
        # REINSTATE
        r1 = api_client.post_agent_event(
            agent["id"], {"event_type": "REINSTATE"}, OPS,
        )
        assert validate_success(r1)["status"] == "ACTIVE"
        # SUSPEND a second time — cycle succeeds
        s2 = api_client.post_agent_event(
            agent["id"], {"event_type": "SUSPEND", "reason": "second"}, OPS,
        )
        assert validate_success(s2)["status"] == "SUSPENDED"

    def test_agent_reinstated_returns_to_active_status(self, api):
        """PRD §3.8: "the reverse transition, reinstatement from `SUSPENDED`
        back to `ACTIVE`, has no side effects."

        Design: Difficulty/non_linear_state_machine/agent_status_cycle_active_suspended_active_rejoins_pool
        """
        set_clock("2026-06-15T10:00:00Z")
        airport = create_airport(iata_code="PDX", meet_buffer_minutes=15)
        agent = create_agent(
            airport["id"], display_name="Cyclic B",
            shift_start_utc="2026-06-15T08:00:00Z",
            shift_end_utc="2026-06-15T20:00:00Z",
        )
        # SUSPEND then REINSTATE
        get_success_data(api_client.post_agent_event(
            agent["id"], {"event_type": "SUSPEND"}, OPS,
        ))
        reinstated = get_success_data(api_client.post_agent_event(
            agent["id"], {"event_type": "REINSTATE"}, OPS,
        ))
        assert reinstated["status"] == "ACTIVE"
        # GET confirms persistence
        fetched = get_success_data(api_client.get_agent(agent["id"], OPS))
        assert fetched["status"] == "ACTIVE"
