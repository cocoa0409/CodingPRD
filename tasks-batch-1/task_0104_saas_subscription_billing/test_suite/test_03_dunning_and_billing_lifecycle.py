"""Parallel lifecycle x billing dimensions, the invoice revert loop, the
dunning-exhaustion cascade, and the dunning attempt boundary.

Queue A (difficulty) translations for:
  non_linear_state_machine (both instances),
  transitive_cascade/dunning_exhaustion_cascade_depth3_billing_lifecycle_mrr,
  boundary_precision/dunning_max_attempts_boundary_two_stays_three_cancels.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    make_account_owner_headers,
    TEST_USERS,
    setup_renewal_with_failing_card,
    set_card_state,
    set_clock,
    run_dunning,
    find_renewal_invoice,
)

ADMIN = TEST_USERS["billing_admin_headers"]


def _owner(account_id):
    return make_account_owner_headers(account_id)


class TestParallelLifecycleAndBilling:
    """lifecycle_status stays ACTIVE while billing_status moves to PAST_DUE."""

    def test_one_failed_payment_moves_billing_not_lifecycle(self, api):
        """PRD §3.7: "On the first failure of an open invoice, the invoice transitions `OPEN → PAST_DUE`, the subscription's `billing_status` mirrors `CURRENT → PAST_DUE`, `dunning_attempt` increments by 1, and `next_retry_at` is set to the first failure time plus the offset indexed by the new `dunning_attempt`." PRD §2.4 and §3.2: the
        lifecycle dimension "evolves on payment outcomes independently of the lifecycle
        dimension."

        Design: Difficulty/non_linear_state_machine/subscription_parallel_lifecycle_and_billing_dimensions
        """
        plan, account, sub = setup_renewal_with_failing_card(email="par@x.com")
        run_dunning()
        s = validate_success(api.get_subscription(sub["id"], _owner(account["id"])), 200)
        assert s["lifecycle_status"] == "ACTIVE", f"lifecycle, got {s['lifecycle_status']}"
        assert s["billing_status"] == "PAST_DUE", f"billing, got {s['billing_status']}"

    def test_one_failed_payment_increments_dunning_attempt(self, api):
        """PRD §3.7: "On the first failure of an open invoice, the invoice transitions `OPEN → PAST_DUE`, the subscription's `billing_status` mirrors `CURRENT → PAST_DUE`, `dunning_attempt` increments by 1, and `next_retry_at` is set to the first failure time plus the offset indexed by the new `dunning_attempt`."

        Design: Difficulty/non_linear_state_machine/subscription_parallel_lifecycle_and_billing_dimensions
        """
        plan, account, sub = setup_renewal_with_failing_card(email="par2@x.com")
        run_dunning()
        s = validate_success(api.get_subscription(sub["id"], _owner(account["id"])), 200)
        assert s["dunning_attempt"] == 1, f"dunning_attempt, got {s['dunning_attempt']}"


class TestInvoiceRevertLoop:
    """Invoice cycles OPEN -> PAST_DUE -> OPEN -> PAID across retries."""

    def test_invoice_clears_after_revert_loop(self, api):
        """PRD §3.7: "When the next tick is due and a queued retry is about to run, the invoice reverts `PAST_DUE → OPEN` so the attempt can execute." PRD §3.7: "If a retry clears while the subscription is `PAST_DUE` and the tick is due, the invoice becomes `PAID` with `amount_paid_cents` set to `total_cents`".

        Design: Difficulty/non_linear_state_machine/invoice_branching_open_pastdue_open_revert_loop
        """
        plan, account, sub = setup_renewal_with_failing_card(email="brn@x.com")
        run_dunning()  # first failure -> PAST_DUE, retry due 2026-07-04
        set_card_state(account["id"], True)
        set_clock("2026-07-04T00:00:00Z")
        run_dunning()  # retry clears
        inv = find_renewal_invoice(account["id"], "2026-07-01T00:00:00Z")
        assert inv is not None
        invoice = validate_success(api.get_invoice(inv["id"], _owner(account["id"])), 200)
        assert invoice["status"] == "PAID", f"invoice status after retry clears, got {invoice['status']}"

    def test_billing_status_recovers_to_current_after_clear(self, api):
        """PRD §3.7: "`billing_status` reverts `PAST_DUE → CURRENT`, `dunning_attempt` resets to 0, `next_retry_at` is cleared, and a revenue schedule entry is created."

        Design: Difficulty/non_linear_state_machine/invoice_branching_open_pastdue_open_revert_loop
        """
        plan, account, sub = setup_renewal_with_failing_card(email="brn2@x.com")
        run_dunning()
        set_card_state(account["id"], True)
        set_clock("2026-07-04T00:00:00Z")
        run_dunning()
        s = validate_success(api.get_subscription(sub["id"], _owner(account["id"])), 200)
        assert s["billing_status"] == "CURRENT", f"billing, got {s['billing_status']}"
        assert s["dunning_attempt"] == 0, f"dunning_attempt reset, got {s['dunning_attempt']}"


class TestDunningExhaustionCascade:
    """Three failed retries cascade billing -> lifecycle -> invoice -> MRR."""

    def _exhaust(self, api, email):
        plan, account, sub = setup_renewal_with_failing_card(email=email)
        run_dunning()  # attempt 1 fails -> PAST_DUE, next retry 2026-07-04
        set_clock("2026-07-04T00:00:00Z")
        run_dunning()  # attempt 2 fails -> still PAST_DUE, next retry 2026-07-08
        set_clock("2026-07-08T00:00:00Z")
        run_dunning()  # attempt 3 fails -> involuntary churn
        return plan, account, sub

    def test_final_fail_sets_billing_unpaid_and_lifecycle_canceled(self, api):
        """PRD §3.7: "If instead `dunning_attempt` has reached the maximum of 3 and the retry fails, the subscription is involuntarily canceled: `billing_status` becomes `UNPAID` and, as the cross-effect on the lifecycle dimension, `lifecycle_status` moves `ACTIVE → CANCELED` with `mrr_contribution_cents` set to 0."

        Design: Difficulty/transitive_cascade/dunning_exhaustion_cascade_depth3_billing_lifecycle_mrr
        """
        plan, account, sub = self._exhaust(api, "dun@x.com")
        s = validate_success(api.get_subscription(sub["id"], _owner(account["id"])), 200)
        assert s["billing_status"] == "UNPAID", f"billing, got {s['billing_status']}"
        assert s["lifecycle_status"] == "CANCELED", f"lifecycle, got {s['lifecycle_status']}"

    def test_final_fail_voids_invoice_and_zeroes_account_mrr(self, api):
        """PRD §3.7: "The open invoice transitions `PAST_DUE → VOID`, and the account's `mrr_cents` is recomputed to drop this subscription — this is the involuntary-churn event."

        Design: Difficulty/transitive_cascade/dunning_exhaustion_cascade_depth3_billing_lifecycle_mrr
        """
        plan, account, sub = self._exhaust(api, "dun2@x.com")
        inv = find_renewal_invoice(account["id"], "2026-07-01T00:00:00Z")
        assert inv is not None
        invoice = validate_success(api.get_invoice(inv["id"], _owner(account["id"])), 200)
        assert invoice["status"] == "VOID", f"invoice status, got {invoice['status']}"
        acct = validate_success(api.get_account(account["id"], _owner(account["id"])), 200)
        assert acct["mrr_cents"] == 0, f"account mrr after involuntary churn, got {acct['mrr_cents']}"


class TestDunningAttemptBoundary:
    """At dunning_attempt 2 the subscription stays ACTIVE; only 3 cancels."""

    def test_after_second_fail_subscription_stays_active_past_due(self, api):
        """PRD §3.7: "The boundary is precise: while `dunning_attempt` is 2 the subscription remains `PAST_DUE`, and only when `dunning_attempt` reaches 3 and that final retry still fails does involuntary churn occur."

        Design: Difficulty/boundary_precision_check/dunning_max_attempts_boundary_two_stays_three_cancels
        """
        plan, account, sub = setup_renewal_with_failing_card(email="d2@x.com")
        run_dunning()  # attempt 1
        set_clock("2026-07-04T00:00:00Z")
        run_dunning()  # attempt 2
        s = validate_success(api.get_subscription(sub["id"], _owner(account["id"])), 200)
        assert s["dunning_attempt"] == 2, f"dunning_attempt, got {s['dunning_attempt']}"
        assert s["lifecycle_status"] == "ACTIVE", f"lifecycle at attempt 2, got {s['lifecycle_status']}"
        assert s["billing_status"] == "PAST_DUE", f"billing at attempt 2, got {s['billing_status']}"

    def test_third_fail_cancels_subscription(self, api):
        """PRD §3.7: "only when `dunning_attempt` reaches 3 and that final retry still fails does involuntary churn occur." PRD §3.7: "`lifecycle_status` moves `ACTIVE → CANCELED` with `mrr_contribution_cents` set to 0."

        Design: Difficulty/boundary_precision_check/dunning_max_attempts_boundary_two_stays_three_cancels
        """
        plan, account, sub = setup_renewal_with_failing_card(email="d3@x.com")
        run_dunning()  # attempt 1
        set_clock("2026-07-04T00:00:00Z")
        run_dunning()  # attempt 2
        set_clock("2026-07-08T00:00:00Z")
        run_dunning()  # attempt 3 -> cancel
        s = validate_success(api.get_subscription(sub["id"], _owner(account["id"])), 200)
        assert s["lifecycle_status"] == "CANCELED", f"lifecycle at attempt 3, got {s['lifecycle_status']}"
