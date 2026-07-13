"""Scheduling gates, the four-step dispatch price, credit reservation and cancellation."""
from test_helpers import (
    PLATFORM,
    ApiErrorId,
    add_confirmed_subscribers,
    add_subscriber,
    advance_epoch_to,
    assert_campaign,
    confirm_subscriber,
    create_approved_campaign,
    create_audience,
    create_campaign,
    create_published_template,
    create_segment,
    deliver,
    emit,
    provision_tenant,
    read_audience,
    read_campaign,
    read_send,
    run_import,
    schedule,
    schedule_ok,
    schedule_payload,
    sends_of_campaign,
    setup_approved_campaign,
    setup_dispatched_campaign,
    setup_suspended_account,
    unsubscribe,
    validate_error,
    validate_success,
)

FUTURE = "2026-05-02T10:00:00Z"


class TestScheduleGateOrdering:
    def test_draft_campaign_reports_not_approved_rather_than_missing_credits(self, api):
        """PRD §3.6: "The campaign must be in `APPROVED`, or the request is refused with
        `ERR_CAMPAIGN_NOT_APPROVED`."
        PRD §3.6: "The account's `send_credit_balance` must be greater than or equal to the
        recipient count, or the request is refused with `ERR_INSUFFICIENT_SEND_CREDITS` — the last
        check to run, after everything above has passed."
        PRD §2.5: "When several rules could reject the same request, the rule that fires is always
        the earliest one in the following sequence. Implementations must not report a later failure
        while an earlier one is also true."

        Design: Difficulty/priority_pair_validation_conflict/schedule_state_precedes_fiscal_not_approved_over_credits
        """
        tenant = provision_tenant(plan_tier="FREE", initial_send_credits=0)
        audience = create_audience(tenant, double_optin_required=False)
        add_confirmed_subscribers(audience["id"], 2, tenant.author_headers)
        template = create_published_template(tenant)
        # Never submitted for review — the campaign is still DRAFT, and the account holds
        # 0 credits, so the fiscal rule would also fail.
        campaign = create_campaign(tenant, audience["id"], template["id"])

        resp = api.schedule_campaign(
            campaign["id"], schedule_payload(FUTURE, tenant.version, 60), tenant.author_headers
        )
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_APPROVED.value)

    def test_rejected_draft_schedule_leaves_campaign_and_ledger_untouched(self, api):
        """PRD §3.6: "The campaign must be in `APPROVED`, or the request is refused with
        `ERR_CAMPAIGN_NOT_APPROVED`."
        PRD §3.6: "On success the campaign moves `APPROVED → SCHEDULED`: `reserved_credit_count`
        is set to the recipient count, the same amount is subtracted from `send_credit_balance`,
        `reserved_send_credits` is recomputed, and the account's `version` increments by one —
        which is exactly why the next schedule against the same account needs a freshly read
        `expected_account_version`."

        Design: Difficulty/priority_pair_validation_conflict/schedule_state_precedes_fiscal_not_approved_over_credits
        """
        tenant = provision_tenant(plan_tier="FREE", initial_send_credits=0)
        audience = create_audience(tenant, double_optin_required=False)
        add_confirmed_subscribers(audience["id"], 2, tenant.author_headers)
        template = create_published_template(tenant)
        campaign = create_campaign(tenant, audience["id"], template["id"])

        validate_error(
            api.schedule_campaign(
                campaign["id"], schedule_payload(FUTURE, tenant.version, 60), tenant.author_headers
            ),
            ApiErrorId.ERR_CAMPAIGN_NOT_APPROVED.value,
        )

        after = read_campaign(campaign["id"])
        assert after["status"] == "DRAFT"
        assert after["recipient_count"] == 0
        assert tenant.refresh()["send_credit_balance"] == 0

    def test_past_scheduled_at_is_reported_before_the_empty_recipient_set(self, api):
        """PRD §3.6: "`scheduled_at` must be strictly after the clock, or it is refused with
        `ERR_SCHEDULE_IN_PAST`."
        PRD §2.5: "And on that same request the credit check is dead last: a schedule that is
        simultaneously in the past and unaffordable reports `ERR_SCHEDULE_IN_PAST`."
        PRD §2.5: "When several rules could reject the same request, the rule that fires is always
        the earliest one in the following sequence. Implementations must not report a later failure
        while an earlier one is also true."

        Design: Corner/validations/schedule_in_past_precedes_empty_recipient_set
        """
        tenant = provision_tenant()
        audience = create_audience(tenant, double_optin_required=False)
        add_confirmed_subscribers(audience["id"], 1, tenant.author_headers)
        segment = create_segment(
            audience["id"], tenant.author_headers, name="SEG", min_engagement_score=90
        )
        assert segment["member_count"] == 0, "the only contact scores 50, below the floor of 90"
        template = create_published_template(tenant)
        campaign = create_approved_campaign(
            tenant, audience["id"], template["id"], segment_id=segment["id"]
        )

        resp = api.schedule_campaign(
            campaign["id"],
            schedule_payload("2026-04-01T00:00:00Z", tenant.version, 60),
            tenant.author_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_IN_PAST.value)
        assert read_campaign(campaign["id"])["status"] == "APPROVED"

    def test_empty_recipient_set_blocks_a_future_schedule(self, api):
        """PRD §3.6: "`recipient_count` is the length of that list. If it is 0, the whole request
        is refused with `ERR_EMPTY_RECIPIENT_SET`."

        Design: Corner/validations/empty_recipient_set_blocks_schedule
        """
        tenant = provision_tenant()
        audience = create_audience(tenant, double_optin_required=False)
        add_confirmed_subscribers(audience["id"], 1, tenant.author_headers)
        segment = create_segment(
            audience["id"], tenant.author_headers, name="SEG", min_engagement_score=90
        )
        template = create_published_template(tenant)
        campaign = create_approved_campaign(
            tenant, audience["id"], template["id"], segment_id=segment["id"]
        )

        resp = api.schedule_campaign(
            campaign["id"], schedule_payload(FUTURE, tenant.version, 60), tenant.author_headers
        )
        validate_error(resp, ApiErrorId.ERR_EMPTY_RECIPIENT_SET.value)

        assert read_campaign(campaign["id"])["status"] == "APPROVED"
        assert tenant.refresh()["send_credit_balance"] == 100

    def test_insufficient_send_credits_blocks_the_schedule(self, api):
        """PRD §3.6: "The account's `send_credit_balance` must be greater than or equal to the
        recipient count, or the request is refused with `ERR_INSUFFICIENT_SEND_CREDITS` — the last
        check to run, after everything above has passed."

        Design: Corner/validations/insufficient_send_credits_blocks_schedule
        """
        env = setup_approved_campaign(num_subscribers=2, initial_send_credits=1)

        resp = schedule(env.tenant, env.campaign["id"], FUTURE, 60)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_SEND_CREDITS.value)

        after = read_campaign(env.campaign["id"])
        assert after["status"] == "APPROVED"
        assert after["reserved_credit_count"] == 0
        assert env.tenant.refresh()["send_credit_balance"] == 1

    def test_suspended_account_may_not_schedule_a_further_campaign(self, api):
        """PRD §2.10: "While an account is `SUSPENDED`, its `status` is `SUSPENDED`,
        `suspension_reason` is non-null, its scheduled campaigns are no longer dispatched by the
        operations epoch and remain `SCHEDULED`, and any attempt to schedule a further campaign is
        refused with `ERR_ACCOUNT_SUSPENDED`."
        PRD §3.6: "The account must be `ACTIVE`, or it is refused with `ERR_ACCOUNT_SUSPENDED`."

        Design: Corner/errors/err_account_suspended_blocks_new_schedule
        """
        env = setup_suspended_account(num_extra_subscribers=2)
        tenant = env["tenant"]
        assert tenant.refresh()["status"] == "SUSPENDED"

        campaign_2 = create_approved_campaign(
            tenant, env["audience_2"]["id"], env["template"]["id"], name="C2"
        )
        resp = schedule(tenant, campaign_2["id"], "2026-05-03T10:00:00Z", 60)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_SUSPENDED.value)

        assert read_campaign(campaign_2["id"])["status"] == "APPROVED"
        assert tenant.refresh()["send_credit_balance"] == 96, "only C1's 4 credits ever left"


