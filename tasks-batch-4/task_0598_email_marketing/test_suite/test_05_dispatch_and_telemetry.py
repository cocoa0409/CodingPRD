"""Dispatch, the two independent send dimensions, bounce cascades and automatic suspension."""
from test_helpers import (
    NON_EXISTENT_UUID,
    PLATFORM,
    ApiErrorId,
    add_confirmed_subscribers,
    add_subscriber,
    advance_epoch_to,
    assert_send,
    click_send,
    create_approved_campaign,
    create_audience,
    create_published_template,
    deliver,
    emit,
    event_payload,
    open_send,
    provision_tenant,
    read_audience,
    read_campaign,
    read_send,
    read_subscriber,
    schedule_ok,
    sends_of_campaign,
    setup_dispatched_campaign,
    setup_suspended_account,
    suppressions_of,
    unsubscribe,
    validate_error,
    validate_paginated,
    validate_success,
)

DISPATCH_AT = "2026-05-02T10:00:00Z"


class TestDispatchMinting:
    def test_recipient_who_unsubscribed_after_the_snapshot_is_minted_suppressed(self, api):
        """PRD §3.7: "Each send's initial `delivery_status` is decided per recipient: it is
        `SUPPRESSED` when that subscriber's `consent_state` is no longer exactly `CONFIRMED`, or
        when that subscriber's address now matches a suppression entry of the account — the
        snapshot was frozen at schedule time, and the world may have moved since — and it is
        `QUEUED` otherwise."
        PRD §3.7: "Dispatch mints exactly one send per position of `recipient_snapshot_ids`, in
        snapshot order, each with the campaign's id in `campaign_id` and a null `journey_id`."

        Design: Corner/state_machines/send_created_suppressed_when_recipient_unsubscribes_before_dispatch
        """
        tenant = provision_tenant()
        audience = create_audience(tenant, double_optin_required=False)
        s1 = add_subscriber(audience["id"], "s1@x.com", tenant.author_headers)
        s2 = add_subscriber(audience["id"], "s2@x.com", tenant.author_headers)
        template = create_published_template(tenant)
        campaign = create_approved_campaign(tenant, audience["id"], template["id"])

        scheduled = schedule_ok(tenant, campaign["id"], DISPATCH_AT, 60)
        assert scheduled["recipient_count"] == 2

        unsubscribe(s2)  # after the snapshot was frozen
        summary = advance_epoch_to(DISPATCH_AT)
        assert summary["sends_created"] == 2

        for_s1, _ = validate_paginated(
            api.list_sends(PLATFORM, {"campaign_id": campaign["id"], "subscriber_id": s1["id"]})
        )
        for_s2, _ = validate_paginated(
            api.list_sends(PLATFORM, {"campaign_id": campaign["id"], "subscriber_id": s2["id"]})
        )
        assert for_s1[0]["delivery_status"] == "QUEUED"
        assert for_s2[0]["delivery_status"] == "SUPPRESSED"
        assert read_campaign(campaign["id"])["status"] == "SENDING"
        assert tenant.refresh()["send_credit_balance"] == 98, "the reservation covers both slots"

    def test_dispatch_passes_over_a_suspended_accounts_campaign(self, api):
        """PRD §3.7: "Every campaign in `SCHEDULED` whose `scheduled_at` is at or before the clock,
        and whose account is `ACTIVE`, moves `SCHEDULED → SENDING`; campaigns are taken in ascending
        `scheduled_at` order, ties broken by ascending `created_at`. A campaign belonging to a
        `SUSPENDED` account is passed over entirely — it stays in `SCHEDULED` and mints nothing, and
        will dispatch on a later epoch only if the account is restored."
        PRD §2.10: "Otherwise, take the percentage of scored sends that are `HARD_BOUNCED`, the
        percentage that are `COMPLAINED`, and the percentage that are `SOFT_BOUNCED`, each expressed
        on a 0-to-100 scale. Start from 100, subtract two times the hard-bounce percentage, subtract
        three times the complaint percentage, and subtract one half of the soft-bounce percentage."

        Design: Corner/state_machines/dispatch_skipped_while_account_suspended
        """
        # C2 must already be SCHEDULED before the suspension lands, so schedule it first.
        tenant = provision_tenant()
        aud1 = create_audience(tenant, name="L1", double_optin_required=False)
        aud2 = create_audience(tenant, name="L2", double_optin_required=False)
        add_confirmed_subscribers(aud1["id"], 4, tenant.author_headers, prefix="a")
        add_confirmed_subscribers(aud2["id"], 2, tenant.author_headers, prefix="b")
        template = create_published_template(tenant)
        c1 = create_approved_campaign(tenant, aud1["id"], template["id"], name="C1")
        c2 = create_approved_campaign(tenant, aud2["id"], template["id"], name="C2")
        schedule_ok(tenant, c1["id"], DISPATCH_AT, 60)
        schedule_ok(tenant, c2["id"], "2026-05-03T10:00:00Z", 60)

        advance_epoch_to(DISPATCH_AT)
        sends = sends_of_campaign(c1["id"])
        deliver(sends[0]["id"])
        deliver(sends[1]["id"])
        deliver(sends[2]["id"])
        emit(sends[3]["id"], "HARD_BOUNCE")

        account = tenant.refresh()
        assert account["status"] == "SUSPENDED"
        assert account["suspension_reason"] == "HIGH_HARD_BOUNCE_RATE"
        assert account["sender_reputation_score"] == 50, "raw = 100 - 2.0 * 25"

        summary = advance_epoch_to("2026-05-03T10:00:00Z")
        assert summary["campaigns_dispatched"] == 0
        assert summary["sends_created"] == 0
        assert read_campaign(c2["id"])["status"] == "SCHEDULED"
        assert sends_of_campaign(c2["id"]) == []


