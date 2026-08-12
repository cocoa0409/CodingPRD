"""Cross-entity state dependency tests: TimeSheet certification gated on Crew
readiness, and Invoice submission gated on the pinned schedule not being
SUPERSEDED (PRD §3.6, §3.8)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    make_program_admin_headers, make_host_coordinator_headers,
    make_responding_coordinator_headers, make_crew_supervisor_headers,
    make_responding_finance_headers,
    set_clock, create_company, create_event, create_and_publish_schedule,
    create_accepted_request, commit_crew, conduct_and_acknowledge_briefing,
    arrive_crew, create_submitted_timesheet, certify_timesheet,
    create_approved_claim, create_draft_invoice, submit_invoice,
    create_billing_rate_schedule_payload, create_timesheet_payload,
    setup_demobilized_with_certified_rows,
)


class TestCertifyRequiresCrewClearedToWork:
    def _setup_uncleared_crew_with_submitted_timesheet(self):
        """Crew committed (readiness AWAITING_BRIEFING — no briefing yet) with
        one SUBMITTED timesheet. Carries the canonical bucket truck (35000c/day)
        so a 600-minute WORK day in the premium window certifies at 180200."""
        set_clock("2026-05-05T09:00:00Z")
        host = create_company(name="Host Power", company_code="HST",
                              role_capability="BOTH", home_region="Coastal")
        rsp = create_company(name="Responder Electric", company_code="RSP",
                             role_capability="RESPONDING", home_region="Inland")
        event = create_event(host["id"], activate=True)
        schedule = create_and_publish_schedule(event["id"], rsp["id"])
        request = create_accepted_request(event["id"], host["id"], rsp["id"])
        crew = commit_crew(request["id"], rsp["id"], equipment_units=[
            {"unit_type": "bucket_truck", "unit_ref": "BT-1", "daily_rate_cents": 35000},
        ])
        ts = create_submitted_timesheet(crew["id"], work_date="2026-05-04",
                                        day_classification="WORK", reported_work_minutes=600)
        return {"host": host, "rsp": rsp, "event": event, "schedule": schedule,
                "request": request, "crew": crew, "ts": ts}

    def test_certify_rejected_while_awaiting_briefing(self):
        """PRD §3.6: "the crew must stand at `CLEARED_TO_WORK`
        (`ERR_CREW_NOT_CLEARED` — this safety gate outranks the temporal check
        when both would fail)"

        Design: Difficulty/cross_entity_state_dependency/certify_requires_crew_cleared_to_work
        """
        ctx = self._setup_uncleared_crew_with_submitted_timesheet()
        resp = api_client.certify_timesheet(
            ctx["ts"]["id"], {"certifier_operator_ref": "HC-1"},
            make_host_coordinator_headers(ctx["host"]["id"]))
        validate_error(resp, ApiErrorId.ERR_CREW_NOT_CLEARED)

    def test_certify_succeeds_after_briefing_acknowledged(self):
        """PRD §3.6: "On success the sheet pins that schedule as its
        `certified_schedule_id`, records the certifier, and prices the day into
        `certified_amount_cents`." PRD §3.5: "A clean acknowledgment records
        `acknowledged_at`, moves the briefing from `CONDUCTED` to `ACKNOWLEDGED`,
        and advances the crew from `BRIEFED` to `CLEARED_TO_WORK`."

        Design: Difficulty/cross_entity_state_dependency/certify_requires_crew_cleared_to_work
        """
        ctx = self._setup_uncleared_crew_with_submitted_timesheet()
        conduct_and_acknowledge_briefing(ctx["crew"]["id"], ctx["event"]["id"],
                                         ctx["host"]["id"])
        resp = api_client.certify_timesheet(
            ctx["ts"]["id"], {"certifier_operator_ref": "HC-1"},
            make_host_coordinator_headers(ctx["host"]["id"]))
        ts = validate_success(resp)
        assert ts["status"] == "CERTIFIED"
        assert ts["certified_amount_cents"] == 180200
        assert ts["certified_schedule_id"] == ctx["schedule"]["id"]


class TestInvoiceSubmitRejectsSupersededSchedule:
    def _setup_superseded_pin(self):
        """T1 CERTIFIED pinning S1; S1 then SUPERSEDED by published S2;
        P1 APPROVED; event DEMOBILIZING; invoice drafted against S1."""
        set_clock("2026-05-01T08:00:00Z")
        host = create_company(name="Host Power", company_code="HST",
                              role_capability="BOTH", home_region="Coastal")
        rsp = create_company(name="Responder Electric", company_code="RSP",
                             role_capability="RESPONDING", home_region="Inland")
        event = create_event(host["id"], activate=True)
        s1 = create_and_publish_schedule(event["id"], rsp["id"])
        request = create_accepted_request(event["id"], host["id"], rsp["id"])
        crew = commit_crew(request["id"], rsp["id"], equipment_units=[
            {"unit_type": "bucket_truck", "unit_ref": "BT-1", "daily_rate_cents": 35000},
        ])
        conduct_and_acknowledge_briefing(crew["id"], event["id"], host["id"])
        arrive_crew(crew["id"], host["id"])
        set_clock("2026-05-05T09:00:00Z")
        ts1 = create_submitted_timesheet(crew["id"], work_date="2026-05-04",
                                         day_classification="WORK", reported_work_minutes=600)
        ts1 = certify_timesheet(ts1["id"], host["id"])
        create_approved_claim(crew["id"], rsp["id"], host["id"], claim_date="2026-05-03")
        # Supersede S1 with an identical S2 (OCC version from a fresh read).
        resp = api_client.get_billing_rate_schedule(s1["id"], make_program_admin_headers())
        s1_version = validate_success(resp)["version"]
        resp = api_client.create_billing_rate_schedule(
            create_billing_rate_schedule_payload(
                event_id=event["id"], supersedes_schedule_id=s1["id"]),
            make_responding_coordinator_headers(rsp["id"]))
        assert resp.status_code == 201, f"Setup failed creating S2: {resp.text}"
        s2 = get_success_data(resp)
        resp = api_client.publish_billing_rate_schedule(
            s2["id"], {"expected_superseded_schedule_version": s1_version},
            make_responding_coordinator_headers(rsp["id"]))
        assert resp.status_code == 200, f"Setup failed publishing S2: {resp.text}"
        s2 = get_success_data(resp)
        resp = api_client.begin_demobilization(event["id"], make_host_coordinator_headers(host["id"]))
        assert resp.status_code == 200, f"Setup failed demobilizing: {resp.text}"
        inv1 = create_draft_invoice(request["id"], s1["id"], rsp["id"])
        return {"host": host, "rsp": rsp, "event": event, "s1": s1, "s2": s2,
                "request": request, "crew": crew, "ts1": ts1, "inv1": inv1}

    def test_submit_rejected_while_pinned_schedule_superseded(self):
        """PRD §3.8: "no covered `CERTIFIED` timesheet may still be pinned to a
        `SUPERSEDED` schedule — such sheets must be recertified first, or the
        submission fails with `ERR_SUPERSEDED_SCHEDULE`"

        Design: Difficulty/cross_entity_state_dependency/invoice_submit_rejects_superseded_schedule
        """
        ctx = self._setup_superseded_pin()
        resp = api_client.submit_invoice(
            ctx["inv1"]["id"], make_responding_finance_headers(ctx["rsp"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SUPERSEDED_SCHEDULE)

    def test_recertify_repins_and_unblocks_submission(self):
        """PRD §3.6: "recertification, available only while the pinned schedule
        stands at `SUPERSEDED` (any other pin is `ERR_INVALID_STATE_TRANSITION`),
        re-resolves the selector against the current effective schedule,
        recomputes the amount under the same segregation and fourteen-day-window
        rules, and increments the timesheet's `version` by one."

        Design: Difficulty/cross_entity_state_dependency/invoice_submit_rejects_superseded_schedule
        """
        ctx = self._setup_superseded_pin()
        resp = api_client.recertify_timesheet(
            ctx["ts1"]["id"], {"certifier_operator_ref": "HC-2"},
            make_host_coordinator_headers(ctx["host"]["id"]))
        ts = validate_success(resp)
        assert ts["certified_schedule_id"] == ctx["s2"]["id"]
        # Void the stale-pinned draft and re-invoice against S2.
        resp = api_client.void_invoice(ctx["inv1"]["id"],
                                       make_responding_finance_headers(ctx["rsp"]["id"]))
        assert resp.status_code == 200, f"Setup failed voiding first invoice: {resp.text}"
        inv2 = create_draft_invoice(ctx["request"]["id"], ctx["s2"]["id"], ctx["rsp"]["id"])
        resp = api_client.submit_invoice(inv2["id"], make_responding_finance_headers(ctx["rsp"]["id"]))
        invoice = validate_success(resp)
        assert invoice["status"] == "SUBMITTED"
        assert invoice["final_total_cents"] == 201866