class TestOptimisticConcurrencyOnSchedule:
    def test_second_schedule_with_a_stale_account_version_is_rejected(self, api):
        """PRD §2.6: "Scheduling a campaign requires `expected_account_version` in the request
        body, carrying the `version` of the owning `Account` as the client last read it. If that
        value does not equal the account's current `version`, the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."
        PRD §2.6: "Two different `APPROVED` campaigns may each legitimately be scheduled, so no
        state precondition rejects the second request — only the stale-version check does."

        Design: Corner/cross_cutting_layers/occ_stale_account_version_on_schedule_returns_412
        """
        tenant = provision_tenant()
        audience = create_audience(tenant, double_optin_required=False)
        add_confirmed_subscribers(audience["id"], 2, tenant.author_headers)
        template = create_published_template(tenant)
        c1 = create_approved_campaign(tenant, audience["id"], template["id"], name="C1")
        c2 = create_approved_campaign(tenant, audience["id"], template["id"], name="C2")

        captured_version = tenant.version

        first = validate_success(
            api.schedule_campaign(
                c1["id"], schedule_payload(FUTURE, captured_version, 60), tenant.author_headers
            )
        )
        assert first["status"] == "SCHEDULED"

        resp = api.schedule_campaign(
            c2["id"],
            schedule_payload("2026-05-02T20:00:00Z", captured_version, 60),
            tenant.author_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)

        after = read_campaign(c2["id"])
        assert after["status"] == "APPROVED"
        assert after["reserved_credit_count"] == 0
        assert tenant.refresh()["send_credit_balance"] == 98


