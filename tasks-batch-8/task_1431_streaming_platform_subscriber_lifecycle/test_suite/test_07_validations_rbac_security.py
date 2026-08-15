"""Authentication and authorization, plan-rule guards, duplicate live
subscriptions, and the cross-entity profile-reactivation guard."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_subscription,
    create_account,
    create_account_payload,
    create_plan,
    create_plan_payload,
    create_profile,
    create_profile_payload,
    create_subscription,
    create_subscription_payload,
    create_winback_campaign_payload,
    get_subscription,
    make_subscriber_headers,
    pause_subscription,
    set_clock,
    setup_account_with_subscription,
    setup_archived_plan,
    setup_deactivated_profile,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
PARTNER_OPS = TEST_USERS["partner_billing_ops_headers"]


class TestAuthentication:

    def test_missing_auth_headers_returns_401(self):
        """PRD section 2.1: "A request that arrives without both headers
        present and well-formed is rejected with `ERR_UNAUTHENTICATED` (HTTP
        401)."

        Design: Corner/validations/missing_auth_header_returns_401
        """
        set_clock("2026-08-01T00:00:00Z")
        resp = api_client.list_plans(headers={"Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestPlanRuleViolations:

    def test_archived_plan_rejects_new_subscription(self):
        """PRD section 3.1: "Archiving flips `is_archived` to true; from that
        moment any attempt to create a new subscription on the plan is
        rejected with `ERR_PLAN_RULE_VIOLATION`, while every existing
        subscription on the plan continues untouched".

        Design: Corner/validations/archived_plan_rejects_new_subscription
        """
        archived = setup_archived_plan(plan_code="OLD", tier="BASIC",
                                       monthly_price_cents=2000,
                                       max_profiles=1, max_households=1)
        account = create_account(email="v2@x.com", full_name="V2")
        resp = api_client.create_subscription(
            create_subscription_payload(account["account_id"],
                                        archived["plan_id"]),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_RULE_VIOLATION)

    def test_second_live_subscription_rejected(self):
        """PRD section 3.2: "An account may hold at most one live subscription:
        attempting to create a second while one stands in `TRIALING`,
        `ACTIVE`, `PAST_DUE`, or `PAUSED` is rejected with
        `ERR_DUPLICATE_ACTIVE_SUBSCRIPTION`."

        Design: Corner/validations/duplicate_active_subscription_rejected
        """
        plan, account, sub = setup_account_with_subscription()
        assert sub["subscription_status"] == "ACTIVE"
        resp = api_client.create_subscription(
            create_subscription_payload(account["account_id"], plan["plan_id"]),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_SUBSCRIPTION)


class TestProfileReactivationGuards:
    """Profile → Subscription cross-entity dependency (PRD section 3.3)."""

    def test_reactivation_blocked_while_subscription_paused(self):
        """PRD section 3.3: "A profile can return `DEACTIVATED → ACTIVE` only
        when its owning account is `ACTIVE`, when the account's subscription
        stands in `TRIALING`, `ACTIVE`, or `PAST_DUE` (a `PAUSED` subscription
        blocks reactivation outright, surfacing `ERR_INVALID_STATE`)".

        Design: Difficulty/cross_entity_state_dependency/profile_reactivation_depends_on_subscription_state
        """
        plan, account, sub, profile = setup_deactivated_profile()
        pause_subscription(sub["subscription_id"], duration_months=1)
        resp = api_client.reactivate_profile(profile["profile_id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_reactivation_allowed_while_subscription_active(self):
        """PRD section 3.3: "A profile can return `DEACTIVATED → ACTIVE` only
        when its owning account is `ACTIVE`, when the account's subscription
        stands in `TRIALING`, `ACTIVE`, or `PAST_DUE` (a `PAUSED` subscription
        blocks reactivation outright, surfacing `ERR_INVALID_STATE`), and when
        the number of active profiles on the account is strictly below the
        plan's `max_profiles`".

        Design: Difficulty/cross_entity_state_dependency/profile_reactivation_depends_on_subscription_state
        """
        plan, account, sub, profile = setup_deactivated_profile()
        assert get_subscription(sub["subscription_id"])["subscription_status"] == \
            "ACTIVE"
        resp = api_client.reactivate_profile(profile["profile_id"], ADMIN)
        data = validate_success(resp, expected_status=200)
        assert data["profile_status"] == "ACTIVE", (
            "with the account ACTIVE, the subscription ACTIVE, and the "
            "profile cap not hit, reactivation must succeed"
        )


class TestRbac:

    def test_subscriber_cannot_create_plan(self):
        """PRD section 2.1: "A request whose role is not permitted to invoke
        the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD section 4: "| POST | `/v1/plans` | Create a plan | PlatformAdmin |"

        Design: Corner/rbac/subscriber_cannot_create_plan
        """
        account = create_account(email="rbac@x.com", full_name="RBAC")
        resp = api_client.create_plan(
            create_plan_payload(plan_code="HACK", monthly_price_cents=1,
                                max_profiles=1, max_households=1),
            make_subscriber_headers(account["account_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_partner_billing_ops_cannot_create_winback_campaign(self):
        """PRD section 2.1: "A request whose role is not permitted to invoke
        the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD section 4: "| POST | `/v1/winback-campaigns` | Create a win-back
        campaign | PlatformAdmin |"

        Design: Corner/rbac/partner_billing_ops_cannot_call_admin_only_endpoint
        """
        set_clock("2026-08-01T00:00:00Z")
        resp = api_client.create_winback_campaign(
            create_winback_campaign_payload(
                campaign_code="WX", discount_pct=50, duration_months=3,
                min_days_since_cancel=30, max_days_since_cancel=90,
                eligible_cancel_reasons=["USER_REQUESTED"],
            ),
            PARTNER_OPS,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_platform_admin_can_invoke_subscriber_operations(self):
        """PRD section 2.1: "When `X-User-Role` is `PlatformAdmin`, `X-User-ID`
        is again an opaque operator identifier; the platform administrator is
        a superset role that may invoke every operation available to the other
        three roles plus the administrative operations reserved to it."
        PRD section 3.5: "A direct pause takes a `duration_months` argument
        and moves the subscription `ACTIVE → PAUSED`".

        Design: Corner/rbac/hierarchical_override_admin_can_call_subscriber_ops
        """
        _plan, _account, sub = setup_account_with_subscription()
        resp = api_client.pause_subscription(
            sub["subscription_id"], {"duration_months": 1}, ADMIN
        )
        data = validate_success(resp, expected_status=200)
        assert_subscription(data)
        assert data["subscription_status"] == "PAUSED", (
            "the superset role may invoke subscriber-shared operations on "
            "any account"
        )
