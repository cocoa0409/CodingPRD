"""Subscription billing, retries, grace, and reinstatement (PRD §3.2, §3.3)."""

import pytest

from test_helpers import (
    LATE_FEE_PCT_BY_STATE,
    TEST_PLAN_BASE_PRICE_CENTS,
    TEST_USERS,
    assert_account_posture_invariant,
    assert_payment_attempt,
    assert_subscription,
    create_payment_attempt_payload,
    create_subscription_for_member,
    get_member_fresh,
    get_subscription_fresh,
    make_member_headers,
    reach_subscription_delinquent,
    reach_subscription_grace,
    reach_subscription_past_due,
    register_member,
    setup_active_member_with_subscription,
    submit_payment_attempt,
    validate_error,
    validate_success,
)


class TestActivation:

    def test_subscription_starts_pending_until_first_success(self, api):
        """PRD §3.2: "At creation the subscription enters status PENDING_ACTIVATION."
        and "Activation occurs when the first payment attempt for the subscription
        resolves to a SUCCESS outcome. At that moment the subscription transitions
        from PENDING_ACTIVATION to ACTIVE..."

        Claim: a new subscription is PENDING_ACTIVATION; a SUCCESS first attempt
        flips it to ACTIVE.
        """
        member = register_member(state_code="CA")
        sub = create_subscription_for_member(member, plan="PLUS", billing_cycle="MONTHLY")
        assert sub["status"] == "PENDING_ACTIVATION", (
            f"new subscription must be PENDING_ACTIVATION, got {sub['status']}"
        )
        attempt = submit_payment_attempt(member, sub, outcome="SUCCESS")
        assert_payment_attempt(attempt)
        assert attempt["attempt_number"] == 1
        active = get_subscription_fresh(member["id"], sub["id"])
        assert active["status"] == "ACTIVE"
        # PRD §3.2: current_period_start and current_period_end must be set after activation.
        assert active["current_period_start"] is not None
        assert active["current_period_end"] is not None


class TestFailedFirstAttemptCascade:

    def test_failed_first_attempt_new_period_drives_past_due(self, api):
        """PRD §3.2: "A FAILED first attempt of a new period moves the subscription
        to PAST_DUE and cascades Member.billing_status to PAST_DUE as well; the
        derived account_posture recomputes to RESTRICTED, which blocks new bookings
        (waitlist joins are still permitted under RESTRICTED, as described in §2.6)."

        Claim: FAILED first attempt → Subscription.status=PAST_DUE,
        Member.billing_status=PAST_DUE, account_posture=RESTRICTED.
        """
        member, sub = setup_active_member_with_subscription(state_code="CA", plan="PLUS")
        sub = reach_subscription_past_due(member, sub)
        assert sub["status"] == "PAST_DUE"
        member = get_member_fresh(member["id"])
        assert member["billing_status"] == "PAST_DUE"
        assert member["account_posture"] == "RESTRICTED"
        assert_account_posture_invariant(member)


class TestRetryAndGrace:

    def test_retry_limit_drives_grace_with_state_pinned_penalty_CA(self, api):
        """PRD §3.2: "When that counter reaches three — the retry limit — the
        subscription advances from PAST_DUE to GRACE and Member.billing_status
        cascades to GRACE. The grace_period_end is computed as the present clock
        plus the grace-period day count configured for the member's state_code.
        Simultaneously a late-payment penalty is assessed against the member's
        wallet: a per-state percentage of the subscription's pinned base_price_cents
        (five percent for CA, eight percent for NY, three percent for TX) is
        rounded half up to whole cents and subtracted from Member.wallet_credit_cents."

        Claim: third FAILED attempt → GRACE; wallet debited by 5% of base_price_cents for CA.
        """
        member, sub = setup_active_member_with_subscription(state_code="CA", plan="PLUS")
        sub = reach_subscription_grace(member, sub)
        assert sub["status"] == "GRACE"
        assert sub["grace_period_end"] is not None
        member = get_member_fresh(member["id"])
        assert member["billing_status"] == "GRACE"
        expected_penalty_cents = round(sub["base_price_cents"] * 5 / 100)
        # wallet starts at 0 → expected = -penalty (PRD §3.2: "may go negative")
        assert member["wallet_credit_cents"] == -expected_penalty_cents, (
            f"PRD §3.2 CA late-fee 5%: expected wallet -{expected_penalty_cents}, "
            f"got {member['wallet_credit_cents']}"
        )

    def test_retry_limit_drives_grace_with_state_pinned_penalty_NY(self, api):
        """PRD §3.2: "a per-state percentage of the subscription's pinned
        base_price_cents (five percent for CA, eight percent for NY, three percent
        for TX) is rounded half up to whole cents and subtracted from
        Member.wallet_credit_cents."

        Claim: NY late-fee = 8% of base_price_cents.
        """
        member, sub = setup_active_member_with_subscription(state_code="NY", plan="PLUS")
        sub = reach_subscription_grace(member, sub)
        member = get_member_fresh(member["id"])
        expected_penalty_cents = round(sub["base_price_cents"] * 8 / 100)
        assert member["wallet_credit_cents"] == -expected_penalty_cents, (
            f"PRD §3.2 NY late-fee 8%: expected wallet -{expected_penalty_cents}, "
            f"got {member['wallet_credit_cents']}"
        )

    def test_retry_limit_drives_grace_with_state_pinned_penalty_TX(self, api):
        """PRD §3.2: "a per-state percentage of the subscription's pinned
        base_price_cents (five percent for CA, eight percent for NY, three percent
        for TX) is rounded half up to whole cents and subtracted from
        Member.wallet_credit_cents."

        Claim: TX late-fee = 3% of base_price_cents.
        """
        member, sub = setup_active_member_with_subscription(state_code="TX", plan="PLUS")
        sub = reach_subscription_grace(member, sub)
        member = get_member_fresh(member["id"])
        expected_penalty_cents = round(sub["base_price_cents"] * 3 / 100)
        assert member["wallet_credit_cents"] == -expected_penalty_cents


