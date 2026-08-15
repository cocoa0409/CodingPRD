"""Republication enforcement: quota boundary precision, LIVE-entitlement
dependency, monthly bucket reset, and rights violations on taken-down
articles."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_feed,
    create_published_article,
    get_subscription,
    grant_entitlement,
    record_publication,
    record_publication_response,
    set_clock,
    setup_subscription_with_entitlement,
    setup_subscription_with_publications,
    validate_error,
)

SALES = TEST_USERS["salesops_headers"]
EDITOR = TEST_USERS["editor_headers"]
LEGAL = TEST_USERS["legal_headers"]


class TestQuotaBoundary:
    def test_publications_up_to_quota_are_within_quota_and_unbilled(self, api):
        """PRD §3.6: "The republication is `within_quota` when the incremented
        count is no greater than the tier's `monthly_republish_quota`; in that
        case `billed_amount_cents` is zero. Otherwise `within_quota` is false
        and `billed_amount_cents` is the tier's `overage_per_article_cents`."

        Quota is 2: the first and second republications of the month are
        within quota (boundary is "no greater than", i.e. <=).

        Design: Difficulty/boundary_precision_check/quota_exact_crossing_zero_vs_overage
        """
        ctx = setup_subscription_with_publications(2, quota=2, overage=250)
        p1, p2 = ctx["publications"]
        assert p1["within_quota"] is True
        assert p1["billed_amount_cents"] == 0
        assert p2["within_quota"] is True
        assert p2["billed_amount_cents"] == 0

    def test_publication_beyond_quota_is_billed_overage(self, api):
        """PRD §3.6: "The republication is `within_quota` when the incremented
        count is no greater than the tier's `monthly_republish_quota`; in that
        case `billed_amount_cents` is zero. Otherwise `within_quota` is false
        and `billed_amount_cents` is the tier's `overage_per_article_cents`."

        Quota is 2: the third republication of the month crosses the quota and
        is billed the tier's overage_per_article_cents of 250.

        Design: Difficulty/boundary_precision_check/quota_exact_crossing_zero_vs_overage
        """
        ctx = setup_subscription_with_publications(3, quota=2, overage=250)
        p3 = ctx["publications"][2]
        assert p3["within_quota"] is False
        assert p3["billed_amount_cents"] == 250


class TestEntitlementDependency:
    def test_republication_with_revoked_entitlement_rejected(self, api):
        """PRD §3.4: "Entitlements are checked at the moment of republication.
        Recording a republication requires a `LIVE` entitlement for the pairing
        of the subscription and the feed the article was routed to; without
        one, the republication is rejected with `ERR_NO_ENTITLEMENT`
        (HTTP 422)."

        The entitlement was granted and then explicitly revoked, so no LIVE
        entitlement pairs the subscription with the article's feed.

        Design: Difficulty/cross_entity_state_dependency/publication_record_depends_on_entitlement_state
        """
        ctx = setup_subscription_with_entitlement(
            package_overrides={"media_rights": "TEXT_ONLY"},
            feed_overrides={"topic": "BUSINESS", "embargo_window_minutes": 0},
        )
        revoke_res = api.revoke_entitlement(ctx["entitlement"]["id"], SALES)
        assert revoke_res.status_code == 200
        art = create_published_article(
            ctx["feed"]["id"], article_overrides={"headline": "N", "body_word_count": 100}
        )
        res = record_publication_response(
            ctx["subscription"]["id"], art["id"], ctx["subscriber"]["id"]
        )
        validate_error(res, ApiErrorId.ERR_NO_ENTITLEMENT.value, expected_status=422)

    def test_republication_without_entitlement_for_feed_rejected(self, api):
        """PRD §3.4: "Entitlements are checked at the moment of republication.
        Recording a republication requires a `LIVE` entitlement for the pairing
        of the subscription and the feed the article was routed to; without
        one, the republication is rejected with `ERR_NO_ENTITLEMENT`
        (HTTP 422)."

        The subscription holds a LIVE entitlement to a different feed than the
        one the article was routed to, so the (subscription, feed) pairing has
        no LIVE entitlement.

        Design: Difficulty/cross_entity_state_dependency/publication_record_depends_on_entitlement_state
        """
        ctx = setup_subscription_with_entitlement(
            package_overrides={"media_rights": "TEXT_PHOTO_VIDEO"},
            feed_overrides={"topic": "BUSINESS", "embargo_window_minutes": 0},
        )
        other_feed = create_feed(topic="SPORTS", embargo_window_minutes=0)
        art = create_published_article(other_feed["id"])
        res = record_publication_response(
            ctx["subscription"]["id"], art["id"], ctx["subscriber"]["id"]
        )
        validate_error(res, ApiErrorId.ERR_NO_ENTITLEMENT.value, expected_status=422)


class TestMonthBucketReset:
    def _setup_may_publications(self):
        """Two republications recorded in May under a quota of 2."""
        return setup_subscription_with_publications(
            2,
            quota=2,
            overage=100,
            package_overrides={"media_rights": "TEXT_ONLY"},
            feed_overrides={"topic": "SPORTS", "embargo_window_minutes": 0},
        )

    def test_counter_resets_and_bucket_moves_on_new_month(self, api):
        """PRD §3.6: "The subscription's `current_month_bucket` holds the
        YYYY-MM month its `republish_count_current_month` belongs to. If that
        bucket differs from the year-and-month of the current logical clock,
        the counter is first reset to zero and the bucket is moved to the
        current month; the counter is then incremented by one."

        After two May republications (quota exhausted), the clock advances to
        June; the next republication is the first of the new month, so it is
        within quota and billed zero, and the bucket moves to 2026-06.

        Design: Difficulty/compensating_invariant/republish_count_reset_conserves_month_bucket_invariant
        """
        ctx = self._setup_may_publications()
        set_clock("2026-06-01T00:00:00Z")
        art = create_published_article(
            ctx["feed"]["id"], article_overrides={"headline": "A3"}
        )
        pub = record_publication(
            ctx["subscription"]["id"], art["id"], ctx["subscriber"]["id"]
        )
        assert pub["within_quota"] is True
        assert pub["billed_amount_cents"] == 0
        sub_after = get_subscription(ctx["subscription"]["id"])
        assert sub_after["current_month_bucket"] == "2026-06"

    def test_quota_applies_fresh_after_month_reset(self, api):
        """PRD §3.6: "If that bucket differs from the year-and-month of the
        current logical clock, the counter is first reset to zero and the
        bucket is moved to the current month; the counter is then incremented
        by one."
        PRD §3.6: "The republication is `within_quota` when the incremented
        count is no greater than the tier's `monthly_republish_quota`; in that
        case `billed_amount_cents` is zero. Otherwise `within_quota` is false
        and `billed_amount_cents` is the tier's `overage_per_article_cents`."

        June's counter restarts at zero: the first two June republications are
        within quota and only the third is billed — if the May count had
        carried over, the first June republication would already have been
        billed.

        Design: Difficulty/compensating_invariant/republish_count_reset_conserves_month_bucket_invariant
        """
        ctx = self._setup_may_publications()
        set_clock("2026-06-01T00:00:00Z")
        june_pubs = []
        for i in range(3):
            art = create_published_article(
                ctx["feed"]["id"], article_overrides={"headline": f"J{i}"}
            )
            june_pubs.append(
                record_publication(
                    ctx["subscription"]["id"], art["id"], ctx["subscriber"]["id"]
                )
            )
        assert june_pubs[0]["within_quota"] is True
        assert june_pubs[0]["billed_amount_cents"] == 0
        assert june_pubs[1]["within_quota"] is True
        assert june_pubs[1]["billed_amount_cents"] == 0
        assert june_pubs[2]["within_quota"] is False
        assert june_pubs[2]["billed_amount_cents"] == 100


class TestRightsViolation:
    def test_rights_violation_on_taken_down_article(self, api):
        """PRD §3.6: "And rights must be clean: the article must not be
        `TAKEN_DOWN`, and every attached asset's `rights_scope` must be
        compatible with the subscribing package's `media_rights`. The carve-out
        classes are `WIRE`, `EDITORIAL_ONLY`, and `MEMBER_ONLY`; assets marked
        `EDITORIAL_ONLY` or `MEMBER_ONLY` are excluded from syndication, and
        the package's `media_rights` class bounds which asset kinds may ride
        along at all — a `TEXT_ONLY` package licenses no photo or video
        republication, `TEXT_AND_PHOTO` admits photographs but not video, and
        `TEXT_PHOTO_VIDEO` admits both. A failure on either limb is rejected
        with `ERR_RIGHTS_VIOLATION` (HTTP 422)."

        Design: Corner/errors/rights_violation_on_taken_down_article
        """
        ctx = setup_subscription_with_entitlement(
            package_overrides={"media_rights": "TEXT_ONLY"},
            feed_overrides={"topic": "NATIONAL", "embargo_window_minutes": 0},
        )
        art = create_published_article(
            ctx["feed"]["id"], article_overrides={"headline": "TD", "body_word_count": 100}
        )
        takedown_res = api.takedown_article(art["id"], LEGAL)
        assert takedown_res.status_code == 200
        res = record_publication_response(
            ctx["subscription"]["id"], art["id"], ctx["subscriber"]["id"]
        )
        validate_error(res, ApiErrorId.ERR_RIGHTS_VIOLATION.value, expected_status=422)