class TestBubbleUpToSent:
    def test_campaign_stays_sending_until_every_send_is_terminal(self, api):
        """PRD §3.7: "A campaign leaves `SENDING` by bubble-up rather than by any client action:
        the moment every send of the campaign has reached a terminal `delivery_status`, the campaign
        transitions `SENDING → SENT`. This is evaluated at the end of every epoch dispatch and at the
        end of every telemetry event that changes a send's `delivery_status`. A single `SOFT_BOUNCED`
        send is enough to hold the campaign in `SENDING` indefinitely."
        PRD §3.7: "When the campaign reaches `SENT`, its `reserved_credit_count` is retained — the
        reservation is not released, it *moves*: `reserved_send_credits` and `consumed_send_credits`
        are both recomputed, so the amount migrates from the reserved bucket to the consumed bucket
        while `send_credit_balance` does not change."

        Design: Corner/state_machines/campaign_bubbles_to_sent_only_when_all_sends_terminal
        """
        env = setup_dispatched_campaign(num_subscribers=2)

        deliver(env.send_ids[0])
        assert read_campaign(env.campaign_id)["status"] == "SENDING", "one send is still QUEUED"

        emit(env.send_ids[1], "SOFT_BOUNCE")
        assert read_campaign(env.campaign_id)["status"] == "SENDING", "SOFT_BOUNCED is non-terminal"

        deliver(env.send_ids[1])
        assert read_campaign(env.campaign_id)["status"] == "SENT"

        account = env.tenant.refresh()
        assert account["consumed_send_credits"] == 2
        assert account["reserved_send_credits"] == 0
        assert account["send_credit_balance"] == 98


class TestSoftBounceEscalation:
    def test_the_third_soft_bounce_escalates_the_send_to_hard_bounced(self, api):
        """PRD §3.8: "A `SOFT_BOUNCE` event is accepted on a send whose `delivery_status` is
        `QUEUED` or `SOFT_BOUNCED` and increments `soft_bounce_count` by one. While the incremented
        count remains below 3, the send sits (or stays) in `SOFT_BOUNCED` — the transitions
        `QUEUED → SOFT_BOUNCED` and `SOFT_BOUNCED → SOFT_BOUNCED` — and the account's reputation is
        recomputed. On the increment that brings `soft_bounce_count` to 3, the send escalates
        `SOFT_BOUNCED → HARD_BOUNCED` and the full hard-bounce cascade below fires."
        PRD §2.10: "If the account has **at least four** scored sends and the share of those scored
        sends that are `HARD_BOUNCED` is **at least 0.25**, the account's `status` moves from
        `ACTIVE` to `SUSPENDED` and its `suspension_reason` is set to `HIGH_HARD_BOUNCE_RATE`. Both
        comparisons are inclusive: exactly four scored sends of which exactly one hard-bounced (a
        rate of 0.25) *does* suspend the account, while five scored sends of which one hard-bounced
        (a rate of 0.20) does not."

        Design: Corner/state_machines/third_soft_bounce_escalates_send_to_hard_bounced
        """
        env = setup_dispatched_campaign(num_subscribers=1)
        send_id = env.send_ids[0]

        first = emit(send_id, "SOFT_BOUNCE")
        assert first["delivery_status"] == "SOFT_BOUNCED"
        assert first["soft_bounce_count"] == 1

        second = emit(send_id, "SOFT_BOUNCE")
        assert second["delivery_status"] == "SOFT_BOUNCED"
        assert second["soft_bounce_count"] == 2

        third = emit(send_id, "SOFT_BOUNCE")
        assert third["delivery_status"] == "HARD_BOUNCED"
        assert third["soft_bounce_count"] == 3

        assert read_subscriber(env.subscribers[0]["id"])["consent_state"] == "CLEANED"
        assert suppressions_of(env.account_id)[0]["reason"] == "HARD_BOUNCE"
        assert read_campaign(env.campaign_id)["status"] == "SENT"
        assert env.tenant.refresh()["status"] == "ACTIVE", "only 1 scored send, below the floor of 4"


