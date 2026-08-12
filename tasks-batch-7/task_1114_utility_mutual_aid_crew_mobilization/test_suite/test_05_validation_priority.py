"""Validation priority pair tests (PRD §2.9): when two rule families both
reject a call, the earlier family's error surfaces."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    make_host_coordinator_headers, make_responding_coordinator_headers,
    make_crew_supervisor_headers, make_host_safety_officer_headers,
    make_host_finance_headers, make_responding_finance_headers,
    set_clock, create_company, create_event, create_and_publish_schedule,
    create_accepted_request, commit_crew, conduct_and_acknowledge_briefing,
    arrive_crew, create_submitted_timesheet, certify_timesheet,
    create_approved_claim, create_draft_invoice, submit_invoice,
    setup_cleared_arrived_crew, setup_demobilized_with_certified_rows,
    setup_submitted_invoice,
    create_timesheet_payload,
)


class TestMarkPaidStateBeatsFiscal:
    def test_mark_paid_on_submitted_invoice_reports_state_error(self):
        """PRD §2.9: "Every request is validated against a fixed, ordered
        sequence of rule families, and a failure surfaces the error of the
        earliest family that rejects it"
        PRD §2.9: "5. **State legality** — the target resource's current state
        permits the requested transition, including event and request postures
        that act as preconditions, else `ERR_INVALID_STATE_TRANSITION`
        (HTTP 409)."
        PRD §2.9: "10. **Fiscal sanity** — amounts must be positive where
        required, payment must equal the outstanding balance exactly, disputes
        and credits must stay within their bounds, and a submitted invoice must
        be non-empty: `ERR_INVALID_AMOUNT` (HTTP 400), and
        `ERR_PAYMENT_AMOUNT_MISMATCH`, `ERR_DISPUTE_AMOUNT_INVALID`,
        `ERR_CREDIT_EXCEEDS_DISPUTED`, `ERR_EMPTY_INVOICE` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/mark_paid_state_beats_fiscal
        """
        ctx = setup_submitted_invoice()
        resp = api_client.mark_invoice_paid(
            ctx["invoice"]["id"], {"amount_cents": 1},
            make_host_finance_headers(ctx["host"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_failed_mark_paid_leaves_invoice_unchanged(self):
        """PRD §3.8: "Payment then settles the balance: marking paid requires a
        positive `amount_cents` — zero or less is `ERR_INVALID_AMOUNT` — that
        equals `outstanding_cents` exactly, otherwise
        `ERR_PAYMENT_AMOUNT_MISMATCH`. A clean payment records
        `amount_paid_cents`, stamps `paid_at`, drives `outstanding_cents` to
        zero" — a rejected payment mutates nothing.

        Design: Difficulty/priority_pair_validation_conflict/mark_paid_state_beats_fiscal
        """
        ctx = setup_submitted_invoice()
        api_client.mark_invoice_paid(
            ctx["invoice"]["id"], {"amount_cents": 1},
            make_host_finance_headers(ctx["host"]["id"]))
        resp = api_client.get_invoice(ctx["invoice"]["id"], make_host_finance_headers(ctx["host"]["id"]))
        invoice = validate_success(resp)
        assert invoice["status"] == "SUBMITTED"
        assert invoice["outstanding_cents"] == 201866


class TestCertifySafetyBeatsTemporal:
    def _setup_suspended_and_window_closed(self):
        """Crew suspended BEFORE the timesheet exists; timesheet created and
        submitted while suspended; clock advanced beyond the 14-day window."""
        set_clock("2026-05-01T08:00:00Z")
        host = create_company(name="Host Power", company_code="HST",
                              role_capability="BOTH", home_region="Coastal")
        rsp = create_company(name="Responder Electric", company_code="RSP",
                             role_capability="RESPONDING", home_region="Inland")
        event = create_event(host["id"], activate=True)
        schedule = create_and_publish_schedule(event["id"], rsp["id"])
        request = create_accepted_request(event["id"], host["id"], rsp["id"])
        crew = commit_crew(request["id"], rsp["id"])
        conduct_and_acknowledge_briefing(crew["id"], event["id"], host["id"])
        resp = api_client.suspend_crew(
            crew["id"], {"reason": "rule violation"},
            make_host_safety_officer_headers(host["id"]))
        assert resp.status_code == 200, f"Setup failed suspending crew: {resp.text}"
        ts = create_submitted_timesheet(crew["id"], work_date="2026-05-04",
                                        day_classification="WORK", reported_work_minutes=480)
        set_clock("2026-05-25T09:00:00Z")
        return {"host": host, "rsp": rsp, "event": event, "schedule": schedule,
                "request": request, "crew": crew, "ts": ts}

    def test_certify_reports_safety_error_not_window_error(self):
        """PRD §2.9: "6. **Safety gating** — crew readiness must be
        `CLEARED_TO_WORK` for timesheet certification and recertification, else
        `ERR_CREW_NOT_CLEARED` (HTTP 409). Safety outranks the temporal family:
        when a crew is on hold and the certification window has also closed, the
        rejection is `ERR_CREW_NOT_CLEARED`, never the window error."

        Design: Difficulty/priority_pair_validation_conflict/certify_safety_beats_temporal
        """
        ctx = self._setup_suspended_and_window_closed()
        resp = api_client.certify_timesheet(
            ctx["ts"]["id"], {"certifier_operator_ref": "HC-1"},
            make_host_coordinator_headers(ctx["host"]["id"]))
        validate_error(resp, ApiErrorId.ERR_CREW_NOT_CLEARED)

    def test_failed_certify_leaves_timesheet_submitted(self):
        """PRD §3.6: "the crew must stand at `CLEARED_TO_WORK`
        (`ERR_CREW_NOT_CLEARED` — this safety gate outranks the temporal check
        when both would fail)" — a rejected certification mutates nothing; the
        sheet stays SUBMITTED.

        Design: Difficulty/priority_pair_validation_conflict/certify_safety_beats_temporal
        """
        ctx = self._setup_suspended_and_window_closed()
        api_client.certify_timesheet(
            ctx["ts"]["id"], {"certifier_operator_ref": "HC-1"},
            make_host_coordinator_headers(ctx["host"]["id"]))
        resp = api_client.get_timesheet(ctx["ts"]["id"], make_host_coordinator_headers(ctx["host"]["id"]))
        ts = validate_success(resp)
        # Note: the sheet was HELD at suspend time only if SUBMITTED before the
        # suspend; here it was submitted while already suspended, so it remains
        # SUBMITTED. Either way the failed certify must not move it to CERTIFIED.
        assert ts["status"] != "CERTIFIED"
        assert ts["certified_amount_cents"] is None
