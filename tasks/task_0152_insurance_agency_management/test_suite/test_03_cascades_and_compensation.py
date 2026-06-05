"""Depth tests for transitive cascades (renewal completion, cancel ledger) and
compensating invariants (reinstatement conserves trust cash and producer accrual).

Queue A (Difficulty) translations for: transitive_cascade and compensating_invariant.
"""
import pytest

from test_helpers import (
    validate_success,
    get_success_data,
    api_client,
    TEST_USERS,
    is_valid_uuid,
    setup_active_policy,
    setup_active_policy_no_split,
    setup_renewal_task_offered,
    setup_compliant_writer,
    open_trust_account_with_balance,
    open_statement,
    get_statement,
    set_clock,
)

MANAGER = lambda: TEST_USERS["account_manager_headers"]
TRUST = lambda: TEST_USERS["trust_accountant_headers"]


# ===========================================================================
# Rule: transitive_cascade / renewal_complete_cascade_depth3
# ===========================================================================
class TestRenewalCompleteCascade:
    def _offered_in_window(self):
        set_clock("2026-01-01T00:00:00Z")
        s = setup_renewal_task_offered(
            active_setup=setup_active_policy_no_split(
                policy_overrides={
                    "annual_premium_cents": 1_200_000,
                    "effective_date": "2026-01-01T00:00:00Z",
                    "expiration_date": "2027-01-01T00:00:00Z",
                }
            )
        )
        return s

    def test_complete_creates_successor_and_expires_prior(self, api):
        """PRD §3.8: "On completion, a successor `Policy` is created directly in `BOUND`
        status with `term_kind` set to `RENEWAL` and `renewed_from_policy_id` pointing at the
        expiring policy (extending the renewal chain); the task's `successor_policy_id` is set
        to the new policy's id; the task's stage becomes `COMPLETED`; the expiring policy is
        cascaded `PENDING_RENEWAL → EXPIRED`; and the owning account's `active_policy_count`
        is recomputed."

        Design: Difficulty/transitive_cascade/renewal_complete_cascade_depth3
        """
        s = self._offered_in_window()
        task = s["task"]
        resp = api.complete_renewal_task(
            task["id"],
            {
                "expected_renewaltask_version": task["version"],
                "annual_premium_cents": 1_250_000,
                "effective_date": "2027-01-01T00:00:00Z",
                "expiration_date": "2028-01-01T00:00:00Z",
            },
            MANAGER(),
        )
        data = validate_success(resp, 200)
        assert data["stage"] == "COMPLETED", data
        assert is_valid_uuid(data["successor_policy_id"]), data
        # Cascade hop 2: the expiring policy moves PENDING_RENEWAL -> EXPIRED.
        prior = get_success_data(api_client.get_policy(s["policy"]["id"], MANAGER()))
        assert prior["status"] == "EXPIRED", prior

    def test_complete_recomputes_account_count_to_zero(self, api):
        """PRD §3.3: "An account tracks a derived `active_policy_count` — the number of
        policies under it whose status is either `ACTIVE` or `PENDING_RENEWAL` — which starts
        at 0 and is recomputed on every policy state change that could affect it."

        Design: Difficulty/transitive_cascade/renewal_complete_cascade_depth3
        """
        s = self._offered_in_window()
        task = s["task"]
        account_id = s["ctx"]["account"]["id"]
        before = get_success_data(api_client.get_account(account_id, MANAGER()))
        assert before["active_policy_count"] == 1, before  # PENDING_RENEWAL still counts.
        api.complete_renewal_task(
            task["id"],
            {
                "expected_renewaltask_version": task["version"],
                "annual_premium_cents": 1_250_000,
                "effective_date": "2027-01-01T00:00:00Z",
                "expiration_date": "2028-01-01T00:00:00Z",
            },
            MANAGER(),
        )
        # Cascade hop 3: expiring -> EXPIRED (not counted); successor BOUND (not counted).
        after = get_success_data(api_client.get_account(account_id, MANAGER()))
        assert after["active_policy_count"] == 0, after


