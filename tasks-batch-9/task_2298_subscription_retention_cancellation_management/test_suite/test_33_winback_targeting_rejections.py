"""The targeting guard chain and the send guard that reads the frozen suppression verdict.

Targeting runs its guards in a pinned order, so a draft campaign, an active subscriber, a
live suppression window and a duplicate pair each earn their own code; and a subscriber who
opted out of marketing is targeted but never contacted.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_target,
    api_client,
    assert_instant,
    assert_winback_target,
    charge_invoice,
    create_winback_target_payload,
    invoice_at_cycle,
    new_campaign,
    new_plan,
    new_subscriber,
    read_campaign,
    read_subscriber,
    read_target,
    run_renewal,
    set_clock,
    setup_active_subscription,
    setup_launched_campaign,
    setup_voluntarily_lapsed_subscriber,
    update_subscriber_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
RETENTION = TEST_USERS["retention_specialist_headers"]


def _plain_plan():
    """A non-negative-option plan, so no renewal reminder gates the renewal run."""
    return new_plan(code="BOUND", monthly_price_cents=5000, unit_cogs_cents=2500,
                    margin_floor_pct=0.4048, allowed_frequency_weeks=[4],
                    is_negative_option=False)


def _target_count_of(campaign_id):
    _, meta = validate_paginated(api_client.list_winback_targets(
        RETENTION, params={"winback_campaign_id": campaign_id}))
    return meta["total_count"]


class TestCampaignMustBeLaunched:

    def test_a_draft_campaign_refuses_targeting_even_with_the_right_version(self):
        """Version 1 is current, so the refusal is about the campaign's state.

        PRD §3.8: "Its guards run in this order: the stale-version check
        (`ERR_STALE_CAMPAIGN_VERSION`, 412); then the campaign's `state` must be `LAUNCHED`,
        a `DRAFT` or `CLOSED` campaign being rejected with `ERR_CAMPAIGN_NOT_LAUNCHED` (409);
        then the subscriber's `lapsed_at` must not be null and the days since lapse must fall
        between `min_days_since_lapse` and `max_days_since_lapse` inclusive on both ends,
        otherwise `ERR_SUBSCRIBER_NOT_LAPSED` (422); then the subscriber's
        `winback_suppressed_until` must be null or at or before the clock, a later instant
        being rejected with `ERR_WINBACK_SUPPRESSION_ACTIVE` (422); then no target may already
        exist for this `winback_campaign_id` and `subscriber_id` pair, a duplicate being
        rejected with `ERR_DUPLICATE_TARGET` (409)."

        Design: Corner/errors/targeting_a_draft_campaign_is_rejected
        """
        set_clock("2026-02-07")
        campaign = new_campaign(code="WB_DRAFT", min_days_since_lapse=0,
                                max_days_since_lapse=120, offer_discount_pct=0.2000)
        subscriber = new_subscriber(acquisition_channel="SEARCH")
        assert campaign["state"] == "DRAFT"

        validate_error(api_client.create_winback_target(
            campaign["id"], create_winback_target_payload(subscriber["id"], 1), RETENTION),
            ApiErrorId.ERR_CAMPAIGN_NOT_LAUNCHED, 409)

        held = read_campaign(campaign["id"])
        assert held["state"] == "DRAFT"
        assert held["version"] == 1
        assert held["targeted_count"] == 0
        assert _target_count_of(campaign["id"]) == 0


class TestSubscriberMustHaveLapsed:

    def test_an_active_subscriber_cannot_be_targeted_for_win_back(self):
        """The campaign is launched and the version is right; the subscriber never left.

        PRD §3.8: "then the subscriber's `lapsed_at` must not be null and the days since
        lapse must fall between `min_days_since_lapse` and `max_days_since_lapse` inclusive
        on both ends, otherwise `ERR_SUBSCRIBER_NOT_LAPSED` (422)".

        Design: Corner/errors/targeting_an_active_subscriber_returns_subscriber_not_lapsed
        """
        world = setup_active_subscription(
            clock="2026-01-10", subscriber_overrides={"acquisition_channel": "SEARCH"})
        campaign = setup_launched_campaign(code="WB_ACTIVE", min_days_since_lapse=0,
                                           max_days_since_lapse=120,
                                           offer_discount_pct=0.2000)

        validate_error(api_client.create_winback_target(
            campaign["id"],
            create_winback_target_payload(world["subscriber"]["id"], campaign["version"]),
            RETENTION), ApiErrorId.ERR_SUBSCRIBER_NOT_LAPSED, 422)

        subscriber = read_subscriber(world["subscriber"]["id"])
        assert subscriber["lapsed_at"] is None
        assert subscriber["churn_type"] == "NONE"

        held = read_campaign(campaign["id"])
        assert held["targeted_count"] == 0
        assert held["version"] == 2


class TestInvoluntarySuppressionWindow:

    def test_targeting_one_day_before_the_suppression_lifts_is_refused(self):
        """The lapse bound passes at 29 days, and the suppression window is what refuses.

        PRD §3.8: "then the subscriber's `winback_suppressed_until` must be null or at or
        before the clock, a later instant being rejected with
        `ERR_WINBACK_SUPPRESSION_ACTIVE` (422)".

        Design: Corner/errors/targeting_inside_the_involuntary_suppression_window_is_rejected
        """
        world = setup_active_subscription(
            clock="2026-01-10", plan=_plain_plan(),
            subscriber_overrides={"acquisition_channel": "SEARCH"})

        set_clock("2026-02-07")
        run_renewal(world["subscription"]["id"])
        renewal_invoice = invoice_at_cycle(world["subscription"]["id"], 1)
        charge_invoice(renewal_invoice["id"], "HARD_DECLINE", "DO_NOT_HONOR")

        lapsed = read_subscriber(world["subscriber"]["id"])
        assert lapsed["churn_type"] == "INVOLUNTARY"
        assert_instant(lapsed["lapsed_at"], "2026-02-07T00:00:00Z", "lapsed_at")
        assert_instant(lapsed["winback_suppressed_until"], "2026-03-09T00:00:00Z",
                       "winback_suppressed_until")

        set_clock("2026-03-08")
        campaign = setup_launched_campaign(code="WB_SUPP", min_days_since_lapse=0,
                                           max_days_since_lapse=120,
                                           offer_discount_pct=0.2000)
        validate_error(api_client.create_winback_target(
            campaign["id"],
            create_winback_target_payload(world["subscriber"]["id"], campaign["version"]),
            RETENTION), ApiErrorId.ERR_WINBACK_SUPPRESSION_ACTIVE, 422)

        assert read_campaign(campaign["id"])["targeted_count"] == 0
        assert _target_count_of(campaign["id"]) == 0


class TestOneTargetPerCampaignAndSubscriber:

    def test_a_second_target_for_the_same_pair_is_refused_as_duplicate(self):
        """The refreshed version passes the concurrency band, so uniqueness is what bites.

        PRD §3.8: "then no target may already exist for this `winback_campaign_id` and
        `subscriber_id` pair, a duplicate being rejected with `ERR_DUPLICATE_TARGET` (409)."

        Design: Corner/errors/duplicate_target_for_one_subscriber_in_one_campaign_is_rejected
        """
        world = setup_voluntarily_lapsed_subscriber(
            clock="2026-01-10", plan=_plain_plan(),
            subscriber_overrides={"acquisition_channel": "SEARCH"})
        assert_instant(world["subscriber"]["lapsed_at"], "2026-02-07T00:00:00Z", "lapsed_at")

        set_clock("2026-02-08")
        campaign = setup_launched_campaign(min_days_since_lapse=0, max_days_since_lapse=120)
        first_target = add_target(campaign, world["subscriber"]["id"])
        refreshed_version = read_campaign(campaign["id"])["version"]
        assert refreshed_version == 3

        validate_error(api_client.create_winback_target(
            campaign["id"],
            create_winback_target_payload(world["subscriber"]["id"], refreshed_version),
            RETENTION), ApiErrorId.ERR_DUPLICATE_TARGET, 409)

        held = read_campaign(campaign["id"])
        assert held["version"] == 3
        assert held["targeted_count"] == 1
        assert read_target(first_target["id"])["state"] == "ELIGIBLE"
        assert _target_count_of(campaign["id"]) == 1


class TestMarketingOptOutBlocksTheSend:

    def test_an_opted_out_subscriber_is_scored_but_never_contacted(self):
        """The target is created SUPPRESSED on the first predicate, and the send is refused.

        PRD §3.8: "**Sending** a win-back offer requires the campaign to be `LAUNCHED`
        (`ERR_CAMPAIGN_NOT_LAUNCHED`, 409), then the target's `state` to be `ELIGIBLE`, any
        other value being rejected with `ERR_TARGET_SUPPRESSED` (409), and then the contact
        cap: the number of this subscriber's targets whose `sent_at` lies inside the closed
        sliding window from 30 days before the clock up to the clock must be strictly below
        one."

        Design: Corner/errors/sending_to_a_do_not_contact_target_is_rejected_as_suppressed
        """
        world = setup_voluntarily_lapsed_subscriber(
            clock="2026-01-10", plan=_plain_plan(),
            subscriber_overrides={"acquisition_channel": "ORGANIC"})
        assert world["subscriber"]["realized_ltv_cents"] == 0

        validate_success(api_client.update_subscriber(
            world["subscriber"]["id"], update_subscriber_payload(True), ADMIN), 200)

        set_clock("2026-02-08")
        campaign = setup_launched_campaign(min_days_since_lapse=0, max_days_since_lapse=120)
        target = add_target(campaign, world["subscriber"]["id"])

        assert_winback_target(target)
        assert target["state"] == "SUPPRESSED"
        assert target["suppression_reason"] == "DO_NOT_CONTACT"
        assert target["days_since_lapse_at_target"] == 1
        # 0.30 x (1 - 1/120) of recency plus 0.25 of a PRICE reason, on a realized LTV of 0.
        assert target["priority_score"] == pytest.approx(0.5475, abs=5e-5)
        assert target["sent_at"] is None

        validate_error(api_client.send_winback_target(target["id"], RETENTION),
                       ApiErrorId.ERR_TARGET_SUPPRESSED, 409)

        assert read_target(target["id"])["state"] == "SUPPRESSED"
        assert read_campaign(campaign["id"])["sent_count"] == 0
        assert read_subscriber(world["subscriber"]["id"])["last_contacted_at"] is None
