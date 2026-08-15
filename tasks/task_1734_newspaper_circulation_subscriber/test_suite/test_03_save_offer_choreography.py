"""Cancel / save-offer choreography and optimistic concurrency (PRD §3.5, §2.9)."""
from test_helpers import (
    REP,
    ApiErrorId,
    cancel_and_get_offer,
    create_active_subscription,
    create_plan,
    get_subscription,
    run_daily_cycle,
    set_clock,
    setup_cancel_pending,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSaveOfferAccept:
    def test_save_offer_accept_rescues_cancel_pending(self, api):
        """PRD §3.5: "From `ACTIVE` or `GRACE`, the subscription moves to
        `CANCEL_PENDING` rather than dying outright: the system auto-creates
        a save offer in `OFFERED` status with `origin` of `CANCEL_FLOW`, a
        `discount_pct` of 0.25, a `duration_weeks` of 8, and an `expires_at`
        seven days out, records the `cancel_reason` on the subscription, and
        increments the subscription's `version`."
        PRD §3.5: "Accepting flips the offer to `ACCEPTED`, writes
        `save_discount_pct` onto the subscription, sets `save_discount_until`
        to today plus the offer's duration in weeks times seven days (the
        discount applies to charges whose period starts strictly before that
        date), clears the `cancel_reason`, rescues a `CANCEL_PENDING`
        subscription back to `ACTIVE`, and increments the subscription's
        `version`."

        Design: Corner/state_machines/save_offer_accept_rescues_cancel_pending
        """
        ctx = setup_cancel_pending(
            start_date="2026-08-03", clock="2026-08-03T00:00:00Z"
        )
        subscription = ctx["subscription"]
        offer = ctx["offer"]

        assert subscription["billing_status"] == "CANCEL_PENDING"
        assert offer["status"] == "OFFERED"
        assert offer["origin"] == "CANCEL_FLOW"
        assert offer["discount_pct"] == 0.25
        assert offer["duration_weeks"] == 8
        assert offer["expires_at"] == "2026-08-10"

        accepted = validate_success(api.accept_save_offer(offer["id"], REP))
        assert accepted["status"] == "ACCEPTED"

        after = get_subscription(subscription["id"])
        assert after["billing_status"] == "ACTIVE"
        assert after["save_discount_pct"] == 0.25
        assert after["save_discount_until"] == "2026-09-28"  # 2026-08-03 + 8*7 days
        assert after.get("cancel_reason") is None

    def test_save_offer_accept_increments_subscription_version(self, api):
        """PRD §3.5: "Accepting flips the offer to `ACCEPTED`, writes
        `save_discount_pct` onto the subscription, sets `save_discount_until`
        to today plus the offer's duration in weeks times seven days (the
        discount applies to charges whose period starts strictly before that
        date), clears the `cancel_reason`, rescues a `CANCEL_PENDING`
        subscription back to `ACTIVE`, and increments the subscription's
        `version`."

        Design: Corner/state_machines/save_offer_accept_rescues_cancel_pending
        """
        ctx = setup_cancel_pending(
            start_date="2026-08-03", clock="2026-08-03T00:00:00Z"
        )
        before = ctx["subscription"]["version"]
        validate_success(api.accept_save_offer(ctx["offer"]["id"], REP))
        after = get_subscription(ctx["subscription"]["id"])
        assert after["version"] > before, (
            "accept must increment the subscription version"
        )


class TestSaveOfferDecline:
    def test_save_offer_decline_churns_subscription(self, api):
        """PRD §3.5: "**Declining** flips the offer to `DECLINED`; if the
        subscription was sitting in `CANCEL_PENDING`, it churns to
        `CANCELLED` with delivery stopped and `ended_at` stamped."

        Design: Corner/state_machines/save_offer_decline_churns_subscription
        """
        ctx = setup_cancel_pending(
            start_date="2026-08-03", clock="2026-08-03T00:00:00Z"
        )
        declined = validate_success(api.decline_save_offer(ctx["offer"]["id"], REP))
        assert declined["status"] == "DECLINED"

        after = get_subscription(ctx["subscription"]["id"])
        assert after["billing_status"] == "CANCELLED"
        assert after["delivery_status"] == "NOT_DELIVERED"
        assert after["ended_at"] == "2026-08-03"

    def test_save_offer_decline_marks_terminal_offer_state(self, api):
        """PRD §3.5: "**Declining** flips the offer to `DECLINED`; if the
        subscription was sitting in `CANCEL_PENDING`, it churns to
        `CANCELLED` with delivery stopped and `ended_at` stamped."

        Design: Corner/state_machines/save_offer_decline_churns_subscription
        """
        ctx = setup_cancel_pending(
            start_date="2026-08-03", clock="2026-08-03T00:00:00Z"
        )
        validate_success(api.decline_save_offer(ctx["offer"]["id"], REP))
        offer = validate_success(api.get_save_offer(ctx["offer"]["id"], REP))
        assert offer["status"] == "DECLINED"
        subscription = get_subscription(ctx["subscription"]["id"])
        assert subscription["billing_status"] == "CANCELLED"


class TestSaveOfferExpiry:
    def test_save_offer_expiry_auto_cancels(self, api):
        """PRD §3.5: "**Expiry** arrives via the batch cycle when
        `expires_at` is reached: the offer flips to `EXPIRED`, and a
        `CANCEL_PENDING` subscription churns to `CANCELLED` — the churn is
        confirmed."

        Design: Corner/state_machines/save_offer_expiry_auto_cancels
        """
        set_clock("2026-08-03T00:00:00Z")
        plan = create_plan(
            name="SE", plan_type="DIGITAL", issues_per_week=0,
            base_weekly_rate_cents=600, proration_method="PER_DAY",
            min_weekly_rate_cents=0,
        )
        from test_helpers import create_subscriber, create_subscription
        subscriber = create_subscriber(display_name="SE", email="se@x.com")
        subscription = create_subscription(subscriber["id"], plan["id"], start_date="2026-08-03")
        run_daily_cycle()
        offer = cancel_and_get_offer(subscription["id"], reason="quit")
        assert offer["expires_at"] == "2026-08-10"

        # Advance to exactly expires_at: "expires_at is reached" boundary.
        set_clock("2026-08-10T00:00:00Z")
        run_daily_cycle()

        offer_after = validate_success(api.get_save_offer(offer["id"], REP))
        assert offer_after["status"] == "EXPIRED"
        subscription_after = get_subscription(subscription["id"])
        assert subscription_after["billing_status"] == "CANCELLED"

    def test_save_offer_still_open_before_expiry(self, api):
        """PRD §3.5: "**Acceptance** — by the subscriber or staff — requires
        the offer still be `OFFERED` and today strictly before `expires_at`
        (`ERR_OFFER_NOT_OPEN` otherwise), and the subscription's billing
        state must be `CANCEL_PENDING`, `ACTIVE`, or `GRACE`
        (`ERR_SUBSCRIPTION_NOT_ACTIVE` otherwise)."

        Design: Corner/state_machines/save_offer_expiry_auto_cancels
        """
        ctx = setup_cancel_pending(
            start_date="2026-08-03", clock="2026-08-03T00:00:00Z"
        )
        # One day before expires_at (2026-08-10): cycle must not expire it.
        set_clock("2026-08-09T00:00:00Z")
        run_daily_cycle()
        offer = validate_success(api.get_save_offer(ctx["offer"]["id"], REP))
        assert offer["status"] == "OFFERED"
        subscription = get_subscription(ctx["subscription"]["id"])
        assert subscription["billing_status"] == "CANCEL_PENDING"


class TestImmediateConsistency:
    def test_immediate_visibility_after_cancel(self, api):
        """PRD §3.5: "From `ACTIVE` or `GRACE`, the subscription moves to
        `CANCEL_PENDING` rather than dying outright: the system auto-creates
        a save offer in `OFFERED` status with `origin` of `CANCEL_FLOW`, a
        `discount_pct` of 0.25, a `duration_weeks` of 8, and an `expires_at`
        seven days out, records the `cancel_reason` on the subscription, and
        increments the subscription's `version`."

        Design: Corner/consistency_model/immediate_visibility_after_cancel
        """
        set_clock("2026-08-03T00:00:00Z")
        plan = create_plan(
            name="IV", plan_type="DIGITAL", issues_per_week=0,
            base_weekly_rate_cents=400, proration_method="PER_DAY",
            min_weekly_rate_cents=0,
        )
        from test_helpers import create_subscriber, create_subscription
        subscriber = create_subscriber(display_name="IV", email="iv@x.com")
        subscription = create_subscription(subscriber["id"], plan["id"], start_date="2026-08-03")
        run_daily_cycle()

        cancelled = validate_success(
            api.cancel_subscription(subscription["id"], {"reason": "check"}, REP)
        )
        assert cancelled["billing_status"] == "CANCEL_PENDING"

        offers, _meta = validate_paginated(
            api.list_save_offers(REP, params={"subscription_id": subscription["id"]})
        )
        assert len(offers) == 1
        assert offers[0]["status"] == "OFFERED", (
            "auto-created offer must be visible to the very next read"
        )
        assert offers[0]["origin"] == "CANCEL_FLOW"


class TestOptimisticConcurrency:
    def test_plan_change_stale_version_rejected(self, api):
        """PRD §2.9: "Staging a plan change on a subscription requires the
        request to carry `expected_subscription_version` equal to the
        subscription's current `version`; a mismatch is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/plan_change_stale_version_rejected
        """
        ctx = create_active_subscription(
            start_date="2026-08-03", clock="2026-08-03T00:00:00Z"
        )
        plan_b = create_plan(
            name="OCC2", plan_type="PRINT", issues_per_week=7,
            base_weekly_rate_cents=700, proration_method="PER_DAY",
            min_weekly_rate_cents=0,
        )
        subscription = ctx["subscription"]
        observed_version = subscription["version"]

        staged = validate_success(
            api.plan_change_subscription(
                subscription["id"],
                {
                    "new_plan_id": plan_b["id"],
                    "effective_date": "2026-08-17",
                    "expected_subscription_version": observed_version,
                },
                REP,
            )
        )
        assert staged["pending_plan_effective_date"] == "2026-08-17"

        resp = api.plan_change_subscription(
            subscription["id"],
            {
                "new_plan_id": plan_b["id"],
                "effective_date": "2026-08-24",
                "expected_subscription_version": observed_version - 1,
            },
            REP,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

        after = get_subscription(subscription["id"])
        assert after["pending_plan_effective_date"] == "2026-08-17", (
            "the first (current-version) staged change must survive the stale rejection"
        )

    def test_plan_change_current_version_supersedes_pending(self, api):
        """PRD §2.9: "Both operations legitimately supersede prior state — a
        new plan change replaces any pending plan change, and a new manual
        offer auto-expires any existing `OFFERED` offer — so a client whose
        view of the subscription predates the latest superseding mutation is
        dropped rather than allowed to overwrite a change it never observed."

        Design: Corner/cross_cutting_layers/plan_change_stale_version_rejected
        """
        ctx = create_active_subscription(
            start_date="2026-08-03", clock="2026-08-03T00:00:00Z"
        )
        plan_b = create_plan(
            name="OCC2B", plan_type="PRINT", issues_per_week=7,
            base_weekly_rate_cents=700, proration_method="PER_DAY",
            min_weekly_rate_cents=0,
        )
        subscription = ctx["subscription"]

        staged1 = validate_success(
            api.plan_change_subscription(
                subscription["id"],
                {
                    "new_plan_id": plan_b["id"],
                    "effective_date": "2026-08-17",
                    "expected_subscription_version": subscription["version"],
                },
                REP,
            )
        )
        staged2 = validate_success(
            api.plan_change_subscription(
                subscription["id"],
                {
                    "new_plan_id": plan_b["id"],
                    "effective_date": "2026-08-24",
                    "expected_subscription_version": staged1["version"],
                },
                REP,
            )
        )
        assert staged2["pending_plan_effective_date"] == "2026-08-24", (
            "a plan change carrying the current version supersedes the pending one"
        )

    def test_save_offer_create_stale_version_rejected(self, api):
        """PRD §2.9: "Manually creating a save offer on a subscription
        likewise requires `expected_subscription_version` matching the
        subscription's current `version`, with the same `ERR_STALE_VERSION`
        (HTTP 412) on mismatch."

        Design: Corner/cross_cutting_layers/save_offer_create_stale_version_rejected
        """
        ctx = create_active_subscription(
            start_date="2026-08-03", clock="2026-08-03T00:00:00Z"
        )
        subscription = ctx["subscription"]
        observed_version = subscription["version"]

        offer = validate_success(
            api.create_save_offer(
                subscription["id"],
                {
                    "discount_pct": 0.3,
                    "duration_weeks": 8,
                    "expected_subscription_version": observed_version,
                },
                REP,
            ),
            201,
        )

        resp = api.create_save_offer(
            subscription["id"],
            {
                "discount_pct": 0.4,
                "duration_weeks": 12,
                "expected_subscription_version": observed_version - 1,
            },
            REP,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

        offer_after = validate_success(api.get_save_offer(offer["id"], REP))
        assert offer_after["status"] == "OFFERED", (
            "stale create must not supersede the live offer"
        )

    def test_save_offer_create_supersedes_existing_offered(self, api):
        """PRD §3.5: "Manual creation **supersedes**: any existing `OFFERED`
        offer on the same subscription is auto-flipped to `EXPIRED` (the
        supersede flavor of expiry, which leaves the subscription's billing
        state untouched, unlike cycle expiry)."

        Design: Corner/cross_cutting_layers/save_offer_create_stale_version_rejected
        """
        ctx = create_active_subscription(
            start_date="2026-08-03", clock="2026-08-03T00:00:00Z"
        )
        subscription = ctx["subscription"]

        first = validate_success(
            api.create_save_offer(
                subscription["id"],
                {
                    "discount_pct": 0.3,
                    "duration_weeks": 8,
                    "expected_subscription_version": subscription["version"],
                },
                REP,
            ),
            201,
        )
        current = get_subscription(subscription["id"])
        second = validate_success(
            api.create_save_offer(
                subscription["id"],
                {
                    "discount_pct": 0.4,
                    "duration_weeks": 12,
                    "expected_subscription_version": current["version"],
                },
                REP,
            ),
            201,
        )
        assert second["status"] == "OFFERED"
        assert second["origin"] == "RETENTION_REP"

        first_after = validate_success(api.get_save_offer(first["id"], REP))
        assert first_after["status"] == "EXPIRED", (
            "superseded offer flips to EXPIRED"
        )
        subscription_after = get_subscription(subscription["id"])
        assert subscription_after["billing_status"] == "ACTIVE", (
            "supersede expiry leaves the billing axis untouched"
        )
