"""Dual-variant calculation tests: invoice provisional vs final, per-diem
STANDARD vs ACTUAL, and after-action as-billed vs as-certified (PRD §2.6, §3.6,
§3.8, §3.9)."""
import pytest

from test_helpers import (
    api_client, validate_success, get_success_data,
    make_program_admin_headers, make_host_coordinator_headers,
    make_responding_coordinator_headers, make_crew_supervisor_headers,
    make_host_safety_officer_headers, make_host_finance_headers,
    make_responding_finance_headers,
    set_clock, create_company, create_event, create_and_publish_schedule,
    create_request, create_accepted_request, commit_crew,
    conduct_and_acknowledge_briefing, arrive_crew,
    create_submitted_timesheet, certify_timesheet, create_approved_claim,
    create_draft_invoice, submit_invoice, setup_demobilized_with_certified_rows,
    create_after_action_report,
    create_utility_company_payload, create_event_payload,
    create_billing_rate_schedule_payload, create_assistance_request_payload,
    create_crew_payload, create_safety_briefing_payload, create_timesheet_payload,
    create_per_diem_claim_payload, create_invoice_payload,
)


def _full_invoice_scenario_with_unsettled_rows():
    """Event DEMOBILIZING; T1 CERTIFIED 180200; T2 (480) left SUBMITTED;
    P1 APPROVED 6713; P2 left SUBMITTED; invoice drafted BEFORE the rejections.

    Mirrors the design chain: invoice created while T2/P2 are still SUBMITTED,
    then T2 rejected and P2 rejected, then the event demobilized.
    """
    set_clock("2026-05-01T08:00:00Z")
    host = create_company(name="Host Power", company_code="HST",
                          role_capability="BOTH", home_region="Coastal")
    rsp = create_company(name="Responder Electric", company_code="RSP",
                         role_capability="RESPONDING", home_region="Inland")
    event = create_event(host["id"], activate=True)
    schedule = create_and_publish_schedule(event["id"], rsp["id"], mobilization_fee_tiers=[
        {"min_subtotal_cents": 0, "fee_bps": 800},
        {"min_subtotal_cents": 10000000, "fee_bps": 500},
    ])
    request = create_accepted_request(event["id"], host["id"], rsp["id"])
    crew = commit_crew(request["id"], rsp["id"], equipment_units=[
        {"unit_type": "bucket_truck", "unit_ref": "BT-1", "daily_rate_cents": 35000},
    ])
    conduct_and_acknowledge_briefing(crew["id"], event["id"], host["id"])
    crew = arrive_crew(crew["id"], host["id"])
    set_clock("2026-05-05T09:00:00Z")
    ts1 = create_submitted_timesheet(crew["id"], work_date="2026-05-04",
                                     day_classification="WORK", reported_work_minutes=600)
    ts1 = certify_timesheet(ts1["id"], host["id"])
    ts2 = create_submitted_timesheet(crew["id"], work_date="2026-05-05",
                                     day_classification="WORK", reported_work_minutes=480)
    pd1 = create_approved_claim(crew["id"], rsp["id"], host["id"], claim_date="2026-05-03")
    # P2 left SUBMITTED
    resp = api_client.create_per_diem_claim(
        create_per_diem_claim_payload(crew_id=crew["id"], claim_date="2026-05-04"),
        make_responding_coordinator_headers(rsp["id"]))
    assert resp.status_code == 201, f"Setup failed creating P2: {resp.text}"
    pd2 = get_success_data(resp)
    # Invoice drafted while T2/P2 still SUBMITTED (provisional estimate includes them)
    invoice = create_draft_invoice(request["id"], schedule["id"], rsp["id"])
    # Now reject T2 and P2, then demobilize
    resp = api_client.reject_timesheet(ts2["id"], {}, make_host_coordinator_headers(host["id"]))
    assert resp.status_code == 200, f"Setup failed rejecting T2: {resp.text}"
    resp = api_client.reject_per_diem_claim(pd2["id"], make_host_coordinator_headers(host["id"]))
    assert resp.status_code == 200, f"Setup failed rejecting P2: {resp.text}"
    resp = api_client.begin_demobilization(event["id"], make_host_coordinator_headers(host["id"]))
    assert resp.status_code == 200, f"Setup failed beginning demobilization: {resp.text}"
    return {
        "host": host, "rsp": rsp, "event": event, "schedule": schedule,
        "request": request, "crew": crew, "ts1": ts1, "ts2": ts2,
        "pd1": pd1, "pd2": pd2, "invoice": invoice,
    }


