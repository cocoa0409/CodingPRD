"""Price change notices, grandfathering carryover, scheduled effectiveness,
signup attribution, and retention sweeps."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_price_change_notice,
    assert_signup_attribution,
    cancel_subscription,
    create_price_change_notice,
    create_price_change_notice_payload,
    create_subscription,
    get_plan,
    get_signup_attribution,
    get_subscription,
    run_sweeps,
    set_clock,
    setup_account_with_subscription,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]


class TestNoticeLengthValidation:

    def test_effective_under_30_days_rejected(self):
        """PRD section 3.7: "because subscribers deserve warning, an
        `effective_at_utc` less than 30 days after the announcement is
        rejected with `ERR_PRICE_CHANGE_NOTICE_TOO_SHORT`."

        Design: Corner/validations/price_change_notice_too_short_returns_error
        """
        set_clock("2026-08-01T00:00:00Z")
        from test_helpers import create_plan
        plan = create_plan(at="2026-08-01T00:00:00Z")
        # 2026-08-15 is only 14 days after the 2026-08-01 announcement.
        resp = api_client.create_price_change_notice(
            create_price_change_notice_payload(
                plan["plan_id"], old_price_cents=3000, new_price_cents=4000,
                effective_at_utc="2026-08-15T00:00:00Z",
                grandfather_period_months=0,
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_PRICE_CHANGE_NOTICE_TOO_SHORT)


class TestScheduledDeferredAction:

    def test_cancel_pending_notice_prevents_price_change(self):
        """PRD section 3.7: "A notice can be withdrawn while it is still
        pending — cancellation moves it `ANNOUNCED → CANCELLED` — but only
        before its effective instant; cancelling at or after effectiveness is
        rejected with `ERR_OFFER_EXPIRED`."

        Design: Corner/cross_cutting_complexity_layers/scheduled_deferred_action_price_change
        """
        from test_helpers import create_plan
        plan = create_plan(at="2026-08-01T00:00:00Z",
                           plan_code="BASIC", monthly_price_cents=3000)
        notice = create_price_change_notice(
            plan["plan_id"], old_price_cents=3000, new_price_cents=4000,
            effective_at_utc="2026-09-15T00:00:00Z",
            grandfather_period_months=0,
        )
        resp = api_client.cancel_price_change_notice(
            notice["price_change_notice_id"], ADMIN
        )
        data = validate_success(resp, expected_status=200)
        assert data["notice_status"] == "CANCELLED"
        # Even after the would-be effective instant passes, the cancelled
        # notice never propagates to the plan.
        run_sweeps("2026-09-16T00:00:00Z")
        plan_now = get_plan(plan["plan_id"])
        assert plan_now["monthly_price_cents"] == 3000, (
            f"cancelling the notice before effectiveness must prevent the "
            f"price change, got {plan_now['monthly_price_cents']}"
        )


class TestGrandfatheringCarryover:
    """Mode (c) pinned evaluation order: snapshot the old price, compute whole
    months elapsed, decide the new lock, write, then emit the event (PRD
    section 3.7)."""

    def test_notice_effectiveness_updates_plan_and_locks_old_price(self):
        """PRD section 3.7: "The plan's `monthly_price_cents` becomes the
        `new_price_cents`. For each `TRIALING`, `ACTIVE`, or `PAST_DUE`
        subscription on the plan the carryover rule applies: a subscription
        holding no `grandfathered_price_cents` lock gains one equal to the
        notice's `old_price_cents` when `grandfather_period_months` is
        greater than zero, and otherwise pays the new price with no lock".

        Design: Difficulty/combinatorial_formula/grandfathered_price_carryover_circular_order
        """
        from test_helpers import create_account, create_plan
        set_clock("2026-08-01T00:00:00Z")
        plan = create_plan(at="2026-08-01T00:00:00Z", plan_code="PREMIUM",
                           tier="PREMIUM", monthly_price_cents=6000,
                           max_profiles=5, max_households=2)
        acc4 = create_account(at="2026-08-01T00:00:00Z", email="a4@x.com")
        sub4 = create_subscription(acc4["account_id"], plan["plan_id"])
        create_price_change_notice(
            plan["plan_id"], old_price_cents=6000, new_price_cents=7000,
            effective_at_utc="2026-09-01T00:00:00Z",
            grandfather_period_months=6,
        )
        run_sweeps("2026-09-01T00:00:00Z")
        plan_now = get_plan(plan["plan_id"])
        assert plan_now["monthly_price_cents"] == 7000, (
            f"effectiveness applies the new price to the plan, got "
            f"{plan_now['monthly_price_cents']}"
        )
        sub4_now = get_subscription(sub4["subscription_id"])
        assert sub4_now["grandfathered_price_cents"] == 6000, (
            f"a subscription with no prior lock gains a lock equal to the "
            f"notice's old price when grandfather_period_months > 0, got "
            f"{sub4_now['grandfathered_price_cents']}"
        )

    def test_carryover_applies_identically_to_two_unlocked_subscriptions(self):
        """PRD section 3.7: "When the logical clock reaches `effective_at_utc`,
        the sweep moves the notice `ANNOUNCED → EFFECTIVE` and the change
        propagates in a pinned order: the old price is snapshotted first, then
        the months elapsed since announcement are computed as the number of
        whole 30-day months between `announced_at_utc` and `effective_at_utc`,
        then each subscription's new lock is decided, written, and only then
        is a `PRICE_CHANGE_APPLIED` billing event emitted for every affected
        subscription."

        Design: Difficulty/combinatorial_formula/grandfathered_price_carryover_circular_order
        """
        from test_helpers import create_account, create_plan
        set_clock("2026-08-01T00:00:00Z")
        plan = create_plan(at="2026-08-01T00:00:00Z", plan_code="PREMIUM",
                           tier="PREMIUM", monthly_price_cents=6000,
                           max_profiles=5, max_households=2)
        acc4 = create_account(at="2026-08-01T00:00:00Z", email="a4@x.com")
        acc5 = create_account(at="2026-08-01T00:00:00Z", email="a5@x.com")
        sub4 = create_subscription(acc4["account_id"], plan["plan_id"])
        sub5 = create_subscription(acc5["account_id"], plan["plan_id"])
        create_price_change_notice(
            plan["plan_id"], old_price_cents=6000, new_price_cents=7000,
            effective_at_utc="2026-09-01T00:00:00Z",
            grandfather_period_months=6,
        )
        run_sweeps("2026-09-01T00:00:00Z")
        # Two subscriptions with identical plan, notice, and (empty) lock
        # state receive identical locks — the pinned order makes the result
        # well-defined regardless of which subscription is processed first.
        for sub in (sub4, sub5):
            current = get_subscription(sub["subscription_id"])
            assert current["grandfathered_price_cents"] == 6000, (
                f"both unlocked subscriptions take the same new lock at the "
                f"old price, got {current['grandfathered_price_cents']}"
            )


class TestSignupAttribution:

    def test_attribution_row_created_with_cohort_month(self):
        """PRD section 3.2: "Every signup also writes a `SignupAttribution`
        row keyed to the new subscription through the subscription's
        `signup_attribution_id`. The attribution captures the `content_id` —
        the empty string when the signup was organic rather than
        content-driven — and a `channel` of `ORGANIC`, `SEARCH`, `SOCIAL`,
        `AD`, `EMAIL`, or `REFERRAL`. Its `cohort_month` is the `YYYY-MM`
        month derived from the attribution row's own `created_at`."

        Design: Corner/endpoints/signup_attribution_created_on_subscribe
        """
        plan, account, sub = setup_account_with_subscription(
            subscription_overrides={"content_id": "movie-123", "channel": "AD"}
        )
        attribution_id = sub["signup_attribution_id"]
        assert attribution_id, "the subscription must key its attribution row"
        attribution = get_signup_attribution(attribution_id)
        assert_signup_attribution(attribution)
        assert attribution["cohort_month"] == "2026-08", (
            f"signup at the default logical clock lands in cohort 2026-08, "
            f"got {attribution['cohort_month']}"
        )
        assert attribution["content_id"] == "movie-123"
        assert attribution["channel"] == "AD"
        assert attribution["subscription_id"] == sub["subscription_id"]
        assert attribution["account_id"] == account["account_id"]


class TestRetentionSweep:

    def test_day_30_retention_flags(self):
        """PRD section 3.2: "what changes over time are the two retention
        flags, `retained_at_day_30` and `retained_at_day_90`, which the
        day-30 and day-90 retention sweeps recompute. A flag reads true
        exactly when the linked subscription's status is one of `TRIALING`,
        `ACTIVE`, `PAST_DUE`, or `PAUSED` at the instant precisely N days
        after the attribution's creation; a subscription that is `CANCELLED`
        or `EXPIRED` at that day reads false, and a subscription still live
        at the exact boundary instant counts as retained."

        Design: Corner/calculations/retention_sweep_sets_retained_flags
        """
        from test_helpers import create_account, create_plan
        set_clock("2026-08-01T00:00:00Z")
        plan = create_plan(at="2026-08-01T00:00:00Z", plan_code="BASIC",
                           monthly_price_cents=3000)
        acc1 = create_account(at="2026-08-01T00:00:00Z", email="r1@x.com")
        acc2 = create_account(at="2026-08-01T00:00:00Z", email="r2@x.com")
        sub1 = create_subscription(acc1["account_id"], plan["plan_id"])
        sub2 = create_subscription(acc2["account_id"], plan["plan_id"])
        # Cancel sub2 five days in — well before the day-30 measurement.
        set_clock("2026-08-06T00:00:00Z")
        cancel_subscription(sub2["subscription_id"])
        # Run the sweep past the day+30 boundary (2026-08-31).
        run_sweeps("2026-08-31T00:00:00Z")
        attr1 = get_signup_attribution(sub1["signup_attribution_id"])
        attr2 = get_signup_attribution(sub2["signup_attribution_id"])
        assert attr1["retained_at_day_30"] is True, (
            "sub1 is still ACTIVE at day+30, so it reads retained"
        )
        assert attr2["retained_at_day_30"] is False, (
            "sub2 is CANCELLED before day+30, so it reads not retained"
        )