# ===========================================================================
# Rule: transitive_cascade / policy_cancel_cascade_depth2
# ===========================================================================
class TestPolicyCancelCascade:
    def _active_with_trust(self):
        set_clock("2026-07-01T00:00:00Z")
        trust = open_trust_account_with_balance(5_000_000, state_code="CA")
        s = setup_active_policy_no_split(
            policy_overrides={
                "annual_premium_cents": 1_200_000,
                "effective_date": "2026-01-01T00:00:00Z",
                "expiration_date": "2027-01-01T00:00:00Z",
            }
        )
        return trust, s["policy"]

    def test_cancel_posts_return_premium_refund_entry(self, api):
        """PRD §3.6: "A `RETURN_PREMIUM_REFUND` ledger entry for the negative of the return
        premium posts to the trust account held for the policy's state, moving that money out
        of trust and triggering recomputation of the account's `balance_cents`."

        Design: Difficulty/transitive_cascade/policy_cancel_cascade_depth2
        """
        trust, policy = self._active_with_trust()
        get_success_data(
            api_client.cancel_policy(
                policy["id"],
                {
                    "expected_policy_version": policy["version"],
                    "cancellation_date": "2026-07-01T00:00:00Z",
                    "cancellation_reason": "INSURED_REQUEST",
                },
                MANAGER(),
            )
        )
        entries, _ = _list_ledger_for_policy(policy["id"])
        refunds = [e for e in entries if e["entry_type"] == "RETURN_PREMIUM_REFUND"]
        assert len(refunds) == 1, entries
        assert refunds[0]["amount_cents"] == -604932, refunds[0]

    def test_cancel_recomputes_trust_balance(self, api):
        """PRD §2.6: "each `TrustAccount` keeps a derived `balance_cents` that is always
        exactly the sum of the `amount_cents` of every `TrustLedgerEntry` posted to it,
        recomputed on every posting (derived-field reconciliation)."

        Design: Difficulty/transitive_cascade/policy_cancel_cascade_depth2
        """
        trust, policy = self._active_with_trust()
        get_success_data(
            api_client.cancel_policy(
                policy["id"],
                {
                    "expected_policy_version": policy["version"],
                    "cancellation_date": "2026-07-01T00:00:00Z",
                    "cancellation_reason": "INSURED_REQUEST",
                },
                MANAGER(),
            )
        )
        refreshed = get_success_data(api_client.get_trust_account(trust["id"], TRUST()))
        assert refreshed["balance_cents"] == 5_000_000 - 604932, refreshed


# ===========================================================================
# Rule: compensating_invariant / reinstate_conserves_trust_cash
# ===========================================================================
class TestReinstateConservesTrustCash:
    def _cancel_then(self):
        set_clock("2026-07-01T00:00:00Z")
        trust = open_trust_account_with_balance(5_000_000, state_code="CA")
        s = setup_active_policy_no_split(
            policy_overrides={
                "annual_premium_cents": 1_200_000,
                "effective_date": "2026-01-01T00:00:00Z",
                "expiration_date": "2027-01-01T00:00:00Z",
            }
        )
        policy = s["policy"]
        cancelled = get_success_data(
            api_client.cancel_policy(
                policy["id"],
                {
                    "expected_policy_version": policy["version"],
                    "cancellation_date": "2026-07-01T00:00:00Z",
                    "cancellation_reason": "INSURED_REQUEST",
                },
                MANAGER(),
            )
        )
        return trust, cancelled

    def test_balance_returns_to_pre_cancel_value(self, api):
        """PRD §3.7: "A reversing `PREMIUM_RECEIPT` ledger entry for the positive of the
        previously refunded amount posts to the state's trust account, restoring exactly the
        money the refund removed and triggering recomputation of `balance_cents` — the
        compensation invariant that leaves the ledger whole."

        Design: Difficulty/compensating_invariant/reinstate_conserves_trust_cash
        """
        trust, cancelled = self._cancel_then()
        # Sanity: cancel removed money from trust.
        mid = get_success_data(api_client.get_trust_account(trust["id"], TRUST()))
        assert mid["balance_cents"] == 5_000_000 - 604932, mid
        get_success_data(
            api_client.reinstate_policy(
                cancelled["id"], {"expected_policy_version": cancelled["version"]}, MANAGER()
            )
        )
        after = get_success_data(api_client.get_trust_account(trust["id"], TRUST()))
        assert after["balance_cents"] == 5_000_000, after

    def test_reinstate_zeroes_return_premium(self, api):
        """PRD §3.7: "The policy's `return_premium_cents` and `earned_premium_cents` are both
        reset to 0."

        Design: Difficulty/compensating_invariant/reinstate_conserves_trust_cash
        """
        trust, cancelled = self._cancel_then()
        data = get_success_data(
            api_client.reinstate_policy(
                cancelled["id"], {"expected_policy_version": cancelled["version"]}, MANAGER()
            )
        )
        assert data["return_premium_cents"] == 0, data