class TestRecipientSnapshot:
    def test_snapshot_admits_only_confirmed_unsuppressed_contacts(self, api):
        """PRD §3.6: "Start from the subscribers of the campaign's audience whose `consent_state`
        is exactly `CONFIRMED` — and note that this filter is applied first and is not overridable,
        so a `PENDING` or `UNSUBSCRIBED` contact never receives a campaign email even when the
        campaign's segment lists those states as admissible."
        PRD §3.6: "Then drop every contact whose address matches a suppression entry of the
        campaign's account."
        PRD §3.2: "Its `subscriber_count` is derived, never supplied: it counts the audience's
        subscribers whose `consent_state` is `PENDING`, `CONFIRMED` or `UNSUBSCRIBED`."

        Design: Corner/calculations/recipient_snapshot_excludes_pending_and_suppressed
        """
        tenant = provision_tenant()
        audience = create_audience(tenant, double_optin_required=True)

        s1 = add_subscriber(audience["id"], "s1@x.com", tenant.author_headers, "SIGNUP_FORM")
        confirm_subscriber(s1)
        add_subscriber(audience["id"], "s2@x.com", tenant.author_headers, "SIGNUP_FORM")  # PENDING
        s3 = add_subscriber(audience["id"], "s3@x.com", tenant.author_headers, "SIGNUP_FORM")
        confirm_subscriber(s3)
        unsubscribe(s3)

        template = create_published_template(tenant)
        campaign = create_approved_campaign(tenant, audience["id"], template["id"])

        scheduled = schedule_ok(tenant, campaign["id"], FUTURE, 60)
        assert_campaign(scheduled)
        assert scheduled["recipient_count"] == 1, "only the CONFIRMED, unsuppressed contact"
        assert scheduled["reserved_credit_count"] == 1

        assert read_audience(audience["id"])["subscriber_count"] == 3
        assert tenant.refresh()["send_credit_balance"] == 99

    def test_schedule_response_already_carries_every_derived_field(self, api):
        """PRD §3.6: "On success the campaign moves `APPROVED → SCHEDULED`: `reserved_credit_count`
        is set to the recipient count, the same amount is subtracted from `send_credit_balance`,
        `reserved_send_credits` is recomputed, and the account's `version` increments by one —
        which is exactly why the next schedule against the same account needs a freshly read
        `expected_account_version`."
        PRD §3.6: "**Step four** assembles the charge: round the raw subtotal half up to a whole
        cent, subtract the discount, add the surcharge."

        Design: Corner/consistency_model/schedule_response_reflects_all_derived_fields_immediately
        """
        env = setup_approved_campaign(num_subscribers=2)

        scheduled = schedule_ok(env.tenant, env.campaign["id"], FUTURE, 60)

        assert scheduled["status"] == "SCHEDULED"
        assert scheduled["recipient_count"] == 2
        assert scheduled["reserved_credit_count"] == 2
        # subtotal_raw = 2 * 2.8 = 5.6 -> discount tier below 20 cents -> 0; score 100 -> no
        # surcharge; round_half_up(5.6) = 6.
        assert scheduled["send_charge_cents"] == 6

        account = env.tenant.refresh()
        assert account["send_credit_balance"] == 98
        assert account["reserved_send_credits"] == 2
        assert account["consumed_send_credits"] == 0


