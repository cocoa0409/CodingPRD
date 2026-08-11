"""Corner queue B — errors section instances."""
import pytest

from test_helpers import (
    get_success_data, validate_success, validate_error, ApiErrorId,
    set_clock, setup_completed_request,
    make_billing_clerk_headers, make_requester_headers,
    api_client, TEST_USERS,
)


ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["ops_manager_headers"]
REQ = TEST_USERS["requester_headers"]
DISP = TEST_USERS["dispatcher_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]


class TestWriteOffSegregationOfDuties:
    def test_error_segregation_write_off_clerk_equals_provisional_creator(self, api):
        """PRD §3.6: "When `bill_to` is `AIRLINE`, the clerk performing the
        write-off must differ from the clerk who created the original provisional
        invoice — a self-write-off is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/errors/error_segregation_write_off_clerk_equals_provisional_creator
        """
        # The submitting user_id is recorded as the provisional-invoice creator.
        # We drive SUBMIT as Requester "dual_user", then attempt WRITE_OFF as
        # BillingClerk with the SAME user_id "dual_user".
        from test_helpers.fixtures import (
            create_airport, create_terminal, create_segment, create_passenger,
            create_assist_request, create_leg, submit_request, dispatch_leg,
            create_agent, create_wheelchair, walk_assignment_to_handed_off,
            complete_assignment,
        )
        set_clock("2026-06-15T10:00:00Z")
        airport = create_airport(iata_code="OKC", meet_buffer_minutes=15)
        terminal = create_terminal(airport["id"], code="M", requires_secure_escort=False)
        segment = create_segment(
            airport["id"], terminal["id"], flight_no="OKC1",
            direction="ARRIVAL", scheduled_utc="2026-06-16T10:00:00Z",
        )
        passenger = create_passenger(
            full_name="P OKC", dob="1990-01-01", mobility_code="WCHR",
            airline_pnr="OKC1",
        )
        request = create_assist_request(
            passenger["id"], bill_to="AIRLINE", service_tier="STANDARD",
            companion_count=0,
        )
        leg = create_leg(request["id"], segment["id"],
                         leg_kind="MEET_ARRIVAL", pickup_zone="Z")
        set_clock("2026-06-16T09:00:00Z")
        # SUBMIT as user "dual_user" (Requester role)
        submit_request(request["id"], headers=make_requester_headers("dual_user"))
        agent = create_agent(
            airport["id"], display_name="OKC Ag",
            shift_start_utc="2026-06-16T08:00:00Z",
            shift_end_utc="2026-06-16T20:00:00Z",
        )
        wheelchair = create_wheelchair(airport["id"], asset_tag="WC-OKC-1")
        assignment = dispatch_leg(leg["id"], request["id"], DISP)
        walk_assignment_to_handed_off(assignment["id"], agent["id"])
        get_success_data(api_client.post_segment_event(
            segment["id"],
            {"event_type": "LANDED", "actual_utc": "2026-06-16T10:00:00Z"},
            OPS,
        ))
        complete_assignment(assignment["id"], confirmer_user_id="conf_okc")
        invoices = get_success_data(api_client.list_request_invoices(request["id"], CLERK))
        final_inv = next(i for i in invoices if i["invoice_kind"] == "FINAL")
        # DISPUTE as clerk_a (a different clerk)
        disputed = get_success_data(api_client.post_invoice_event(
            final_inv["id"],
            {"event_type": "DISPUTE",
             "expected_invoice_version": final_inv["version"]},
            make_billing_clerk_headers("clerk_a"),
        ))
        # WRITE_OFF as dual_user — same user who triggered SUBMIT (the provisional creator)
        resp = api_client.post_invoice_event(
            final_inv["id"],
            {"event_type": "WRITE_OFF",
             "expected_invoice_version": disputed["version"]},
            make_billing_clerk_headers("dual_user"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
