"""Action endpoints, a cross-resource link, a computed read and a narrow patch.

Launching carries no body but moves the version the next call must quote; a signup can cite
a sent win-back target and undo a lapse; the plan's subscription count is derived from the
subscription set; and the subscriber patch touches exactly one field.
"""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    add_target,
    assert_instant,
    assert_subscriber,
    assert_winback_campaign,
    complete_session,
    create_subscription_payload,
    new_campaign,
    new_core_plan,
    new_payment_method,
    new_plan,
    new_subscriber,
    read_campaign,
    read_payment_method,
    read_subscriber,
    read_subscription,
    read_target,
    run_renewal,
    send_target,
    set_clock,
    setup_active_subscription,
    setup_launched_campaign,
    setup_reason_captured_session,
    updater_result_payload,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BILLING = TEST_USERS["billing_operator_headers"]
RETENTION = TEST_USERS["retention_specialist_headers"]


class TestCampaignLaunchAction:

    def test_launching_bumps_the_version_the_first_targeting_call_must_quote(self):
        """DRAFT to LAUNCHED with version 2 and all three counters still at zero.

        PRD §3.8: "Launching moves a campaign from `DRAFT` to `LAUNCHED` and increments its
        `version`. A campaign already `LAUNCHED` may not be launched again."

        Design: Corner/endpoints/campaign_launch_action_moves_draft_to_launched_and_bumps_version
        """
        set_clock("2026-02-07")
        campaign = new_campaign(code="WB_LAUNCH", min_days_since_lapse=0,
                                max_days_since_lapse=120)
        assert campaign["state"] == "DRAFT"
        assert campaign["version"] == 1

        launched = validate_success(
            api_client.launch_winback_campaign(campaign["id"], RETENTION), 200)

        assert_winback_campaign(launched)
        assert launched["state"] == "LAUNCHED"
        assert launched["version"] == 2
        assert launched["targeted_count"] == 0
        assert launched["sent_count"] == 0
        assert launched["converted_count"] == 0
        assert launched["send_window_days"] == 14
        assert launched["suppression_days"] == 60


class TestWinBackConversion:

    def test_a_signup_citing_a_sent_target_converts_it_and_undoes_the_lapse(self):
        """The target converts, the churn stamp clears, and the original cohort survives.

        PRD §3.2: "When `winback_target_id` is supplied, the cited target moves to
        `CONVERTED` with `converted_at` at the clock, the subscriber's `churn_type` returns
        to `NONE`, `lapsed_at` is cleared to null, `won_back_at` is set to the clock, and the
        owning campaign's `converted_count` increments."

        Design: Corner/endpoints/new_subscription_citing_a_sent_target_converts_it_and_clears_the_lapse
        """
        plain_plan = new_plan(code="BOUND", monthly_price_cents=5000, unit_cogs_cents=2500,
                             margin_floor_pct=0.4048, allowed_frequency_weeks=[4],
                             is_negative_option=False)
        world = setup_active_subscription(
            clock="2026-01-10", plan=plain_plan,
            subscriber_overrides={"acquisition_channel": "SEARCH"})
        session = setup_reason_captured_session(world, reason_code="PRICE")
        complete_session(session["id"], world["subscriber_headers"])

        set_clock("2026-02-07")
        run_renewal(world["subscription"]["id"])
        assert read_subscriber(world["subscriber"]["id"])["churn_type"] == "VOLUNTARY"

        campaign = setup_launched_campaign(min_days_since_lapse=0, max_days_since_lapse=120)
        target = add_target(campaign, world["subscriber"]["id"])
        sent = send_target(target["id"])
        assert_instant(sent["sent_at"], "2026-02-07T00:00:00Z", "sent_at")
        assert_instant(sent["expires_at"], "2026-02-21T00:00:00Z", "expires_at")

        new_subscription = validate_success(api_client.create_subscription(
            create_subscription_payload(world["subscriber"]["id"], plain_plan["id"],
                                        world["payment_method"]["id"],
                                        winback_target_id=target["id"]), ADMIN), 201)

        converted = read_target(target["id"])
        assert converted["state"] == "CONVERTED"
        assert_instant(converted["converted_at"], "2026-02-07T00:00:00Z", "converted_at")
        assert_instant(converted["sent_at"], "2026-02-07T00:00:00Z", "sent_at")

        owning_campaign = read_campaign(campaign["id"])
        assert owning_campaign["targeted_count"] == 1
        assert owning_campaign["sent_count"] == 1
        assert owning_campaign["converted_count"] == 1

        won_back = read_subscriber(world["subscriber"]["id"])
        assert won_back["churn_type"] == "NONE"
        assert won_back["lapsed_at"] is None
        assert_instant(won_back["won_back_at"], "2026-02-07T00:00:00Z", "won_back_at")
        # A win-back is not a new acquisition, so the original cohort is kept.
        assert won_back["cohort_month"] == "2026-01"

        assert new_subscription["lifecycle_state"] == "ACTIVE"
        assert new_subscription["committed_price_cents"] == 5000


