"""Subscription and subscriber lifecycles: suspend/reinstate branching,
subscriber-suspend cascades, activation's dependency on subscriber state,
termination notice windows, minimum commitment, and activation OCC."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_subscription,
    api_client,
    create_draft_subscription,
    create_package,
    create_subscriber,
    create_tier,
    get_entitlement,
    get_subscriber,
    get_subscription,
    grant_entitlement,
    set_clock,
    setup_active_subscription,
    setup_subscription_with_entitlement,
    validate_error,
    validate_success,
)

SALES = TEST_USERS["salesops_headers"]


class TestSuspendReinstateBranching:
    def test_suspend_revokes_entitlements_and_reinstate_does_not_restore(self, api):
        """PRD §3.3: "Suspending moves a subscription from `ACTIVE` to
        `SUSPENDED` — the owning subscriber must be `ACTIVE` — and flips all of
        the subscription's entitlements to `REVOKED`, stamping each
        `revoked_at`. Reinstating moves it from `SUSPENDED` back to `ACTIVE` —
        again the subscriber must be `ACTIVE` — but entitlements previously
        revoked remain `REVOKED`; access is restored only by granting new
        entitlements explicitly."

        Design: Difficulty/non_linear_state_machine/subscription_active_suspended_active_branching
        """
        ctx = setup_subscription_with_entitlement()
        subp_id = ctx["subscription"]["id"]
        ent_id = ctx["entitlement"]["id"]
        assert ctx["entitlement"]["status"] == "LIVE"
        assert ctx["entitlement"]["revoked_at"] is None

        suspended = validate_success(api.suspend_subscription(subp_id, SALES), 200)
        assert suspended["status"] == "SUSPENDED"
        ent_after_suspend = get_entitlement(ent_id)
        assert ent_after_suspend["status"] == "REVOKED"
        assert ent_after_suspend["revoked_at"] is not None

        reinstated = validate_success(api.reinstate_subscription(subp_id, SALES), 200)
        assert reinstated["status"] == "ACTIVE"
        ent_after_reinstate = get_entitlement(ent_id)
        assert ent_after_reinstate["status"] == "REVOKED"

    def test_reinstated_subscription_accepts_explicit_new_entitlement(self, api):
        """PRD §3.3: "Reinstating moves it from `SUSPENDED` back to `ACTIVE` —
        again the subscriber must be `ACTIVE` — but entitlements previously
        revoked remain `REVOKED`; access is restored only by granting new
        entitlements explicitly."
        PRD §3.4: "Revocation — either an explicit revocation by `SalesOps` or
        a cascade from a subscription suspension, cancellation, or expiry —
        moves a `LIVE` entitlement to `REVOKED` and stamps `revoked_at` from
        the current clock; while live, `revoked_at` is null. `REVOKED` is
        terminal: there is no path back to `LIVE`, only a fresh grant."

        Design: Difficulty/non_linear_state_machine/subscription_active_suspended_active_branching
        """
        ctx = setup_subscription_with_entitlement()
        subp_id = ctx["subscription"]["id"]
        old_ent_id = ctx["entitlement"]["id"]

        validate_success(api.suspend_subscription(subp_id, SALES), 200)
        validate_success(api.reinstate_subscription(subp_id, SALES), 200)

        new_ent = validate_success(
            api.create_entitlement(subp_id, {"feed_id": ctx["feed"]["id"]}, SALES), 201
        )
        assert new_ent["status"] == "LIVE"
        assert new_ent["revoked_at"] is None
        assert get_entitlement(old_ent_id)["status"] == "REVOKED"


class TestSubscriberSuspendCascade:
    def test_subscriber_suspend_cascades_to_subscription_then_entitlement(self, api):
        """PRD §3.2: "Suspending a subscriber moves it from `ACTIVE` to
        `SUSPENDED` and cascades downward: every `ACTIVE` or `DRAFT`
        subscription belonging to that subscriber flips to `SUSPENDED`."
        PRD §2.9: "Suspending, cancelling, or expiring a subscription flips all
        of its entitlements to `REVOKED`."

        Design: Difficulty/transitive_cascade/subscriber_suspend_cascades_to_subscriptions_then_entitlements
        """
        ctx = setup_subscription_with_entitlement()
        sub_id = ctx["subscriber"]["id"]
        subp_id = ctx["subscription"]["id"]
        ent_id = ctx["entitlement"]["id"]

        suspended = validate_success(api.suspend_subscriber(sub_id, SALES), 200)
        assert suspended["status"] == "SUSPENDED"
        assert get_subscriber(sub_id)["status"] == "SUSPENDED"
        assert get_subscription(subp_id)["status"] == "SUSPENDED"
        assert get_entitlement(ent_id)["status"] == "REVOKED"

    def test_subscriber_suspend_also_suspends_draft_subscriptions(self, api):
        """PRD §3.2: "Suspending a subscriber moves it from `ACTIVE` to
        `SUSPENDED` and cascades downward: every `ACTIVE` or `DRAFT`
        subscription belonging to that subscriber flips to `SUSPENDED`."

        Design: Difficulty/transitive_cascade/subscriber_suspend_cascades_to_subscriptions_then_entitlements
        """
        ctx = setup_active_subscription()
        sub_id = ctx["subscriber"]["id"]
        # A second subscription still in DRAFT.
        draft = create_draft_subscription(sub_id, ctx["package"]["id"])
        assert draft["status"] == "DRAFT"

        validate_success(api.suspend_subscriber(sub_id, SALES), 200)
        assert get_subscription(ctx["subscription"]["id"])["status"] == "SUSPENDED"
        assert get_subscription(draft["id"])["status"] == "SUSPENDED"


class TestActivationDependsOnSubscriberState:
    def _setup_suspended_subscriber_with_draft(self):
        set_clock("2026-05-10T00:00:00Z")
        pkg = create_package(media_rights="TEXT_ONLY", base_monthly_fee_cents=10000)
        create_tier(
            min_audience=1,
            max_audience=10000,
            circulation_multiplier_basis_points=10000,
            monthly_republish_quota=5,
            overage_per_article_cents=100,
            member_discount_pct=0,
        )
        sub = create_subscriber(legal_name="S", declared_audience=5000)
        validate_success(api_client.suspend_subscriber(sub["id"], SALES), 200)
        subp = create_draft_subscription(sub["id"], pkg["id"])
        return sub, subp

    def test_activate_rejected_while_subscriber_suspended(self, api):
        """PRD §3.3: "The subscription must be `DRAFT` and its owning
        subscriber must be `ACTIVE` — a wrong from-state on either is
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/subscription_activate_depends_on_subscriber_state
        """
        sub, subp = self._setup_suspended_subscriber_with_draft()
        fresh = get_subscriber(sub["id"])
        res = api.activate_subscription(
            subp["id"], {"expected_subscriber_version": fresh["version"]}, SALES
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)

    def test_activate_succeeds_after_subscriber_reinstated(self, api):
        """PRD §3.3: "The subscription must be `DRAFT` and its owning
        subscriber must be `ACTIVE` — a wrong from-state on either is
        `ERR_INVALID_STATE` (HTTP 409)."
        PRD §3.2: "Reinstating moves the subscriber from `SUSPENDED` back to
        `ACTIVE` but, by design, does not auto-reinstate any subscription —
        each subscription must be reinstated individually."

        Design: Difficulty/cross_entity_state_dependency/subscription_activate_depends_on_subscriber_state
        """
        sub, subp = self._setup_suspended_subscriber_with_draft()
        validate_success(api.reinstate_subscriber(sub["id"], SALES), 200)
        activated = activate_subscription(subp["id"], sub["id"])
        assert activated["status"] == "ACTIVE"


class TestTerminationNoticeWindow:
    def _subscriber_with_notice(self):
        set_clock("2026-05-10T00:00:00Z")
        sub = create_subscriber(legal_name="TN", declared_audience=5000)
        validate_success(api_client.give_termination_notice(sub["id"], SALES), 200)
        return sub

    def test_terminate_before_30_days_rejected(self, api):
        """PRD §3.2: "The actual termination — whether the subscriber stands
        `ACTIVE` or `SUSPENDED` at the time — is only lawful once the logical
        clock has reached or passed `termination_notice_at` plus 30 days; an
        attempt made earlier is rejected with `ERR_TEMPORAL_VIOLATION`
        (HTTP 422)."

        Notice given at 2026-05-10T00:00:00Z; the attempt at 2026-06-08 is 29
        days later, inside the notice period.

        Design: Difficulty/resource_temporal_overlap/termination_notice_window_requires_full_30_days
        """
        sub = self._subscriber_with_notice()
        set_clock("2026-06-08T00:00:00Z")
        res = api.terminate_subscriber(sub["id"], SALES)
        validate_error(res, ApiErrorId.ERR_TEMPORAL_VIOLATION.value, expected_status=422)

    def test_terminate_at_exactly_30_days_succeeds(self, api):
        """PRD §3.2: "The actual termination — whether the subscriber stands
        `ACTIVE` or `SUSPENDED` at the time — is only lawful once the logical
        clock has reached or passed `termination_notice_at` plus 30 days; an
        attempt made earlier is rejected with `ERR_TEMPORAL_VIOLATION`
        (HTTP 422)."

        Notice given at 2026-05-10T00:00:00Z; at 2026-06-09T00:00:00Z the clock
        has reached exactly notice + 30 days, so termination is lawful.
        `TERMINATED` is terminal.

        Design: Difficulty/resource_temporal_overlap/termination_notice_window_requires_full_30_days
        """
        sub = self._subscriber_with_notice()
        set_clock("2026-06-09T00:00:00Z")
        terminated = validate_success(api.terminate_subscriber(sub["id"], SALES), 200)
        assert terminated["status"] == "TERMINATED"


class TestMinimumCommitment:
    def test_cancel_subscription_before_min_commitment_rejected(self, api):
        """PRD §3.3: "Whether the subscription is cancelled from `ACTIVE`
        (permitted while the owning subscriber is `ACTIVE` or `SUSPENDED`) or
        from `SUSPENDED`, the subscription's `months_used_current_period` — the
        count of months consumed since `start_at` or the last renewal — must
        have reached at least 3; otherwise the cancellation is rejected with
        `ERR_MIN_COMMITMENT_NOT_MET` (HTTP 422)."
        PRD §3.3: "The draft is born in `DRAFT` status with
        `months_used_current_period` and `republish_count_current_month` both
        at zero."

        Design: Corner/state_machines/cancel_subscription_before_min_commitment_rejected
        """
        ctx = setup_active_subscription()
        res = api.cancel_subscription(ctx["subscription"]["id"], SALES)
        validate_error(
            res, ApiErrorId.ERR_MIN_COMMITMENT_NOT_MET.value, expected_status=422
        )


class TestActivationOcc:
    def test_activate_with_stale_subscriber_version_returns_412(self, api):
        """PRD §2.7: "Activating a subscription requires the request to carry
        `expected_subscriber_version`, holding the `version` of the owning
        subscriber as the client last observed it. If the subscriber's current
        `version` has advanced since that observation — because another writer
        modified the subscriber, for example its `member_credit_balance_cents`
        or `declared_audience`, between the client's read and the activation —
        the activation is rejected with `ERR_STALE_VERSION` (HTTP 412),
        preventing the client from resolving a tier and price against
        subscriber inputs it has not observed."

        The client observed the subscriber at creation (v1); the suspend and
        reinstate mutations advanced the subscriber's version before the
        activation attempt.

        Design: Corner/endpoints/activate_with_stale_subscriber_version_returns_412
        """
        set_clock("2026-05-10T00:00:00Z")
        pkg = create_package(media_rights="TEXT_ONLY", base_monthly_fee_cents=10000)
        create_tier(
            min_audience=1,
            max_audience=10000,
            circulation_multiplier_basis_points=10000,
            monthly_republish_quota=5,
            overage_per_article_cents=100,
        )
        sub = create_subscriber(legal_name="S", declared_audience=5000)
        stale_version = sub["version"]
        validate_success(api.suspend_subscriber(sub["id"], SALES), 200)
        validate_success(api.reinstate_subscriber(sub["id"], SALES), 200)
        subp = create_draft_subscription(sub["id"], pkg["id"])

        res = api.activate_subscription(
            subp["id"], {"expected_subscriber_version": stale_version}, SALES
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)