class TestInvoiceProvisionalVsFinalTotals:
    def test_provisional_total_includes_uncertified_rows(self):
        """PRD §3.8: "Drafting immediately computes the provisional figures:
        `provisional_subtotal_cents` sums the certified amounts of the period's
        `CERTIFIED` timesheets, a provisional pricing of the period's
        still-`SUBMITTED` timesheets obtained by evaluating the daily-billing
        rules of §3.6 on their reported minutes, the period's `APPROVED`
        per-diem claims, and the period's still-`SUBMITTED` claims;
        `provisional_fee_cents` applies the schedule's mobilization-fee tiers
        to that subtotal; and `provisional_total_cents` is their sum."

        Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_totals
        """
        ctx = _full_invoice_scenario_with_unsettled_rows()
        invoice = ctx["invoice"]
        # Provisional: certified 180200 + estimated T2 (480 WORK, premium window,
        # equipment 35000 -> 140600) + approved 6713 + submitted P2 6713 = 334226;
        # fee 800bps -> 26738; total 360964.
        assert invoice["provisional_total_cents"] == 360964, (
            f"provisional_total_cents must estimate unsettled rows, "
            f"got {invoice['provisional_total_cents']}"
        )

    def test_final_total_after_rejections_diverges_from_provisional(self):
        """PRD §3.8: "Because uncertified rows are estimated, a provisional
        total legitimately diverges from the final figure computed later on
        identical raw rows."
        PRD §3.8: "The final totals count only settled rows:
        `labor_subtotal_cents` sums `certified_amount_cents` over the request's
        crews' `CERTIFIED` timesheets whose `work_date` falls inside the
        billing period and whose `billed_invoice_id` is still empty, and
        `per_diem_subtotal_cents` sums `amount_cents` over `APPROVED` claims
        in the period not yet swept by a non-`VOID` invoice — both inputs are
        sums of already-rounded integers, so no further rounding occurs."

        Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_totals
        """
        ctx = _full_invoice_scenario_with_unsettled_rows()
        resp = api_client.submit_invoice(
            ctx["invoice"]["id"], make_responding_finance_headers(ctx["rsp"]["id"]))
        invoice = validate_success(resp)
        assert invoice["status"] == "SUBMITTED"
        assert invoice["labor_subtotal_cents"] == 180200
        assert invoice["per_diem_subtotal_cents"] == 6713
        assert invoice["mobilization_fee_cents"] == 14953
        assert invoice["final_total_cents"] == 201866
        assert invoice["outstanding_cents"] == 201866
        assert invoice["final_total_cents"] != invoice["provisional_total_cents"], (
            "final and provisional totals must diverge once unsettled rows are rejected"
        )


class TestPerDiemStandardVsActualMethod:
    def _setup_two_utility_claims(self):
        set_clock("2026-05-01T08:00:00Z")
        host = create_company(name="Host Power", company_code="HST",
                              role_capability="BOTH", home_region="Coastal")
        rspa = create_company(name="Responder A", company_code="RSPA",
                              role_capability="RESPONDING", home_region="Inland")
        rspb = create_company(name="Responder B", company_code="RSPB",
                              role_capability="RESPONDING", home_region="North")
        event = create_event(host["id"], activate=True)
        scha = create_and_publish_schedule(event["id"], rspa["id"], per_diem_method="STANDARD")
        schb = create_and_publish_schedule(event["id"], rspb["id"], per_diem_method="ACTUAL")
        reqa = create_accepted_request(
            event["id"], host["id"], rspa["id"],
            requested_crews=[{"crew_type": "LINE", "count": 1}])
        crewa = commit_crew(reqa["id"], rspa["id"])
        reqb = create_accepted_request(
            event["id"], host["id"], rspb["id"],
            requested_crews=[{"crew_type": "LINE", "count": 1}])
        crewb = commit_crew(reqb["id"], rspb["id"])
        return host, rspa, rspb, event, crewa, crewb

    def test_standard_method_claim_amount_and_marker(self):
        """PRD §3.6: "Under `STANDARD`, the raw entitlement is `member_count`
        times the schedule's `per_diem_rate_cents`, scaled by the day factor —
        a `FULL` day counts whole, a `TRAVEL` day counts three-quarters — and
        scaled again by the meal factor, which removes one third of the day for
        each host-provided meal, so three provided meals reduce the formula-based
        entitlement to zero; any `receipts_total_cents` supplied is ignored."
        PRD §3.6: "At creation the system resolves the effective schedule
        covering the `claim_date`, copies its `per_diem_method` onto the claim
        as `method_applied`, computes `lodging_covered` — true when the crew
        holds a non-cancelled lodging assignment whose stay interval contains
        the claim date — and prices the claim into `amount_cents`."

        Design: Difficulty/dual_variant_calc/per_diem_standard_vs_actual_method
        """
        host, rspa, _, _, crewa, _ = self._setup_two_utility_claims()
        resp = api_client.create_per_diem_claim(
            create_per_diem_claim_payload(crew_id=crewa["id"], claim_date="2026-05-03"),
            make_responding_coordinator_headers(rspa["id"]))
        claim = validate_success(resp, expected_status=201)
        assert claim["method_applied"] == "STANDARD"
        # round_half_up(1 * 8950 * 0.75 * 1.0) = round_half_up(6712.5) = 6713
        assert claim["amount_cents"] == 6713

    def test_actual_method_claim_uses_receipts(self):
        """PRD §3.6: "Under `ACTUAL`, the raw entitlement is the receipted
        amount capped at one and a half times the members' standard day rate —
        the cap being `member_count` times `per_diem_rate_cents` times one and a
        half, rounded half-up before the comparison — and filing an
        `ACTUAL`-method claim without `receipts_total_cents` is
        `ERR_INVALID_REQUEST`."

        Design: Difficulty/dual_variant_calc/per_diem_standard_vs_actual_method
        """
        host, _, rspb, _, _, crewb = self._setup_two_utility_claims()
        resp = api_client.create_per_diem_claim(
            create_per_diem_claim_payload(
                crew_id=crewb["id"], claim_date="2026-05-03",
                receipts_total_cents=5000),
            make_responding_coordinator_headers(rspb["id"]))
        claim = validate_success(resp, expected_status=201)
        assert claim["method_applied"] == "ACTUAL"
        # min(5000, round_half_up(1 * 8950 * 1.5)=13425) = 5000
        assert claim["amount_cents"] == 5000


