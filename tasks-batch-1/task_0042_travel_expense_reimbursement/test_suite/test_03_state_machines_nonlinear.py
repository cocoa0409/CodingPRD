"""Non-linear state machines: report revision cycle, trip submit fork-join.

Queue A (Difficulty) — rule non_linear_state_machine.
"""
from test_helpers import (
    get_success_data,
    setup_base_env,
    create_approved_trip,
    create_pending_trip,
    create_report,
    add_mileage_line,
    submit_report,
    decide_report,
)


class TestReportRevisionCycle:
    def test_submitted_to_returned_records_reason(self, api):
        """PRD §3.8: "A return decision sends the report from SUBMITTED back to
        RETURNED for revision; it requires a return_reason in the payload, and a
        return decision without one is rejected with ERR_RETURN_REASON_REQUIRED. The
        supplied reason is stored on the report's return_reason."

        Design: Difficulty/non_linear_state_machine/report_revision_cycle_returned_to_draft
        """
        env = setup_base_env()
        trip = create_approved_trip(env, budget_total_cents=50000)
        report = create_report(env, trip, title="Cycle Rpt")
        add_mileage_line(env, report, miles=100)
        submit_report(env, report)
        data = decide_report(env, report, "RETURN", return_reason="Need itemization")
        assert data["status"] == "RETURNED", f"expected RETURNED, got {data['status']}"
        assert data["return_reason"] == "Need itemization", "return_reason must be stored"

    def test_returned_reopened_to_draft_clears_reason(self, api):
        """PRD §3.8: "A RETURNED report can be reopened by its owning Traveler, moving
        it from RETURNED back to DRAFT, clearing return_reason, and making its lines
        editable again — this is the revision cycle DRAFT → SUBMITTED → RETURNED → DRAFT."

        Design: Difficulty/non_linear_state_machine/report_revision_cycle_returned_to_draft
        """
        env = setup_base_env()
        trip = create_approved_trip(env, budget_total_cents=50000)
        report = create_report(env, trip, title="Cycle Rpt")
        add_mileage_line(env, report, miles=100)
        submit_report(env, report)
        decide_report(env, report, "RETURN", return_reason="Need itemization")
        data = get_success_data(api.reopen_expense_report(report["id"], env["traveler_headers"]))
        assert data["status"] == "DRAFT", f"expected DRAFT after reopen, got {data['status']}"
        assert not data.get("return_reason"), "return_reason must be cleared on reopen"


class TestTripSubmitForkJoin:
    def test_out_of_policy_budget_forks_to_pending_oop(self, api):
        """PRD §3.2: "When requires_oop evaluates to true, the trip takes the
        out-of-policy branch: it sets requires_oop to true and moves from PENDING to
        PENDING_OOP_APPROVAL, where it awaits an approver's decision."
        PRD §3.2: "when budget_total_cents strictly exceeds two times the sum of the
        destination's lodging_cap_cents and mie_cents, multiplied by the number of
        trip nights, where the number of nights is the count of days between
        start_date and end_date (the later date minus the earlier date, with no
        inclusive adjustment)."

        Design: Difficulty/non_linear_state_machine/trip_submit_fork_join_oop_vs_auto
        """
        env = setup_base_env(lodging_cap_cents=20000, mie_cents=8000)
        # 4 nights, baseline 2*(20000+8000)*4 = 224000; budget 300000 > baseline -> OOP
        trip = create_pending_trip(env, budget_total_cents=300000,
                                   start_date="2026-06-01", end_date="2026-06-05")
        data = get_success_data(api.submit_trip_request(trip["id"], env["traveler_headers"]))
        assert data["status"] == "PENDING_OOP_APPROVAL", (
            f"over-baseline budget must fork to PENDING_OOP_APPROVAL, got {data['status']}"
        )
        assert data["requires_oop"] is True, "requires_oop must be set true"

    def test_in_policy_budget_auto_approves_and_inits_ledger(self, api):
        """PRD §3.2: "When requires_oop evaluates to false, the trip takes the
        in-policy branch: it sets requires_oop to false and moves from PENDING to
        AUTO_APPROVED, and the system immediately joins that branch forward to the
        terminal APPROVED state with no manual review."
        PRD §3.2: "the same initialization occurs as the trip's budget ledger comes
        alive: remaining_budget_cents is initialized to the full budget_total_cents and
        committed_amount_cents is initialized to zero."

        Design: Difficulty/non_linear_state_machine/trip_submit_fork_join_oop_vs_auto
        """
        env = setup_base_env(lodging_cap_cents=20000, mie_cents=8000)
        # 4 nights, baseline 224000; budget 200000 <= baseline -> in-policy -> APPROVED
        trip = create_pending_trip(env, budget_total_cents=200000,
                                   start_date="2026-06-01", end_date="2026-06-05")
        data = get_success_data(api.submit_trip_request(trip["id"], env["traveler_headers"]))
        assert data["status"] == "APPROVED", (
            f"in-policy budget must auto-approve to APPROVED, got {data['status']}"
        )
        assert data["requires_oop"] is False, "requires_oop must be false"
        assert data["remaining_budget_cents"] == 200000, "remaining initialized to full budget"