# ===========================================================================
# Rule: compensating_invariant / reinstate_conserves_producer_commission_accrual
# ===========================================================================
class TestReinstateConservesAccrual:
    def _setup_cancelled_with_open_statement(self):
        """ACTIVE policy annual 1.2M, product new_business 0.20, single WRITING split 1.0,
        activated 2026-02-01; OPEN statement spanning activation and the later cancel."""
        set_clock("2026-02-01T00:00:00Z")
        open_trust_account_with_balance(5_000_000, state_code="CA")
        ctx = setup_compliant_writer(
            product_overrides={"new_business_commission_pct": 0.20, "cancellation_basis": "PRO_RATA"}
        )
        s = setup_active_policy(
            ctx=ctx,
            policy_overrides={
                "annual_premium_cents": 1_200_000,
                "effective_date": "2026-02-01T00:00:00Z",
                "expiration_date": "2027-02-01T00:00:00Z",
            },
        )
        policy = s["policy"]
        stmt = open_statement(ctx["producer"]["id"], "2026-01-01T00:00:00Z", "2026-12-01T00:00:00Z")
        set_clock("2026-07-01T00:00:00Z")
        cancelled = get_success_data(
            api_client.cancel_policy(
                policy["id"],
                {
                    "expected_policy_version": policy["version"],
                    "cancellation_date": "2026-07-01T00:00:00Z",
                    "cancellation_reason": "INSURED_REQUEST",
                },
                MANAGER(),
            )
        )
        return ctx, stmt, cancelled

    def test_open_statement_net_drops_after_cancel(self, api):
        """PRD §3.10: "The `chargeback_cents` is the sum, over the producer's splits on
        policies that were cancelled within the period (their `cancellation_date` falling at
        or after `period_start` and strictly before `period_end`), of each split's accrual
        multiplied by the policy's return-premium fraction — that is, multiplied by
        `return_premium_cents` divided by `annual_premium_cents` — with each such per-policy
        clawback rounded half-up to whole cents before summation."

        Design: Difficulty/compensating_invariant/reinstate_conserves_producer_commission_accrual
        """
        ctx, stmt, cancelled = self._setup_cancelled_with_open_statement()
        after_cancel = get_statement(stmt["id"])
        # gross 264000; return_premium for 2026-02-01..2027-02-01 (365d) cancelled 2026-07-01
        # (215 unearned days) = round(1200000*215/365) = 706849; chargeback =
        # round(264000 * 706849/1200000) = 155507; net = 264000 - 155507 = 108493.
        assert after_cancel["net_payable_cents"] == 108493, after_cancel

    def test_reinstate_restores_net_to_pre_cancel(self, api):
        """PRD §3.7: "The prior commission chargeback is reversed, restoring the producer's
        accrual to its pre-cancellation value."

        Design: Difficulty/compensating_invariant/reinstate_conserves_producer_commission_accrual
        """
        ctx, stmt, cancelled = self._setup_cancelled_with_open_statement()
        get_success_data(
            api_client.reinstate_policy(
                cancelled["id"], {"expected_policy_version": cancelled["version"]}, MANAGER()
            )
        )
        after_reinstate = get_statement(stmt["id"])
        assert after_reinstate["net_payable_cents"] == 264000, after_reinstate


def _list_ledger_for_policy(policy_id):
    resp = api_client.list_trust_ledger_entries(TRUST(), params={"policy_id": policy_id})
    body = resp.json()
    return body["data"], body["meta"]
