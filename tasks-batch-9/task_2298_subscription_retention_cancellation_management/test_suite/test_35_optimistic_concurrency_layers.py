"""The version field the client must prove it has read, on both resources that demand one.

A version that a successful earlier write superseded is refused before any business rule
runs, the launch of a campaign is itself such a write, and the counter moves once per write
to the row — including writes reached indirectly through another resource.
"""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_instant,
    capture_reason,
    complete_session,
    create_modification_payload,
    create_payment_method_payload,
    create_winback_target_payload,
    modifications_for,
    new_campaign,
    new_subscriber,
    open_session,
    read_campaign,
    read_payment_method,
    read_subscription,
    request_modification,
    set_clock,
    setup_active_subscription,
    validate_error,
    validate_success,
)

RETENTION = TEST_USERS["retention_specialist_headers"]


class TestStaleSubscriptionVersion:

    def test_replaying_the_version_a_previous_change_superseded_is_refused(self):
        """Version 1 is stale once the cadence change lands; version 2 is accepted.

        PRD §2.7: "A modification request against a subscription must carry
        `expected_subscription_version`, holding the client's last observed `version` of that
        `Subscription`. If that value does not equal the subscription's current `version`, the
        request is rejected with `ERR_STALE_SUBSCRIPTION_VERSION` (HTTP 412)."

        Design: Corner/cross-cutting complexity layers/stale_expected_subscription_version_returns_412
        """
        world = setup_active_subscription(
            clock="2026-01-10", subscriber_overrides={"acquisition_channel": "SEARCH"})
        request_modification(world["subscription"]["id"], "FREQUENCY_CHANGE",
                            world["subscriber_headers"], expected_version=1,
                            frequency_weeks=8)
        assert read_subscription(world["subscription"]["id"])["version"] == 2

        stale_payload = create_modification_payload("ADDON_ADD", 1, addon_code="MUG",
                                                   addon_qty=1)
        validate_error(api_client.create_modification(
            world["subscription"]["id"], stale_payload, world["subscriber_headers"]),
            ApiErrorId.ERR_STALE_SUBSCRIPTION_VERSION, 412)

        untouched = read_subscription(world["subscription"]["id"])
        assert untouched["addons"] == []
        assert untouched["committed_price_cents"] == 4999
        assert untouched["version"] == 2

        fresh_payload = create_modification_payload("ADDON_ADD", 2, addon_code="MUG",
                                                    addon_qty=1)
        accepted = validate_success(api_client.create_modification(
            world["subscription"]["id"], fresh_payload, world["subscriber_headers"]), 201)
        assert accepted["delta_price_cents"] == 1299

        updated = read_subscription(world["subscription"]["id"])
        assert updated["committed_price_cents"] == 6298
        assert updated["version"] == 3
        assert len(modifications_for(world["subscription"]["id"])) == 2


class TestStaleCampaignVersion:

    def test_the_draft_era_version_is_stale_and_outranks_the_lapse_check(self):
        """Launching bumped the version, so a never-lapsed subscriber still earns the 412.

        PRD §2.6: "Band 7 outranking band 9 has a consequence worth stating plainly: a
        modification request that is both stale and aimed at a subscription that can no longer
        be modified is rejected as stale, not as unmodifiable. The same applies to win-back
        targeting, where a stale campaign version outranks the campaign's own lifecycle state."

        Design: Corner/cross-cutting complexity layers/stale_expected_campaign_version_from_before_launch_returns_412
        """
        set_clock("2026-02-07")
        subscriber = new_subscriber(acquisition_channel="SEARCH")
        draft = new_campaign(code="WB_OCC", min_days_since_lapse=0, max_days_since_lapse=120)
        assert draft["version"] == 1
        launched = validate_success(
            api_client.launch_winback_campaign(draft["id"], RETENTION), 200)
        assert launched["version"] == 2

        validate_error(api_client.create_winback_target(
            draft["id"], create_winback_target_payload(subscriber["id"], 1), RETENTION),
            ApiErrorId.ERR_STALE_CAMPAIGN_VERSION, 412)

        held = read_campaign(draft["id"])
        assert held["state"] == "LAUNCHED"
        assert held["version"] == 2
        assert held["targeted_count"] == 0


class TestVersionCountsWritesNotCalls:

    def test_a_card_swap_moves_the_subscription_version_without_naming_it(self):
        """Signup 1, modification 2, indirect repoint 3, completion 4; reads move nothing.

        PRD §3.2: "Attaching a card is not an isolated act: the subscriber's previously
        `ACTIVE` method becomes `REPLACED`, and every subscription of that subscriber whose
        `lifecycle_state` is anything other than `CANCELLED` has its `payment_method_id`
        repointed at the new method, each such repoint incrementing that subscription's
        `version` by one."

        Design: Corner/cross-cutting complexity layers/subscription_version_increments_once_per_write_including_indirect_ones
        """
        world = setup_active_subscription(
            clock="2026-01-10", subscriber_overrides={"acquisition_channel": "SEARCH"})
        subscription_id = world["subscription"]["id"]

        request_modification(subscription_id, "FREQUENCY_CHANGE",
                             world["subscriber_headers"], frequency_weeks=8)
        assert read_subscription(subscription_id)["version"] == 2
        # A read is not a write.
        assert validate_success(api_client.get_subscription(subscription_id, RETENTION),
                                200)["version"] == 2

        replacement = validate_success(api_client.create_payment_method(
            create_payment_method_payload(world["subscriber"]["id"], card_last4="1881",
                                          exp_month=6, exp_year=2031, network="MASTERCARD"),
            world["subscriber_headers"]), 201)

        repointed = read_subscription(subscription_id)
        assert repointed["payment_method_id"] == replacement["id"]
        assert repointed["version"] == 3
        assert read_payment_method(world["payment_method"]["id"])["status"] == "REPLACED"
        assert read_payment_method(replacement["id"])["status"] == "ACTIVE"

        session = open_session(world)
        capture_reason(session["id"], "OTHER", world["subscriber_headers"])
        before_completion = read_subscription(subscription_id)
        assert before_completion["version"] == 3

        complete_session(session["id"], world["subscriber_headers"])
        cancelling = read_subscription(subscription_id)
        assert cancelling["lifecycle_state"] == "PENDING_CANCEL"
        assert cancelling["version"] == 4
        assert_instant(cancelling["cancel_effective_at"],
                       before_completion["next_renewal_at"], "cancel_effective_at")