class TestDispatchPricing:
    def test_volume_rate_drops_at_eleven_recipients(self, api):
        """PRD §3.6: "**Step one** picks a per-email rate keyed on the recipient count: 2.8 cents
        each when the count is 10 or fewer, 2.2 cents each when it is between 11 and 50 inclusive,
        and 1.6 cents each when it is 51 or more."
        PRD §3.6: "**Step two** derives a volume discount from that raw, pre-surcharge subtotal —
        never from the campaign's final total, which would be circular: the discount is 0 percent
        when the raw subtotal is below 20 cents, 5 percent when it is at least 20 and below 40
        cents, and 10 percent when it is 40 cents or more."
        PRD §3.6: "**Step four** assembles the charge: round the raw subtotal half up to a whole
        cent, subtract the discount, add the surcharge."

        Design: Corner/calculations/send_charge_volume_tier_switches_at_eleven_recipients
        """
        tenant = provision_tenant(plan_tier="STANDARD")
        audience = create_audience(tenant, double_optin_required=False)
        run_import(
            audience["id"],
            [f"r{i:02d}@x.com" for i in range(1, 12)],
            tenant.author_headers,
        )
        template = create_published_template(tenant)
        campaign = create_approved_campaign(tenant, audience["id"], template["id"])
        assert tenant.refresh()["sender_reputation_score"] == 100

        scheduled = schedule_ok(tenant, campaign["id"], FUTURE, 60)

        assert scheduled["recipient_count"] == 11
        # subtotal_raw = 11 * 2.2 = 24.2 -> 5% discount -> round_half_up(1.21) = 1;
        # reputation 100 -> no surcharge; round_half_up(24.2) = 24; 24 - 1 + 0 = 23.
        assert scheduled["send_charge_cents"] == 23
        assert tenant.refresh()["send_credit_balance"] == 89

    def test_discount_tier_is_keyed_on_the_presurcharge_subtotal(self, api):
        """PRD §3.6: "**Step two** derives a volume discount from that raw, pre-surcharge subtotal
        — never from the campaign's final total, which would be circular: the discount is 0 percent
        when the raw subtotal is below 20 cents, 5 percent when it is at least 20 and below 40
        cents, and 10 percent when it is 40 cents or more."
        PRD §3.6: "**Step three** derives a reputation surcharge from the account's
        `sender_reputation_score` as it stands right now: 0 percent when the score is 90 or above,
        5 percent when it is at least 70 and below 90, and 20 percent when it is below 70."
        PRD §3.6: "**Step four** assembles the charge: round the raw subtotal half up to a whole
        cent, subtract the discount, add the surcharge."

        Design: Difficulty/combinatorial_formula/campaign_send_charge_discount_keyed_on_presurcharge_subtotal
        """
        env = _seven_recipient_account_at_reputation_80()
        tenant, audience, template = env["tenant"], env["audience"], env["template"]

        c2 = create_approved_campaign(tenant, audience["id"], template["id"], name="C2")
        scheduled = schedule_ok(tenant, c2["id"], "2026-05-02T18:00:00Z", 60)

        assert scheduled["recipient_count"] == 7
        # subtotal_raw = 7 * 2.8 = 19.6 -> below 20 -> 0% discount -> 0 cents.
        # reputation 80 -> 5% surcharge on (19.6 - 0) -> round_half_up(0.98) = 1.
        # round_half_up(19.6) = 20; 20 - 0 + 1 = 21.  (The circular reading yields 20.)
        assert scheduled["send_charge_cents"] == 21
        assert scheduled["status"] == "SCHEDULED"

    def test_reputation_at_schedule_time_prices_the_dispatch(self, api):
        """PRD §3.6: "**Step three** derives a reputation surcharge from the account's
        `sender_reputation_score` as it stands right now: 0 percent when the score is 90 or above,
        5 percent when it is at least 70 and below 90, and 20 percent when it is below 70."
        PRD §2.10: "Otherwise, take the percentage of scored sends that are `HARD_BOUNCED`, the
        percentage that are `COMPLAINED`, and the percentage that are `SOFT_BOUNCED`, each expressed
        on a 0-to-100 scale. Start from 100, subtract two times the hard-bounce percentage, subtract
        three times the complaint percentage, and subtract one half of the soft-bounce percentage."

        Design: Difficulty/combinatorial_formula/campaign_send_charge_discount_keyed_on_presurcharge_subtotal
        """
        env = _seven_recipient_account_at_reputation_80()
        tenant, audience, template = env["tenant"], env["audience"], env["template"]

        # 5 scored sends: 3 DELIVERED, 2 SOFT_BOUNCED -> raw = 100 - 0.5 * 40 = 80.
        assert tenant.refresh()["sender_reputation_score"] == 80

        c2 = create_approved_campaign(tenant, audience["id"], template["id"], name="C2")
        schedule_ok(tenant, c2["id"], "2026-05-02T18:00:00Z", 60)

        assert tenant.refresh()["send_credit_balance"] == 88, "100 - 5 (C1) - 7 (C2)"


