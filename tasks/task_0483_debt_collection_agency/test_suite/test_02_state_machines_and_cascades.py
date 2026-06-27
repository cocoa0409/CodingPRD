"""Non-linear state machines, transitive cascades, and compensating invariants.

All tests translate difficulty-design (queue A) instances.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    set_clock,
    setup_working_account,
    setup_working_account_with_verified_dispute,
    setup_working_account_with_plan_payment,
    setup_validation_sent_account,
    propose_arrangement,
    accept_arrangement,
    post_payment,
    raise_dispute,
    log_phone_attempt,
    refresh_account,
    assert_ledger_conserved,
    TEST_USERS,
)

COLLECTOR = TEST_USERS["collector_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ===========================================================================
# non_linear_state_machine / dispute_cyclic_resolve_reopen_resolve
# ===========================================================================
class TestDisputeCyclicReopen:
    """A dispute cycles RESOLVED -> REOPENED -> RESOLVED, clearing resolution on reopen."""

    def test_reopen_clears_resolution_and_sets_reopened(self):
        """PRD §3.4: "Reopening clears the `resolution` back to null and moves the
        dispute to `REOPENED`; if the dispute is a `VALIDATION` dispute whose
        `within_validation_window` is true, reopening re-applies the hold by pushing
        the account's `contact_status` back to `VALIDATION_HELD`."

        Design: Difficulty/non_linear_state_machine/dispute_cyclic_resolve_reopen_resolve
        """
        ctx = setup_working_account_with_verified_dispute(clock="2026-01-01T00:00:00Z")
        disp_id = ctx["dispute"]["id"]
        reopened = validate_success(api_client.reopen_dispute(disp_id, COMPLIANCE), 200)
        assert reopened["status"] == "REOPENED"
        assert reopened["resolution"] is None

    def test_resolve_again_from_reopened_returns_to_resolved(self):
        """PRD §3.4: "From `REOPENED`, the same resolution rules apply as from
        `INVESTIGATING`: a `resolution` of `VERIFIED` or `DELETED` must be supplied,
        the dispute returns to `RESOLVED`, and the same downstream effects — lifting
        the hold on `VERIFIED` `VALIDATION` disputes, closing the account and
        deleting open furnishings on `DELETED` — apply identically."

        Design: Difficulty/non_linear_state_machine/dispute_cyclic_resolve_reopen_resolve
        """
        ctx = setup_working_account_with_verified_dispute(clock="2026-01-01T00:00:00Z")
        disp_id = ctx["dispute"]["id"]
        get_success_data(api_client.reopen_dispute(disp_id, COMPLIANCE))
        resolved = validate_success(
            api_client.resolve_dispute(disp_id, {"resolution": "VERIFIED"}, COMPLIANCE), 200
        )
        assert resolved["status"] == "RESOLVED"


# ===========================================================================
# non_linear_state_machine / account_parallel_dimensions_work_vs_contact_status
# ===========================================================================
class TestAccountParallelDimensions:
    """cease-communication flips contact_status to CEASED while work_status stays WORKING."""

    def test_cease_sets_contact_status_ceased(self):
        """PRD §3.5: "The request drives the account's `contact_status` to `CEASED`
        from whichever of `PRE_VALIDATION`, `CONTACTABLE`, or `VALIDATION_HELD` it
        currently holds, and `CEASED` is terminal on the communication axis."

        Design: Difficulty/non_linear_state_machine/account_parallel_dimensions_work_vs_contact_status
        """
        ctx = setup_working_account(clock="2026-01-01T00:00:00Z")
        acct = validate_success(
            api_client.cease_communication(ctx["account"]["id"], COMPLIANCE), 200
        )
        assert acct["contact_status"] == "CEASED"

    def test_work_status_unchanged_by_cease(self):
        """PRD §2.8: "These two dimensions evolve largely independently: an account
        may be `WORKING` on the placement axis while `CEASED` on the communication
        axis."

        Design: Difficulty/non_linear_state_machine/account_parallel_dimensions_work_vs_contact_status
        """
        ctx = setup_working_account(clock="2026-01-01T00:00:00Z")
        acct = validate_success(
            api_client.cease_communication(ctx["account"]["id"], COMPLIANCE), 200
        )
        assert acct["work_status"] == "WORKING"
        assert acct["contact_status"] == "CEASED"


# ===========================================================================
# transitive_cascade / recall_cascades_arrangement_payment_ledger_depth3
# ===========================================================================
class TestRecallCascadeDepth3:
    """Recall -> cancel arrangement -> void payment -> restore ledger (3-hop chain)."""

    def _setup(self):
        return setup_working_account_with_plan_payment(
            clock="2026-01-01T00:00:00Z",
            payment_cents=30000,
            installment_count=4,
            account_overrides={"original_principal_cents": 100000},
        )

    def test_recall_sets_work_status_recalled(self):
        """PRD §3.8: "A successful recall increments the account's `version` by one,
        moves `work_status` to `RECALLED`, and runs a three-level cascade."

        Design: Difficulty/transitive_cascade/recall_cascades_arrangement_payment_ledger_depth3
        """
        ctx = self._setup()
        v_pre = ctx["account"]["version"]
        acct = validate_success(
            api_client.recall_account(
                ctx["account"]["id"], {"expected_account_version": v_pre},
                ctx["creditor_headers"],
            ), 200
        )
        assert acct["work_status"] == "RECALLED"

    def test_recall_cancels_arrangement_voids_payment_restores_ledger(self):
        """PRD §3.8: "At the first level, every `PaymentArrangement` on the account
        whose `status` is `PROPOSED`, `ACCEPTED`, or `COUNTERED` is moved to
        `CANCELLED`. At the second level, each arrangement just cancelled voids its
        still-live payments: every payment tied to it that is in `POSTED` status
        moves to `VOIDED`. At the third level, each voided payment subtracts its
        `amount_cents` from the account's `amount_collected_cents` and adds it back
        to `balance_cents`, restoring the ledger."

        Design: Difficulty/transitive_cascade/recall_cascades_arrangement_payment_ledger_depth3
        """
        ctx = self._setup()
        v_pre = ctx["account"]["version"]
        arr_id = ctx["arrangement"]["id"]
        pay_id = ctx["payment"]["id"]
        get_success_data(
            api_client.recall_account(
                ctx["account"]["id"], {"expected_account_version": v_pre},
                ctx["creditor_headers"],
            )
        )
        arr = validate_success(api_client.get_arrangement(arr_id, COLLECTOR), 200)
        pay = validate_success(api_client.get_payment(pay_id, COLLECTOR), 200)
        acct = refresh_account(ctx)
        assert arr["status"] == "CANCELLED"
        assert pay["status"] == "VOIDED"
        assert acct["amount_collected_cents"] == 0
        assert acct["balance_cents"] == 100000


# ===========================================================================
# transitive_cascade / validation_dispute_holds_contact_then_blocks_attempt_depth2
# ===========================================================================
class TestValidationHoldBlocksAttempt:
    """In-window VALIDATION dispute -> contact_status VALIDATION_HELD -> attempt rejected."""

    def _setup_held(self):
        # notice sent at 2026-01-01 (deadline 2026-01-31); raise VALIDATION dispute
        # in-window at 2026-01-05T15:00:00Z so contact_status -> VALIDATION_HELD.
        ctx = setup_validation_sent_account(clock="2026-01-01T00:00:00Z")
        set_clock("2026-01-05T15:00:00Z")
        disp = raise_dispute(ctx["account"]["id"], "VALIDATION")
        ctx["dispute"] = disp
        refresh_account(ctx)
        return ctx

    def test_in_window_validation_dispute_holds_contact(self):
        """PRD §3.4: "When a `VALIDATION` dispute is raised inside the validation
        window — that is, when `within_validation_window` is true — it pushes the
        account's `contact_status` to `VALIDATION_HELD`, pausing collection
        communication on the account until the dispute resolves in the agency's
        favor."

        Design: Difficulty/transitive_cascade/validation_dispute_holds_contact_then_blocks_attempt_depth2
        """
        ctx = self._setup_held()
        assert ctx["account"]["contact_status"] == "VALIDATION_HELD"

    def test_attempt_under_hold_rejected_validation_hold(self):
        """PRD §3.5: "Likewise, if the account's `contact_status` is
        `VALIDATION_HELD` because an in-window validation dispute is unresolved, the
        cadence-counting attempt is refused with `ERR_VALIDATION_HOLD`."

        Design: Difficulty/transitive_cascade/validation_dispute_holds_contact_then_blocks_attempt_depth2
        """
        ctx = self._setup_held()
        res = log_phone_attempt(ctx["account"]["id"], "2026-01-05T15:00:00Z", "LOGGED")
        validate_error(res, ApiErrorId.ERR_VALIDATION_HOLD.value)


# ===========================================================================
# compensating_invariant / payment_reverse_conserves_balance_plus_collected
# ===========================================================================
class TestPaymentReverseConserves:
    """Post then reverse leaves balance_cents + amount_collected_cents unchanged."""

    def _setup_posted(self):
        ctx = setup_working_account(
            clock="2026-01-01T00:00:00Z",
            account_overrides={"original_principal_cents": 100000},
        )
        pay = get_success_data(post_payment(ctx["account"]["id"], 30000))
        ctx["payment"] = pay
        refresh_account(ctx)
        return ctx

    def test_conserved_quantity_before_reverse(self):
        """PRD §2.9: "across a payment's posting and later reversal or voiding, with
        no forgiveness in between, the sum of `balance_cents` and
        `amount_collected_cents` on the account is preserved, because every cent
        removed from one is added back to the other."

        Design: Difficulty/compensating_invariant/payment_reverse_conserves_balance_plus_collected
        """
        ctx = self._setup_posted()
        assert_ledger_conserved(ctx["account"], 100000)
        # also confirm the post applied (balance 70000, collected 30000)
        assert ctx["account"]["balance_cents"] == 70000
        assert ctx["account"]["amount_collected_cents"] == 30000

    def test_reverse_restores_ledger_and_conserves(self):
        """PRD §3.7: "Reversal moves the payment from `POSTED` to `REVERSED`,
        subtracts the payment's `amount_cents` from the account's
        `amount_collected_cents` and adds it back to `balance_cents` so the ledger is
        restored, recomputes the account's commission, `last_payment_date`, and
        `time_barred`, and increments the account's `version` by one."

        Design: Difficulty/compensating_invariant/payment_reverse_conserves_balance_plus_collected
        """
        ctx = self._setup_posted()
        v_pre = ctx["account"]["version"]
        pay = validate_success(
            api_client.reverse_payment(
                ctx["payment"]["id"], {"expected_account_version": v_pre}, COLLECTOR
            ), 200
        )
        assert pay["status"] == "REVERSED"
        acct = refresh_account(ctx)
        assert acct["amount_collected_cents"] == 0
        assert acct["balance_cents"] == 100000
        assert_ledger_conserved(acct, 100000)


# ===========================================================================
# compensating_invariant / recall_cancel_conserves_attempt_window_count
# ===========================================================================
class TestRecallConservesAttemptCount:
    """Recall voids payments but leaves attempts_in_window_count untouched."""

    def _setup(self):
        # WORKING account; two PHONE LOGGED attempts in window; ACCEPTED PLAN with
        # one 30000 payment. Clock at 2026-03-01T15:00:00Z (daytime, offset 0).
        ctx = setup_working_account(
            clock="2026-03-01T15:00:00Z",
            account_overrides={"original_principal_cents": 100000},
        )
        acct_id = ctx["account"]["id"]
        get_success_data(log_phone_attempt(acct_id, "2026-03-01T09:00:00Z", "LOGGED"))
        get_success_data(log_phone_attempt(acct_id, "2026-03-01T10:00:00Z", "LOGGED"))
        arr = propose_arrangement(acct_id, "PLAN", installment_count=4)
        arr = accept_arrangement(arr["id"])
        pay = get_success_data(post_payment(acct_id, 30000, arrangement_id=arr["id"]))
        ctx["payment"] = pay
        refresh_account(ctx)
        return ctx

    def test_attempt_count_two_before_recall(self):
        """PRD §3.5: "The account publishes `attempts_in_window_count`, the number of
        cadence-counting communication attempts on the account whose `outcome` is
        `LOGGED` or `CONVERSATION` and whose `attempted_at` falls strictly after the
        instant seven days before the clock and at or before the clock itself — a
        half-open window that excludes its start and includes its end."

        Design: Difficulty/compensating_invariant/recall_cancel_conserves_attempt_window_count
        """
        ctx = self._setup()
        assert ctx["account"]["attempts_in_window_count"] == 2

    def test_recall_voids_payment_but_conserves_attempt_count(self):
        """PRD §2.9: "across a payment's posting and later reversal or voiding, with
        no forgiveness in between, the sum of `balance_cents` and
        `amount_collected_cents` on the account is preserved, because every cent
        removed from one is added back to the other."
        PRD §3.5: "The account publishes `attempts_in_window_count`, the number of
        cadence-counting communication attempts on the account whose `outcome` is
        `LOGGED` or `CONVERSATION` and whose `attempted_at` falls strictly after the
        instant seven days before the clock and at or before the clock itself — a
        half-open window that excludes its start and includes its end."

        Design: Difficulty/compensating_invariant/recall_cancel_conserves_attempt_window_count
        """
        ctx = self._setup()
        v_pre = ctx["account"]["version"]
        recalled = validate_success(
            api_client.recall_account(
                ctx["account"]["id"], {"expected_account_version": v_pre},
                ctx["creditor_headers"],
            ), 200
        )
        pay = validate_success(api_client.get_payment(ctx["payment"]["id"], COLLECTOR), 200)
        assert recalled["work_status"] == "RECALLED"
        assert pay["status"] == "VOIDED"
        assert recalled["attempts_in_window_count"] == 2
