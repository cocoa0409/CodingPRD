"""Compensating invariant tests: create-then-withdraw conserves
committed_crew_count, and submit-then-void conserves the invoiced totals
(PRD §2.10)."""
import pytest

from test_helpers import (
    api_client, validate_success, get_success_data,
    make_program_admin_headers, make_host_coordinator_headers,
    make_responding_coordinator_headers, make_responding_finance_headers,
    commit_crew, setup_event_with_accepted_request,
    setup_demobilized_with_certified_rows, create_draft_invoice,
)


class TestCrewCreateWithdrawConservesCommittedCount:
    def test_commit_raises_committed_count(self):
        """PRD §3.3: "That count tallies the request's crews whose mobility is
        `COMMITTED`, `ARRIVED`, or `DEMOBILIZING`" and "the request's
        `committed_crew_count` immediately reflects it."

        Design: Difficulty/compensating_invariant/crew_create_withdraw_conserves_committed_count
        """
        ctx = setup_event_with_accepted_request()
        resp = api_client.get_assistance_request(ctx["request"]["id"], make_program_admin_headers())
        assert validate_success(resp)["committed_crew_count"] == 0
        crew = commit_crew(ctx["request"]["id"], ctx["rsp"]["id"])
        resp = api_client.get_assistance_request(ctx["request"]["id"], make_program_admin_headers())
        assert validate_success(resp)["committed_crew_count"] == 1

    def test_withdraw_returns_count_to_zero_without_drift(self):
        """PRD §2.10: "Committing a crew and later withdrawing it leaves the
        request's `committed_crew_count` exactly where it started, because a
        crew in `WITHDRAWN` no longer counts."

        Design: Difficulty/compensating_invariant/crew_create_withdraw_conserves_committed_count
        """
        ctx = setup_event_with_accepted_request()
        crew = commit_crew(ctx["request"]["id"], ctx["rsp"]["id"])
        resp = api_client.withdraw_crew(crew["id"],
                                        make_responding_coordinator_headers(ctx["rsp"]["id"]))
        crew = validate_success(resp)
        assert crew["mobility_status"] == "WITHDRAWN"
        resp = api_client.get_assistance_request(ctx["request"]["id"], make_program_admin_headers())
        assert validate_success(resp)["committed_crew_count"] == 0


class TestInvoiceSubmitVoidConservesEventInvoicedTotal:
    def test_submit_raises_event_invoiced_total(self):
        """PRD §3.8: "sets `outstanding_cents` equal to `final_total_cents`,
        stamps `submitted_at`, and recomputes the event's
        `total_invoiced_cents` and the request's `invoiced_total_cents`, the
        latter mirroring the live invoice's final total."

        Design: Difficulty/compensating_invariant/invoice_submit_void_conserves_event_invoiced_total
        """
        ctx = setup_demobilized_with_certified_rows()
        resp = api_client.get_event(ctx["event"]["id"], make_program_admin_headers())
        assert validate_success(resp)["total_invoiced_cents"] == 0
        invoice = create_draft_invoice(ctx["request"]["id"], ctx["schedule"]["id"],
                                       ctx["rsp"]["id"])
        resp = api_client.submit_invoice(invoice["id"],
                                         make_responding_finance_headers(ctx["rsp"]["id"]))
        validate_success(resp)
        resp = api_client.get_event(ctx["event"]["id"], make_program_admin_headers())
        assert validate_success(resp)["total_invoiced_cents"] == 201866

    def test_void_restores_total_and_clears_swept_pin(self):
        """PRD §2.10: "submitting an invoice and later voiding it leaves the
        event's `total_invoiced_cents` and the request's `invoiced_total_cents`
        exactly where they stood before the submission, because a `VOID` invoice
        no longer contributes to either total." PRD §3.8: "Voiding a `SUBMITTED`
        invoice clears `billed_invoice_id` from every swept timesheet"

        Design: Difficulty/compensating_invariant/invoice_submit_void_conserves_event_invoiced_total
        """
        ctx = setup_demobilized_with_certified_rows()
        invoice = create_draft_invoice(ctx["request"]["id"], ctx["schedule"]["id"],
                                       ctx["rsp"]["id"])
        api_client.submit_invoice(invoice["id"], make_responding_finance_headers(ctx["rsp"]["id"]))
        resp = api_client.void_invoice(invoice["id"],
                                       make_responding_finance_headers(ctx["rsp"]["id"]))
        invoice = validate_success(resp)
        assert invoice["status"] == "VOID"
        resp = api_client.get_event(ctx["event"]["id"], make_program_admin_headers())
        assert validate_success(resp)["total_invoiced_cents"] == 0
        resp = api_client.get_timesheet(ctx["ts1"]["id"], make_program_admin_headers())
        assert validate_success(resp)["billed_invoice_id"] is None
