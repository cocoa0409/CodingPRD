"""Editorial pipeline: publish/withdraw/republish cycle with embargo
recomputation, embargo windows blocking republication, terminal-state
lockdown, member credit grants at publish, the takedown cascade, and
republish OCC."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_asset_payload,
    create_feed,
    create_published_article,
    create_subscriber,
    get_article,
    get_subscriber,
    make_subscriberrep_headers,
    parse_instant,
    publish_contributing_article,
    record_publication,
    set_clock,
    setup_subscription_with_entitlement,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SALES = TEST_USERS["salesops_headers"]
EDITOR = TEST_USERS["editor_headers"]
LEGAL = TEST_USERS["legal_headers"]


class TestWithdrawRepublishCycle:
    def test_withdraw_then_republish_restores_published_with_embargo(self, api):
        """PRD §3.5: "Republishing moves a `WITHDRAWN` article back to
        `PUBLISHED`, provided no outstanding takedown request stands against
        it; the request must carry `expected_article_version` matching the
        article's current `version` per §2.7, with a mismatch rejected as
        `ERR_STALE_VERSION` (HTTP 412). A successful republish refreshes
        `published_at` from the current logical clock, recomputes
        `embargo_until` from the feed's window, resets `embargo_status` to
        `EMBARGOED` or `CLEAR` by the same comparison used at publish, and
        increments the article's `version` by one."

        Design: Difficulty/non_linear_state_machine/article_withdraw_republish_cycle
        """
        set_clock("2026-05-10T00:00:00Z")
        feed = create_feed(topic="NATIONAL", embargo_window_minutes=60)
        published = create_published_article(
            feed["id"], article_overrides={"headline": "X", "body_word_count": 500}
        )
        assert published["status"] == "PUBLISHED"
        assert published["embargo_status"] == "EMBARGOED"
        version_after_publish = published["version"]

        withdrawn = validate_success(api.withdraw_article(published["id"], EDITOR), 200)
        assert withdrawn["status"] == "WITHDRAWN"

        # OCC token must be the article's current version (post-withdraw).
        current = get_article(published["id"])
        republished = validate_success(
            api.republish_article(
                published["id"], {"expected_article_version": current["version"]}, EDITOR
            ),
            200,
        )
        assert republished["status"] == "PUBLISHED"
        assert republished["embargo_status"] == "EMBARGOED"
        assert republished["version"] > version_after_publish

    def test_republish_recomputes_embargo_from_current_clock(self, api):
        """PRD §3.5: "A successful republish refreshes `published_at` from the
        current logical clock, recomputes `embargo_until` from the feed's
        window, resets `embargo_status` to `EMBARGOED` or `CLEAR` by the same
        comparison used at publish, and increments the article's `version` by
        one."
        PRD §3.5: "On publish, `published_at` is stamped from the current
        logical clock, `embargo_until` is computed as `published_at` plus the
        feed's `embargo_window_minutes`, and `embargo_status` becomes
        `EMBARGOED` when that computed `embargo_until` lies later than
        `published_at`, or `CLEAR` when it does not."

        Feed window is 60 minutes; after the clock advances a day, the
        republished article's embargo window is anchored at the new instant.

        Design: Difficulty/non_linear_state_machine/article_withdraw_republish_cycle
        """
        set_clock("2026-05-10T00:00:00Z")
        feed = create_feed(topic="NATIONAL", embargo_window_minutes=60)
        published = create_published_article(feed["id"])
        validate_success(api.withdraw_article(published["id"], EDITOR), 200)

        set_clock("2026-05-11T00:00:00Z")
        current = get_article(published["id"])
        republished = validate_success(
            api.republish_article(
                published["id"], {"expected_article_version": current["version"]}, EDITOR
            ),
            200,
        )
        assert parse_instant(republished["published_at"]) == parse_instant(
            "2026-05-11T00:00:00Z"
        )
        assert parse_instant(republished["embargo_until"]) == parse_instant(
            "2026-05-11T01:00:00Z"
        )
        assert republished["embargo_status"] == "EMBARGOED"


class TestEmbargoWindowBlocking:
    def _setup_embargoed_article(self):
        set_clock("2026-05-10T00:00:00Z")
        ctx = setup_subscription_with_entitlement(
            clock_to=None,
            package_overrides={"media_rights": "TEXT_ONLY"},
            tier_overrides={"monthly_republish_quota": 5},
            feed_overrides={"topic": "NATIONAL", "embargo_window_minutes": 120},
        )
        art = create_published_article(
            ctx["feed"]["id"], article_overrides={"headline": "EM", "body_word_count": 100}
        )
        # Published at 2026-05-10T00:00:00Z with a 120-minute window, so
        # embargo_until is 2026-05-10T02:00:00Z.
        assert art["embargo_status"] == "EMBARGOED"
        return ctx, art

    def test_republication_inside_embargo_window_rejected(self, api):
        """PRD §3.6: "The article's `embargo_until` must not lie in the future
        — republication of still-embargoed copy is a temporal violation,
        rejected with `ERR_TEMPORAL_VIOLATION` (HTTP 422)."

        The clock sits one hour into a two-hour embargo window.

        Design: Difficulty/resource_temporal_overlap/embargo_window_blocks_republication_until_expiry
        """
        ctx, art = self._setup_embargoed_article()
        set_clock("2026-05-10T01:00:00Z")
        res = api.create_publication(
            {"subscription_id": ctx["subscription"]["id"], "article_id": art["id"]},
            make_subscriberrep_headers(ctx["subscriber"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_TEMPORAL_VIOLATION.value, expected_status=422)

    def test_republication_at_exact_embargo_expiry_allowed(self, api):
        """PRD §3.6: "The article's `embargo_until` must not lie in the future
        — republication of still-embargoed copy is a temporal violation,
        rejected with `ERR_TEMPORAL_VIOLATION` (HTTP 422)."

        At exactly embargo_until the instant no longer lies in the future, so
        the republication is recorded.

        Design: Difficulty/resource_temporal_overlap/embargo_window_blocks_republication_until_expiry
        """
        ctx, art = self._setup_embargoed_article()
        set_clock("2026-05-10T02:00:00Z")
        pub = record_publication(
            ctx["subscription"]["id"], art["id"], ctx["subscriber"]["id"]
        )
        assert pub["status"] == "RECORDED"
        assert pub["within_quota"] is True
        assert pub["billed_amount_cents"] == 0


class TestTerminalLockdown:
    def test_article_terminal_taken_down_rejects_withdraw(self, api):
        """PRD §3.5: "A `Legal` operator may take down an article standing
        `PUBLISHED` or `WITHDRAWN`, moving it to `TAKEN_DOWN`, which is
        terminal."
        PRD §3.5: "Withdrawing moves a `PUBLISHED` article to `WITHDRAWN` and
        cascades: every publication row referencing the article that still
        stands `RECORDED` flips to `AUDIT_FLAGGED`, and each subscriber whose
        publication was flagged receives an audit review marker."
        PRD §2.8: "the target resource is in the exact from-state the
        transition requires (for example, an article must be `DRAFT` before
        publishing, a subscription must be `DRAFT` before activation); failure
        yields `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/article_terminal_taken_down_rejects_withdraw
        """
        set_clock("2026-05-10T00:00:00Z")
        feed = create_feed(topic="NATIONAL", embargo_window_minutes=0)
        art = create_published_article(
            feed["id"], article_overrides={"headline": "T", "body_word_count": 100}
        )
        validate_success(api.takedown_article(art["id"], LEGAL), 200)
        res = api.withdraw_article(art["id"], EDITOR)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)

    def test_draft_article_cannot_be_withdrawn(self, api):
        """PRD §3.5: "Withdrawing moves a `PUBLISHED` article to `WITHDRAWN`
        and cascades: every publication row referencing the article that still
        stands `RECORDED` flips to `AUDIT_FLAGGED`, and each subscriber whose
        publication was flagged receives an audit review marker."
        PRD §2.8: "the target resource is in the exact from-state the
        transition requires (for example, an article must be `DRAFT` before
        publishing, a subscription must be `DRAFT` before activation); failure
        yields `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/draft_article_cannot_be_withdrawn
        """
        feed = create_feed(topic="SPORTS", embargo_window_minutes=0)
        art = validate_success(
            api.create_article(
                {
                    "feed_id": feed["id"],
                    "headline": "D",
                    "body_word_count": 100,
                    "slug": "d1",
                },
                EDITOR,
            ),
            201,
        )
        assert art["status"] == "DRAFT"
        res = api.withdraw_article(art["id"], EDITOR)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


class TestMemberCreditGrant:
    def _setup_member_article(self):
        """Member subscriber; article at 1000 words with 2 PHOTO + 1 VIDEO
        assets. Piecewise credit: base 9000 (900 <= 1000 < 1500) + 2*1500
        (photos) + 4000 (video) = 16000."""
        set_clock("2026-05-10T00:00:00Z")
        feed = create_feed(code="NAT", topic="NATIONAL", embargo_window_minutes=0)
        sub = create_subscriber(
            legal_name="Member Pub",
            billing_email="m@m.com",
            declared_audience=5000,
            is_member=True,
        )
        art = publish_contributing_article(
            feed["id"],
            sub["id"],
            body_word_count=1000,
            asset_payloads=[
                create_asset_payload(kind="PHOTO", rights_scope="WIRE", file_ref="p1.jpg"),
                create_asset_payload(kind="PHOTO", rights_scope="WIRE", file_ref="p2.jpg"),
                create_asset_payload(kind="VIDEO", rights_scope="WIRE", file_ref="v1.mp4"),
            ],
        )
        return feed, sub, art

    def test_member_credit_cents_piecewise_computation(self, api):
        """PRD §3.5: "The base is 2000 cents for a body under 400 words, 5000
        cents for a body of at least 400 but under 900 words, 9000 cents for a
        body of at least 900 but under 1500 words, and 14000 cents for a body
        of 1500 words or more. The bonus adds 1500 cents for every attached
        asset whose `kind` is `PHOTO` and 4000 cents for every attached asset
        whose `kind` is `VIDEO`, counting all of the article's assets
        regardless of their status at publish time."

        9000 (1000-word base) + 2 * 1500 (PHOTO) + 4000 (VIDEO) = 16000 — a
        flat per-article credit would not produce this figure.

        Design: Difficulty/dual_variant_calc/member_credit_grant_piecewise_vs_flat_counterfactual
        """
        _, _, art = self._setup_member_article()
        assert art["status"] == "PUBLISHED"
        assert art["member_credit_cents"] == 16000
        fetched = get_article(art["id"])
        assert fetched["member_credit_cents"] == 16000

    def test_member_credit_credited_to_contributor_balance(self, api):
        """PRD §3.5: "Publishing is also the moment the member contribution
        model pays out: when `contributing_member_subscriber_id` is set and
        that subscriber's `is_member` is true, the article's
        `member_credit_cents` is computed and credited to the contributing
        subscriber's `member_credit_balance_cents`."

        Design: Difficulty/dual_variant_calc/member_credit_grant_piecewise_vs_flat_counterfactual
        """
        _, sub, art = self._setup_member_article()
        balance = get_subscriber(sub["id"])["member_credit_balance_cents"]
        assert balance == 16000


class TestTakedownCascade:
    def _setup_takedown_scenario(self):
        """Member subscriber with an active subscription, a published
        1000-word contributing article carrying 2 PHOTO assets (credit
        9000 + 3000 = 12000), and one recorded republication."""
        ctx = setup_subscription_with_entitlement(
            package_overrides={"media_rights": "TEXT_AND_PHOTO"},
            tier_overrides={"monthly_republish_quota": 5},
            subscriber_overrides={"is_member": True},
            feed_overrides={"embargo_window_minutes": 0},
        )
        art = publish_contributing_article(
            ctx["feed"]["id"],
            ctx["subscriber"]["id"],
            body_word_count=1000,
            asset_payloads=[
                create_asset_payload(kind="PHOTO", rights_scope="WIRE", file_ref="ph1.jpg"),
                create_asset_payload(kind="PHOTO", rights_scope="WIRE", file_ref="ph2.jpg"),
            ],
        )
        assert art["member_credit_cents"] == 12000
        pub = record_publication(
            ctx["subscription"]["id"], art["id"], ctx["subscriber"]["id"]
        )
        ctx["article"] = art
        ctx["publication"] = pub
        return ctx

    def test_takedown_cascades_to_assets_publications_and_credit(self, api):
        """PRD §3.5: "The cascade is threefold: every asset of the article
        flips to `TAKEN_DOWN`; every publication row referencing the article
        flips to `AUDIT_FLAGGED`; and if the article had a
        `contributing_member_subscriber_id`, that member's
        `member_credit_balance_cents` is decremented by the article's
        `member_credit_cents`, with the balance floored at zero so it never
        goes negative."

        Design: Difficulty/transitive_cascade/article_takedown_cascades_to_assets_and_publications_then_credit_debit
        """
        ctx = self._setup_takedown_scenario()
        sub_id = ctx["subscriber"]["id"]
        assert get_subscriber(sub_id)["member_credit_balance_cents"] == 12000

        taken_down = validate_success(api.takedown_article(ctx["article"]["id"], LEGAL), 200)
        assert taken_down["status"] == "TAKEN_DOWN"

        assets, _meta = validate_paginated(
            api.list_article_assets(ctx["article"]["id"], LEGAL)
        )
        assert len(assets) == 2
        for asset in assets:
            assert asset["status"] == "TAKEN_DOWN"

        pub_after = validate_success(
            api.get_publication(ctx["publication"]["id"], TEST_USERS["auditor_headers"]), 200
        )
        assert pub_after["status"] == "AUDIT_FLAGGED"

        assert get_subscriber(sub_id)["member_credit_balance_cents"] == 0

    def test_takedown_from_withdrawn_applies_same_cascade(self, api):
        """PRD §3.5: "A `Legal` operator may take down an article standing
        `PUBLISHED` or `WITHDRAWN`, moving it to `TAKEN_DOWN`, which is
        terminal."
        PRD §3.5: "The cascade is threefold: every asset of the article flips
        to `TAKEN_DOWN`; every publication row referencing the article flips to
        `AUDIT_FLAGGED`; and if the article had a
        `contributing_member_subscriber_id`, that member's
        `member_credit_balance_cents` is decremented by the article's
        `member_credit_cents`, with the balance floored at zero so it never
        goes negative."

        Design: Difficulty/transitive_cascade/article_takedown_cascades_to_assets_and_publications_then_credit_debit
        """
        set_clock("2026-05-10T00:00:00Z")
        feed = create_feed(topic="FEATURES", embargo_window_minutes=0)
        sub = create_subscriber(
            legal_name="M", declared_audience=5000, is_member=True
        )
        art = publish_contributing_article(
            feed["id"],
            sub["id"],
            body_word_count=500,
            asset_payloads=[
                create_asset_payload(kind="PHOTO", rights_scope="WIRE", file_ref="w1.jpg"),
            ],
        )
        # 500 words -> 5000 base + 1500 photo = 6500 credited.
        assert art["member_credit_cents"] == 6500
        validate_success(api.withdraw_article(art["id"], EDITOR), 200)

        taken_down = validate_success(api.takedown_article(art["id"], LEGAL), 200)
        assert taken_down["status"] == "TAKEN_DOWN"
        assets, _meta = validate_paginated(api.list_article_assets(art["id"], LEGAL))
        assert len(assets) == 1
        assert assets[0]["status"] == "TAKEN_DOWN"
        assert get_subscriber(sub["id"])["member_credit_balance_cents"] == 0


class TestRepublishOcc:
    def test_republish_with_stale_article_version_returns_412(self, api):
        """PRD §2.7: "Republishing a withdrawn article requires the request to
        carry `expected_article_version`, holding the `version` of the article
        as the client last observed it. If the article's current `version` has
        advanced since that observation — because another writer recorded an
        embargo extension or metadata change in the interim — the republish is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        The client holds the creation-time version; publish and withdraw have
        each advanced the article's version since.

        Design: Corner/endpoints/republish_with_stale_article_version_returns_412
        """
        set_clock("2026-05-10T00:00:00Z")
        feed = create_feed(topic="NATIONAL", embargo_window_minutes=0)
        art = validate_success(
            api.create_article(
                {
                    "feed_id": feed["id"],
                    "headline": "X",
                    "body_word_count": 100,
                    "slug": "x",
                },
                EDITOR,
            ),
            201,
        )
        stale_version = art["version"]
        validate_success(api.publish_article(art["id"], EDITOR), 200)
        validate_success(api.withdraw_article(art["id"], EDITOR), 200)

        res = api.republish_article(
            art["id"], {"expected_article_version": stale_version}, EDITOR
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)
