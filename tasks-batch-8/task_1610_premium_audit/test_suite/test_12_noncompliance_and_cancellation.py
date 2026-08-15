"""Non-compliance escalation: the estimated-audit 1.25x branch, the
delinquency cascade to policy cancellation, manual cancellation, and
mod-revision application."""
from test_helpers import (
    TEST_USERS,
    list_policy_mod_revisions,
    parse_ts,
    schedule_appointment,
    set_clock,
    setup_issued_standard_result,
    setup_noncompliant_work_order,
    setup_selected_work_order,
    approve_estimated,
    validate_success,
)

MANAGER = TEST_USERS["audit_manager_headers"]
UNDERWRITER = TEST_USERS["underwriter_headers"]


class TestEstimatedBillingAndDelinquency:
    def test_estimated_billing_figures_and_past_due(self, api):
        """PRD: "Approval creates the result directly in `ISSUED` (estimated
        results never pass through `PRELIMINARY`) with `variant`
        `ESTIMATED_NONCOMPLIANCE`: `earned_premium_cents` is the policy's
        `estimated_annual_premium_cents` multiplied by 1.25 and rounded half
        up to integer cents, **bypassing both the minimum-premium floor and
        the experience mod factor**."
        PRD: "Billing delinquency is clock-driven: strictly past `due_at` an
        `ISSUED` transaction becomes `PAST_DUE`"

        Design: Difficulty/transitive_cascade/records_overdue_to_policy_cancellation_chain
        """
        ctx = setup_noncompliant_work_order(policy_number="WC-800")
        request = ctx["requests"][0]
        overdue = validate_success(api.get_records_request(request["id"],
                                                           MANAGER))
        assert overdue["status"] == "OVERDUE", (
            "Hop 0: the clock sweep past due_at flipped the request OVERDUE")

        result = approve_estimated(ctx, approver="mgr-2")
        assert result["variant"] == "ESTIMATED_NONCOMPLIANCE"
        assert result["status"] == "ISSUED"
        assert result["earned_premium_cents"] == 2500000, (
            "round_half_up(2000000 * 1.25) = 2500000")
        assert result["adjustment_cents"] == 500000

        billing = ctx["billing"]
        assert billing["type"] == "ADDITIONAL_PREMIUM_INVOICE"
        assert billing["amount_cents"] == 500000
        assert billing["status"] == "ISSUED"
        assert parse_ts(billing["due_at"]) == parse_ts("2026-09-16T00:00:00Z")

        set_clock("2026-09-17T00:00:00Z")
        past_due = validate_success(
            api.get_billing_transaction(billing["id"], MANAGER))
        assert past_due["status"] == "PAST_DUE", (
            "Hop: strictly past due_at, the invoice becomes PAST_DUE")

    def test_delinquency_cancels_policy_and_work_order(self, api):
        """PRD: "Third, any billing transaction that remains unpaid strictly
        more than thirty days past its `due_at` triggers the
        policy-cancellation cascade described in §3.8."
        PRD: "Policy cancellation — whether entered manually by an
        `Underwriter` or fired by the delinquency sweep — moves the policy to
        terminal `CANCELLED` from `ACTIVE`, `AUDIT_PENDING`, or
        `AUDIT_FINALIZED`, increments `Policy.version`, and cascades: every
        work order of the policy in a non-terminal state moves to `CANCELLED`,
        every appointment of those work orders in `SCHEDULED` or `CONFIRMED`
        moves to `CANCELLED`, and every billing transaction of the policy's
        results in `ISSUED` or `PAST_DUE` moves to `CANCELLED`."

        Design: Difficulty/transitive_cascade/records_overdue_to_policy_cancellation_chain
        """
        ctx = setup_noncompliant_work_order(policy_number="WC-800")
        approve_estimated(ctx, approver="mgr-2")
        billing = ctx["billing"]
        set_clock("2026-09-17T00:00:00Z")
        mid = validate_success(api.get_billing_transaction(billing["id"],
                                                           MANAGER))
        assert mid["status"] == "PAST_DUE"

        # due_at 2026-09-16 + 30 days = 2026-10-16T00:00:00Z; 2026-10-17 is
        # strictly more than thirty days past due_at.
        set_clock("2026-10-17T00:00:00Z")

        policy = validate_success(api.get_policy(ctx["policy"]["id"], MANAGER))
        assert policy["status"] == "CANCELLED"
        wo = validate_success(api.get_work_order(ctx["work_order"]["id"],
                                                 MANAGER))
        assert wo["status"] == "CANCELLED"
        bill = validate_success(api.get_billing_transaction(billing["id"],
                                                            MANAGER))
        assert bill["status"] == "CANCELLED"


class TestManualCancellation:
    def test_policy_cancel_cascades_children(self, api):
        """PRD: "Policy cancellation — whether entered manually by an
        `Underwriter` or fired by the delinquency sweep — moves the policy to
        terminal `CANCELLED` from `ACTIVE`, `AUDIT_PENDING`, or
        `AUDIT_FINALIZED`, increments `Policy.version`, and cascades: every
        work order of the policy in a non-terminal state moves to `CANCELLED`,
        every appointment of those work orders in `SCHEDULED` or `CONFIRMED`
        moves to `CANCELLED`, and every billing transaction of the policy's
        results in `ISSUED` or `PAST_DUE` moves to `CANCELLED`."

        Design: Corner/state_machines/policy_cancel_cascades_children
        """
        ctx = setup_selected_work_order(
            policy_number="WC-S7", estimated_annual_premium_cents=2000000,
            minimum_premium_cents=100000)
        appt = schedule_appointment(ctx)

        cancelled = validate_success(
            api.cancel_policy(ctx["policy"]["id"], UNDERWRITER), 200)
        assert cancelled["status"] == "CANCELLED"

        wo = validate_success(api.get_work_order(ctx["work_order"]["id"],
                                                 MANAGER))
        assert wo["status"] == "CANCELLED"
        appt_after = validate_success(api.get_appointment(appt["id"], MANAGER))
        assert appt_after["status"] == "CANCELLED"


class TestModRevisionApplication:
    def test_mod_revision_apply_updates_policy(self, api):
        """PRD: "A revision takes effect only when an `Underwriter` applies
        it: the revision moves `DRAFT → APPLIED`, the policy's
        `experience_mod_factor` becomes `revised_mod_factor`, and
        `Policy.version` increments"
        PRD: "`version` (integer): starts at 1 and increments by one on every
        mutation of the resource."

        Design: Corner/state_machines/mod_revision_apply_updates_policy
        """
        ctx = setup_issued_standard_result(policy_number="WC-S8",
                                           experience_mod_factor=1.20)
        revisions = list_policy_mod_revisions(ctx)
        assert len(revisions) == 1
        revision = revisions[0]
        assert revision["status"] == "DRAFT"
        assert revision["revised_mod_factor"] == 1.19

        before = validate_success(api.get_policy(ctx["policy"]["id"], MANAGER))

        applied = validate_success(
            api.apply_mod_revision(revision["id"], UNDERWRITER), 200)
        assert applied["status"] == "APPLIED"

        after = validate_success(api.get_policy(ctx["policy"]["id"], MANAGER))
        assert after["experience_mod_factor"] == 1.19
        assert after["version"] == before["version"] + 1