class TestHardBounceCascade:
    def test_hard_bounce_cascades_from_send_through_subscriber_to_audience_and_account(self, api):
        """PRD §3.8: "A `HARD_BOUNCE` event is accepted on a send whose `delivery_status` is
        `QUEUED` or `SOFT_BOUNCED` and drives it straight to `HARD_BOUNCED`. The cascade is four
        links long and every link must fire. Because the send hard-bounced, its subscriber's
        `consent_state` moves to `CLEANED` — from `CONFIRMED` or from `PENDING` alike — and a
        suppression entry with `reason` `HARD_BOUNCE` is written for that account and address unless
        one already exists. Because the subscriber became `CLEANED`, the audience's
        `subscriber_count` is recomputed and falls. Because `subscriber_count` changed, the account's
        `billable_contact_count` is recomputed and falls with it."

        Design: Difficulty/transitive_cascade/hard_bounce_send_to_subscriber_to_audience_to_account
        """
        env = setup_dispatched_campaign(num_subscribers=1)
        subscriber_id = env.subscribers[0]["id"]
        assert read_audience(env.audience_id)["subscriber_count"] == 1
        assert env.tenant.refresh()["billable_contact_count"] == 1

        bounced = emit(env.send_ids[0], "HARD_BOUNCE")

        assert_send(bounced)
        assert bounced["delivery_status"] == "HARD_BOUNCED"  # link 1
        assert read_subscriber(subscriber_id)["consent_state"] == "CLEANED"  # link 2
        assert read_audience(env.audience_id)["subscriber_count"] == 0  # link 3
        assert env.tenant.refresh()["billable_contact_count"] == 0  # link 4

    def test_hard_bounce_writes_the_suppression_row_and_zeroes_the_reputation(self, api):
        """PRD §3.8: "And the account's `sender_reputation_score` is recomputed and the suspension
        threshold of §2.10 evaluated on the same event, which is where an account with at least four
        scored sends and a hard-bounce share of at least 0.25 flips `ACTIVE → SUSPENDED` with
        `suspension_reason` `HIGH_HARD_BOUNCE_RATE`. If every send of the parent campaign is now
        terminal, the campaign bubbles to `SENT`."
        PRD §2.10: "Otherwise, take the percentage of scored sends that are `HARD_BOUNCED`, the
        percentage that are `COMPLAINED`, and the percentage that are `SOFT_BOUNCED`, each expressed
        on a 0-to-100 scale. Start from 100, subtract two times the hard-bounce percentage, subtract
        three times the complaint percentage, and subtract one half of the soft-bounce percentage.
        Round that raw value half up to a whole number and clamp it into 0 through 100."

        Design: Difficulty/transitive_cascade/hard_bounce_send_to_subscriber_to_audience_to_account
        """
        env = setup_dispatched_campaign(num_subscribers=1)

        emit(env.send_ids[0], "HARD_BOUNCE")

        entries = suppressions_of(env.account_id)
        assert len(entries) == 1
        assert entries[0]["email"] == "s1@x.com"
        assert entries[0]["reason"] == "HARD_BOUNCE"

        account = env.tenant.refresh()
        assert account["sender_reputation_score"] == 0, "raw = 100 - 2.0 * 100, clamped to 0"
        assert account["status"] == "ACTIVE", "1 scored send is below the 4-send floor"
        assert read_campaign(env.campaign_id)["status"] == "SENT", "HARD_BOUNCED is terminal"

    def test_exactly_four_scored_sends_with_one_hard_bounce_suspends_the_account(self, api):
        """PRD §2.10: "If the account has **at least four** scored sends and the share of those
        scored sends that are `HARD_BOUNCED` is **at least 0.25**, the account's `status` moves from
        `ACTIVE` to `SUSPENDED` and its `suspension_reason` is set to `HIGH_HARD_BOUNCE_RATE`. Both
        comparisons are inclusive: exactly four scored sends of which exactly one hard-bounced (a
        rate of 0.25) *does* suspend the account, while five scored sends of which one hard-bounced
        (a rate of 0.20) does not."

        Design: Corner/cross_cutting_layers/hard_bounce_rate_exactly_at_threshold_suspends_account
        """
        env = setup_suspended_account()
        account = env["tenant"].refresh()

        assert account["status"] == "SUSPENDED", "1/4 == 0.25 meets the inclusive threshold"
        assert account["suspension_reason"] == "HIGH_HARD_BOUNCE_RATE"
        assert account["sender_reputation_score"] == 50, "raw = 100 - 2.0 * 25"
        assert read_campaign(env["campaign_1"]["id"])["status"] == "SENT"