def _seven_recipient_account_at_reputation_80() -> dict:
    """STANDARD account whose first campaign left 3 DELIVERED and 2 SOFT_BOUNCED sends
    (sender_reputation_score 80), and whose audience now holds 7 CONFIRMED contacts."""
    tenant = provision_tenant(plan_tier="STANDARD")
    audience = create_audience(tenant, double_optin_required=False)
    add_confirmed_subscribers(audience["id"], 5, tenant.author_headers)
    template = create_published_template(tenant)

    c1 = create_approved_campaign(tenant, audience["id"], template["id"], name="C1")
    schedule_ok(tenant, c1["id"], FUTURE, 60)
    advance_epoch_to(FUTURE)
    sends = sends_of_campaign(c1["id"])
    deliver(sends[0]["id"])
    deliver(sends[1]["id"])
    deliver(sends[2]["id"])
    emit(sends[3]["id"], "SOFT_BOUNCE")
    emit(sends[4]["id"], "SOFT_BOUNCE")

    add_subscriber(audience["id"], "s6@x.com", tenant.author_headers)
    add_subscriber(audience["id"], "s7@x.com", tenant.author_headers)
    return {"tenant": tenant, "audience": audience, "template": template, "campaign_1": c1}


class TestAudienceFatigueBuffer:
    def test_a_gap_of_exactly_six_hours_is_allowed(self, api):
        """PRD §3.6: "**Audience fatigue** treats scheduled dispatches on the same list as point
        events: for every other campaign of the same `audience_id` whose `status` is `SCHEDULED` or
        `SENDING`, the absolute gap between its `scheduled_at` and this one must be at least 6
        hours. A gap of strictly less than 6 hours is refused with `ERR_AUDIENCE_FATIGUE_CONFLICT`;
        a gap of exactly 6 hours is allowed."

        Design: Difficulty/boundary_precision_check/fatigue_buffer_exactly_six_hours_boundary
        """
        tenant = provision_tenant()
        audience = create_audience(tenant, double_optin_required=False)
        add_confirmed_subscribers(audience["id"], 2, tenant.author_headers)
        template = create_published_template(tenant)
        c1 = create_approved_campaign(tenant, audience["id"], template["id"], name="C1")
        c2 = create_approved_campaign(tenant, audience["id"], template["id"], name="C2")

        schedule_ok(tenant, c1["id"], "2026-05-02T10:00:00Z", 60)
        second = schedule_ok(tenant, c2["id"], "2026-05-02T16:00:00Z", 60)

        assert second["status"] == "SCHEDULED", "exactly 6h after C1 — the rule uses a strict `<`"

    def test_a_gap_of_five_hours_fifty_nine_minutes_is_refused(self, api):
        """PRD §3.6: "**Audience fatigue** treats scheduled dispatches on the same list as point
        events: for every other campaign of the same `audience_id` whose `status` is `SCHEDULED` or
        `SENDING`, the absolute gap between its `scheduled_at` and this one must be at least 6
        hours. A gap of strictly less than 6 hours is refused with `ERR_AUDIENCE_FATIGUE_CONFLICT`;
        a gap of exactly 6 hours is allowed."

        Design: Difficulty/boundary_precision_check/fatigue_buffer_exactly_six_hours_boundary
        """
        tenant = provision_tenant()
        audience = create_audience(tenant, double_optin_required=False)
        add_confirmed_subscribers(audience["id"], 2, tenant.author_headers)
        template = create_published_template(tenant)
        c1 = create_approved_campaign(tenant, audience["id"], template["id"], name="C1")
        c2 = create_approved_campaign(tenant, audience["id"], template["id"], name="C2")
        c3 = create_approved_campaign(tenant, audience["id"], template["id"], name="C3")

        schedule_ok(tenant, c1["id"], "2026-05-02T10:00:00Z", 60)
        schedule_ok(tenant, c2["id"], "2026-05-02T16:00:00Z", 60)

        resp = schedule(tenant, c3["id"], "2026-05-02T15:59:00Z", 60)
        validate_error(resp, ApiErrorId.ERR_AUDIENCE_FATIGUE_CONFLICT.value)

        after = read_campaign(c3["id"])
        assert after["status"] == "APPROVED"
        assert after["recipient_count"] == 0
        assert tenant.refresh()["send_credit_balance"] == 96, "only C1 and C2 reserved 2 each"

    def test_four_hour_gap_conflicts_even_though_the_send_windows_are_disjoint(self, api):
        """PRD §3.6: "**Audience fatigue** treats scheduled dispatches on the same list as point
        events: for every other campaign of the same `audience_id` whose `status` is `SCHEDULED` or
        `SENDING`, the absolute gap between its `scheduled_at` and this one must be at least 6
        hours. A gap of strictly less than 6 hours is refused with `ERR_AUDIENCE_FATIGUE_CONFLICT`;
        a gap of exactly 6 hours is allowed."

        Design: Difficulty/resource_temporal_overlap/audience_fatigue_point_buffer_conflict
        """
        tenant = provision_tenant()
        audience = create_audience(tenant, double_optin_required=False)
        add_confirmed_subscribers(audience["id"], 3, tenant.author_headers)
        template = create_published_template(tenant)
        c1 = create_approved_campaign(tenant, audience["id"], template["id"], name="C1")
        c2 = create_approved_campaign(tenant, audience["id"], template["id"], name="C2")

        schedule_ok(tenant, c1["id"], "2026-05-02T10:00:00Z", 60)

        # The two 60-minute windows do not overlap at all — the point-buffer rule still bites.
        resp = schedule(tenant, c2["id"], "2026-05-02T14:00:00Z", 60)
        validate_error(resp, ApiErrorId.ERR_AUDIENCE_FATIGUE_CONFLICT.value)

    def test_fatigue_rejection_reserves_no_credits(self, api):
        """PRD §3.6: "**Audience fatigue** treats scheduled dispatches on the same list as point
        events: for every other campaign of the same `audience_id` whose `status` is `SCHEDULED` or
        `SENDING`, the absolute gap between its `scheduled_at` and this one must be at least 6
        hours. A gap of strictly less than 6 hours is refused with `ERR_AUDIENCE_FATIGUE_CONFLICT`;
        a gap of exactly 6 hours is allowed."
        PRD §3.6: "On success the campaign moves `APPROVED → SCHEDULED`: `reserved_credit_count`
        is set to the recipient count, the same amount is subtracted from `send_credit_balance`,
        `reserved_send_credits` is recomputed, and the account's `version` increments by one —
        which is exactly why the next schedule against the same account needs a freshly read
        `expected_account_version`."

        Design: Difficulty/resource_temporal_overlap/audience_fatigue_point_buffer_conflict
        """
        tenant = provision_tenant()
        audience = create_audience(tenant, double_optin_required=False)
        add_confirmed_subscribers(audience["id"], 3, tenant.author_headers)
        template = create_published_template(tenant)
        c1 = create_approved_campaign(tenant, audience["id"], template["id"], name="C1")
        c2 = create_approved_campaign(tenant, audience["id"], template["id"], name="C2")

        schedule_ok(tenant, c1["id"], "2026-05-02T10:00:00Z", 60)
        validate_error(
            schedule(tenant, c2["id"], "2026-05-02T14:00:00Z", 60),
            ApiErrorId.ERR_AUDIENCE_FATIGUE_CONFLICT.value,
        )

        after = read_campaign(c2["id"])
        assert after["status"] == "APPROVED"
        assert after["recipient_count"] == 0
        assert after["reserved_credit_count"] == 0
        assert tenant.refresh()["send_credit_balance"] == 97, "only C1's 3 credits are reserved"


