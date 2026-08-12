"""Access control: authentication, role gating, and SubscriberRep
cross-account ownership enforcement."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_draft_subscription,
    create_feed,
    create_package,
    create_published_article,
    create_subscriber,
    create_subscription_payload,
    create_tier,
    make_subscriberrep_headers,
    record_publication_response,
    set_clock,
    setup_active_subscription,
    setup_subscription_with_entitlement,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SALES = TEST_USERS["salesops_headers"]
EDITOR = TEST_USERS["editor_headers"]
LEGAL = TEST_USERS["legal_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
BILLING = TEST_USERS["billing_headers"]


class TestAuthentication:
    def test_missing_auth_headers_returns_401(self, api):
        """PRD §2.1: "Every request carries two headers: `X-User-ID`,
        identifying the acting principal, and `X-User-Role`, declaring the role
        under which the principal acts. A request missing either header, or
        carrying a role string the platform does not declare, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_returns_401
        """
        res = api.list_subscribers(headers={})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)


class TestRoleGating:
    def test_editor_cannot_terminate_subscriber(self, api):
        """PRD §2.1: "A request whose role is recognised but not permitted on
        the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §2.1: "`SalesOps` — manages subscribers, subscriptions, and
        entitlements: registration, suspension, reinstatement, termination,
        activation, cancellation, renewal, granting and revocation."

        Design: Corner/validations/editor_cannot_terminate_subscriber
        """
        sub = create_subscriber(legal_name="V", declared_audience=1000)
        res = api.terminate_subscriber(sub["id"], EDITOR)
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)

    def test_auditor_cannot_publish_article(self, api):
        """PRD §2.1: "A request whose role is recognised but not permitted on
        the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §2.1: "`Auditor` — reviews republication audit; flags publications
        and dismisses flagged publications."

        Design: Corner/validations/auditor_cannot_publish_article
        """
        feed = create_feed(topic="WORLD", embargo_window_minutes=0)
        art = validate_success(
            api.create_article(
                {
                    "feed_id": feed["id"],
                    "headline": "H",
                    "body_word_count": 100,
                    "slug": "h",
                },
                EDITOR,
            ),
            201,
        )
        res = api.publish_article(art["id"], AUDITOR)
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)

    def test_legal_role_only_performs_takedown(self, api):
        """PRD §2.1: "`Legal` — legal counsel; issues article takedowns and
        reads articles, assets, and publications."
        PRD §2.1: "A request whose role is recognised but not permitted on the
        target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/legal_role_only_performs_takedown
        """
        feed = create_feed(topic="WORLD", embargo_window_minutes=0)
        art = validate_success(
            api.create_article(
                {
                    "feed_id": feed["id"],
                    "headline": "L",
                    "body_word_count": 100,
                    "slug": "l",
                },
                EDITOR,
            ),
            201,
        )
        res = api.publish_article(art["id"], LEGAL)
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)

    def test_billing_cannot_grant_entitlement(self, api):
        """PRD §2.1: "`Billing` — generates, issues, marks paid, and voids
        invoices."
        PRD §2.1: "A request whose role is recognised but not permitted on the
        target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/billing_cannot_grant_entitlement
        """
        feed = create_feed(topic="BUSINESS", embargo_window_minutes=0)
        ctx = setup_active_subscription()
        res = api.create_entitlement(
            ctx["subscription"]["id"], {"feed_id": feed["id"]}, BILLING
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)


class TestSubscriberRepCrossAccount:
    def test_subscriberrep_reads_own_subscription(self, api):
        """PRD §2.1: "When `X-User-Role` is `SubscriberRep`, by contrast,
        `X-User-ID` is the `id` of the acting `Subscriber`; ownership checks on
        any resource that references a `Subscriber` compare the resource's
        foreign-key field to `X-User-ID`. A `SubscriberRep` attempting to touch
        a resource owned by a different subscriber is rejected with
        `ERR_FORBIDDEN_CROSS_ACCOUNT` (HTTP 403)."

        Design: Corner/endpoints/subscriberrep_reads_own_subscription
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
        sub_a = create_subscriber(legal_name="A", declared_audience=5000)
        sub_b = create_subscriber(legal_name="B", declared_audience=5000)
        subp_a = create_draft_subscription(sub_a["id"], pkg["id"])
        subp_b = create_draft_subscription(sub_b["id"], pkg["id"])

        # Own subscription: readable.
        own = validate_success(
            api.get_subscription(subp_a["id"], make_subscriberrep_headers(sub_a["id"])), 200
        )
        assert own["id"] == subp_a["id"]

        # Another subscriber's subscription: rejected.
        res = api.get_subscription(subp_b["id"], make_subscriberrep_headers(sub_a["id"]))
        validate_error(
            res, ApiErrorId.ERR_FORBIDDEN_CROSS_ACCOUNT.value, expected_status=403
        )

    def test_cross_account_beats_missing_entitlement_on_republication(self, api):
        """PRD §3.6: "Because the caller is a `SubscriberRep`, the
        cross-account rule of §2.8 applies first among the business checks: the
        subscriber that owns the referenced subscription must be the subscriber
        identified by `X-User-ID`, otherwise the request is rejected with
        `ERR_FORBIDDEN_CROSS_ACCOUNT` (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/referential_vs_constraint_priority_on_subscriberrep_cross_account
        """
        set_clock("2026-05-10T00:00:00Z")
        pkg = create_package(media_rights="TEXT_ONLY", base_monthly_fee_cents=10000)
        tier = create_tier(
            min_audience=1,
            max_audience=10000,
            circulation_multiplier_basis_points=10000,
            monthly_republish_quota=5,
            overage_per_article_cents=100,
        )
        feed = create_feed(topic="SPORTS", embargo_window_minutes=0)
        sub_a = create_subscriber(legal_name="SubA", declared_audience=5000)
        # Subscriber B has an ACTIVE subscription with NO entitlements.
        ctx_b = setup_active_subscription(
            package=pkg, tier=tier, clock_to=None,
            subscriber_overrides={"legal_name": "SubB", "declared_audience": 5000},
        )
        art = create_published_article(
            feed["id"], article_overrides={"headline": "C", "body_word_count": 400}
        )
        # Subscriber A's rep attempts to record a republication against B's
        # subscription — cross-account failure must surface even though the
        # entitlement check would also fail.
        res = record_publication_response(
            ctx_b["subscription"]["id"], art["id"], sub_a["id"]
        )
        validate_error(
            res, ApiErrorId.ERR_FORBIDDEN_CROSS_ACCOUNT.value, expected_status=403
        )

    def test_cross_account_rejected_even_when_all_other_gates_pass(self, api):
        """PRD §3.6: "Because the caller is a `SubscriberRep`, the
        cross-account rule of §2.8 applies first among the business checks: the
        subscriber that owns the referenced subscription must be the subscriber
        identified by `X-User-ID`, otherwise the request is rejected with
        `ERR_FORBIDDEN_CROSS_ACCOUNT` (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/referential_vs_constraint_priority_on_subscriberrep_cross_account
        """
        # Subscriber B's subscription is fully entitled and the article is
        # rights-clean and unembargoed — the ONLY failing check is ownership.
        ctx_b = setup_subscription_with_entitlement(
            package_overrides={"media_rights": "TEXT_PHOTO_VIDEO"},
            feed_overrides={"embargo_window_minutes": 0},
        )
        sub_a = create_subscriber(legal_name="Intruder", declared_audience=5000)
        art = create_published_article(ctx_b["feed"]["id"])
        res = record_publication_response(
            ctx_b["subscription"]["id"], art["id"], sub_a["id"]
        )
        validate_error(
            res, ApiErrorId.ERR_FORBIDDEN_CROSS_ACCOUNT.value, expected_status=403
        )
