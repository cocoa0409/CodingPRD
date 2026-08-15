"""Subscription lifecycle: entry state, cancel, terminal lockdown, pause/resume
cycles, and the account-level live-subscription invariant."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_subscription,
    cancel_subscription,
    cancel_subscription_payload,
    create_plan_payload,
    create_subscription,
    get_account,
    get_subscription,
    pause_subscription,
    pause_subscription_payload,
    resume_subscription,
    set_clock,
    setup_account_with_subscription,
    setup_cancelled_subscription,
    setup_paused_subscription,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]


class TestEntryState:

    def test_subscription_with_trial_starts_trialing(self):
        """PRD section 3.2: "When `trial_days` is greater than zero the
        subscription begins `TRIALING` with `trial_end_utc` set to the
        trial's expiry and a `TRIAL_START` billing event posted".

        Design: Corner/state_machines/subscription_initial_state_trialing_when_trial_days_positive
        """
        plan, account, sub = setup_account_with_subscription(
            plan_overrides={"plan_code": "TRIAL", "trial_days": 14,
                            "monthly_price_cents": 1000, "max_profiles": 1,
                            "max_households": 1}
        )
        assert_subscription(sub)
        assert sub["subscription_status"] == "TRIALING"
        # trial_end_utc is the trial's expiry: 2026-08-01 + 14 days.
        # Compare as instants — PRD does not pin the fractional-digit format
        # of trial_end_utc, only that it records the trial's expiry.
        from datetime import datetime, timezone
        def _parse(s):
            v = s[:-1] + "+00:00" if s.endswith("Z") else s
            return datetime.fromisoformat(v).astimezone(timezone.utc)
        assert _parse(sub["trial_end_utc"]) == _parse("2026-08-15T00:00:00Z"), (
            f"trial_end_utc must be 14 days after signup at the default "
            f"logical clock, got {sub['trial_end_utc']}"
        )
        assert sub["billing_state"] == "CURRENT"


class TestCancellation:

    def test_cancel_transitions_and_records_reason(self):
        """PRD section 3.6: "From `ACTIVE` or `PAUSED` the subscription moves
        to `CANCELLED`".
        PRD section 3.6: "a subscriber's own cancellation records
        `USER_REQUESTED`".

        Design: Corner/endpoints/cancel_action_endpoint
        """
        _plan, _account, sub = setup_account_with_subscription()
        resp = api_client.cancel_subscription(
            sub["subscription_id"], cancel_subscription_payload(), ADMIN
        )
        data = validate_success(resp, expected_status=200)
        assert_subscription(data)
        assert data["subscription_status"] == "CANCELLED"
        assert data["cancel_reason"] == "USER_REQUESTED"

    def test_second_cancel_returns_invalid_state(self):
        """PRD section 2.8: "the target resource must be in a state from which
        the requested transition is allowed; this guards every state-transition
        endpoint (cancel, pause, resume, recover, accept, decline, reconcile,
        and the like) and surfaces `ERR_INVALID_STATE` (409)."
        PRD section 3.6: "All of `CANCELLED` and `EXPIRED` are terminal."

        Design: Corner/state_machines/cancel_from_already_cancelled_returns_invalid_state
        """
        _plan, _account, cancelled = setup_cancelled_subscription()
        resp = api_client.cancel_subscription(
            cancelled["subscription_id"], cancel_subscription_payload(), ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_pause_on_cancelled_subscription_returns_invalid_state(self):
        """PRD section 3.6: "All of `CANCELLED` and `EXPIRED` are terminal."
        PRD section 2.8: "the target resource must be in a state from which
        the requested transition is allowed; this guards every state-transition
        endpoint (cancel, pause, resume, recover, accept, decline, reconcile,
        and the like) and surfaces `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/terminal_state_lockdown_on_cancelled_subscription
        """
        _plan, _account, cancelled = setup_cancelled_subscription()
        resp = api_client.pause_subscription(
            cancelled["subscription_id"], pause_subscription_payload(), ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_cancel_clears_account_active_subscription_pointer(self):
        """PRD section 3.2: "A new account stands immediately in `ACTIVE`
        status, with `active_subscription_id` null until a subscription
        exists."
        PRD section 3.6: "From `ACTIVE` or `PAUSED` the subscription moves to
        `CANCELLED`".

        Design: Difficulty/compensating_invariant/cancel_restores_account_active_subscription_invariant
        """
        plan, account, sub = setup_account_with_subscription()
        after_create = get_account(account["account_id"])
        assert after_create["active_subscription_id"] == sub["subscription_id"], (
            "creation sets the account's active_subscription_id (PRD section 3.2: "
            "'the account's `active_subscription_id` is set to the new subscription')"
        )
        cancel_subscription(sub["subscription_id"])
        after_cancel = get_account(account["account_id"])
        # The account again has no live subscription, so the pointer returns
        # to its initial value: null.
        assert after_cancel["active_subscription_id"] is None, (
            f"after cancel no live subscription stands, so "
            f"active_subscription_id must be null, got "
            f"{after_cancel['active_subscription_id']}"
        )

    def test_create_cancel_create_restores_single_live_subscription(self):
        """PRD section 3.2: "An account may hold at most one live subscription:
        attempting to create a second while one stands in `TRIALING`,
        `ACTIVE`, `PAST_DUE`, or `PAUSED` is rejected with
        `ERR_DUPLICATE_ACTIVE_SUBSCRIPTION`."
        PRD section 3.6: "From `ACTIVE` or `PAUSED` the subscription moves to
        `CANCELLED`".

        Design: Difficulty/compensating_invariant/cancel_restores_account_active_subscription_invariant
        """
        plan, account, sub = setup_account_with_subscription()
        cancel_subscription(sub["subscription_id"])
        # With the first subscription CANCELLED (no longer live), a fresh
        # subscription may open — the conserved count of live subscriptions
        # returned to zero, so +1 is legal again.
        replacement = create_subscription(account["account_id"], plan["plan_id"])
        assert_subscription(replacement)
        assert replacement["subscription_status"] == "ACTIVE"
        account_now = get_account(account["account_id"])
        assert account_now["active_subscription_id"] == \
            replacement["subscription_id"]


class TestPauseResumeCycle:

    def test_pause_then_resume_returns_to_active(self):
        """PRD section 3.5: "A direct pause takes a `duration_months` argument
        and moves the subscription `ACTIVE → PAUSED`, setting
        `paused_until_utc` to the resume instant — the current logical time
        plus the pause duration — and posting a `PRORATION_CREDIT` event for
        the unused days of the current period."
        PRD section 3.5: "Resumption — whether automatic when the logical clock
        reaches `paused_until_utc` or early at the subscriber's request —
        returns the subscription `PAUSED → ACTIVE`, clears `paused_until_utc`
        to null, and posts a `CHARGE` for the prorated remaining period."

        Design: Difficulty/non_linear_state_machine/subscription_pause_resume_cycle
        """
        _plan, _account, sub = setup_account_with_subscription()
        paused = pause_subscription(sub["subscription_id"], duration_months=1)
        assert paused["subscription_status"] == "PAUSED"
        assert paused["paused_until_utc"] is not None
        resumed = resume_subscription(sub["subscription_id"])
        assert resumed["subscription_status"] == "ACTIVE", (
            f"subscription must cycle ACTIVE → PAUSED → ACTIVE, got "
            f"{resumed['subscription_status']}"
        )
        assert resumed["paused_until_utc"] is None, (
            "resumption clears paused_until_utc to null"
        )

    def test_paused_subscription_can_be_cancelled(self):
        """PRD section 3.6: "From `ACTIVE` or `PAUSED` the subscription moves
        to `CANCELLED`; cancelling from `ACTIVE` additionally flips any save
        offer still `PRESENTED` on the subscription to `SUPERSEDED` and clears
        any scheduled `pending_plan_id`. Cancelling from `PAUSED` records
        `USER_REQUESTED`."

        Design: Difficulty/non_linear_state_machine/subscription_pause_resume_cycle
        """
        _plan, _account, paused = setup_paused_subscription()
        assert paused["subscription_status"] == "PAUSED"
        resp = api_client.cancel_subscription(
            paused["subscription_id"], cancel_subscription_payload(), ADMIN
        )
        data = validate_success(resp, expected_status=200)
        assert data["subscription_status"] == "CANCELLED"
        assert data["cancel_reason"] == "USER_REQUESTED"


class TestPauseCooldown:

    def test_second_pause_within_trailing_12_months_rejected(self):
        """PRD section 3.5: "Direct pauses carry a cooldown: an account that
        has already paused within the trailing 12 months is refused with
        `ERR_PAUSE_NOT_ALLOWED`".

        Design: Difficulty/resource_temporal_overlap/pause_cooldown_12_month_rolling_window
        """
        set_clock("2026-01-01T00:00:00Z")
        plan, account, sub = setup_account_with_subscription(
            at="2026-01-01T00:00:00Z"
        )
        set_clock("2026-01-15T00:00:00Z")
        pause_subscription(sub["subscription_id"], duration_months=1)
        # Let the pause lapse via the sweep at paused_until_utc.
        from test_helpers import run_sweeps
        run_sweeps("2026-02-15T00:00:00Z")
        assert get_subscription(sub["subscription_id"])["subscription_status"] == \
            "ACTIVE"
        set_clock("2026-08-01T00:00:00Z")
        # The prior pause (January) sits inside the trailing 12-month window
        # even though its interval does not overlap the new request.
        resp = api_client.pause_subscription(
            sub["subscription_id"], pause_subscription_payload(duration_months=1),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_PAUSE_NOT_ALLOWED)

    def test_pause_after_cooldown_window_elapsed_succeeds(self):
        """PRD section 3.5: "Direct pauses carry a cooldown: an account that
        has already paused within the trailing 12 months is refused with
        `ERR_PAUSE_NOT_ALLOWED`".

        Design: Difficulty/resource_temporal_overlap/pause_cooldown_12_month_rolling_window
        """
        set_clock("2025-08-01T00:00:00Z")
        plan, account, sub = setup_account_with_subscription(
            at="2025-08-01T00:00:00Z"
        )
        pause_subscription(sub["subscription_id"], duration_months=1)
        from test_helpers import run_sweeps
        run_sweeps("2025-09-01T00:00:00Z")
        assert get_subscription(sub["subscription_id"])["subscription_status"] == \
            "ACTIVE"
        # More than 12 months after the prior pause — the window is clear.
        set_clock("2026-08-02T00:00:00Z")
        resp = api_client.pause_subscription(
            sub["subscription_id"], pause_subscription_payload(duration_months=1),
            ADMIN,
        )
        data = validate_success(resp, expected_status=200)
        assert data["subscription_status"] == "PAUSED", (
            "a pause more than 12 months after the previous one is outside "
            "the trailing cooldown window and must be allowed"
        )