class TestAccountSendWindowCapacity:
    def test_overlapping_half_open_windows_exceed_the_account_capacity(self, api):
        """PRD §3.6: "**Send-window capacity** treats dispatches on the same account as intervals:
        a campaign occupies the half-open interval that begins at its `scheduled_at` and ends
        `send_window_minutes` later, so two windows that merely touch end-to-end do not overlap.
        Sum `recipient_count` across every campaign of the account whose `status` is `SCHEDULED` or
        `SENDING` and whose window overlaps this campaign's window, add this campaign's own
        recipient count, and the total must not exceed `hourly_send_capacity`. A total strictly
        greater than the capacity is refused with `ERR_SEND_CAPACITY_EXCEEDED`; a total exactly
        equal to it passes."

        Design: Difficulty/resource_temporal_overlap/account_send_window_halfopen_aggregate_capacity
        """
        tenant, aud1, aud2, template, c1, c2 = _two_audience_capacity_five_account()
        schedule_ok(tenant, c1["id"], "2026-05-02T10:00:00Z", 60)

        # [10:00, 11:00) and [10:30, 11:30) overlap -> 3 + 3 = 6 > capacity 5.
        resp = schedule(tenant, c2["id"], "2026-05-02T10:30:00Z", 60)
        validate_error(resp, ApiErrorId.ERR_SEND_CAPACITY_EXCEEDED.value)
        assert read_campaign(c2["id"])["status"] == "APPROVED"

    def test_touching_half_open_windows_do_not_overlap(self, api):
        """PRD §3.6: "**Send-window capacity** treats dispatches on the same account as intervals:
        a campaign occupies the half-open interval that begins at its `scheduled_at` and ends
        `send_window_minutes` later, so two windows that merely touch end-to-end do not overlap.
        Sum `recipient_count` across every campaign of the account whose `status` is `SCHEDULED` or
        `SENDING` and whose window overlaps this campaign's window, add this campaign's own
        recipient count, and the total must not exceed `hourly_send_capacity`. A total strictly
        greater than the capacity is refused with `ERR_SEND_CAPACITY_EXCEEDED`; a total exactly
        equal to it passes."

        Design: Difficulty/resource_temporal_overlap/account_send_window_halfopen_aggregate_capacity
        """
        tenant, aud1, aud2, template, c1, c2 = _two_audience_capacity_five_account()
        schedule_ok(tenant, c1["id"], "2026-05-02T10:00:00Z", 60)
        validate_error(
            schedule(tenant, c2["id"], "2026-05-02T10:30:00Z", 60),
            ApiErrorId.ERR_SEND_CAPACITY_EXCEEDED.value,
        )

        # [11:00, 12:00) only touches [10:00, 11:00) -> no overlap -> 0 + 3 <= 5.
        scheduled = schedule_ok(tenant, c2["id"], "2026-05-02T11:00:00Z", 60)

        assert scheduled["status"] == "SCHEDULED"
        assert scheduled["recipient_count"] == 3
        account = tenant.refresh()
        assert account["send_credit_balance"] == 94
        assert account["reserved_send_credits"] == 6


