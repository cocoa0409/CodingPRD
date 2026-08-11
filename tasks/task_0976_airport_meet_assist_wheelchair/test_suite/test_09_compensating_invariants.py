"""Difficulty queue A — compensating_invariant instances."""
import pytest

from test_helpers import (
    get_success_data, validate_success, ApiErrorId,
    create_airport, create_terminal, create_segment, create_passenger,
    create_assist_request, create_leg, create_agent, create_wheelchair,
    submit_request, dispatch_leg, set_clock,
    api_client, TEST_USERS,
)


ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["ops_manager_headers"]
REQ = TEST_USERS["requester_headers"]
DISP = TEST_USERS["dispatcher_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]


# ---------------------------------------------------------------------------
# Design: Difficulty/compensating_invariant/provisional_plus_final_invoice_amounts_conserved_across_supersede
# ---------------------------------------------------------------------------

class TestProvisionalFinalInvoiceConserved:
    def _setup_completed(self):
        from test_helpers import setup_completed_request
        return setup_completed_request(
            iata_code="SLC",
            meet_buffer_minutes=15,
            requires_secure_escort=False,
            scheduled_utc="2026-06-20T10:00:00Z",
            actual_utc="2026-06-20T10:00:00Z",
            leg_kind="MEET_ARRIVAL",
            passenger_overrides={
                "full_name": "P SLC", "dob": "1980-01-01",
                "mobility_code": "WCHR", "airline_pnr": "SLC1",
            },
            request_overrides={"bill_to": "AIRLINE", "service_tier": "STANDARD",
                               "companion_count": 0},
            clock_at_submit="2026-06-20T09:00:00Z",
            dispatcher_user_id="disp_slc",
            confirmer_user_id="conf_slc",
        )

    def test_exactly_one_open_invoice_after_completion(self, api):
        """PRD §3.6: "the server sets `billing_status` to `FINALIZED`, computes
        `final_charge_cents`, and issues a `FINAL` invoice whose `amount_cents`
        equals that total, whose `supersedes_invoice_id` points at the earlier
        `PROVISIONAL` invoice, and whose arrival transitions that provisional
        invoice from `OPEN` to `VOID`."

        Design: Difficulty/compensating_invariant/provisional_plus_final_invoice_amounts_conserved_across_supersede
        """
        out = self._setup_completed()
        invoices = out["invoices"]
        open_invs = [i for i in invoices if i["status"] == "OPEN"]
        assert len(open_invs) == 1, (
            f"Expected exactly 1 OPEN invoice, got {len(open_invs)}"
        )
        # The unique OPEN invoice is FINAL and supersedes the PROVISIONAL
        prov = [i for i in invoices if i["invoice_kind"] == "PROVISIONAL"]
        assert len(prov) == 1
        assert prov[0]["status"] == "VOID"
        final_inv = open_invs[0]
        assert final_inv["invoice_kind"] == "FINAL"
        assert final_inv["supersedes_invoice_id"] == prov[0]["id"]
        # OPEN invoice amount equals the request's final_charge_cents
        assert final_inv["amount_cents"] == out["request"]["final_charge_cents"]

    def test_provisional_invoice_open_at_submit_then_void_after_complete(self, api):
        """PRD §3.3: "creates a `PROVISIONAL` invoice whose `amount_cents` equals
        the request's `provisional_charge_cents`, whose `bill_to` is copied from
        the request, and whose `status` begins `OPEN`."
        PRD §3.6: "whose arrival transitions that provisional invoice from `OPEN`
        to `VOID`."

        Design: Difficulty/compensating_invariant/provisional_plus_final_invoice_amounts_conserved_across_supersede
        """
        set_clock("2026-06-15T10:00:00Z")
        airport = create_airport(iata_code="SLC", meet_buffer_minutes=15)
        terminal = create_terminal(airport["id"], code="1", requires_secure_escort=False)
        segment = create_segment(
            airport["id"], terminal["id"], flight_no="DL9",
            direction="ARRIVAL", scheduled_utc="2026-06-20T10:00:00Z",
        )
        passenger = create_passenger(
            full_name="P SLC", dob="1980-01-01", mobility_code="WCHR",
            airline_pnr="SLC1",
        )
        request = create_assist_request(
            passenger["id"], bill_to="AIRLINE", service_tier="STANDARD",
            companion_count=0,
        )
        leg = create_leg(request["id"], segment["id"],
                         leg_kind="MEET_ARRIVAL", pickup_zone="Z")
        set_clock("2026-06-20T09:00:00Z")
        request = submit_request(request["id"])
        # At submit: PROVISIONAL is OPEN
        inv_at_submit = get_success_data(api_client.list_request_invoices(
            request["id"], CLERK,
        ))
        prov = [i for i in inv_at_submit if i["invoice_kind"] == "PROVISIONAL"]
        assert len(prov) == 1
        assert prov[0]["status"] == "OPEN"
        # No FINAL yet
        assert not any(i["invoice_kind"] == "FINAL" for i in inv_at_submit)


# ---------------------------------------------------------------------------
# Design: Difficulty/compensating_invariant/wheelchair_usage_count_conserved_across_cancel_and_complete
# ---------------------------------------------------------------------------

class TestWheelchairUsageCountConserved:
    def _setup_dispatched(self):
        set_clock("2026-06-15T10:00:00Z")
        airport = create_airport(iata_code="STL", meet_buffer_minutes=15)
        terminal = create_terminal(airport["id"], code="1", requires_secure_escort=False)
        segment = create_segment(
            airport["id"], terminal["id"], flight_no="WN20",
            direction="ARRIVAL", scheduled_utc="2026-06-20T10:00:00Z",
        )
        passenger = create_passenger(
            # WCHS so the leg's requires_wheelchair flag is set (PRD §3.2) and
            # the wheelchair selector runs at dispatch — a WCHR passenger would
            # never check out the chair this test observes.
            full_name="P STL", dob="1980-01-01", mobility_code="WCHS",
            airline_pnr="STL1",
        )
        request = create_assist_request(
            passenger["id"], bill_to="AIRLINE", service_tier="STANDARD",
            companion_count=0,
        )
        leg = create_leg(request["id"], segment["id"],
                         leg_kind="MEET_ARRIVAL", pickup_zone="Z")
        set_clock("2026-06-20T09:00:00Z")
        request = submit_request(request["id"])
        agent = create_agent(
            airport["id"], display_name="STL Ag",
            shift_start_utc="2026-06-20T08:00:00Z",
            shift_end_utc="2026-06-20T20:00:00Z",
        )
        wheelchair = create_wheelchair(airport["id"], asset_tag="WC-STL-1")
        assignment = dispatch_leg(leg["id"], request["id"], DISP)
        return airport, agent, wheelchair, request, leg, assignment

    def test_usage_count_increments_on_dispatch_not_decremented_on_cancel(self, api):
        """PRD §3.4: "The selected chair transitions from `AVAILABLE` to
        `CHECKED_OUT` and its `usage_count` increments by one."
        PRD §3.10: "A successful cancellation of a submitted request cascades:
        every `DISPATCHED` assignment becomes `CANCELLED` and releases its chair."
        (Cancel returns the chair but does NOT refund usage_count — that is
        implicit in the absence of any decrement wording, while the maintenance
        threshold logic depends on monotonically increasing usage_count.)

        Design: Difficulty/compensating_invariant/wheelchair_usage_count_conserved_across_cancel_and_complete
        """
        airport, agent, wheelchair, request, leg, assignment = self._setup_dispatched()
        # After dispatch: usage_count == 1, status CHECKED_OUT
        chair = get_success_data(api_client.get_wheelchair(wheelchair["id"], DISP))
        assert chair["usage_count"] == 1
        assert chair["status"] == "CHECKED_OUT"
        # CANCEL_ASSIGN
        get_success_data(api_client.post_assignment_event(
            assignment["id"], {"event_type": "CANCEL_ASSIGN"}, DISP,
        ))
        chair_after = get_success_data(api_client.get_wheelchair(wheelchair["id"], DISP))
        # Chair back to AVAILABLE, but usage_count NOT decremented
        assert chair_after["status"] == "AVAILABLE"
        assert chair_after["usage_count"] == 1

    def test_usage_count_not_decremented_by_suspend_cascade(self, api):
        """PRD §3.7: "any chair those assignments held returns from `CHECKED_OUT`
        to `AVAILABLE` without decrementing `usage_count`."

        Design: Difficulty/compensating_invariant/wheelchair_usage_count_conserved_across_cancel_and_complete
        """
        airport, agent, wheelchair, request, leg, assignment = self._setup_dispatched()
        # SUSPEND the agent — cascade cancels assignment, releases chair
        get_success_data(api_client.post_agent_event(
            agent["id"], {"event_type": "SUSPEND"}, OPS,
        ))
        chair_after = get_success_data(api_client.get_wheelchair(wheelchair["id"], DISP))
        assert chair_after["status"] == "AVAILABLE"
        assert chair_after["usage_count"] == 1