class TestAarAsBilledVsAsCertifiedVariance:
    def _setup_approved_invoice_then_released(self):
        ctx = setup_demobilized_with_certified_rows()
        invoice = create_draft_invoice(ctx["request"]["id"], ctx["schedule"]["id"],
                                       ctx["rsp"]["id"])
        invoice = submit_invoice(invoice["id"], ctx["rsp"]["id"])
        resp = api_client.approve_invoice(
            invoice["id"], {"approver_operator_ref": "FIN-9"},
            make_host_finance_headers(ctx["host"]["id"]))
        assert resp.status_code == 200, f"Setup failed approving invoice: {resp.text}"
        invoice = get_success_data(resp)
        resp = api_client.release_crew(ctx["crew"]["id"],
                                       make_host_coordinator_headers(ctx["host"]["id"]))
        assert resp.status_code == 200, f"Setup failed releasing crew: {resp.text}"
        resp = api_client.complete_return(ctx["crew"]["id"],
                                          make_responding_coordinator_headers(ctx["rsp"]["id"]))
        assert resp.status_code == 200, f"Setup failed completing return: {resp.text}"
        ctx["invoice"] = invoice
        return ctx

    def test_submit_computes_both_cost_views(self):
        """PRD §3.9: "`as_certified_total_cents` is the audit view, summing
        certified timesheet amounts and approved per-diem amounts across the
        event's requests with no mobilization fee and no unresolved billing;
        `as_billed_total_cents` is the contractual view, summing
        `final_total_cents` over invoices in `APPROVED` or `PAID` status,
        mobilization fee included and disputed-but-unresolved invoices
        excluded."

        Design: Difficulty/dual_variant_calc/aar_as_billed_vs_as_certified_variance
        """
        ctx = self._setup_approved_invoice_then_released()
        aar = create_after_action_report(ctx["event"]["id"], ctx["host"]["id"])
        resp = api_client.submit_after_action_report(
            aar["id"], make_host_coordinator_headers(ctx["host"]["id"]))
        report = validate_success(resp)
        assert report["status"] == "SUBMITTED"
        assert report["as_certified_total_cents"] == 186913   # 180200 + 6713
        assert report["as_billed_total_cents"] == 201866      # fee included

    def test_variance_equals_mobilization_fee(self):
        """PRD §3.9: "The two views legitimately differ on identical underlying
        data, and `variance_cents` records their difference, as-billed minus
        as-certified." PRD §3.9: "`total_crew_days` counts the event's
        `CERTIFIED` timesheets classified `WORK`."

        Design: Difficulty/dual_variant_calc/aar_as_billed_vs_as_certified_variance
        """
        ctx = self._setup_approved_invoice_then_released()
        aar = create_after_action_report(ctx["event"]["id"], ctx["host"]["id"])
        resp = api_client.submit_after_action_report(
            aar["id"], make_host_coordinator_headers(ctx["host"]["id"]))
        report = validate_success(resp)
        assert report["total_crew_days"] == 1
        assert report["variance_cents"] == 14953  # exactly the mobilization fee
        assert report["variance_cents"] == (
            report["as_billed_total_cents"] - report["as_certified_total_cents"]
        )