class TestComputedPlanCounter:

    def test_a_pending_cancel_subscription_still_counts_towards_the_plan(self):
        """Two signups, one of them on its way out, still read as two.

        PRD §3.1: "`active_subscription_count` is maintained by the server rather than
        supplied: it is the number of subscriptions on this plan whose `lifecycle_state` is
        `ACTIVE`, `PAUSED` or `PENDING_CANCEL`, and it starts at 0."

        Design: Corner/endpoints/plan_active_subscription_count_is_a_computed_read
        """
        plan = new_core_plan()
        stayer = setup_active_subscription(
            clock="2026-01-10", plan=plan,
            subscriber_overrides={"acquisition_channel": "SEARCH"})
        leaver = setup_active_subscription(
            plan=plan, subscriber_overrides={"acquisition_channel": "SEARCH"})

        session = setup_reason_captured_session(leaver, reason_code="PRICE")
        complete_session(session["id"], leaver["subscriber_headers"])

        assert validate_success(api_client.get_plan(plan["id"], RETENTION),
                                200)["active_subscription_count"] == 2
        assert read_subscription(stayer["subscription"]["id"])["lifecycle_state"] == "ACTIVE"
        assert read_subscription(
            leaver["subscription"]["id"])["lifecycle_state"] == "PENDING_CANCEL"


class TestUpdaterIngestionPrecondition:

    def test_an_updater_result_for_a_card_nobody_asked_about_is_refused(self):
        """A fresh card sits at NONE, so the replacement details are never applied.

        PRD §3.7: "The **card-updater result** is ingested by a `BillingOperator` for a
        method whose `updater_status` is `PENDING`; ingesting a result for any other value
        is rejected with `ERR_UPDATER_NOT_PENDING` (409)."

        Design: Corner/endpoints/updater_result_on_a_card_that_was_never_requested_returns_updater_not_pending
        """
        set_clock("2026-01-10")
        subscriber = new_subscriber(acquisition_channel="SEARCH")
        card = new_payment_method(subscriber["id"])

        validate_error(api_client.submit_updater_result(
            card["id"],
            updater_result_payload("UPDATED", new_card_last4="9999", new_exp_month=1,
                                   new_exp_year=2033), BILLING),
            ApiErrorId.ERR_UPDATER_NOT_PENDING, 409)

        stored = read_payment_method(card["id"])
        assert stored["updater_status"] == "NONE"
        assert stored["updater_requested_at"] is None
        assert stored["card_last4"] == "4242"
        assert stored["exp_year"] == 2030
        assert stored["status"] == "ACTIVE"
        assert stored["version"] == 1


class TestMarketingPreferencePatch:

    def test_the_patch_flips_the_opt_out_and_nothing_else(self):
        """One flag, one version bump, every other field left where it was.

        PRD §3.2: "A `do_not_contact` flag records the marketing opt-out and defaults to
        false; a subscriber or a `PlatformAdmin` may later flip it, which is the only field
        the marketing-preference update touches and which bumps the subscriber's `version`."

        Design: Corner/endpoints/patch_subscriber_updates_the_contact_preference_only
        """
        set_clock("2026-01-10")
        subscriber = new_subscriber(acquisition_channel="ORGANIC")
        assert subscriber["do_not_contact"] is False

        updated = validate_success(api_client.update_subscriber(
            subscriber["id"], {"do_not_contact": True}, ADMIN), 200)

        assert_subscriber(updated)
        assert updated["do_not_contact"] is True
        assert updated["email"] == subscriber["email"]
        assert updated["acquisition_channel"] == "ORGANIC"
        assert updated["first_subscribed_at"] is None
        assert updated["tenure_days"] == 0
        assert updated["churn_type"] == "NONE"
        assert updated["version"] == 2
