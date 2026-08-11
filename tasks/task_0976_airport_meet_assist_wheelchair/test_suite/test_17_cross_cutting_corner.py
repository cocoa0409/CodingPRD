"""Corner queue B — cross_cutting_complexity_layers and consistency_model sections."""
import pytest

from test_helpers import (
    get_success_data, validate_success, validate_error, validate_paginated,
    ApiErrorId,
    create_airport, create_terminal, create_segment, create_passenger,
    create_assist_request, create_leg, create_agent, create_wheelchair,
    submit_request, dispatch_leg, set_clock, setup_completed_request,
    make_billing_clerk_headers, api_client, TEST_USERS,
)


ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["ops_manager_headers"]
REQ = TEST_USERS["requester_headers"]
DISP = TEST_USERS["dispatcher_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]


class TestStaleInvoiceVersionOcc:
    def test_stale_invoice_version_occ_conflict(self, api):
        """PRD §2.7: "Posting `MARK_PAID`, `DISPUTE`, `RESOLVE_PAID`, or
        `WRITE_OFF` against an invoice requires the body to carry
        `expected_invoice_version` matching that invoice's current `version`.
        A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/stale_invoice_version_occ_conflict
        """
        out = setup_completed_request(
            iata_code="TUS",
            meet_buffer_minutes=15,
            requires_secure_escort=False,
            scheduled_utc="2026-06-16T10:00:00Z",
            actual_utc="2026-06-16T10:00:00Z",
            leg_kind="MEET_ARRIVAL",
            passenger_overrides={
                "full_name": "P TUS", "dob": "1990-01-01",
                "mobility_code": "WCHR", "airline_pnr": "TUS1",
            },
            request_overrides={"bill_to": "AIRLINE", "service_tier": "STANDARD",
                               "companion_count": 0},
            clock_at_submit="2026-06-16T09:00:00Z",
            dispatcher_user_id="disp_tus",
            confirmer_user_id="conf_tus",
        )
        final_inv = next(i for i in out["invoices"] if i["invoice_kind"] == "FINAL")
        stale_v = final_inv["version"]
        # DISPUTE — advances version
        get_success_data(api_client.post_invoice_event(
            final_inv["id"],
            {"event_type": "DISPUTE", "expected_invoice_version": stale_v},
            make_billing_clerk_headers("clerk_1"),
        ))
        # RESOLVE_PAID with stale version
        resp = api_client.post_invoice_event(
            final_inv["id"],
            {"event_type": "RESOLVE_PAID", "expected_invoice_version": stale_v},
            make_billing_clerk_headers("clerk_1"),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestPaginationDefaultsAgentsList:
    def test_pagination_defaults_applied_to_agents_list(self, api):
        """PRD §2.3: "The `limit` parameter defaults to **10**, must be at least
        **1**, and is capped at **100**. The `offset` parameter defaults to **0**."
        PRD §2.2: "The response `meta` block for list endpoints carries four
        pagination fields: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/cross_cutting_complexity_layers/pagination_defaults_applied_to_agents_list
        """
        airport = create_airport(iata_code="ELP", meet_buffer_minutes=15)
        # Create 12 agents
        for i in range(12):
            create_agent(
                airport["id"], display_name=f"Agent seed {i}",
                shift_start_utc="2026-06-16T08:00:00Z",
                shift_end_utc="2026-06-16T20:00:00Z",
            )
        resp = api_client.list_agents(airport["id"], DISP)
        data, meta = validate_paginated(resp)
        assert "total_count" in meta
        assert "has_more" in meta
        assert meta["total_count"] == 12
        assert meta["has_more"] is True
        assert len(data) == 10  # default limit


class TestImmediateVisibilityOfDispatch:
    def test_immediate_visibility_of_dispatch_to_get(self, api):
        """PRD §3.4: "Successful dispatch creates an `Assignment` in `DISPATCHED`
        status."

        Design: Corner/consistency_model/immediate_visibility_of_dispatch_to_get
        """
        set_clock("2026-06-15T10:00:00Z")
        airport = create_airport(iata_code="CHS", meet_buffer_minutes=15)
        terminal = create_terminal(airport["id"], code="M", requires_secure_escort=False)
        segment = create_segment(
            airport["id"], terminal["id"], flight_no="CHS1",
            direction="ARRIVAL", scheduled_utc="2026-06-16T10:00:00Z",
        )
        passenger = create_passenger(
            full_name="P CHS", dob="1990-01-01", mobility_code="WCHR",
            airline_pnr="CHS1",
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
            airport["id"], display_name="CHS Ag",
            shift_start_utc="2026-06-16T08:00:00Z",
            shift_end_utc="2026-06-16T20:00:00Z",
        )
        wheelchair = create_wheelchair(airport["id"], asset_tag="WC-CHS-1")
        assignment = dispatch_leg(leg["id"], request["id"], DISP)
        # Immediately GET — must be visible (no eventual-consistency lag)
        fetched = get_success_data(api_client.get_assignment(assignment["id"], DISP))
        assert fetched["status"] == "DISPATCHED"
        assert fetched["service_leg_id"] == leg["id"]
