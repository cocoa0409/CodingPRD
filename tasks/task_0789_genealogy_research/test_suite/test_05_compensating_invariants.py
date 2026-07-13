"""Compensating-action conservation: time-entry void restores consumed_hours;
milestone cancel-after-invoice conserves net billed money and outstanding balance."""
import pytest

from test_helpers import (
    get_success_data, make_researcher_headers, TEST_USERS,
    create_active_project, log_time_data, setup_invoiced_milestone,
    assert_project_ledger_invariants, api_client,
)

PM = TEST_USERS["project_manager_headers"]


# ==========================================================================
# compensating_invariant / consumed_hours_conserved_on_time_entry_void
# ==========================================================================
class TestConsumedHoursConservedOnVoid:
    def _log_and_void(self):
        client, researcher, project = create_active_project(
            package_type="BASIC_PACKAGE", package_price_cents=100000, budget_hours=10)
        entry = log_time_data(project["id"], researcher["id"], hours=4, billable=True)
        rh = make_researcher_headers(researcher["id"])
        voided = get_success_data(api_client.void_time_entry(
            entry["id"], rh, {"reason": "duplicate entry"}))
        return voided, project

    def test_void_marks_entry_voided(self):
        """PRD §3.2: "An entry may later be voided (`ACTIVE → VOIDED`), which is a
        compensating action: if the entry was billable, its `hours` are subtracted
        back out of `consumed_hours`, and the project's actual cost is recomputed,
        so that consumed hours are conserved across a create-then-void pair."

        Design: Difficulty/compensating_invariant/consumed_hours_conserved_on_time_entry_void
        """
        voided, _ = self._log_and_void()
        assert voided["status"] == "VOIDED"

    def test_consumed_hours_conserved_after_void(self):
        """PRD §3.2: "if the entry was billable, its `hours` are subtracted back out
        of `consumed_hours`, and the project's actual cost is recomputed, so that
        consumed hours are conserved across a create-then-void pair."

        Design: Difficulty/compensating_invariant/consumed_hours_conserved_on_time_entry_void
        """
        _, project = self._log_and_void()
        proj = get_success_data(api_client.get_project(project["id"], PM))
        assert proj["consumed_hours"] == pytest.approx(0.0, abs=0.001), (
            f"void must return consumed_hours to its pre-log value 0.0, got {proj['consumed_hours']}")


# ==========================================================================
# compensating_invariant / net_billed_conserved_on_milestone_cancel
# ==========================================================================
class TestNetBilledConservedOnMilestoneCancel:
    def _invoice_and_cancel(self):
        client, researcher, project = create_active_project(
            client_tier="STANDARD", package_type="BASIC_PACKAGE",
            package_price_cents=100000, budget_hours=10, priority="STANDARD")
        milestone = setup_invoiced_milestone(project["id"], researcher["id"], client["id"],
                                             amount_cents=40000, sequence_no=1)
        cancelled = get_success_data(api_client.cancel_milestone(
            milestone["id"], PM, {"reason": "client withdrew scope"}))
        return cancelled, project

    def test_cancel_credits_line_total_without_undoing_invoice(self):
        """PRD §3.9: "Cancelling an `INVOICED` milestone, by contrast, does not undo
        the invoice: instead it adds the milestone's `line_total_cents` to the
        project's `credited_total_cents` as a compensating credit and recomputes
        `outstanding_balance_cents` and `billable_amount_cents`, so that
        `invoiced_total_cents` stays put while the credit offsets it."

        Design: Difficulty/compensating_invariant/net_billed_conserved_on_milestone_cancel
        """
        cancelled, project = self._invoice_and_cancel()
        assert cancelled["status"] == "CANCELLED"
        proj = get_success_data(api_client.get_project(project["id"], PM))
        # base 40000 STANDARD/STANDARD -> invoiced 40000; fee round_half_up(3000)=3000; line 43000.
        assert proj["invoiced_total_cents"] == 43000, (
            f"invoiced_total_cents must stay put at 43000, got {proj['invoiced_total_cents']}")
        assert proj["credited_total_cents"] == 43000, (
            f"cancel must credit the 43000 line total, got {proj['credited_total_cents']}")

    def test_outstanding_balance_returns_to_zero(self):
        """PRD §3.9: "the project's `outstanding_balance_cents` is defined as
        `invoiced_total_cents` less `paid_total_cents` less `credited_total_cents`".

        Design: Difficulty/compensating_invariant/net_billed_conserved_on_milestone_cancel
        """
        _, project = self._invoice_and_cancel()
        proj = get_success_data(api_client.get_project(project["id"], PM))
        assert proj["outstanding_balance_cents"] == 0, (
            f"cancel-after-invoice must return outstanding_balance to 0, "
            f"got {proj['outstanding_balance_cents']}")
        assert_project_ledger_invariants(proj)
