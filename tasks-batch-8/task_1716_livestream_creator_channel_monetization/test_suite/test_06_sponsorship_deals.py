"""Sponsorship deals, deliverable performance/disclosure axes, and clawbacks."""
from test_helpers import (
    ApiErrorId,
    SPONSOR_ACME_ID,
    TEST_USERS,
    assert_deliverable,
    assert_instant_equals,
    create_channel,
    create_deal,
    create_deliverable,
    create_ended_stream,
    create_stream,
    create_verified_channel,
    get_channel,
    get_success_data,
    issue_strike,
    make_creator_headers,
    make_sponsor_headers,
    run_ops,
    set_clock,
    setup_active_deal,
    setup_deal_with_deliverable,
    start_stream,
    transition_deal,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


class TestDealNegotiationAndExclusivity:
    def test_sponsor_cannot_accept_foreign_deal(self, api):
        """PRD §3.7: "The negotiation arc is short. The owner proposes, moving
        the deal from `DRAFT` to `PROPOSED`; the sponsor accepts, moving it
        from `PROPOSED` to `ACCEPTED` — with the sponsor's `X-User-ID` checked
        against `sponsor_ref`, a mismatch drawing `ERR_SPONSOR_MISMATCH` — and
        the owner may cancel from any of `DRAFT`, `PROPOSED`, or `ACCEPTED`,
        moving the deal to the terminal `CANCELLED`."

        Design: Corner/rbac/sponsor_cannot_accept_foreign_deal
        """
        channel = create_channel(handle="rb_sp", home_platform="TWITCH")
        deal = create_deal(channel["id"], sponsor_ref=SPONSOR_ACME_ID,
                           title="D", category="OTHER",
                           total_value_cents=100000)
        transition_deal(deal["id"], "PROPOSE", make_creator_headers(channel["id"]))

        resp = api.transition_deal(deal["id"], {"action": "ACCEPT"},
                                   make_sponsor_headers("sponsor_evil"))
        validate_error(resp, ApiErrorId.ERR_SPONSOR_MISMATCH)

        current = get_success_data(api.get_deal(deal["id"], ADMIN))
        assert current["deal_status"] == "PROPOSED"

    def test_deal_category_exclusivity_closed_interval(self, api):
        """PRD §3.7: "Activation is the gatekeeper's moment, and three
        conditions guard the move from `ACCEPTED` to `ACTIVE`: the channel's
        posture must not be `SUSPENDED` (`ERR_CHANNEL_SUSPENDED`); the clock
        must fall within the closed flight interval — at or after
        `flight_start` and at or before `flight_end` (otherwise
        `ERR_INVALID_STATE`); and category exclusivity must hold, meaning no
        other deal of the channel in `ACCEPTED` or `ACTIVE` status with the
        same `category` may have a closed flight interval intersecting this
        one, where even a shared boundary instant counts as a conflict
        (`ERR_CATEGORY_EXCLUSIVITY_CONFLICT`)."

        Design: Corner/validations/deal_category_exclusivity_closed_interval
        """
        channel, _form = create_verified_channel("val_cat")
        set_clock("2026-08-01T00:00:00Z")
        deal1 = create_deal(channel["id"], title="D1", category="VPN",
                            total_value_cents=100000,
                            flight_start="2026-08-05T00:00:00Z",
                            flight_end="2026-08-20T00:00:00Z")
        transition_deal(deal1["id"], "PROPOSE",
                        make_creator_headers(channel["id"]))
        transition_deal(deal1["id"], "ACCEPT",
                        make_sponsor_headers(SPONSOR_ACME_ID))
        set_clock("2026-08-05T00:00:00Z")
        transition_deal(deal1["id"], "ACTIVATE",
                        make_creator_headers(channel["id"]))

        # Deal2 shares only the boundary instant 2026-08-20 with ACTIVE deal1;
        # it is brought to ACCEPTED after deal1 is ACTIVE so that deal1's own
        # activation above was not itself blocked by this sibling (the PRD's
        # exclusivity gate counts ACCEPTED siblings too).
        deal2 = create_deal(channel["id"], title="D2", category="VPN",
                            total_value_cents=100000,
                            flight_start="2026-08-20T00:00:00Z",
                            flight_end="2026-09-10T00:00:00Z")
        deal3 = create_deal(channel["id"], title="D3", category="OTHER",
                            total_value_cents=100000,
                            flight_start="2026-08-20T00:00:00Z",
                            flight_end="2026-09-10T00:00:00Z")
        for deal in (deal2, deal3):
            transition_deal(deal["id"], "PROPOSE",
                            make_creator_headers(channel["id"]))
            transition_deal(deal["id"], "ACCEPT",
                            make_sponsor_headers(SPONSOR_ACME_ID))

        set_clock("2026-08-20T00:00:00Z")
        conflict = api.transition_deal(deal2["id"], {"action": "ACTIVATE"},
                                       make_creator_headers(channel["id"]))
        validate_error(conflict, ApiErrorId.ERR_CATEGORY_EXCLUSIVITY_CONFLICT)

        activated = transition_deal(deal3["id"], "ACTIVATE",
                                    make_creator_headers(channel["id"]))
        assert activated["deal_status"] == "ACTIVE", (
            "a different category over the same dates activates fine")


class TestDeliverablePerformance:
    def test_deliverable_perform_after_due_rejected(self, api):
        """PRD §3.7: "Performance is the owner's move, requires a `stream_id`
        naming the stream the deliverable was performed in, and is guarded
        three ways: the channel must not be `SUSPENDED`
        (`ERR_CHANNEL_SUSPENDED`), the clock must not have passed `due_at`
        (`ERR_DELIVERABLE_OVERDUE`), and the referenced stream must have
        `stream_status` `ENDED` (`ERR_INVALID_STATE`)."

        Design: Corner/validations/deliverable_perform_after_due_rejected
        """
        channel, _form = create_verified_channel("val_due",
                                                 home_platform="YOUTUBE")
        set_clock("2026-08-01T00:00:00Z")
        deal, deliverable = setup_deal_with_deliverable(
            channel, due_at="2026-08-10T00:00:00Z")
        stream = create_ended_stream(
            channel["id"], scheduled_start="2026-08-08T10:00:00Z",
            scheduled_end="2026-08-08T11:00:00Z")
        set_clock("2026-08-10T00:00:01Z")

        resp = api.transition_deliverable(
            deliverable["id"],
            {"action": "PERFORM", "stream_id": stream["id"]},
            make_creator_headers(channel["id"]))
        validate_error(resp, ApiErrorId.ERR_DELIVERABLE_OVERDUE)

        current = get_success_data(api.get_deliverable(
            deliverable["id"], make_creator_headers(channel["id"])))
        assert current["performance_status"] == "SCHEDULED"
        assert current["performed_at"] is None

    def test_deliverable_perform_rejected_while_stream_live(self, api):
        """PRD §3.7: "Performance is the owner's move, requires a `stream_id`
        naming the stream the deliverable was performed in, and is guarded
        three ways: the channel must not be `SUSPENDED`
        (`ERR_CHANNEL_SUSPENDED`), the clock must not have passed `due_at`
        (`ERR_DELIVERABLE_OVERDUE`), and the referenced stream must have
        `stream_status` `ENDED` (`ERR_INVALID_STATE`)."

        Design: Difficulty/cross_entity_state_dependency/deliverable_perform_requires_ended_stream
        """
        channel, _form = create_verified_channel("ce_strm",
                                                 home_platform="YOUTUBE")
        set_clock("2026-08-01T00:00:00Z")
        deal, deliverable = setup_deal_with_deliverable(
            channel, kind="SPONSORED_SEGMENT", due_at="2026-08-20T00:00:00Z",
            category="GAME_PUBLISHER", total_value_cents=250000)
        stream = create_stream(channel["id"],
                               scheduled_start="2026-08-15T10:00:00Z",
                               scheduled_end="2026-08-15T11:00:00Z")
        set_clock("2026-08-15T10:00:00Z")
        start_stream(stream["id"], channel["id"])
        set_clock("2026-08-15T10:30:00Z")

        resp = api.transition_deliverable(
            deliverable["id"],
            {"action": "PERFORM", "stream_id": stream["id"]},
            make_creator_headers(channel["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        current = get_success_data(api.get_deliverable(
            deliverable["id"], make_creator_headers(channel["id"])))
        assert current["performance_status"] == "SCHEDULED", (
            "a LIVE stream does not admit performance")

    def test_deliverable_perform_succeeds_after_stream_ends(self, api):
        """PRD §3.7: "Performance is the owner's move, requires a `stream_id`
        naming the stream the deliverable was performed in, and is guarded
        three ways: the channel must not be `SUSPENDED`
        (`ERR_CHANNEL_SUSPENDED`), the clock must not have passed `due_at`
        (`ERR_DELIVERABLE_OVERDUE`), and the referenced stream must have
        `stream_status` `ENDED` (`ERR_INVALID_STATE`). A valid performance
        moves the deliverable from `SCHEDULED` to `PERFORMED`, stamps
        `performed_at`, binds the stream, and sets `disclosure_deadline` to
        exactly twenty-four hours after `performed_at`."

        Design: Difficulty/cross_entity_state_dependency/deliverable_perform_requires_ended_stream
        """
        channel, _form = create_verified_channel("ce_strm2",
                                                 home_platform="YOUTUBE")
        set_clock("2026-08-01T00:00:00Z")
        deal, deliverable = setup_deal_with_deliverable(
            channel, kind="SPONSORED_SEGMENT", due_at="2026-08-20T00:00:00Z",
            category="GAME_PUBLISHER", total_value_cents=250000)
        stream = create_ended_stream(
            channel["id"], scheduled_start="2026-08-15T10:00:00Z",
            scheduled_end="2026-08-15T11:00:00Z")
        set_clock("2026-08-15T12:00:00Z")

        performed = validate_success(api.transition_deliverable(
            deliverable["id"],
            {"action": "PERFORM", "stream_id": stream["id"]},
            make_creator_headers(channel["id"])), 200)
        assert_deliverable(performed)
        assert performed["performance_status"] == "PERFORMED"
        assert performed["stream_id"] == stream["id"], "the stream is bound"
        assert_instant_equals(performed["performed_at"], "2026-08-15T12:00:00Z",
                              label="performed_at")
        assert_instant_equals(performed["disclosure_deadline"],
                              "2026-08-16T12:00:00Z",
                              label="disclosure_deadline = performed_at + 24h")


class TestDeliverableParallelAxes:
    def _performed_undisclosed(self, handle, api):
        """ACTIVE deal, stream ended 2026-08-15 10:00-11:00, deliverable
        PERFORMED at 2026-08-15T12:00 with disclosure still PENDING."""
        channel, _form = create_verified_channel(handle,
                                                 home_platform="YOUTUBE")
        set_clock("2026-08-01T00:00:00Z")
        deal, deliverable = setup_deal_with_deliverable(
            channel, kind="AD_READ", due_at="2026-08-20T00:00:00Z",
            category="GAMING_HARDWARE", total_value_cents=6000000)
        stream = create_ended_stream(
            channel["id"], scheduled_start="2026-08-15T10:00:00Z",
            scheduled_end="2026-08-15T11:00:00Z", peak_viewers=200,
            avg_viewers=150)
        set_clock("2026-08-15T12:00:00Z")
        performed = validate_success(api.transition_deliverable(
            deliverable["id"],
            {"action": "PERFORM", "stream_id": stream["id"]},
            make_creator_headers(channel["id"])), 200)
        return channel, deal, performed

    def test_perform_leaves_disclosure_axis_pending(self, api):
        """PRD §3.7: "A deliverable carries **two parallel state dimensions on
        one row**: `performance_status`, walking `SCHEDULED`, `PERFORMED`,
        `VERIFIED`, `MISSED`, and `DISPUTED`, and `disclosure_status`, walking
        `PENDING`, `DISCLOSED_ON_TIME`, `DISCLOSED_LATE`, and `MISSING`."
        PRD §3.7: "Verification belongs to the sponsor, whose `X-User-ID` must
        match `sponsor_ref` (`ERR_SPONSOR_MISMATCH`), and disclosure comes
        first: verification while the disclosure axis is `PENDING` or
        `MISSING` is rejected with `ERR_DISCLOSURE_REQUIRED`, so only
        `DISCLOSED_ON_TIME` or `DISCLOSED_LATE` deliverables can be verified."

        Design: Difficulty/non_linear_state_machine/deliverable_parallel_performance_disclosure_axes
        """
        channel, _deal, performed = self._performed_undisclosed("nl_del", api)
        assert performed["performance_status"] == "PERFORMED"
        assert performed["disclosure_status"] == "PENDING", (
            "the two axes evolve independently on one row")

        blocked = api.transition_deliverable(
            performed["id"], {"action": "VERIFY"},
            make_sponsor_headers(SPONSOR_ACME_ID))
        validate_error(blocked, ApiErrorId.ERR_DISCLOSURE_REQUIRED)

        current = get_success_data(api.get_deliverable(
            performed["id"], make_creator_headers(channel["id"])))
        assert current["performance_status"] == "PERFORMED", (
            "the blocked VERIFY leaves the performance axis untouched")
        assert current["disclosure_status"] == "PENDING"

    def test_disclose_then_verify_reaches_verified(self, api):
        """PRD §3.7: "Disclosure then runs on its own axis. The owner
        discloses a `PERFORMED` deliverable: within the deadline the axis
        moves from `PENDING` to `DISCLOSED_ON_TIME`; past the deadline it
        moves to `DISCLOSED_LATE`."
        PRD §3.7: "Verification moves the deliverable to `VERIFIED` —
        reachable from `PERFORMED` and, after a dispute, from `DISPUTED` —
        and the deal's `verified_deliverable_count` is recomputed."

        Design: Difficulty/non_linear_state_machine/deliverable_parallel_performance_disclosure_axes
        """
        channel, deal, performed = self._performed_undisclosed("nl_del2", api)

        disclosed = validate_success(api.transition_deliverable(
            performed["id"], {"action": "DISCLOSE"},
            make_creator_headers(channel["id"])), 200)
        assert disclosed["disclosure_status"] == "DISCLOSED_ON_TIME", (
            "disclosed within performed_at + 24h")
        assert disclosed["performance_status"] == "PERFORMED"

        verified = validate_success(api.transition_deliverable(
            performed["id"], {"action": "VERIFY"},
            make_sponsor_headers(SPONSOR_ACME_ID)), 200)
        assert verified["performance_status"] == "VERIFIED"
        assert verified["disclosure_status"] == "DISCLOSED_ON_TIME", (
            "the combined terminal resting state keeps the disclosure axis")

        deal_after = get_success_data(api.get_deal(deal["id"], ADMIN))
        assert deal_after["verified_deliverable_count"] == 1


class TestDeliverableSuspendedBeatsOverdue:
    def _suspended_overdue_deliverable(self, handle):
        """Deliverable whose PERFORM attempt is simultaneously overdue and
        under a SUSPENDED channel; the referenced stream is ENDED so the
        state gate cannot fire first."""
        channel, _form = create_verified_channel(handle,
                                                 home_platform="YOUTUBE")
        set_clock("2026-08-01T00:00:00Z")
        deal, deliverable = setup_deal_with_deliverable(
            channel, kind="AD_READ", due_at="2026-08-10T00:00:00Z",
            category="ENERGY_DRINK", total_value_cents=500000)
        stream = create_ended_stream(
            channel["id"], scheduled_start="2026-08-08T10:00:00Z",
            scheduled_end="2026-08-08T11:00:00Z")
        set_clock("2026-08-09T00:00:00Z")
        issue_strike(channel["id"], policy_code="HARASSMENT",
                     severity="SEVERE", evidence_ref="clip://11")
        set_clock("2026-08-12T00:00:00Z")
        return channel, deal, deliverable, stream

    def test_perform_suspended_reports_channel_suspended(self, api):
        """PRD §2.9: "When several checks could reject the same request, they
        are evaluated in the following fixed priority order, so the error a
        caller sees is deterministic:"
        PRD §2.9: "**Suspension gates.** A `SUSPENDED` channel blocks exactly
        five operations — payout opening, payout retry, deal activation,
        deliverable performance, and simulcast-grant approval — each rejected
        with `ERR_CHANNEL_SUSPENDED`." (priority 7)
        PRD §2.9: "**Deliverable timeliness.** Performance after `due_at` is
        rejected with `ERR_DELIVERABLE_OVERDUE`." (priority 15)

        Design: Difficulty/priority_pair_validation_conflict/deliverable_perform_suspended_beats_overdue
        """
        channel, _deal, deliverable, stream = self._suspended_overdue_deliverable(
            "pp_perf")
        assert get_channel(channel["id"])["monetization_posture"] == "SUSPENDED"

        resp = api.transition_deliverable(
            deliverable["id"],
            {"action": "PERFORM", "stream_id": stream["id"]},
            make_creator_headers(channel["id"]))
        validate_error(resp, ApiErrorId.ERR_CHANNEL_SUSPENDED)

    def test_perform_suspended_leaves_deliverable_untouched(self, api):
        """PRD §2.9: "**Suspension gates.** A `SUSPENDED` channel blocks
        exactly five operations — payout opening, payout retry, deal
        activation, deliverable performance, and simulcast-grant approval —
        each rejected with `ERR_CHANNEL_SUSPENDED`."
        PRD §3.7: "A valid performance moves the deliverable from `SCHEDULED`
        to `PERFORMED`, stamps `performed_at`, binds the stream, and sets
        `disclosure_deadline` to exactly twenty-four hours after
        `performed_at`."

        Design: Difficulty/priority_pair_validation_conflict/deliverable_perform_suspended_beats_overdue
        """
        channel, _deal, deliverable, stream = self._suspended_overdue_deliverable(
            "pp_perf2")

        resp = api.transition_deliverable(
            deliverable["id"],
            {"action": "PERFORM", "stream_id": stream["id"]},
            make_creator_headers(channel["id"]))
        validate_error(resp, ApiErrorId.ERR_CHANNEL_SUSPENDED)

        current = get_success_data(api.get_deliverable(
            deliverable["id"], make_creator_headers(channel["id"])))
        assert current["performance_status"] == "SCHEDULED"
        assert current["performed_at"] is None
        assert current["stream_id"] is None


class TestDeliverableMissBreachClawback:
    def _breached_deal(self, handle):
        """ACTIVE deal (value 6000000, 3 required deliverables, all due
        2026-08-06) swept by the ops run at 2026-08-07."""
        channel, _form = create_verified_channel(handle)
        set_clock("2026-08-01T00:00:00Z")
        deal = setup_active_deal(channel, category="VPN",
                                 total_value_cents=6000000,
                                 required_deliverable_count=3,
                                 title="Acme breach")
        for kind in ("AD_READ", "SPONSORED_SEGMENT", "LOGO_PLACEMENT"):
            create_deliverable(deal["id"], channel["id"], kind=kind,
                               due_at="2026-08-06T00:00:00Z")
        set_clock("2026-08-07T00:00:00Z")
        run_ops()
        return channel, deal

    def test_three_misses_breach_the_deal(self, api):
        """PRD §3.7: "Missing a deadline has permanent consequences. Ops step
        6 moves a deliverable still `SCHEDULED` past its `due_at` to `MISSED`
        and increments the deal's `miss_count` by 1. When the count reaches
        three, the deal is breached: it moves from `ACTIVE` to the terminal
        `BREACHED`, and the platform claws the sponsorship back by creating a
        `CHARGEBACK` revenue event whose `gross_cents` is the negation of
        `total_value_cents`, whose `platform_fee_bps` is 1,000, whose
        `reverses_event_id` names the activation-time `SPONSORSHIP` event, and
        whose `recognition_status` is `CLEARED` — the clawback net lands in
        the channel's `balance_payable_cents` immediately, per §3.2."

        Design: Difficulty/transitive_cascade/deliverable_miss_deal_breach_clawback_cascade
        """
        channel, deal = self._breached_deal("tc_breach")

        deal_after = get_success_data(api.get_deal(deal["id"], ADMIN))
        assert deal_after["miss_count"] == 3, (
            "link 1: each of the three MISSED transitions incremented")
        assert deal_after["deal_status"] == "BREACHED", (
            "link 2: the count reaching three transitions the deal")

    def test_breach_clawback_rebalances_payable(self, api):
        """PRD §3.7: "When the count reaches three, the deal is breached: it
        moves from `ACTIVE` to the terminal `BREACHED`, and the platform claws
        the sponsorship back by creating a `CHARGEBACK` revenue event whose
        `gross_cents` is the negation of `total_value_cents`, whose
        `platform_fee_bps` is 1,000, whose `reverses_event_id` names the
        activation-time `SPONSORSHIP` event, and whose
        `recognition_status` is `CLEARED` — the clawback net lands in the
        channel's `balance_payable_cents` immediately, per §3.2."
        PRD §3.2: "A `CHARGEBACK` event never waits for month settlement — it
        is ingested directly in `CLEARED` status, always uses its plain fee
        with no rebate, and its negative net subtracts from
        `balance_payable_cents` immediately."

        Design: Difficulty/transitive_cascade/deliverable_miss_deal_breach_clawback_cascade
        """
        channel, deal = self._breached_deal("tc_breach2")

        sponsorship_events, _m1 = validate_paginated(api.list_revenue_events(
            ADMIN, params={"channel_id": channel["id"], "kind": "SPONSORSHIP"}))
        assert len(sponsorship_events) == 1
        chargebacks, meta = validate_paginated(api.list_revenue_events(
            ADMIN, params={"channel_id": channel["id"], "kind": "CHARGEBACK"}))
        assert meta["total_count"] == 1, "link 3: exactly one clawback event"
        clawback = chargebacks[0]
        assert clawback["gross_cents"] == -6000000
        assert clawback["recognition_status"] == "CLEARED"
        assert clawback["reverses_event_id"] == sponsorship_events[0]["id"]

        assert get_channel(channel["id"])["balance_payable_cents"] == -5_400_000, (
            "link 4: clawback net -6000000 * 0.9 lands in payable while the "
            "activation inflow is still PENDING")


class TestDeliverableRescheduleOcc:
    def test_occ_deliverable_reschedule_stale_rejected(self, api):
        """PRD §3.7: "The owner may reschedule one from `MISSED` or from
        `DISPUTED` back to `SCHEDULED`, supplying a new `due_at` within the
        deal flight plus the OCC field `expected_deliverable_version` of §2.8
        — a stale version is rejected with `ERR_STALE_VERSION` (HTTP 412).
        Rescheduling replaces `due_at`, resets the disclosure axis to
        `PENDING`, and increments the deliverable's `version` by 1;
        rescheduling from `DISPUTED` additionally clears `performed_at` and
        unbinds `stream_id`. What rescheduling never does is decrement
        `miss_count` — misses are permanent history."

        Design: Corner/cross_cutting/occ_deliverable_reschedule_stale_rejected
        """
        channel, _form = create_verified_channel("cc_del")
        set_clock("2026-08-01T00:00:00Z")
        deal = setup_active_deal(channel, category="VPN",
                                 total_value_cents=100000)
        deliverable = create_deliverable(deal["id"], channel["id"],
                                         kind="AD_READ",
                                         due_at="2026-08-06T00:00:00Z")
        stale_version = deliverable["version"]
        set_clock("2026-08-07T00:00:00Z")
        run_ops()  # ops step 6 marks the deliverable MISSED, mutating it

        stale = api.reschedule_deliverable(
            deliverable["id"],
            {"due_at": "2026-08-20T00:00:00Z",
             "expected_deliverable_version": stale_version},
            make_creator_headers(channel["id"]))
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        fresh = get_success_data(api.get_deliverable(
            deliverable["id"], make_creator_headers(channel["id"])))
        assert fresh["performance_status"] == "MISSED"
        rescheduled = validate_success(api.reschedule_deliverable(
            deliverable["id"],
            {"due_at": "2026-08-20T00:00:00Z",
             "expected_deliverable_version": fresh["version"]},
            make_creator_headers(channel["id"])), 200)
        assert rescheduled["performance_status"] == "SCHEDULED"
        assert_instant_equals(rescheduled["due_at"], "2026-08-20T00:00:00Z",
                              label="due_at replaced")
        assert rescheduled["disclosure_status"] == "PENDING"
        assert rescheduled["version"] == fresh["version"] + 1

        deal_after = get_success_data(api.get_deal(deal["id"], ADMIN))
        assert deal_after["miss_count"] == 1, (
            "rescheduling never erases the miss history")
