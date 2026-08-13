"""Renewal failures, the parallel billing axis, dunning exhaustion, and the
depth-3 cascade from subscription expiry down to profiles."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    create_account,
    create_billing_event_payload,
    get_account,
    get_profile,
    get_subscription,
    post_charge_failed,
    run_sweeps,
    set_clock,
    setup_account_with_profiles,
    setup_account_with_subscription,
    setup_dunning_exhausted,
    setup_subscription_in_dunning,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]


class TestParallelBillingAxis:

    def test_failed_renewal_moves_both_axes(self):
        """PRD section 3.4: "When a renewal charge fails on an `ACTIVE`
        subscription whose `billing_state` was `CURRENT`, the subscription
        falls `ACTIVE → PAST_DUE` and, in the same motion, `billing_state`
        flips to `DUNNING`, `dunning_attempt_count` is set to 1, and a
        `CHARGE_FAILED` event is posted to the ledger."

        Design: Difficulty/non_linear_state_machine/subscription_parallel_billing_state_dimension
        """
        _plan, account, sub = setup_account_with_subscription()
        set_clock("2026-09-01T00:00:00Z")
        post_charge_failed(account["account_id"], sub["subscription_id"], "1")
        run_sweeps("2026-09-01T00:00:00Z")
        current = get_subscription(sub["subscription_id"])
        assert current["subscription_status"] == "PAST_DUE", (
            f"subscriber-facing axis must fall to PAST_DUE, got "
            f"{current['subscription_status']}"
        )
        assert current["billing_state"] == "DUNNING", (
            f"billing axis must flip to DUNNING in the same motion, got "
            f"{current['billing_state']}"
        )

    def test_failed_renewal_sets_dunning_attempt_count_to_one(self):
        """PRD section 3.4: "When a renewal charge fails on an `ACTIVE`
        subscription whose `billing_state` was `CURRENT`, the subscription
        falls `ACTIVE → PAST_DUE` and, in the same motion, `billing_state`
        flips to `DUNNING`, `dunning_attempt_count` is set to 1, and a
        `CHARGE_FAILED` event is posted to the ledger."

        Design: Difficulty/non_linear_state_machine/subscription_parallel_billing_state_dimension
        """
        _plan, account, sub = setup_account_with_subscription()
        assert sub["billing_state"] == "CURRENT"
        assert sub["dunning_attempt_count"] == 0
        set_clock("2026-09-01T00:00:00Z")
        post_charge_failed(account["account_id"], sub["subscription_id"], "1")
        run_sweeps("2026-09-01T00:00:00Z")
        current = get_subscription(sub["subscription_id"])
        assert current["dunning_attempt_count"] == 1, (
            f"first failure must set dunning_attempt_count to 1, got "
            f"{current['dunning_attempt_count']}"
        )


class TestDunningExhaustion:

    def test_fifth_failure_expires_subscription(self):
        """PRD section 3.4: "Once `dunning_attempt_count` reaches five, the
        subscription transitions `PAST_DUE → EXPIRED`, its `cancel_reason` is
        set to `PAYMENT_FAILED`, the unpaid amount is added to the account's
        `outstanding_balance_cents`, and the owning account is automatically
        moved to `SUSPENDED`".

        Design: Difficulty/transitive_cascade/dunning_exhaustion_cascade_to_account_and_profiles
        """
        plan, account, sub, _profiles = setup_dunning_exhausted()
        current = get_subscription(sub["subscription_id"])
        assert current["subscription_status"] == "EXPIRED", (
            f"the fifth failed attempt must expire the subscription, got "
            f"{current['subscription_status']}"
        )
        assert current["cancel_reason"] == "PAYMENT_FAILED"
        assert current["dunning_attempt_count"] == 5
        account_now = get_account(account["account_id"])
        assert account_now["account_status"] == "SUSPENDED", (
            "exhaustion cascades: the owning account is automatically moved "
            "to SUSPENDED"
        )

    def test_dunning_exhaustion_cascades_to_profiles(self):
        """PRD section 2.10: "When an account transitions to `SUSPENDED` —
        whether manually or because dunning exhausted on its subscription —
        every profile on the account becomes `DEACTIVATED`."
        PRD section 3.4: "the owning account is automatically moved to
        `SUSPENDED` — the automatic suspension is precisely the case of a
        linked subscription expiring with `cancel_reason` `PAYMENT_FAILED` —
        which in turn deactivates every profile on the account per §2.10."

        Design: Difficulty/transitive_cascade/dunning_exhaustion_cascade_to_account_and_profiles
        """
        plan, account, sub, profiles = setup_dunning_exhausted(num_profiles=2)
        for profile in profiles:
            current = get_profile(profile["profile_id"])
            assert current["profile_status"] == "DEACTIVATED", (
                f"depth-3 cascade must deactivate every profile, got "
                f"{current['profile_status']} for {profile['profile_id']}"
            )
        account_now = get_account(account["account_id"])
        assert account_now["account_status"] == "SUSPENDED"
        assert account_now["outstanding_balance_cents"] > 0, (
            "the unpaid amount is added to the account's "
            "outstanding_balance_cents"
        )

    def test_dunning_backoff_max_attempts_constant(self):
        """PRD section 3.4: "While `dunning_attempt_count` remains below five,
        each failure schedules the next retry at the offset corresponding to
        the current attempt count".
        PRD section 3.4: "Once `dunning_attempt_count` reaches five, the
        subscription transitions `PAST_DUE → EXPIRED`".

        Design: Corner/calculations/dunning_backoff_constants_applied
        """
        plan, account, sub = setup_account_with_subscription()
        set_clock("2026-09-01T00:00:00Z")
        for i in range(5):
            post_charge_failed(account["account_id"], sub["subscription_id"],
                               f"f{i+1}")
        run_sweeps("2026-09-02T00:00:00Z")
        current = get_subscription(sub["subscription_id"])
        assert current["subscription_status"] == "EXPIRED"
        assert current["dunning_attempt_count"] == 5, (
            f"MAX_ATTEMPTS is five: the fifth failure is the exhaustion "
            f"boundary, got {current['dunning_attempt_count']}"
        )


class TestFullCascadeChain:

    def test_dunning_cascade_full_chain(self):
        """PRD section 3.4: "Once `dunning_attempt_count` reaches five, the
        subscription transitions `PAST_DUE → EXPIRED`, its `cancel_reason` is
        set to `PAYMENT_FAILED`, the unpaid amount is added to the account's
        `outstanding_balance_cents`, and the owning account is automatically
        moved to `SUSPENDED` — the automatic suspension is precisely the case
        of a linked subscription expiring with `cancel_reason`
        `PAYMENT_FAILED` — which in turn deactivates every profile on the
        account per §2.10."

        Design: Corner/cross_cutting_complexity_layers/cascading_side_effects_full_chain
        """
        plan, account, sub, profiles = setup_dunning_exhausted(num_profiles=2)
        assert get_subscription(sub["subscription_id"])["subscription_status"] == \
            "EXPIRED"
        assert get_account(account["account_id"])["account_status"] == "SUSPENDED"
        for profile in profiles:
            assert get_profile(profile["profile_id"])["profile_status"] == \
                "DEACTIVATED"


class TestAccountSuspensionGuards:

    def test_manual_suspend_cascades_to_profiles(self):
        """PRD section 2.10: "When an account transitions to `SUSPENDED` —
        whether manually or because dunning exhausted on its subscription —
        every profile on the account becomes `DEACTIVATED`."
        PRD section 3.4: "A `PlatformAdmin` may also suspend an account
        manually at any time, with no precondition beyond the account being
        `ACTIVE`; the profile cascade is identical."

        Design: Corner/state_machines/cascade_account_suspend_deactivates_profiles
        """
        plan, account, sub, profiles = setup_account_with_profiles(
            num_profiles=2,
            plan_overrides={"max_profiles": 5, "max_households": 2},
        )
        resp = api_client.suspend_account(account["account_id"], ADMIN)
        data = validate_success(resp, expected_status=200)
        assert data["account_status"] == "SUSPENDED"
        for profile in profiles:
            current = get_profile(profile["profile_id"])
            assert current["profile_status"] == "DEACTIVATED", (
                f"manual suspension must cascade to profiles, got "
                f"{current['profile_status']}"
            )

    def test_unsuspend_with_outstanding_balance_rejected(self):
        """PRD section 3.4: "Unsuspension moves the account `SUSPENDED →
        ACTIVE` and is available to both `PlatformAdmin` and `SupportAgent`,
        but only while `outstanding_balance_cents` is zero — any residual
        balance rejects the request with `ERR_OUTSTANDING_BALANCE`."

        Design: Corner/state_machines/guarded_transition_unsuspend_requires_zero_balance
        """
        plan, account, sub = setup_account_with_subscription()
        api_client.suspend_account(account["account_id"], ADMIN)
        # Post an unsettled CHARGE_FAILED so the computed outstanding balance
        # is non-zero.
        resp = api_client.create_billing_event(
            create_billing_event_payload(
                account["account_id"], sub["subscription_id"],
                event_type="CHARGE_FAILED", amount_cents=3000,
                external_reference="x", notes="unpaid",
            ),
            ADMIN,
        )
        validate_success(resp, expected_status=201)
        resp = api_client.unsuspend_account(account["account_id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_OUTSTANDING_BALANCE)


class TestImmediateConsistency:

    def test_cancel_effects_visible_immediately(self):
        """PRD section 3.6: "From `ACTIVE` or `PAUSED` the subscription moves
        to `CANCELLED`".
        PRD section 3.2: "A new account stands immediately in `ACTIVE` status,
        with `active_subscription_id` null until a subscription exists."

        Design: Corner/consistency_model/immediate_consistency_on_cancel
        """
        _plan, account, sub = setup_account_with_subscription()
        resp = api_client.cancel_subscription(
            sub["subscription_id"],
            {"cancel_reason": "USER_REQUESTED"},
            ADMIN,
        )
        data = validate_success(resp, expected_status=200)
        assert data["subscription_status"] == "CANCELLED", (
            "the cancel response itself must already show CANCELLED — "
            "consistency is immediate, with no read lag"
        )
        account_now = get_account(account["account_id"])
        assert account_now["active_subscription_id"] is None, (
            "a follow-up read in the same instant shows "
            "active_subscription_id already null"
        )