def _two_audience_capacity_five_account():
    """One account with hourly_send_capacity 5 and two 3-contact audiences, each with an
    APPROVED campaign — so the fatigue rule (same audience) can never fire."""
    tenant = provision_tenant(hourly_send_capacity=5)
    aud1 = create_audience(tenant, name="List One", double_optin_required=False)
    aud2 = create_audience(tenant, name="List Two", double_optin_required=False)
    add_confirmed_subscribers(aud1["id"], 3, tenant.author_headers, prefix="a")
    add_confirmed_subscribers(aud2["id"], 3, tenant.author_headers, prefix="b")
    template = create_published_template(tenant)
    c1 = create_approved_campaign(tenant, aud1["id"], template["id"], name="C1")
    c2 = create_approved_campaign(tenant, aud2["id"], template["id"], name="C2")
    return tenant, aud1, aud2, template, c1, c2


class TestCancellationCascade:
    def test_cancel_from_sending_cancels_the_non_terminal_sends(self, api):
        """PRD §3.6: "A campaign cancelled from `SENDING` cascades further: because the campaign
        became `CANCELLED`, every one of its sends whose `delivery_status` is `QUEUED` or
        `SOFT_BOUNCED` transitions to `CANCELLED`, and such a send is thereafter excluded from
        every reputation and engagement denominator; because those sends were cancelled, the
        campaign releases its *whole original* reservation — `reserved_credit_count` drops to 0;
        because it dropped to 0, that entire released amount is added back to `send_credit_balance`
        and `reserved_send_credits` is recomputed; and the account's `version` increments."
        PRD §3.6: "Sends that had already reached a terminal `delivery_status` — `DELIVERED`,
        `HARD_BOUNCED`, `SUPPRESSED` or `COMPLAINED` — are left exactly as they are, but the full
        original reservation is still returned."

        Design: Difficulty/transitive_cascade/campaign_cancel_to_sends_to_reservation_to_account_balance
        """
        env = setup_dispatched_campaign(num_subscribers=3)
        deliver(env.send_ids[0])

        cancelled = validate_success(
            api.cancel_campaign(env.campaign_id, env.tenant.author_headers)
        )
        assert cancelled["status"] == "CANCELLED"

        assert read_send(env.send_ids[1])["delivery_status"] == "CANCELLED"
        assert read_send(env.send_ids[2])["delivery_status"] == "CANCELLED"
        assert read_send(env.send_ids[0])["delivery_status"] == "DELIVERED", "already terminal"

    def test_cancel_returns_the_whole_reservation_to_the_balance(self, api):
        """PRD §3.6: "A campaign cancelled from `SENDING` cascades further: because the campaign
        became `CANCELLED`, every one of its sends whose `delivery_status` is `QUEUED` or
        `SOFT_BOUNCED` transitions to `CANCELLED`, and such a send is thereafter excluded from
        every reputation and engagement denominator; because those sends were cancelled, the
        campaign releases its *whole original* reservation — `reserved_credit_count` drops to 0;
        because it dropped to 0, that entire released amount is added back to `send_credit_balance`
        and `reserved_send_credits` is recomputed; and the account's `version` increments."
        PRD §2.7: "At every observable instant, `granted_send_credits` equals the balance plus the
        reservations plus the consumption."

        Design: Difficulty/transitive_cascade/campaign_cancel_to_sends_to_reservation_to_account_balance
        """
        env = setup_dispatched_campaign(num_subscribers=3)
        deliver(env.send_ids[0])

        validate_success(api.cancel_campaign(env.campaign_id, env.tenant.author_headers))

        assert read_campaign(env.campaign_id)["reserved_credit_count"] == 0
        account = env.tenant.refresh()
        assert account["send_credit_balance"] == 100
        assert account["reserved_send_credits"] == 0
        assert account["consumed_send_credits"] == 0