class TestDelinquencyCascade:

    def test_grace_end_crossing_drives_delinquent_and_frozen(self, api):
        """PRD §3.2: "If the clock advances past grace_period_end without any
        SUCCESS in the interval, the subscription transitions from GRACE to
        DELINQUENT. This cascades into Member.billing_status of DELINQUENT, which
        in turn drives Member.access_status to SUSPENDED and immediately afterward
        to FROZEN; account_posture resolves to FROZEN. Every future booking of this
        member in RESERVED or CONFIRMED is cancelled with the state-specific refund
        schedule."

        Claim: clock past grace_period_end → DELINQUENT, billing=DELINQUENT,
        access=FROZEN, posture=FROZEN.
        """
        member, sub = setup_active_member_with_subscription(state_code="CA", plan="PLUS")
        sub = reach_subscription_delinquent(member, sub)
        assert sub["status"] == "DELINQUENT"
        member = get_member_fresh(member["id"])
        assert member["billing_status"] == "DELINQUENT"
        assert member["access_status"] == "FROZEN"
        assert member["account_posture"] == "FROZEN"
        assert_account_posture_invariant(member)


class TestReinstated:

    def test_success_during_past_due_clears_to_reinstated(self, api):
        """PRD §3.2: "A SUCCESS payment recorded while a subscription is PAST_DUE
        or GRACE clears the storm without requiring delinquency: the subscription
        returns to ACTIVE, failed_payment_attempts resets to zero, grace_period_end
        becomes null, and Member.billing_status advances from PAST_DUE or GRACE to
        REINSTATED."

        Claim: SUCCESS while PAST_DUE → Subscription.status=ACTIVE,
        failed_payment_attempts=0, Member.billing_status=REINSTATED.
        """
        member, sub = setup_active_member_with_subscription(state_code="CA", plan="PLUS")
        sub = reach_subscription_past_due(member, sub)
        assert sub["status"] == "PAST_DUE"
        submit_payment_attempt(member, sub, outcome="SUCCESS")
        sub_after = get_subscription_fresh(member["id"], sub["id"])
        assert sub_after["status"] == "ACTIVE"
        assert sub_after["failed_payment_attempts"] == 0
        assert sub_after["grace_period_end"] is None
        member_after = get_member_fresh(member["id"])
        assert member_after["billing_status"] == "REINSTATED"

    def test_success_during_grace_clears_to_reinstated_grace_end_null(self, api):
        """PRD §3.2: "A SUCCESS payment recorded while a subscription is PAST_DUE
        or GRACE clears the storm without requiring delinquency: the subscription
        returns to ACTIVE, failed_payment_attempts resets to zero, grace_period_end
        becomes null..."

        Claim: SUCCESS while GRACE → ACTIVE with grace_period_end=null.
        """
        member, sub = setup_active_member_with_subscription(state_code="CA", plan="PLUS")
        sub = reach_subscription_grace(member, sub)
        assert sub["status"] == "GRACE"
        submit_payment_attempt(member, sub, outcome="SUCCESS")
        sub_after = get_subscription_fresh(member["id"], sub["id"])
        assert sub_after["status"] == "ACTIVE"
        assert sub_after["grace_period_end"] is None


class TestAmountMismatch:

    def test_client_supplied_amount_mismatch_rejected(self, api):
        """PRD §3.3: "the server independently recomputes the expected amount_cents
        from the subscription, the member's wallet, and any subscription-level
        coupon, and rejects the attempt with ERR_AMOUNT_MISMATCH and HTTP 422 if
        the client-supplied amount_cents (sent in the body or implied by the
        gateway record) disagrees with the server's calculation."

        Claim: a SUCCESS attempt carrying an obviously wrong amount_cents →
        ERR_AMOUNT_MISMATCH (422).
        """
        member = register_member(state_code="CA")
        sub = create_subscription_for_member(member, plan="PLUS", billing_cycle="MONTHLY")
        # Force a clearly wrong amount_cents (1 cent for a non-trivial plan).
        payload = create_payment_attempt_payload(outcome="SUCCESS", amount_cents=1)
        res = api.create_payment_attempt(
            member["id"], sub["id"], payload, TEST_USERS["billing_admin_headers"]
        )
        validate_error(res, "ERR_AMOUNT_MISMATCH")