class TestIndependentSendDimensions:
    def test_a_complaint_leaves_the_engagement_axis_at_clicked(self, api):
        """PRD §3.8: "A `COMPLAINT` event is accepted only on a send whose `delivery_status` is
        exactly `DELIVERED`, and drives `DELIVERED → COMPLAINED`. The send's `engagement_status` is
        left exactly as it was — a contact who opened, clicked and *then* complained keeps
        `CLICKED`, because the two dimensions genuinely do not constrain each other."
        PRD §3.7: "Each send then carries **two independent state dimensions on the same row**, and
        neither constrains the other beyond one gate."

        Design: Difficulty/non_linear_state_machine/send_delivery_and_engagement_dimensions_advance_independently
        """
        env = setup_dispatched_campaign(num_subscribers=1)
        send_id = env.send_ids[0]

        deliver(send_id)
        open_send(send_id)
        click_send(send_id)
        complained = emit(send_id, "COMPLAINT")

        assert complained["delivery_status"] == "COMPLAINED"
        assert complained["engagement_status"] == "CLICKED", "the engagement axis is untouched"
        assert complained["open_count"] == 1
        assert complained["click_count"] == 1

    def test_a_complaint_unsubscribes_the_contact_and_suppresses_the_address(self, api):
        """PRD §3.8: "The subscriber moves `CONFIRMED → UNSUBSCRIBED` with `unsubscribed_at`
        stamped, a suppression entry with `reason` `COMPLAINT` is written unless one already exists
        for that account and address, and the account's `sender_reputation_score` is recomputed."
        PRD §3.7: "A campaign leaves `SENDING` by bubble-up rather than by any client action: the
        moment every send of the campaign has reached a terminal `delivery_status`, the campaign
        transitions `SENDING → SENT`."

        Design: Difficulty/non_linear_state_machine/send_delivery_and_engagement_dimensions_advance_independently
        """
        env = setup_dispatched_campaign(num_subscribers=1)
        send_id = env.send_ids[0]

        deliver(send_id)
        open_send(send_id)
        click_send(send_id)
        emit(send_id, "COMPLAINT")

        assert read_subscriber(env.subscribers[0]["id"])["consent_state"] == "UNSUBSCRIBED"
        assert suppressions_of(env.account_id)[0]["reason"] == "COMPLAINT"
        assert read_campaign(env.campaign_id)["status"] == "SENT"

    def test_a_click_on_an_unopened_send_is_refused(self, api):
        """PRD §3.8: "A `CLICK` event requires `delivery_status` to be `DELIVERED` and requires the
        send's `engagement_status` to already be `OPENED` or `CLICKED`; a click on a send still in
        `NOT_OPENED` is refused with `ERR_CLICK_WITHOUT_OPEN`."

        Design: Corner/validations/click_without_open_rejected
        """
        env = setup_dispatched_campaign(num_subscribers=1)
        send_id = env.send_ids[0]
        deliver(send_id)

        resp = api.emit_event(event_payload(send_id, "CLICK"), PLATFORM)
        validate_error(resp, ApiErrorId.ERR_CLICK_WITHOUT_OPEN.value)

        after = read_send(send_id)
        assert after["engagement_status"] == "NOT_OPENED"
        assert after["click_count"] == 0

    def test_an_event_against_an_unknown_send_is_a_not_found(self, api):
        """PRD §3.8: "An unknown `send_id` is refused with `ERR_SEND_NOT_FOUND`, and an event whose
        kind is not admissible from the send's current state is refused with `ERR_INVALID_STATE`."

        Design: Corner/errors/err_send_not_found_on_event_emit
        """
        resp = api.emit_event(event_payload(NON_EXISTENT_UUID, "DELIVERED"), PLATFORM)
        validate_error(resp, ApiErrorId.ERR_SEND_NOT_FOUND.value)
